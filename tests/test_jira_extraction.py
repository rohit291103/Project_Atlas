"""Extraction over a second source (slice 1C): Jira tools, the Jira seed prompt,
and cross-source `conflicts_with`.

Two things here carry real risk and so are tested hardest:

1. **The GitHub system prompt must not move.** It was tuned and validated through
   the Phase 0 eval loop; adding a source must not silently re-word the prompt
   that evidence was gathered against. A golden copy is asserted byte-for-byte.
2. **An edge onto an existing node must name a node that exists.** Cross-source
   conflict detection lets the agent point a `conflicts_with` edge at a node from
   an *earlier* run, which means the agent supplies a UUID. An invented UUID must
   be rejected at the gate, not stored -- a fabricated relationship is the same
   class of failure as a fabricated excerpt.
"""

from __future__ import annotations

import uuid
from typing import Any

import httpx
import pytest

from atlas.extraction import prompts, tools
from atlas.extraction.agent import ExtractionError, build_result
from atlas.ingestion.jira import JiraClient
from atlas.models.schema import RelationType, SourceType
from tests.asyncio_support import run_await

WORKSPACE_ID = uuid.uuid4()
FEATURE_SCOPE_ID = uuid.uuid4()


def make_jira_client() -> JiraClient:
    return JiraClient(
        base_url="https://acme.atlassian.net",
        email="pm@acme.test",
        api_token="t",
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={})),
    )


# --- the GitHub prompt is frozen ------------------------------------------------
#
# **Re-baselined 2026-08-15, deliberately.** The 2026-08-14 Jira quality run found
# the agent emitting a `goal` that restated a `requirement`/`decision` it had
# already emitted -- once off the *identical* excerpt -- so a reviewer would have
# to rule twice on one idea and could confirm one copy while rejecting the other.
# The fix is rule 5 ("ONE CLAIM, ONE NODE") plus a sharper goal/requirement
# distinction in the type guide, and both belong in the *shared* prompt: the
# defect is a property of the extraction task, not of Jira.
#
# That means this constant no longer describes the prompt Phase 0's evals were
# gathered against, and pretending otherwise by exempting the change would make
# the guard decorative. The baseline moves, and the evidence moves with it: the
# golden set was re-recorded and re-graded in the same change
# (`docs/research/2026-08-15-deduplication-prompt-run.md`). The guard's job is
# unchanged -- it fails the moment the prompt drifts from the version the
# recorded evidence describes.

GITHUB_SYSTEM_PROMPT_AS_VALIDATED = """\
You are Atlas, an extraction agent. You read the raw content of a GitHub pull \
request and its linked context, and you distil it into a small set of typed, \
provenance-linked knowledge elements (Nodes) and the relationships between them \
(Edges). You never invent information.

Node types:
- goal: the outcome the work is meant to achieve -- why it is being done
- problem: a pain point or motivating issue
- evidence: a concrete observation supporting a claim
- decision: a choice that was made
- requirement: something the solution must do -- what it must do
- constraint: a limit the solution must respect
- architecture_note: a technical design detail
- open_question: an unresolved question
- rejected_alternative: an option considered and explicitly not taken

Edge relation types: supports, derives_from, conflicts_with, implements, \
rejects, depends_on.

Rules you must follow exactly:
1. PROVENANCE IS MANDATORY. Every Node must carry at least one source_ref whose \
`excerpt` is a *verbatim* span copied from the source text -- never a paraphrase \
or summary. If you cannot point to literal text, do not create the Node.
2. Extract a draft, not a fact. Prefer omitting a weak claim over guessing. \
Assess your confidence for each Node and Edge as low, medium, or high.
3. Follow references, don't fabricate them. When the text mentions a linked \
issue, a commit sha, or another PR, use the available tools \
(`fetch_linked_issue`, `fetch_commit`, `search_repo`) to read the real content \
before extracting from it. Use at most a handful of tool calls.
4. Flag conflicts, don't resolve them. If two sources disagree on the same \
point, emit both Nodes and a `conflicts_with` Edge between them.
5. ONE CLAIM, ONE NODE. Never emit two Nodes that assert the same thing in \
different words, and never emit two Nodes from the same excerpt unless they \
genuinely say different things. A sentence often states an outcome *and* what \
must be built to reach it -- pick the single type that fits it best and emit it \
once. A `goal` that restates a `requirement` or `decision` you have already \
emitted is a duplicate, not a second claim, and it forces a reviewer to rule \
twice on one idea.
6. Finish with exactly one call to `emit_extraction`, passing every Node and \
Edge. Give each Node a short local `ref` (e.g. "n1") and wire Edges by \
`from_ref`/`to_ref`. Do not write anything to any system -- extraction is \
read-only.
"""


