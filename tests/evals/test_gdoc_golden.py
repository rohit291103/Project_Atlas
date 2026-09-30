"""Tier-1 eval for Google Docs extraction over recorded doc fixtures (Phase 3).

Same three deterministic checks as the PR golden set, plus one that only a doc
source needs: every citation names the doc as `gdoc` with its own id, because
the agent writes each `source_ref` itself and `gdoc` is not a value it could
infer. Offline, over `gdoc-*/extraction.json`; skips a fixture until recorded.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from atlas.models.schema import Edge, Node

GOLDEN = Path(__file__).parent / "golden_set"
DOC_DIRS = sorted(p for p in GOLDEN.glob("gdoc-*") if p.is_dir())


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _load(directory: Path) -> tuple[dict[str, Any], list[Node], list[Edge]]:
    extraction = directory / "extraction.json"
    if not extraction.exists():
        pytest.skip(f"no recorded extraction for {directory.name}")
    raw = json.loads((directory / "raw.json").read_text())
    data = json.loads(extraction.read_text())
    return (
        raw,
        [Node.model_validate(n) for n in data["nodes"]],
        [Edge.model_validate(e) for e in data["edges"]],
    )


@pytest.mark.parametrize("directory", DOC_DIRS, ids=[d.name for d in DOC_DIRS])
def test_every_excerpt_is_verbatim_in_the_document(directory: Path) -> None:
    raw, nodes, _ = _load(directory)
    corpus = _squash(raw["text"])
    missing = [
        ref.excerpt
        for node in nodes
        for ref in node.source_refs
        if _squash(ref.excerpt) not in corpus
    ]
    assert missing == [], f"fabricated or altered excerpts: {missing}"


@pytest.mark.parametrize("directory", DOC_DIRS, ids=[d.name for d in DOC_DIRS])
def test_every_citation_names_the_doc(directory: Path) -> None:
    raw, nodes, _ = _load(directory)
    wrong = [
        (ref.source_type.value, ref.external_id)
        for node in nodes
        for ref in node.source_refs
        if ref.source_type.value != "gdoc" or ref.external_id != raw["id"]
    ]
    assert wrong == []


@pytest.mark.parametrize("directory", DOC_DIRS, ids=[d.name for d in DOC_DIRS])
def test_rubric_floor(directory: Path) -> None:
    _, nodes, edges = _load(directory)
    rubric = yaml.safe_load((directory / "rubric.yaml").read_text())
    types = {node.type.value for node in nodes}
    missing_types = [t for t in rubric.get("required_node_types", []) if t not in types]
    known = set(rubric.get("known_gaps", []))
    if missing_types and set(missing_types) <= known:
        # A recorded, explained miss: reported every run as an expected
        # failure, never silently passed and never dropped from the floor.
        pytest.xfail(f"known gap, see rubric.yaml: missing {missing_types}")
    assert missing_types == [], f"missing required node types: {missing_types}"
    for keyword in rubric.get("must_mention", []):
        assert any(keyword.lower() in node.content.lower() for node in nodes), keyword
    ids = {node.id for node in nodes}
    assert all(e.from_node_id in ids for e in edges), "an edge starts at an unknown node"
