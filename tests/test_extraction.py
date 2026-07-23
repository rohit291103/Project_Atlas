"""Tests for the extraction agent (extraction/agent.py + tools.py).

The load-bearing part is the validation gate `build_result` -- CLAUDE.md's one
rule with zero exceptions is that nothing reaches storage without passing schema
validation, so this file leans on failure cases: missing provenance, unknown
enums, hallucinated fields, dangling edges, duplicate refs. The LLM itself is
never called: `run_extraction` takes an injectable `AgentCall`, so the
validate/retry-once flow is exercised with a fake agent and no API key. Tool
handlers are driven through the connector's `httpx.MockTransport` seam, same as
the connector's own tests. Async paths run via `asyncio.run` to avoid depending
on a pytest async plugin/config.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path
from typing import Any

import httpx
import pytest
from claude_agent_sdk import AssistantMessage, TextBlock, ToolUseBlock
from pydantic import ValidationError

from atlas.extraction import tools
from atlas.extraction.agent import (
    ConfidenceLevel,
    ExtractionError,
    ExtractionResult,
    _make_permission_gate,
    build_result,
    confidence_to_score,
    emitted_payload,
    run_extraction,
)
from atlas.ingestion.github import GitHubClient

WORKSPACE_ID = uuid.UUID(int=0)
FEATURE_SCOPE_ID = uuid.uuid4()


def raw_node(
    ref: str = "n1", *, node_type: str = "requirement", confidence: str = "high"
) -> dict[str, Any]:
    return {
        "ref": ref,
        "type": node_type,
        "content": "The gateway must rate-limit per client IP.",
        "confidence": confidence,
        "source_refs": [
            {
                "source_type": "github_pr",
                "external_id": "42",
                "url": "https://github.com/acme/gateway/pull/42",
                "excerpt": "adds a per-IP token-bucket limiter",
            }
        ],
    }


def build(
    *, nodes: list[dict[str, Any]] | None = None, edges: list[dict[str, Any]] | None = None
) -> ExtractionResult:
    payload = {"nodes": nodes or [], "edges": edges or []}
    return build_result(payload, workspace_id=WORKSPACE_ID, feature_scope_id=FEATURE_SCOPE_ID)


# --- confidence mapping --------------------------------------------------------


@pytest.mark.parametrize(
    ("level", "score"),
    [(ConfidenceLevel.LOW, 0.3), (ConfidenceLevel.MEDIUM, 0.6), (ConfidenceLevel.HIGH, 0.9)],
)
def test_confidence_maps_to_bounded_score(level: ConfidenceLevel, score: float) -> None:
    assert confidence_to_score(level) == score


# --- the validation gate: happy path ------------------------------------------


def test_build_result_materializes_nodes_with_stamped_scope_and_provenance() -> None:
    result = build(nodes=[raw_node(confidence="medium")])

    assert len(result.nodes) == 1
    node = result.nodes[0]
    assert node.confidence_score == 0.6
    assert node.workspace_id == WORKSPACE_ID
    assert node.feature_scope_id == FEATURE_SCOPE_ID
    assert node.source_refs[0].excerpt == "adds a per-IP token-bucket limiter"
    assert node.source_refs[0].workspace_id == WORKSPACE_ID


def test_build_result_wires_edges_through_local_refs() -> None:
    result = build(
        nodes=[raw_node("n1"), raw_node("n2", node_type="goal")],
        edges=[
            {"from_ref": "n1", "to_ref": "n2", "relation_type": "supports", "confidence": "low"}
        ],
    )

    node_ids = {n.id for n in result.nodes}
    assert len(result.edges) == 1
    edge = result.edges[0]
    assert edge.from_node_id in node_ids
    assert edge.to_node_id in node_ids
    assert edge.from_node_id != edge.to_node_id
    assert edge.confidence_score == 0.3


def test_build_result_empty_payload_is_empty() -> None:
    result = build()
    assert result.nodes == []
    assert result.edges == []


# --- the validation gate: failure cases (where the bugs live) ------------------


def test_node_without_provenance_is_rejected() -> None:
    bad = raw_node()
    bad["source_refs"] = []
    with pytest.raises(ValidationError):
        build(nodes=[bad])


def test_blank_excerpt_is_rejected() -> None:
    bad = raw_node()
    bad["source_refs"][0]["excerpt"] = "   "
    with pytest.raises(ValidationError):
        build(nodes=[bad])


def test_unknown_node_type_is_rejected() -> None:
    with pytest.raises(ValidationError):
        build(nodes=[raw_node(node_type="wild_guess")])


def test_hallucinated_field_is_rejected() -> None:
    bad = raw_node()
    bad["severity"] = "critical"  # not in the contract
    with pytest.raises(ValidationError):
        build(nodes=[bad])


def test_duplicate_node_ref_is_rejected() -> None:
    with pytest.raises(ExtractionError, match="duplicate node ref"):
        build(nodes=[raw_node("n1"), raw_node("n1")])


def test_edge_referencing_unknown_node_is_rejected() -> None:
    with pytest.raises(ExtractionError, match="unknown node ref"):
        build(
            nodes=[raw_node("n1")],
            edges=[
                {
                    "from_ref": "n1",
                    "to_ref": "n99",
                    "relation_type": "supports",
                    "confidence": "low",
                }
            ],
        )


def test_self_referential_edge_is_rejected() -> None:
    with pytest.raises(ValidationError):
        build(
            nodes=[raw_node("n1")],
            edges=[
                {"from_ref": "n1", "to_ref": "n1", "relation_type": "supports", "confidence": "low"}
            ],
        )


# --- emitted_payload: transcript parsing --------------------------------------


def _assistant(*blocks: Any) -> AssistantMessage:
    return AssistantMessage(content=list(blocks), model="claude-opus-4-8")


def test_emitted_payload_returns_the_emit_tool_input() -> None:
    payload = {"nodes": [raw_node()], "edges": []}
    messages = [
        _assistant(TextBlock(text="Let me look at the PR.")),
        _assistant(ToolUseBlock(id="t1", name="mcp__atlas__emit_extraction", input=payload)),
    ]
    assert emitted_payload(messages) == payload


def test_emitted_payload_none_when_never_emitted() -> None:
    messages = [
        _assistant(ToolUseBlock(id="t1", name="mcp__atlas__fetch_commit", input={"sha": "abc"}))
    ]
    assert emitted_payload(messages) is None


# --- run_extraction: validate + retry-once seam -------------------------------


class FakeAgent:
    """An AgentCall stand-in returning queued payloads, recording each prompt."""

    def __init__(self, *payloads: dict[str, Any] | None) -> None:
        self._queue = list(payloads)
        self.calls: list[str] = []

    async def __call__(self, prompt: str) -> dict[str, Any] | None:
        self.calls.append(prompt)
        return self._queue.pop(0)


def _run(agent: FakeAgent) -> ExtractionResult:
    return asyncio.run(
        run_extraction(
            seed_prompt="seed",
            workspace_id=WORKSPACE_ID,
            feature_scope_id=FEATURE_SCOPE_ID,
            agent_call=agent,
        )
    )


def test_run_extraction_succeeds_on_first_try() -> None:
    agent = FakeAgent({"nodes": [raw_node()], "edges": []})
    result = _run(agent)
    assert len(result.nodes) == 1
    assert len(agent.calls) == 1


def test_run_extraction_retries_once_then_succeeds() -> None:
    invalid = {"nodes": [{**raw_node(), "source_refs": []}], "edges": []}
    valid = {"nodes": [raw_node()], "edges": []}
    agent = FakeAgent(invalid, valid)

    result = _run(agent)

    assert len(result.nodes) == 1
    assert len(agent.calls) == 2  # retried exactly once
    assert "rejected" in agent.calls[1]  # the correction was fed back to the agent


def test_run_extraction_raises_after_two_failures() -> None:
    invalid = {"nodes": [{**raw_node(), "source_refs": []}], "edges": []}
    agent = FakeAgent(invalid, invalid)
    with pytest.raises(ExtractionError, match="validation twice"):
        _run(agent)
    assert len(agent.calls) == 2  # retried once, no more


def test_run_extraction_errors_when_agent_emits_nothing() -> None:
    agent = FakeAgent(None)
    with pytest.raises(ExtractionError, match="did not emit"):
        _run(agent)


# --- tools: read-only fetch wrappers ------------------------------------------


def _load(name: str) -> object:
    return json.loads((Path(__file__).parent / "fixtures" / "github" / f"{name}.json").read_text())


def _github_client(handler: Any) -> GitHubClient:
    return GitHubClient("test-token", transport=httpx.MockTransport(handler))


def test_build_extraction_tools_exposes_the_four_tools() -> None:
    client = _github_client(lambda req: httpx.Response(404, json={}))
    names = {spec.name for spec in tools.build_extraction_tools(client, "acme", "gateway")}
    assert names == {"fetch_linked_issue", "fetch_commit", "search_repo", "emit_extraction"}


def test_fetch_linked_issue_tool_returns_formatted_issue() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_load("issue"))

    client = _github_client(handler)
    specs = {s.name: s for s in tools.build_extraction_tools(client, "acme", "gateway")}
    out = asyncio.run(specs["fetch_linked_issue"].handler({"number": 17}))

    text = out["content"][0]["text"]
    assert "Issue #17" in text
    assert "burst traffic" in text
    assert out.get("is_error") is None


def test_fetch_tool_reports_github_error_without_raising() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"message": "Not Found"})

    client = _github_client(handler)
    specs = {s.name: s for s in tools.build_extraction_tools(client, "acme", "gateway")}
    out = asyncio.run(specs["fetch_commit"].handler({"sha": "deadbeef"}))

    assert out["is_error"] is True
    assert "404" in out["content"][0]["text"]


def test_fetch_tool_surfaces_transport_error_as_is_error() -> None:
    """A network failure mid-run must reach the agent as an error result, not
    crash the extraction (a raised httpx.TransportError would)."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    client = _github_client(handler)
    specs = {s.name: s for s in tools.build_extraction_tools(client, "acme", "gateway")}
    out = asyncio.run(specs["fetch_linked_issue"].handler({"number": 17}))

    assert out["is_error"] is True
    assert "connection refused" in out["content"][0]["text"]


# --- permission gate: read-only + tool-call cap -------------------------------


def test_permission_gate_caps_reads_allows_emit_denies_builtins() -> None:
    gate = _make_permission_gate(2)

    async def run() -> tuple[list[str], str, str]:
        reads = [
            (await gate("mcp__atlas__fetch_commit", {}, None)).behavior  # type: ignore[arg-type]
            for _ in range(3)
        ]
        emit = (await gate("mcp__atlas__emit_extraction", {}, None)).behavior  # type: ignore[arg-type]
        builtin = (await gate("Bash", {}, None)).behavior  # type: ignore[arg-type]
        return reads, emit, builtin

    reads, emit, builtin = asyncio.run(run())

    assert reads == ["allow", "allow", "deny"]  # third fetch over the budget of 2
    assert emit == "allow"  # emit_extraction is never capped
    assert builtin == "deny"  # non-atlas tools are always denied (least-privilege)