def test_github_system_prompt_is_unchanged_by_adding_a_second_source() -> None:
    """Regression guard for the Phase 0 eval baseline. If this fails, the GitHub
    extraction evidence no longer describes the prompt actually being sent, and
    `extraction-quality-review` has to be re-run before the change ships."""
    assert prompts.SYSTEM_PROMPT == GITHUB_SYSTEM_PROMPT_AS_VALIDATED


def test_jira_system_prompt_names_its_own_source_and_tools() -> None:
    prompt = prompts.JIRA_SYSTEM_PROMPT

    assert "Jira issue" in prompt
    assert "search_project" in prompt
    assert "search_repo" not in prompt
    # The non-negotiables are shared, not re-written per source.
    assert "PROVENANCE IS MANDATORY" in prompt
    assert "Flag conflicts, don't resolve them" in prompt


# --- the Jira seed prompt -------------------------------------------------------


def _issue(**overrides: object) -> Any:
    from atlas.ingestion.jira import IssueLink, JiraComment, JiraIssue

    defaults: dict[str, object] = {
        "key": "GATE-42",
        "summary": "Rate-limit the gateway per client IP",
        "description": "Bursty clients can starve everyone else.",
        "status": "In Progress",
        "issue_type": "Story",
        "url": "https://acme.atlassian.net/browse/GATE-42",
        "reporter": "Priya Raman",
        "created_at": None,
        "labels": ("gateway",),
        "parent_key": "GATE-1",
        "links": (IssueLink(key="GATE-43", summary="Token bucket", relation="blocks"),),
        "comments": (
            JiraComment(
                id="1",
                author="Dan Okafor",
                body="We agreed to buffer, not stream.",
                url="https://acme.atlassian.net/browse/GATE-42?focusedCommentId=1",
                created_at=None,
            ),
        ),
    }
    defaults.update(overrides)
    return JiraIssue(**defaults)  # type: ignore[arg-type]


def test_jira_seed_prompt_carries_the_issue_its_comments_and_its_links() -> None:
    prompt = prompts.build_jira_seed_prompt(_issue())

    assert "GATE-42" in prompt
    assert "Rate-limit the gateway per client IP" in prompt
    assert "Bursty clients can starve everyone else." in prompt
    assert "We agreed to buffer, not stream." in prompt
    assert "GATE-43" in prompt  # the link it should follow rather than guess at


def test_jira_seed_prompt_survives_an_issue_with_no_description() -> None:
    prompt = prompts.build_jira_seed_prompt(_issue(description="", comments=(), links=()))

    assert "GATE-42" in prompt


# --- cross-source context -------------------------------------------------------


def test_known_nodes_block_lists_existing_claims_with_their_ids() -> None:
    """What makes cross-source conflict detection possible: the second source's
    run is told what the first source already established."""
    node_id = uuid.uuid4()

    block = prompts.build_known_nodes_block(
        [(node_id, "requirement", "Must stream stdin, not buffer.", SourceType.GITHUB_PR)]
    )

    assert str(node_id) in block
    assert "Must stream stdin, not buffer." in block
    assert "conflicts_with" in block  # it must say what to do about a disagreement


def test_known_nodes_block_is_empty_when_the_scope_is_new() -> None:
    assert prompts.build_known_nodes_block([]) == ""


# --- the gate: edges onto existing nodes ---------------------------------------


