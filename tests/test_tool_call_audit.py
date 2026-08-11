"""Tool-call audit logging (slice 1D, closing the Phase 0 follow-up in
`docs/decisions/2026-07-28-extraction-tool-call-audit-logging.md`).

`Phase0_Architecture.md` §2 lists "every tool call is logged" as a guardrail
next to the call cap, and it was the one guardrail that existed only on paper.
Without it, "the agent only made read-only, in-budget calls" is enforced by the
permission gate but not *checkable afterwards* -- and a guardrail someone else
has to trust has to be observable.

So what is asserted here is the record, not the enforcement (that already has
tests): allowed calls appear with their arguments, **denied calls appear too**
(they are the evidence the gate refused something), and the manifest survives
onto the `ingestion_run` event where it is replayable.
"""

from __future__ import annotations

import asyncio
import uuid

from atlas.extraction.agent import _make_permission_gate
from atlas.models.schema import IngestionRunPayload, SourceType, ToolCallRecord


def _decide(gate, tool: str, arguments: dict[str, object]) -> str:
    async def run() -> str:
        result = await gate(tool, arguments, None)  # type: ignore[arg-type]
        return str(result.behavior)

    return asyncio.run(run())


def test_manifest_records_an_allowed_read_with_its_arguments() -> None:
    manifest: list[ToolCallRecord] = []
    gate = _make_permission_gate(4, manifest)

    _decide(gate, "mcp__atlas__fetch_linked_issue", {"number": 109})

    assert [(call.tool, call.allowed) for call in manifest] == [("fetch_linked_issue", True)]
    assert manifest[0].arguments == {"number": 109}


def test_manifest_records_a_denied_builtin() -> None:
    """The interesting half. A denial is the proof the read-only boundary held,
    and it is exactly what an auditor would want to see."""
    manifest: list[ToolCallRecord] = []
    gate = _make_permission_gate(4, manifest)

    behaviour = _decide(gate, "Bash", {"command": "curl evil.example"})

    assert behaviour == "deny"
    assert manifest == [
        ToolCallRecord(tool="Bash", arguments={"command": "curl evil.example"}, allowed=False)
    ]


def test_manifest_records_the_call_that_exceeded_the_budget() -> None:
    manifest: list[ToolCallRecord] = []
    gate = _make_permission_gate(1, manifest)

    _decide(gate, "mcp__atlas__fetch_commit", {"sha": "a" * 7})
    _decide(gate, "mcp__atlas__fetch_commit", {"sha": "b" * 7})

    assert [call.allowed for call in manifest] == [True, False]


def test_emit_is_not_part_of_the_access_record() -> None:
    """`emit_extraction` is the run's own result, not a read of a source system,
    so it neither spends budget nor belongs in a record of what was accessed."""
    manifest: list[ToolCallRecord] = []
    gate = _make_permission_gate(2, manifest)

    _decide(gate, "mcp__atlas__emit_extraction", {"nodes": [], "edges": []})

    assert manifest == []


def test_jira_search_tool_is_permitted_by_the_gate() -> None:
    """Regression guard for adding a source: a connector's read tool that isn't
    in the gate's allow-list is silently unusable -- the agent would be denied
    its own search tool and quietly extract less."""
    manifest: list[ToolCallRecord] = []
    gate = _make_permission_gate(4, manifest)

    behaviour = _decide(gate, "mcp__atlas__search_project", {"query": "rate limiting"})

    assert behaviour == "allow"


def test_manifest_lands_on_the_ingestion_run_event() -> None:
    payload = IngestionRunPayload(
        feature_scope_id=uuid.uuid4(),
        title="Rate-limit the gateway",
        source_type=SourceType.JIRA_TICKET,
        external_id="GATE-42",
        url="https://acme.atlassian.net/browse/GATE-42",
        tool_calls=[ToolCallRecord(tool="fetch_linked_issue", arguments={}, allowed=True)],
    )

    restored = IngestionRunPayload.model_validate(payload.model_dump(mode="json"))

    assert restored.tool_calls[0].tool == "fetch_linked_issue"


def test_an_ingestion_run_written_before_slice_1d_still_replays() -> None:
    """The forward-compatibility slice 1A' left room for: an optional field with
    an empty default, so no historical event is invalid and no backfill has to
    invent tool calls that were never made."""
    older = {
        "feature_scope_id": str(uuid.uuid4()),
        "title": "Add a --pre preprocessor flag",
        "source_type": "github_pr",
        "external_id": "BurntSushi/ripgrep#111",
        "url": "https://github.com/BurntSushi/ripgrep/pull/111",
    }

    assert IngestionRunPayload.model_validate(older).tool_calls == []
