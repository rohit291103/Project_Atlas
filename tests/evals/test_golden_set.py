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


def rubric_failures(nodes: list[Node], rubric: Mapping[str, Any]) -> list[str]:
    """Human-readable rubric-floor violations; empty == the floor is met."""
    failures: list[str] = []
    present_types = {node.type.value for node in nodes}
    for required in rubric.get("required_node_types") or []:
        if required not in present_types:
            failures.append(f"missing required node type: {required}")
    contents = [node.content.lower() for node in nodes]
    for keyword in rubric.get("must_mention") or []:
        if not any(str(keyword).lower() in content for content in contents):
            failures.append(f"no node mentions {keyword!r}")
    return failures


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
def test_extraction_meets_rubric(golden_dir: Path) -> None:
    path = golden_dir / "extraction.json"
    if not path.exists():
        pytest.skip(f"no recorded extraction.json for {golden_dir.name} yet")
    nodes, _ = load_extraction(path)
    failures = rubric_failures(nodes, load_rubric(golden_dir / "rubric.yaml"))
    assert not failures, f"{golden_dir.name} rubric floor not met: {failures}"