def _payload(to_ref: str) -> dict[str, object]:
    return {
        "nodes": [
            {
                "ref": "n1",
                "type": "decision",
                "content": "Buffer preprocessor output.",
                "confidence": "high",
                "source_refs": [
                    {
                        "source_type": "jira_ticket",
                        "external_id": "GATE-42",
                        "url": "https://acme.atlassian.net/browse/GATE-42",
                        "excerpt": "We agreed to buffer, not stream.",
                    }
                ],
            }
        ],
        "edges": [
            {
                "from_ref": "n1",
                "to_ref": to_ref,
                "relation_type": "conflicts_with",
                "confidence": "high",
            }
        ],
    }


def test_edge_can_point_at_a_node_from_an_earlier_run() -> None:
    existing = uuid.uuid4()

    result = build_result(
        _payload(str(existing)),
        workspace_id=WORKSPACE_ID,
        feature_scope_id=FEATURE_SCOPE_ID,
        known_node_ids=[existing],
    )

    (edge,) = result.edges
    assert edge.to_node_id == existing
    assert edge.relation_type is RelationType.CONFLICTS_WITH
    assert result.nodes[0].id == edge.from_node_id


def test_an_invented_node_id_is_rejected_at_the_gate() -> None:
    """A UUID the agent made up must not become a stored relationship. It is
    shaped exactly like a real one, so nothing downstream could tell."""
    with pytest.raises(ExtractionError, match="unknown node"):
        build_result(
            _payload(str(uuid.uuid4())),
            workspace_id=WORKSPACE_ID,
            feature_scope_id=FEATURE_SCOPE_ID,
            known_node_ids=[uuid.uuid4()],
        )


def test_a_uuid_is_not_accepted_when_no_existing_nodes_were_offered() -> None:
    with pytest.raises(ExtractionError, match="unknown node"):
        build_result(
            _payload(str(uuid.uuid4())),
            workspace_id=WORKSPACE_ID,
            feature_scope_id=FEATURE_SCOPE_ID,
        )


def test_a_local_ref_still_resolves_normally() -> None:
    payload = _payload("n2")
    payload["nodes"] = [
        *payload["nodes"],  # type: ignore[misc]
        {
            "ref": "n2",
            "type": "requirement",
            "content": "Stream stdin.",
            "confidence": "medium",
            "source_refs": [
                {
                    "source_type": "jira_ticket",
                    "external_id": "GATE-42",
                    "url": "https://acme.atlassian.net/browse/GATE-42",
                    "excerpt": "must not buffer",
                }
            ],
        },
    ]

    result = build_result(
        payload,
        workspace_id=WORKSPACE_ID,
        feature_scope_id=FEATURE_SCOPE_ID,
        known_node_ids=[uuid.uuid4()],
    )

    assert {edge.to_node_id for edge in result.edges} == {result.nodes[1].id}


# --- the Jira tools -------------------------------------------------------------


def test_build_jira_extraction_tools_exposes_its_three_tools() -> None:
    names = {spec.name for spec in tools.build_jira_extraction_tools(make_jira_client(), "GATE")}

    assert names == {"fetch_linked_issue", "search_project", "emit_extraction"}


def test_jira_fetch_tool_surfaces_an_error_instead_of_raising() -> None:
    client = JiraClient(
        base_url="https://acme.atlassian.net",
        email="pm@acme.test",
        api_token="t",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(403, json={"errorMessages": ["nope"]})
        ),
    )
    specs = {s.name: s for s in tools.build_jira_extraction_tools(client, "GATE")}

    result = run_await(specs["fetch_linked_issue"].handler({"key": "GATE-43"}))

    assert result["is_error"] is True
    assert "403" in result["content"][0]["text"]


def test_jira_search_tool_is_scoped_to_its_project() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(request.url.params)
        return httpx.Response(200, json={"issues": []})

    client = JiraClient(
        base_url="https://acme.atlassian.net",
        email="pm@acme.test",
        api_token="t",
        transport=httpx.MockTransport(handler),
    )
    specs = {s.name: s for s in tools.build_jira_extraction_tools(client, "GATE")}

    run_await(specs["search_project"].handler({"query": "rate limiting"}))

    assert seen["jql"].startswith('project = "GATE"')
    assert "rate limiting" in seen["jql"]
