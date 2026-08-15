"""Tier 1 deterministic golden-set eval (see the `writing-evals` skill).

Three deterministic checks per validation PR, applied to *real* recorded agent
output (`extraction.json`), not hand-built fixtures:

1. **Schema validity** — the output re-validates through the Pydantic gate.
2. **Provenance** — every `SourceRef.excerpt` appears (whitespace-tolerant) in the
   actual recorded source corpus (`raw.json`). A fabricated/unprovenanced excerpt
   is a blocker, full stop (CLAUDE.md: provenance is the one non-negotiable).
3. **Rubric minimums** — a conservative, hand-authored floor per PR (`rubric.yaml`):
   required node types + must-mention keywords. Not full expected-output equality.

Judgment checks (content correctness, completeness, calibration) are NOT here —
they need a human and run via the `extraction-quality-review` skill. At N=4 this
is a smoke test, not a pass-rate metric (`writing-evals`: statistical honesty).

The pure checkers below are unit-tested directly (deterministic code, `tdd`
discipline). The parametrized golden-dir tests apply them to recorded data;
fixture-wellformedness runs now, the extraction-dependent checks `skip` until a
key-gated live run drops an `extraction.json` into each PR dir (kept as a
replayable fixture so re-runs need no API key / token cost, per Phase0 §5).
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from atlas.models.schema import Edge, Node, NodeType

GOLDEN_ROOT = Path(__file__).parent / "golden_set"
GOLDEN_DIRS = sorted(p for p in GOLDEN_ROOT.glob("pr-*") if p.is_dir())
JIRA_DIRS = sorted(p for p in GOLDEN_ROOT.glob("jira-*") if p.is_dir())
_VALID_NODE_TYPES = {t.value for t in NodeType}


# --- pure checkers -------------------------------------------------------------


def corpus_text(raw: Mapping[str, Any]) -> str:
    """All source text a provenance excerpt could legitimately come from: the PR
    title/body, every conversation comment, and every linked issue + commit that
    was recorded for this PR."""
    parts: list[str] = []
    pr = raw.get("pull_request") or {}
    parts.append(pr.get("title") or "")
    parts.append(pr.get("body") or "")
    for comment in pr.get("comments") or []:
        parts.append(comment.get("body") or "")
    for issue in raw.get("linked_issues") or []:
        parts.append(issue.get("title") or "")
        parts.append(issue.get("body") or "")
    for commit in raw.get("commits") or []:
        parts.append(commit.get("message") or "")
    return "\n".join(parts)


def _normalize_ws(text: str) -> str:
    """Collapse any whitespace run to a single space so an excerpt that differs
    from the source only in wrapping/indentation still matches."""
    return " ".join(text.split())


def excerpt_in_corpus(excerpt: str, corpus: str) -> bool:
    if not excerpt.strip():
        return False
    return _normalize_ws(excerpt) in _normalize_ws(corpus)


def unprovenanced_excerpts(nodes: list[Node], corpus: str) -> list[tuple[str, str]]:
    """(node_id, excerpt) pairs whose excerpt can't be found in the source corpus.
    Empty list == every claim is traceable to literal source text."""
    misses: list[tuple[str, str]] = []
    for node in nodes:
        for ref in node.source_refs:
            if not excerpt_in_corpus(ref.excerpt, corpus):
                misses.append((str(node.id), ref.excerpt))
    return misses


def jira_corpus(raw: Mapping[str, Any]) -> str:
    """All source text an excerpt from *one* Jira issue could legitimately quote:
    its summary, its description, every comment body, and the summaries of the
    issues it links to (which the agent is shown verbatim)."""
    issue = raw.get("issue") or {}
    parts: list[str] = [issue.get("summary") or "", issue.get("description") or ""]
    for comment in issue.get("comments") or []:
        parts.append(comment.get("body") or "")
    for link in issue.get("links") or []:
        parts.append(link.get("summary") or "")
    return "\n".join(parts)


def jira_corpora(directories: list[Path]) -> dict[str, str]:
    """`{issue key: its corpus}` across every recorded Jira fixture.

    Keyed by issue rather than merged into one blob because a Jira extraction
    legitimately quotes *other* issues -- both recorded runs pull background from
    the epic (SCRUM-6) while ingesting a child. Against a merged corpus, an
    excerpt lifted from the epic but stamped with the child's id and URL would
    pass: the text is "in the sources" somewhere. That is precisely the failure
    this project exists to prevent -- a reviewer clicks a plausible link and
    lands on a page that does not contain the claim -- so the check has to be
    per-source, not per-run.
    """
    corpora: dict[str, str] = {}
    for directory in directories:
        raw = json.loads((directory / "raw.json").read_text())
        key = raw.get("issue_key")
        if key:
            corpora[str(key)] = jira_corpus(raw)
    return corpora


def misattributed_excerpts(
    nodes: list[Node], corpora: Mapping[str, str]
) -> list[tuple[str, str, str]]:
    """`(node id, external id, problem)` for every ref that cannot be verified
    against the source it names. Empty == every excerpt is literally present in
    the specific issue its provenance points at.

    A ref naming an issue that was never recorded is reported, not skipped: an
    excerpt nobody can check is not the same as a correct one, and silently
    passing it would put the one non-negotiable guarantee on the honour system.
    """
    misses: list[tuple[str, str, str]] = []
    for node in nodes:
        for ref in node.source_refs:
            corpus = corpora.get(ref.external_id)
            if corpus is None:
                misses.append((str(node.id), ref.external_id, "source not recorded"))
            elif not excerpt_in_corpus(ref.excerpt, corpus):
                misses.append((str(node.id), ref.external_id, ref.excerpt))
    return misses


def rubric_failures(nodes: list[Node], rubric: Mapping[str, Any]) -> list[str]:
    """Human-readable rubric violations; empty == the rubric is satisfied.

    Floors (`required_node_types`, `must_mention`) ask "did extraction find what
    is there". Ceilings (`max_nodes`, `max_confidence`) ask the opposite question
    -- "did it invent claims where there are none, and how sure did it sound" --
    and only apply to fixtures that carry no extractable feature content. See
    golden_set/jira-SCRUM-1/rubric.yaml.
    """
    failures: list[str] = []
    present_types = {node.type.value for node in nodes}
    for required in rubric.get("required_node_types") or []:
        if required not in present_types:
            failures.append(f"missing required node type: {required}")
    contents = [node.content.lower() for node in nodes]
    for keyword in rubric.get("must_mention") or []:
        if not any(str(keyword).lower() in content for content in contents):
            failures.append(f"no node mentions {keyword!r}")

    max_nodes = rubric.get("max_nodes")
    if max_nodes is not None and len(nodes) > int(max_nodes):
        failures.append(f"over-extraction: {len(nodes)} nodes, ceiling is {max_nodes}")
    ceiling = rubric.get("max_confidence")
    if ceiling is not None:
        overconfident = [
            f"{node.type.value}@{node.confidence_score}"
            for node in nodes
            if node.confidence_score is not None and node.confidence_score > float(ceiling)
        ]
        if overconfident:
            failures.append(
                f"confidence above the {ceiling} ceiling for content with no "
                f"feature claims: {overconfident}"
            )
    return failures


def duplicate_claims(nodes: list[Node]) -> list[str]:
    """Nodes that cite the *identical* excerpt -- the deterministic half of the
    duplication finding.

    The 2026-08-14 Jira quality run found the agent emitting a `goal` that
    restated a `requirement`/`decision` it had already emitted, in three of four
    tickets, once off the byte-identical excerpt. That last case is checkable
    without judgement, and it is the worst one: a reviewer is asked to rule twice
    on one idea and can confirm one copy while rejecting the other, leaving the
    feature holding two contradictory answers with the same citation.

    Restating *in different words* is real too and is deliberately **not** graded
    here -- it needs a human, and it belongs to the Tier-2 pass
    (`extraction-quality-review`). A checker that guessed at paraphrase would be
    grading its own similarity threshold rather than the extraction.

    A fixture may opt out with `allow_shared_excerpts: true` when one long quote
    genuinely carries two different claims.
    """
    by_excerpt: dict[str, list[Node]] = {}
    for node in nodes:
        for ref in node.source_refs:
            by_excerpt.setdefault(" ".join(ref.excerpt.split()), []).append(node)
    return [
        f"{len(sharing)} nodes ({', '.join(sorted(n.type.value for n in sharing))}) "
        f"cite the same excerpt: {excerpt[:70]!r}"
        for excerpt, sharing in by_excerpt.items()
        if len({node.id for node in sharing}) > 1
    ]


def load_extraction(path: Path) -> tuple[list[Node], list[Edge]]:
    """Parse a recorded `extraction.json` through the schema gate. Raises
    pydantic.ValidationError on anything malformed -- that IS the schema check."""
    data = json.loads(path.read_text())
    nodes = [Node.model_validate(n) for n in data.get("nodes", [])]
    edges = [Edge.model_validate(e) for e in data.get("edges", [])]
    return nodes, edges


def load_rubric(path: Path) -> dict[str, Any]:
    parsed = yaml.safe_load(path.read_text())
    assert isinstance(parsed, dict), f"{path} must be a YAML mapping"
    return parsed


# --- unit tests for the checkers (hand-built inputs, no golden data needed) -----


def _source_ref(excerpt: str) -> dict[str, Any]:
    return {
        "source_type": "github_pr",
        "external_id": "1",
        "url": "https://github.com/o/r/pull/1",
        "excerpt": excerpt,
    }


def _node(*, node_type: str, content: str, excerpt: str) -> Node:
    import uuid

    return Node.model_validate(
        {
            "type": node_type,
            "content": content,
            "confidence_score": 0.7,
            "source_refs": [_source_ref(excerpt) | {"workspace_id": str(uuid.uuid4())}],
            "workspace_id": str(uuid.uuid4()),
            "feature_scope_id": str(uuid.uuid4()),
        }
    )


def test_corpus_text_collects_body_comments_and_issues() -> None:
    raw = {
        "pull_request": {
            "title": "T",
            "body": "PR body text",
            "comments": [{"body": "a comment"}],
        },
        "linked_issues": [{"title": "IT", "body": "issue body text"}],
        "commits": [{"message": "commit msg"}],
    }
    text = corpus_text(raw)
    for expected in ("PR body text", "a comment", "issue body text", "commit msg", "T", "IT"):
        assert expected in text


def test_excerpt_matching_is_whitespace_tolerant() -> None:
    corpus = "the quick brown\n    fox jumps"
    assert excerpt_in_corpus("quick brown fox", corpus)  # newline+indent collapsed


def test_excerpt_matching_rejects_absent_or_blank() -> None:
    assert not excerpt_in_corpus("never appears", "some source text")
    assert not excerpt_in_corpus("   ", "some source text")


def test_unprovenanced_flags_only_the_fabricated_excerpt() -> None:
    corpus = "we should skip traversing directories below a depth"
    good = _node(node_type="goal", content="limit depth", excerpt="skip traversing directories")
    bad = _node(node_type="decision", content="x", excerpt="a claim never in the source")
    misses = unprovenanced_excerpts([good, bad], corpus)
    assert [m[1] for m in misses] == ["a claim never in the source"]


def test_rubric_flags_missing_type_and_mention() -> None:
    nodes = [_node(node_type="goal", content="about depth", excerpt="depth")]
    rubric = {"required_node_types": ["goal", "decision"], "must_mention": ["depth", "padding"]}
    failures = rubric_failures(nodes, rubric)
    assert any("decision" in f for f in failures)
    assert any("padding" in f for f in failures)
    assert not any("goal" in f for f in failures)


def test_rubric_passes_when_floor_met() -> None:
    nodes = [
        _node(node_type="goal", content="fixed width line numbers", excerpt="line numbers"),
        _node(node_type="constraint", content="format needs padding", excerpt="padding"),
    ]
    rubric = {"required_node_types": ["goal", "constraint"], "must_mention": ["line", "padding"]}
    assert rubric_failures(nodes, rubric) == []


def test_jira_corpus_collects_summary_description_comments_and_links() -> None:
    raw = {
        "issue_key": "GATE-42",
        "issue": {
            "summary": "Rate-limit the gateway",
            "description": "We must throttle per client IP.",
            "comments": [{"body": "buffer, not stream"}],
            "links": [{"key": "GATE-7", "summary": "linked issue summary"}],
        },
    }
    text = jira_corpus(raw)
    for expected in ("Rate-limit", "throttle per client IP", "buffer", "linked issue summary"):
        assert expected in text


def _jira_node(*, external_id: str, excerpt: str) -> Node:
    import uuid

    return Node.model_validate(
        {
            "type": "decision",
            "content": "a claim",
            "confidence_score": 0.9,
            "source_refs": [
                {
                    "source_type": "jira_ticket",
                    "external_id": external_id,
                    "url": f"https://acme.atlassian.net/browse/{external_id}",
                    "excerpt": excerpt,
                    "workspace_id": str(uuid.uuid4()),
                }
            ],
            "workspace_id": str(uuid.uuid4()),
            "feature_scope_id": str(uuid.uuid4()),
        }
    )


def test_misattribution_is_caught_even_though_the_text_exists_elsewhere() -> None:
    """The check that a merged-corpus check cannot make. The excerpt is real and
    appears verbatim in the epic -- but the node points a reviewer at the child
    issue, where it does not appear. Plausible link, wrong page."""
    corpora = {"SCRUM-6": "the epic explains the monorepo background", "SCRUM-10": "mindepth?"}
    node = _jira_node(external_id="SCRUM-10", excerpt="the epic explains the monorepo background")

    misses = misattributed_excerpts([node], corpora)

    assert [(m[1], m[2]) for m in misses] == [
        ("SCRUM-10", "the epic explains the monorepo background")
    ]


def test_quoting_another_issue_passes_when_attributed_to_that_issue() -> None:
    corpora = {"SCRUM-6": "the epic explains the monorepo background", "SCRUM-10": "mindepth?"}
    node = _jira_node(external_id="SCRUM-6", excerpt="the epic explains the monorepo background")

    assert misattributed_excerpts([node], corpora) == []


def test_a_ref_to_an_unrecorded_source_is_reported_not_skipped() -> None:
    node = _jira_node(external_id="SCRUM-99", excerpt="anything at all")

    misses = misattributed_excerpts([node], {"SCRUM-6": "..."})

    assert misses == [(str(node.id), "SCRUM-99", "source not recorded")]


def test_rubric_ceilings_flag_volume_and_overconfidence() -> None:
    nodes = [
        _node(node_type="requirement", content="a", excerpt="a"),
        _node(node_type="requirement", content="b", excerpt="b"),
    ]
    failures = rubric_failures(nodes, {"max_nodes": 1, "max_confidence": 0.6})

    assert any("over-extraction" in f for f in failures)
    assert any("ceiling" in f and "0.6" in f for f in failures)  # _node builds at 0.7


def test_rubric_ceilings_pass_when_within_limits() -> None:
    nodes = [_node(node_type="requirement", content="a", excerpt="a")]

    assert rubric_failures(nodes, {"max_nodes": 4, "max_confidence": 0.7}) == []


def test_load_extraction_enforces_schema_gate(tmp_path: Path) -> None:
    # A node with an empty source_refs list must fail the provenance gate on read.
    bad = {"nodes": [{"type": "goal", "content": "x", "confidence_score": 0.5, "source_refs": []}]}
    path = tmp_path / "extraction.json"
    path.write_text(json.dumps(bad))
    with pytest.raises(ValidationError):
        load_extraction(path)


# --- fixture wellformedness (runs now, no extraction.json required) -------------


def test_golden_set_is_non_empty() -> None:
    assert GOLDEN_DIRS, "no golden_set/pr-* fixtures found"


@pytest.mark.parametrize("golden_dir", GOLDEN_DIRS, ids=[p.name for p in GOLDEN_DIRS])
def test_raw_json_wellformed(golden_dir: Path) -> None:
    raw = json.loads((golden_dir / "raw.json").read_text())
    assert raw.get("pull_request", {}).get("body") is not None
    assert corpus_text(raw).strip(), "recorded corpus is empty"


@pytest.mark.parametrize("golden_dir", GOLDEN_DIRS, ids=[p.name for p in GOLDEN_DIRS])
def test_rubric_yaml_wellformed(golden_dir: Path) -> None:
    rubric = load_rubric(golden_dir / "rubric.yaml")
    required = rubric.get("required_node_types") or []
    assert required, "rubric must require at least one node type"
    unknown = set(required) - _VALID_NODE_TYPES
    assert not unknown, f"rubric references unknown node types: {unknown}"
    assert rubric.get("must_mention"), "rubric must list at least one must_mention keyword"


# --- extraction-dependent checks (skip until a live run records extraction.json) -


@pytest.mark.parametrize("golden_dir", GOLDEN_DIRS, ids=[p.name for p in GOLDEN_DIRS])
def test_extraction_schema_valid(golden_dir: Path) -> None:
    path = golden_dir / "extraction.json"
    if not path.exists():
        pytest.skip(f"no recorded extraction.json for {golden_dir.name} yet")
    nodes, _ = load_extraction(path)
    assert nodes, "extraction produced no nodes"


@pytest.mark.parametrize("golden_dir", GOLDEN_DIRS, ids=[p.name for p in GOLDEN_DIRS])
def test_extraction_provenance(golden_dir: Path) -> None:
    path = golden_dir / "extraction.json"
    if not path.exists():
        pytest.skip(f"no recorded extraction.json for {golden_dir.name} yet")
    nodes, _ = load_extraction(path)
    corpus = corpus_text(json.loads((golden_dir / "raw.json").read_text()))
    misses = unprovenanced_excerpts(nodes, corpus)
    assert not misses, f"unprovenanced excerpts (not found in source): {misses}"


@pytest.mark.parametrize("golden_dir", GOLDEN_DIRS, ids=[p.name for p in GOLDEN_DIRS])
def test_extraction_has_no_duplicate_claims(golden_dir: Path) -> None:
    """Pins the 2026-08-15 de-duplication prompt change so it cannot regress."""
    path = golden_dir / "extraction.json"
    if not path.exists():
        pytest.skip(f"no recorded extraction.json for {golden_dir.name} yet")
    if load_rubric(golden_dir / "rubric.yaml").get("allow_shared_excerpts"):
        pytest.skip(f"{golden_dir.name} allows one excerpt to carry two claims")
    nodes, _ = load_extraction(path)
    duplicates = duplicate_claims(nodes)
    assert not duplicates, f"{golden_dir.name} emits duplicate claims: {duplicates}"


@pytest.mark.parametrize("golden_dir", GOLDEN_DIRS, ids=[p.name for p in GOLDEN_DIRS])
def test_extraction_meets_rubric(golden_dir: Path) -> None:
    path = golden_dir / "extraction.json"
    if not path.exists():
        pytest.skip(f"no recorded extraction.json for {golden_dir.name} yet")
    nodes, _ = load_extraction(path)
    failures = rubric_failures(nodes, load_rubric(golden_dir / "rubric.yaml"))
    assert not failures, f"{golden_dir.name} rubric floor not met: {failures}"


# --- the Jira half of the golden set (slice 1C) ---------------------------------
#
# Same three deterministic checks, one structural difference: provenance is
# verified **per source issue** rather than against a merged corpus, because a
# Jira extraction routinely quotes an issue other than the one being ingested.
# Re-record with `scripts/record_jira_golden.py` after any prompt/tool change.
#
# Read `golden_set/jira-SCRUM-7/rubric.yaml` before trusting a green run here:
# four of these five fixtures were authored by the build team, and the
# `writing-evals` skill is explicit that synthetic examples inflate scores.
# jira-SCRUM-1 is the one that was not.


@pytest.mark.parametrize("golden_dir", JIRA_DIRS, ids=[p.name for p in JIRA_DIRS])
def test_jira_raw_json_wellformed(golden_dir: Path) -> None:
    raw = json.loads((golden_dir / "raw.json").read_text())
    assert raw.get("issue_key"), "raw.json must record which issue it is"
    assert jira_corpus(raw).strip(), "recorded corpus is empty"


@pytest.mark.parametrize("golden_dir", JIRA_DIRS, ids=[p.name for p in JIRA_DIRS])
def test_jira_rubric_yaml_wellformed(golden_dir: Path) -> None:
    """Looser than the PR equivalent by design: a ceiling-only rubric (the
    restraint fixture) states no floor at all, and that is the point of it."""
    path = golden_dir / "rubric.yaml"
    if not path.exists():
        pytest.skip(f"{golden_dir.name} is corpus-only (no extraction is graded)")
    rubric = load_rubric(path)
    graded_by = {"required_node_types", "must_mention", "max_nodes", "max_confidence"}
    assert graded_by & rubric.keys(), f"rubric grades nothing: expected one of {sorted(graded_by)}"
    unknown = set(rubric.get("required_node_types") or []) - _VALID_NODE_TYPES
    assert not unknown, f"rubric references unknown node types: {unknown}"


@pytest.mark.parametrize("golden_dir", JIRA_DIRS, ids=[p.name for p in JIRA_DIRS])
def test_jira_extraction_schema_valid(golden_dir: Path) -> None:
    path = golden_dir / "extraction.json"
    if not path.exists():
        pytest.skip(f"no recorded extraction.json for {golden_dir.name}")
    nodes, _ = load_extraction(path)
    assert nodes, "extraction produced no nodes"


@pytest.mark.parametrize("golden_dir", JIRA_DIRS, ids=[p.name for p in JIRA_DIRS])
def test_jira_extraction_provenance(golden_dir: Path) -> None:
    path = golden_dir / "extraction.json"
    if not path.exists():
        pytest.skip(f"no recorded extraction.json for {golden_dir.name}")
    nodes, _ = load_extraction(path)
    misses = misattributed_excerpts(nodes, jira_corpora(JIRA_DIRS))
    assert not misses, f"excerpts not found in the issue they point at: {misses}"


@pytest.mark.parametrize("golden_dir", JIRA_DIRS, ids=[p.name for p in JIRA_DIRS])
def test_jira_extraction_has_no_duplicate_claims(golden_dir: Path) -> None:
    """The check the 2026-08-14 finding earned. This is where it was found."""
    path = golden_dir / "extraction.json"
    rubric_path = golden_dir / "rubric.yaml"
    if not path.exists():
        pytest.skip(f"no recorded extraction.json for {golden_dir.name}")
    if rubric_path.exists() and load_rubric(rubric_path).get("allow_shared_excerpts"):
        pytest.skip(f"{golden_dir.name} allows one excerpt to carry two claims")
    nodes, _ = load_extraction(path)
    duplicates = duplicate_claims(nodes)
    assert not duplicates, f"{golden_dir.name} emits duplicate claims: {duplicates}"


@pytest.mark.parametrize("golden_dir", JIRA_DIRS, ids=[p.name for p in JIRA_DIRS])
def test_jira_extraction_meets_rubric(golden_dir: Path) -> None:
    path = golden_dir / "extraction.json"
    if not path.exists():
        pytest.skip(f"no recorded extraction.json for {golden_dir.name}")
    nodes, _ = load_extraction(path)
    failures = rubric_failures(nodes, load_rubric(golden_dir / "rubric.yaml"))
    assert not failures, f"{golden_dir.name} rubric not met: {failures}"


# --- cross-source conflicts (the fixture the 2026-08-14 review asked for) -------
#
# `conflicts_with` across two sources is the thing Atlas does that reading either
# tool alone cannot, and until this fixture it had no deterministic coverage: the
# five conflicts found live on 2026-08-13 were judged by eye and never recorded,
# so a prompt change that quietly stopped finding them would have passed every
# test. The fixture holds three files rather than two — `known.json` is the claims
# the *other* source had already produced, which is the whole input that makes a
# cross-source conflict possible.

CROSS_DIRS = sorted(p for p in GOLDEN_ROOT.glob("cross-*") if p.is_dir())


def offered_ids(golden_dir: Path) -> set[str]:
    known = json.loads((golden_dir / "known.json").read_text())
    return {str(Node.model_validate(node).id) for node in known["nodes"]}


def cross_source_conflicts(edges: list[Edge], offered: set[str]) -> list[Edge]:
    """Edges that disagree with a claim the other source made."""
    return [
        edge
        for edge in edges
        if edge.relation_type.value == "conflicts_with" and str(edge.to_node_id) in offered
    ]


def fabricated_endpoints(nodes: list[Node], edges: list[Edge], offered: set[str]) -> list[str]:
    """Edge endpoints that are neither this run's own nodes nor ids it was offered.

    `agent.build_result` already refuses these, so a hit means the gate regressed.
    It is checked twice on purpose: a fabricated relationship is indistinguishable
    from a real one once stored, which is the failure this product exists to
    prevent.
    """
    known = {str(node.id) for node in nodes} | offered
    return [
        f"{edge.relation_type.value} -> {endpoint}"
        for edge in edges
        for endpoint in (str(edge.from_node_id), str(edge.to_node_id))
        if endpoint not in known
    ]


@pytest.mark.parametrize("golden_dir", CROSS_DIRS, ids=[p.name for p in CROSS_DIRS])
def test_cross_source_fixture_is_wellformed(golden_dir: Path) -> None:
    known = json.loads((golden_dir / "known.json").read_text())
    assert known.get("from"), "known.json must record which extraction it came from"
    assert known["nodes"], "a cross-source run with no known nodes is a first ingestion"


@pytest.mark.parametrize("golden_dir", CROSS_DIRS, ids=[p.name for p in CROSS_DIRS])
def test_cross_source_provenance(golden_dir: Path) -> None:
    """The new claims still quote the issue they came from — a conflict is not a
    licence to paraphrase."""
    nodes, _ = load_extraction(golden_dir / "extraction.json")
    misses = misattributed_excerpts(nodes, jira_corpora([*JIRA_DIRS, golden_dir]))
    assert not misses, f"excerpts not found in the issue they point at: {misses}"


@pytest.mark.parametrize("golden_dir", CROSS_DIRS, ids=[p.name for p in CROSS_DIRS])
def test_cross_source_edges_never_reach_a_node_nobody_offered(golden_dir: Path) -> None:
    nodes, edges = load_extraction(golden_dir / "extraction.json")
    fabricated = fabricated_endpoints(nodes, edges, offered_ids(golden_dir))
    assert not fabricated, f"edges reach ids that were never offered: {fabricated}"


@pytest.mark.parametrize("golden_dir", CROSS_DIRS, ids=[p.name for p in CROSS_DIRS])
def test_cross_source_conflicts_are_actually_found(golden_dir: Path) -> None:
    """The floor is below what the recording achieved, deliberately: a floor set
    at the observed number grades this sample rather than the behaviour. What
    must not happen is finding none."""
    rubric = load_rubric(golden_dir / "rubric.yaml")
    _, edges = load_extraction(golden_dir / "extraction.json")
    found = cross_source_conflicts(edges, offered_ids(golden_dir))
    floor = int(rubric.get("min_cross_source_conflicts", 1))
    assert len(found) >= floor, (
        f"{golden_dir.name} found {len(found)} cross-source conflict(s), floor is {floor} — "
        "the second source was ingested next to the first, each unaware of it"
    )


@pytest.mark.parametrize("golden_dir", CROSS_DIRS, ids=[p.name for p in CROSS_DIRS])
def test_cross_source_meets_rubric(golden_dir: Path) -> None:
    nodes, _ = load_extraction(golden_dir / "extraction.json")
    failures = rubric_failures(nodes, load_rubric(golden_dir / "rubric.yaml"))
    assert not failures, f"{golden_dir.name} rubric not met: {failures}"
