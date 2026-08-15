"""The extraction agent: raw agent output -> schema-validated Node/Edge.

This module is the single validation gate for everything the LLM produces
(CLAUDE.md's one rule with zero exceptions: nothing reaches storage without
passing Pydantic validation). The agent emits its result through a forced
`emit_extraction(nodes, edges)` tool call; `build_result` is the gate that turns
that raw payload into domain `Node`/`Edge` objects or refuses.

Two layers, deliberately split so the gate is testable without an API key:

  * `build_result` -- pure. Validates the raw contract (`RawExtraction`), maps
    the agent's low/medium/high confidence to a numeric score, assigns a real
    UUID per Node, wires Edges through the agent's local `ref` ids, stamps
    workspace/feature scope, and constructs domain models (which re-enforce
    provenance, confidence bounds, no self-edges). Any structural problem raises.
  * `run_extraction` -- orchestration. Calls the agent (an injectable
    `AgentCall` seam), runs the payload through `build_result`, and retries
    once with a correction on a validation failure before surfacing an
    `ExtractionError` (TRD Sec5.1: retry once, then error -- never guess).

`extract_from_pull_request` wires the real Claude Agent SDK call to the seam.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Collection, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from claude_agent_sdk import (
    AssistantMessage,
    CanUseTool,
    ClaudeAgentOptions,
    PermissionResultAllow,
    PermissionResultDeny,
    ToolPermissionContext,
    ToolUseBlock,
    create_sdk_mcp_server,
    query,
)
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from atlas.extraction import prompts
from atlas.extraction.tools import (
    EMIT_TOOL,
    build_extraction_tools,
    build_jira_extraction_tools,
)
from atlas.ingestion.github import GitHubClient
from atlas.ingestion.jira import JiraClient
from atlas.models.schema import (
    Edge,
    IngestionRunPayload,
    Node,
    NodeType,
    RelationType,
    SourceRef,
    SourceType,
    ToolCallRecord,
)

__all__ = [
    "ExtractionError",
    "ExtractionResult",
    "RawExtraction",
    "build_result",
    "extract_from_jira_issue",
    "extract_from_pull_request",
    "run_extraction",
]

DEFAULT_MODEL = "claude-opus-4-8"
# Bound exploration on a single PR (Phase0_Architecture.md Sec2 guardrail).
MAX_TOOL_CALLS = 8


class ExtractionError(RuntimeError):
    """Raised when agent output can't be turned into valid Node/Edge state.

    Surfaced as an ingestion error rather than silently dropped or guessed
    (TRD Sec5.1). `build_result` raises it for structural problems the schema
    can't express (a dangling edge, a duplicate ref); Pydantic raises
    `ValidationError` for shape problems. `run_extraction` treats both as
    retryable once.
    """


class ConfidenceLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


_CONFIDENCE_SCORES: dict[ConfidenceLevel, float] = {
    ConfidenceLevel.LOW: 0.3,
    ConfidenceLevel.MEDIUM: 0.6,
    ConfidenceLevel.HIGH: 0.9,
}


def confidence_to_score(level: ConfidenceLevel) -> float:
    """Map the agent's self-assessed low/medium/high to the numeric
    `confidence_score` the schema stores (TRD Sec5.1)."""
    return _CONFIDENCE_SCORES[level]


# --- raw agent-output contract -------------------------------------------------
#
# What the agent is allowed to emit. Distinct from the domain models: it uses
# local `ref` ids (the agent has no UUIDs) and low/medium/high confidence, and it
# omits the fields the system stamps (ids, workspace/feature scope, timestamps).
# `extra="forbid"` rejects any hallucinated key -- an unexpected field is a bug,
# not something to silently ignore.


class _RawModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RawSourceRef(_RawModel):
    source_type: SourceType
    external_id: str = Field(min_length=1)
    url: str = Field(min_length=1)
    excerpt: str = Field(min_length=1)


class RawNode(_RawModel):
    ref: str = Field(min_length=1)
    type: NodeType
    content: str = Field(min_length=1)
    confidence: ConfidenceLevel
    source_refs: list[RawSourceRef] = Field(min_length=1)


class RawEdge(_RawModel):
    from_ref: str = Field(min_length=1)
    to_ref: str = Field(min_length=1)
    relation_type: RelationType
    confidence: ConfidenceLevel


class RawExtraction(_RawModel):
    nodes: list[RawNode] = Field(default_factory=list)
    edges: list[RawEdge] = Field(default_factory=list)


@dataclass(frozen=True, slots=True)
class ExtractionResult:
    """Validated Node/Edge draft, ready to be written as events (all unconfirmed)."""

    nodes: list[Node] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)


def build_result(
    payload: dict[str, Any],
    *,
    workspace_id: uuid.UUID,
    feature_scope_id: uuid.UUID,
    known_node_ids: Collection[uuid.UUID] = (),
) -> ExtractionResult:
    """The validation gate: raw agent payload -> domain Node/Edge, or raise.

    Raises `pydantic.ValidationError` if the payload doesn't fit the raw contract
    (unknown enum, empty excerpt, missing provenance, extra key), and
    `ExtractionError` for structural problems the schema can't catch (a duplicate
    node ref, an edge pointing at a ref that was never emitted).

    `known_node_ids` are nodes an *earlier* run already established for this
    feature scope. An edge may point at one of them by id, which is what makes
    cross-source `conflicts_with` expressible (TRD Sec5.2) -- each run only ever
    reads its own artifact, so a GitHub/Jira contradiction can only be stated as
    an edge onto something already stored. Any id **not** in this set is rejected:
    a fabricated relationship is shaped exactly like a real one, so nothing
    downstream could tell it apart, which puts it in the same class as a
    fabricated excerpt.
    """
    raw = RawExtraction.model_validate(payload)
    known = set(known_node_ids)

    ref_to_id: dict[str, uuid.UUID] = {}
    nodes: list[Node] = []
    for raw_node in raw.nodes:
        if raw_node.ref in ref_to_id:
            raise ExtractionError(f"duplicate node ref {raw_node.ref!r}")
        node = Node(
            type=raw_node.type,
            content=raw_node.content,
            confidence_score=confidence_to_score(raw_node.confidence),
            source_refs=[
                SourceRef(
                    source_type=ref.source_type,
                    external_id=ref.external_id,
                    url=ref.url,
                    excerpt=ref.excerpt,
                    workspace_id=workspace_id,
                )
                for ref in raw_node.source_refs
            ],
            workspace_id=workspace_id,
            feature_scope_id=feature_scope_id,
        )
        ref_to_id[raw_node.ref] = node.id
        nodes.append(node)

    def resolve(ref: str) -> uuid.UUID:
        """A local ref from this run, or the id of a node an earlier run stored."""
        if ref in ref_to_id:
            return ref_to_id[ref]
        try:
            existing = uuid.UUID(ref)
        except ValueError:
            existing = None
        if existing is not None and existing in known:
            return existing
        raise ExtractionError(f"edge references unknown node {ref!r}")

    edges: list[Edge] = []
    for raw_edge in raw.edges:
        edges.append(
            Edge(
                from_node_id=resolve(raw_edge.from_ref),
                to_node_id=resolve(raw_edge.to_ref),
                relation_type=raw_edge.relation_type,
                confidence_score=confidence_to_score(raw_edge.confidence),
            )
        )

    return ExtractionResult(nodes=nodes, edges=edges)


# --- orchestration -------------------------------------------------------------
#
# `AgentCall` is the seam: given a prompt, run the agent and return the payload
# it emitted through `emit_extraction` (or None if it emitted nothing). The real
# implementation drives the Claude Agent SDK; tests inject a fake so the
# validate/retry flow is exercised without an API key.

AgentCall = Callable[[str], Awaitable[dict[str, Any] | None]]

_RETRY_NOTE = (
    "\n\nYour previous extraction was rejected: {error}\n"
    "Fix the problem and call emit_extraction again with corrected data."
)


async def run_extraction(
    *,
    seed_prompt: str,
    workspace_id: uuid.UUID,
    feature_scope_id: uuid.UUID,
    agent_call: AgentCall,
    known_node_ids: Collection[uuid.UUID] = (),
) -> ExtractionResult:
    """Run the agent, validate its output, retry once, then error.

    A malformed or unparseable result is retried a single time with the error
    fed back to the agent; a second failure is surfaced as an `ExtractionError`
    rather than dropped or guessed (TRD Sec5.1, Sec10).
    """
    payload = await agent_call(seed_prompt)
    if payload is None:
        raise ExtractionError("agent did not emit an extraction")
    try:
        return build_result(
            payload,
            workspace_id=workspace_id,
            feature_scope_id=feature_scope_id,
            known_node_ids=known_node_ids,
        )
    except (ValidationError, ExtractionError) as first_error:
        retry_prompt = seed_prompt + _RETRY_NOTE.format(error=first_error)
        # Deliberate: the retry reuses the same `agent_call` (hence the same
        # `can_use_tool` gate + its budget counter), so the ~8-call cap is
        # per-run, not per-attempt (Phase0_Architecture.md Sec2). The retry is a
        # format-correction pass, not a fresh exploration budget -- do not split
        # this into a per-attempt gate, which would silently double the cost cap.
        retry_payload = await agent_call(retry_prompt)
        if retry_payload is None:
            raise ExtractionError("agent did not emit an extraction on retry") from first_error
        try:
            return build_result(
                retry_payload,
                workspace_id=workspace_id,
                feature_scope_id=feature_scope_id,
                known_node_ids=known_node_ids,
            )
        except (ValidationError, ExtractionError) as retry_error:
            raise ExtractionError(
                f"extraction failed validation twice: {retry_error}"
            ) from retry_error


def emitted_payload(messages: list[Any]) -> dict[str, Any] | None:
    """Pull the `emit_extraction` input out of an agent message transcript.

    Returns the last emit call's arguments (the agent may correct itself
    mid-run), or None if it never emitted. Kept pure so the message-parsing
    contract is testable with lightweight stand-in blocks.
    """
    payload: dict[str, Any] | None = None
    for message in messages:
        if not isinstance(message, AssistantMessage):
            continue
        for block in message.content:
            if isinstance(block, ToolUseBlock) and block.name.endswith(EMIT_TOOL):
                payload = block.input
    return payload


# The read-only exploration tools that count against the per-run budget.
# `emit_extraction` is the output tool -- always allowed, never counted.
# Every read tool any connector exposes. A tool missing here is denied by the
# gate, so adding a source means adding its tools here -- deliberately central,
# so the read-only allow-list stays one auditable list rather than per-connector.
_READ_TOOLS = frozenset({"fetch_linked_issue", "fetch_commit", "search_repo", "search_project"})


def _make_permission_gate(
    max_tool_calls: int, manifest: list[ToolCallRecord] | None = None
) -> CanUseTool:
    """Permission callback enforcing read-only, least-privilege, AND the tool-call
    cost cap (Phase0_Architecture.md Sec2) in one place.

    It is the *authority* for every tool call (we don't pre-approve via
    `allowed_tools`, which could bypass it): only the four atlas tools are
    permitted, `emit_extraction` is always allowed, and each fetch/search call is
    counted so the agent can't exceed `max_tool_calls` GitHub calls per run --
    something `max_turns` can't guarantee, since one turn may issue several
    parallel tool calls.

    Every decision it makes is appended to `manifest` -- allowed *and* denied --
    which is what turns "the agent only made read-only, in-budget calls" from a
    claim into a record (TRD Sec9,
    `docs/decisions/2026-07-28-extraction-tool-call-audit-logging.md`). The
    manifest is the caller's list, so it survives the closure and lands on the
    run's `ingestion_run` event.
    """
    used = 0
    recorded = manifest if manifest is not None else []

    def record(tool: str, arguments: dict[str, Any], allowed: bool) -> None:
        recorded.append(ToolCallRecord(tool=tool, arguments=arguments, allowed=allowed))

    async def gate(
        tool_name: str, tool_input: dict[str, Any], context: ToolPermissionContext
    ) -> PermissionResultAllow | PermissionResultDeny:
        nonlocal used
        bare = tool_name.rsplit("__", 1)[-1]  # strip the mcp__atlas__ prefix
        if bare == EMIT_TOOL:
            # Not counted and not recorded: it is the run's own result, not a
            # read of a source system, so it is not part of the access record.
            return PermissionResultAllow()
        if bare not in _READ_TOOLS:
            record(bare, tool_input, allowed=False)
            return PermissionResultDeny(
                message="Only the atlas read-only tools are available; extraction is read-only."
            )
        if used >= max_tool_calls:
            record(bare, tool_input, allowed=False)
            return PermissionResultDeny(
                message="Tool-call budget spent -- call emit_extraction now with what you have."
            )
        used += 1
        record(bare, tool_input, allowed=True)
        return PermissionResultAllow()

    return gate


def _make_agent_call(
    client: GitHubClient,
    owner: str,
    repo: str,
    *,
    model: str,
    max_tool_calls: int,
    manifest: list[ToolCallRecord] | None = None,
) -> AgentCall:
    """Build the real Claude Agent SDK `AgentCall` for one repo."""
    return _agent_call(
        tools=build_extraction_tools(client, owner, repo),
        system_prompt=prompts.SYSTEM_PROMPT,
        model=model,
        max_tool_calls=max_tool_calls,
        manifest=manifest,
    )


def _make_jira_agent_call(
    client: JiraClient,
    project_key: str,
    *,
    model: str,
    max_tool_calls: int,
    manifest: list[ToolCallRecord] | None = None,
) -> AgentCall:
    """The same call, bound to one Jira project instead of one repo."""
    return _agent_call(
        tools=build_jira_extraction_tools(client, project_key),
        system_prompt=prompts.JIRA_SYSTEM_PROMPT,
        model=model,
        max_tool_calls=max_tool_calls,
        manifest=manifest,
    )


def _agent_call(
    *,
    tools: list[Any],
    system_prompt: str,
    model: str,
    max_tool_calls: int,
    manifest: list[ToolCallRecord] | None = None,
) -> AgentCall:
    """Everything about the agent call that is *not* source-specific.

    The permission gate, the hard-denied built-ins and the tool-call cap are
    properties of the extraction guarantee, not of a connector -- so a new source
    inherits them rather than re-declaring (and possibly weakening) them.
    """
    server = create_sdk_mcp_server(name="atlas", tools=tools)
    options = ClaudeAgentOptions(
        model=model,
        system_prompt=system_prompt,
        mcp_servers={"atlas": server},
        # Read-only + least-privilege + the ~8-call cost cap are all enforced by
        # `can_use_tool` (the authority). `disallowed_tools` hard-denies the SDK
        # write/exec/network built-ins before the gate is even consulted, and
        # `setting_sources=[]` blocks inheriting local/project tools or MCP
        # servers. We deliberately do NOT pass `allowed_tools` (pre-approval could
        # bypass the gate and defeat the cap) or `bypassPermissions`.
        can_use_tool=_make_permission_gate(max_tool_calls, manifest),
        disallowed_tools=[
            "Bash",
            "Edit",
            "Write",
            "NotebookEdit",
            "Read",
            "Glob",
            "Grep",
            "WebFetch",
            "WebSearch",
            "TodoWrite",
        ],
        setting_sources=[],
        # Coarse upper bound on turns as well; the gate is the real tool-call cap.
        max_turns=max_tool_calls + 2,
    )

    async def call(prompt: str) -> dict[str, Any] | None:
        messages: list[Any] = [
            message async for message in query(prompt=_as_stream(prompt), options=options)
        ]
        return emitted_payload(messages)

    return call


async def _as_stream(prompt: str) -> AsyncIterator[dict[str, Any]]:
    """Wrap a single prompt as the streaming-input message the SDK requires.

    The Claude Agent SDK only invokes the `can_use_tool` permission callback in
    streaming-input mode -- i.e. when `prompt` is an AsyncIterable of message
    dicts, not a plain string. A string prompt bypasses the gate entirely, which
    would silently defeat our read-only + tool-call-budget enforcement (and in
    fact the SDK now hard-errors on a string prompt when `can_use_tool` is set).
    We yield exactly one user message in the SDK's stream-json shape, then
    complete -- closing the input stream so the agent runs to its result.
    """
    yield {
        "type": "user",
        "session_id": "",
        "message": {"role": "user", "content": prompt},
        "parent_tool_use_id": None,
    }


async def extract_from_jira_issue(
    *,
    client: JiraClient,
    key: str,
    workspace_id: uuid.UUID,
    feature_scope_id: uuid.UUID,
    known_nodes: Sequence[Node] = (),
    model: str = DEFAULT_MODEL,
    max_tool_calls: int = MAX_TOOL_CALLS,
) -> tuple[IngestionRunPayload, ExtractionResult]:
    """End-to-end extraction for one Jira issue (read-only in, validated out).

    `known_nodes` are the claims already extracted for this feature scope from
    other sources. They are handed to the agent as context and their ids are the
    only ones an edge may point at, which is what makes a **cross-source**
    `conflicts_with` possible without letting the agent invent a relationship
    (TRD Sec5.2, `prompts.build_known_nodes_block`).
    """
    issue = await asyncio.to_thread(client.fetch_issue, key)
    project_key = key.split("-", 1)[0]
    seed_prompt = prompts.build_jira_seed_prompt(issue) + prompts.build_known_nodes_block(
        (node.id, node.type.value, node.content, node.source_refs[0].source_type)
        for node in known_nodes
    )
    manifest: list[ToolCallRecord] = []
    agent_call = _make_jira_agent_call(
        client, project_key, model=model, max_tool_calls=max_tool_calls, manifest=manifest
    )
    result = await run_extraction(
        seed_prompt=seed_prompt,
        workspace_id=workspace_id,
        feature_scope_id=feature_scope_id,
        agent_call=agent_call,
        known_node_ids=[node.id for node in known_nodes],
    )
    run = IngestionRunPayload(
        feature_scope_id=feature_scope_id,
        title=issue.summary or key,
        source_type=SourceType.JIRA_TICKET,
        external_id=key,
        url=issue.url,
        # Built after the run, so the event records what the agent actually did
        # rather than what it was about to be allowed to do.
        tool_calls=manifest,
    )
    return run, result


async def extract_from_pull_request(
    *,
    client: GitHubClient,
    owner: str,
    repo: str,
    number: int,
    workspace_id: uuid.UUID,
    feature_scope_id: uuid.UUID,
    known_nodes: Sequence[Node] = (),
    model: str = DEFAULT_MODEL,
    max_tool_calls: int = MAX_TOOL_CALLS,
) -> tuple[IngestionRunPayload, ExtractionResult]:
    """End-to-end extraction for one PR (read-only in, validated out).

    Returns *what was ingested* alongside *what was extracted from it*: the
    `IngestionRunPayload` names the feature scope after the PR that seeded it, so
    the scope is something a reviewer can recognize (Phase1_Architecture Sec4.4).
    It is built here rather than by the caller because this is where the fetched
    `PullRequest` lives -- deriving the title anywhere else would mean fetching
    the same PR twice or hand-assembling a URL the connector already parsed.

    `known_nodes` mirrors the Jira path exactly (slice 2B): once a source can be
    connected from the UI, GitHub is as likely to be the *second* source into a
    feature as the first, and without this a PM who connects Jira then GitHub
    gets no cross-source conflicts at all -- the asymmetry would be invisible and
    would silently withhold the product's most valuable output. When it is empty
    the seed prompt is byte-identical to the one Phase 0's evals validated, which
    is what keeps that evidence good (`build_known_nodes_block` returns "" for an
    empty sequence, and the *system* prompt is untouched and still golden-tested).
    """
    pr = await asyncio.to_thread(client.fetch_pull_request, owner, repo, number)
    seed_prompt = prompts.build_seed_prompt(pr) + prompts.build_known_nodes_block(
        (node.id, node.type.value, node.content, node.source_refs[0].source_type)
        for node in known_nodes
    )
    manifest: list[ToolCallRecord] = []
    agent_call = _make_agent_call(
        client, owner, repo, model=model, max_tool_calls=max_tool_calls, manifest=manifest
    )
    result = await run_extraction(
        seed_prompt=seed_prompt,
        workspace_id=workspace_id,
        feature_scope_id=feature_scope_id,
        agent_call=agent_call,
        known_node_ids=[node.id for node in known_nodes],
    )
    run = IngestionRunPayload(
        feature_scope_id=feature_scope_id,
        title=pr.title,
        source_type=SourceType.GITHUB_PR,
        # Fully qualified: a feature scope is workspace-global, so a bare PR
        # number (unique only within one repo) would not identify its source.
        external_id=f"{owner}/{repo}#{pr.number}",
        url=pr.url,
        # Built after the run, so the event records what the agent actually did.
        tool_calls=manifest,
    )
    return run, result
