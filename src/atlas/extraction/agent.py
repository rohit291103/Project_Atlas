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
from collections.abc import Awaitable, Callable
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
from atlas.extraction.tools import EMIT_TOOL, build_extraction_tools
from atlas.ingestion.github import GitHubClient
from atlas.models.schema import Edge, Node, NodeType, RelationType, SourceRef, SourceType

__all__ = [
    "ExtractionError",
    "ExtractionResult",
    "RawExtraction",
    "build_result",
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
) -> ExtractionResult:
    """The validation gate: raw agent payload -> domain Node/Edge, or raise.

    Raises `pydantic.ValidationError` if the payload doesn't fit the raw contract
    (unknown enum, empty excerpt, missing provenance, extra key), and
    `ExtractionError` for structural problems the schema can't catch (a duplicate
    node ref, an edge pointing at a ref that was never emitted).
    """
    raw = RawExtraction.model_validate(payload)

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

    edges: list[Edge] = []
    for raw_edge in raw.edges:
        try:
            from_id = ref_to_id[raw_edge.from_ref]
            to_id = ref_to_id[raw_edge.to_ref]
        except KeyError as missing:
            raise ExtractionError(
                f"edge references unknown node ref {missing.args[0]!r}"
            ) from missing
        edges.append(
            Edge(
                from_node_id=from_id,
                to_node_id=to_id,
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
        return build_result(payload, workspace_id=workspace_id, feature_scope_id=feature_scope_id)
    except (ValidationError, ExtractionError) as first_error:
        retry_prompt = seed_prompt + _RETRY_NOTE.format(error=first_error)
        retry_payload = await agent_call(retry_prompt)
        if retry_payload is None:
            raise ExtractionError("agent did not emit an extraction on retry") from first_error
        try:
            return build_result(
                retry_payload, workspace_id=workspace_id, feature_scope_id=feature_scope_id
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
_READ_TOOLS = frozenset({"fetch_linked_issue", "fetch_commit", "search_repo"})


def _make_permission_gate(max_tool_calls: int) -> CanUseTool:
    """Permission callback enforcing read-only, least-privilege, AND the tool-call
    cost cap (Phase0_Architecture.md Sec2) in one place.

    It is the *authority* for every tool call (we don't pre-approve via
    `allowed_tools`, which could bypass it): only the four atlas tools are
    permitted, `emit_extraction` is always allowed, and each fetch/search call is
    counted so the agent can't exceed `max_tool_calls` GitHub calls per run --
    something `max_turns` can't guarantee, since one turn may issue several
    parallel tool calls.
    """
    used = 0

    async def gate(
        tool_name: str, tool_input: dict[str, Any], context: ToolPermissionContext
    ) -> PermissionResultAllow | PermissionResultDeny:
        nonlocal used
        bare = tool_name.rsplit("__", 1)[-1]  # strip the mcp__atlas__ prefix
        if bare == EMIT_TOOL:
            return PermissionResultAllow()
        if bare not in _READ_TOOLS:
            return PermissionResultDeny(
                message="Only the atlas read-only tools are available; extraction is read-only."
            )
        if used >= max_tool_calls:
            return PermissionResultDeny(
                message="Tool-call budget spent -- call emit_extraction now with what you have."
            )
        used += 1
        return PermissionResultAllow()

    return gate


def _make_agent_call(
    client: GitHubClient,
    owner: str,
    repo: str,
    *,
    model: str,
    max_tool_calls: int,
) -> AgentCall:
    """Build the real Claude Agent SDK `AgentCall` for one repo."""
    tools = build_extraction_tools(client, owner, repo)
    server = create_sdk_mcp_server(name="atlas", tools=tools)
    options = ClaudeAgentOptions(
        model=model,
        system_prompt=prompts.SYSTEM_PROMPT,
        mcp_servers={"atlas": server},
        # Read-only + least-privilege + the ~8-call cost cap are all enforced by
        # `can_use_tool` (the authority). `disallowed_tools` hard-denies the SDK
        # write/exec/network built-ins before the gate is even consulted, and
        # `setting_sources=[]` blocks inheriting local/project tools or MCP
        # servers. We deliberately do NOT pass `allowed_tools` (pre-approval could
        # bypass the gate and defeat the cap) or `bypassPermissions`.
        can_use_tool=_make_permission_gate(max_tool_calls),
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
        messages: list[Any] = [message async for message in query(prompt=prompt, options=options)]
        return emitted_payload(messages)

    return call


async def extract_from_pull_request(
    *,
    client: GitHubClient,
    owner: str,
    repo: str,
    number: int,
    workspace_id: uuid.UUID,
    feature_scope_id: uuid.UUID,
    model: str = DEFAULT_MODEL,
    max_tool_calls: int = MAX_TOOL_CALLS,
) -> ExtractionResult:
    """End-to-end Phase 0 extraction for one PR (read-only in, validated out)."""
    pr = await asyncio.to_thread(client.fetch_pull_request, owner, repo, number)
    seed_prompt = prompts.build_seed_prompt(pr)
    agent_call = _make_agent_call(client, owner, repo, model=model, max_tool_calls=max_tool_calls)
    return await run_extraction(
        seed_prompt=seed_prompt,
        workspace_id=workspace_id,
        feature_scope_id=feature_scope_id,
        agent_call=agent_call,
    )
