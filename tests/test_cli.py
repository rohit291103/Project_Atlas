"""Tests for the CLI's reusable pieces (cli.py) -- the parts that don't need a
live API key or database. `_parse_repo` is pure; `record_extraction` +
`render_projection` are exercised through an in-memory SQLite round trip, which
also proves the ingest-persist -> review-replay path end to end (minus the LLM):
events written by `record_extraction` reconstruct via `load_projection` into the
same nodes the report then renders.

The `ingest`/`review` command bodies themselves (env loading, live GitHub, the
agent, live Postgres) are intentionally not unit-tested -- that's the lighter
touch the tdd skill prescribes for CLI wiring.
"""

from __future__ import annotations

import uuid

import pytest
import typer
from rich.console import Console
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from atlas.cli import _parse_repo, record_extraction, render_projection
from atlas.extraction.agent import build_result
from atlas.models.schema import CreatedBy, Node, NodeStatus, NodeType, SourceRef, SourceType
from atlas.storage.db import Base, get_engine, get_sessionmaker, session_scope
from atlas.storage.projections import Projection, load_projection

WORKSPACE_ID = uuid.UUID(int=0)
FEATURE_SCOPE_ID = uuid.uuid4()


def _sample_result() -> object:
    payload = {
        "nodes": [
            {
                "ref": "n1",
                "type": "requirement",
                "content": "The gateway must rate-limit per client IP.",
                "confidence": "high",
                "source_refs": [
                    {
                        "source_type": "github_pr",
                        "external_id": "42",
                        "url": "https://github.com/acme/gateway/pull/42",
                        "excerpt": "adds a per-IP token-bucket limiter",
                    }
                ],
            },
            {
                "ref": "n2",
                "type": "problem",
                "content": "Gateway stalls under burst traffic.",
                "confidence": "medium",
                "source_refs": [
                    {
                        "source_type": "github_issue",
                        "external_id": "17",
                        "url": "https://github.com/acme/gateway/issues/17",
                        "excerpt": "the gateway's event loop stalls",
                    }
                ],
            },
        ],
        "edges": [
            {
                "from_ref": "n1",
                "to_ref": "n2",
                "relation_type": "derives_from",
                "confidence": "high",
            }
        ],
    }
    return build_result(payload, workspace_id=WORKSPACE_ID, feature_scope_id=FEATURE_SCOPE_ID)


# --- _parse_repo ---------------------------------------------------------------


def test_parse_repo_splits_owner_and_name() -> None:
    assert _parse_repo("acme/gateway") == ("acme", "gateway")


@pytest.mark.parametrize("bad", ["gateway", "acme/", "/gateway", ""])
def test_parse_repo_rejects_malformed(bad: str) -> None:
    with pytest.raises(typer.BadParameter):
        _parse_repo(bad)


# --- record_extraction + load_projection round trip ---------------------------


@pytest.fixture
def session_factory() -> sessionmaker[Session]:
    engine: Engine = get_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return get_sessionmaker(engine)


def test_record_extraction_round_trips_through_the_event_log(
    session_factory: sessionmaker[Session],
) -> None:
    result = _sample_result()

    with session_scope(session_factory) as session:
        record_extraction(session, result, workspace_id=WORKSPACE_ID)  # type: ignore[arg-type]

    with session_scope(session_factory) as session:
        projection = load_projection(
            session, workspace_id=WORKSPACE_ID, feature_scope_id=FEATURE_SCOPE_ID
        )

    assert {n.content for n in projection.nodes.values()} == {
        "The gateway must rate-limit per client IP.",
        "Gateway stalls under burst traffic.",
    }
    assert len(projection.edges) == 1
    # provenance survives the write/replay round trip
    excerpts = {ref.excerpt for node in projection.nodes.values() for ref in node.source_refs}
    assert "adds a per-IP token-bucket limiter" in excerpts


# --- render_projection ---------------------------------------------------------


def _render(projection: object) -> str:
    console = Console(record=True, width=200)
    console.print(render_projection(projection))  # type: ignore[arg-type]
    return console.export_text()


def test_render_projection_shows_content_confidence_status_and_provenance(
    session_factory: sessionmaker[Session],
) -> None:
    result = _sample_result()
    with session_scope(session_factory) as session:
        record_extraction(session, result, workspace_id=WORKSPACE_ID)  # type: ignore[arg-type]
    with session_scope(session_factory) as session:
        projection = load_projection(
            session, workspace_id=WORKSPACE_ID, feature_scope_id=FEATURE_SCOPE_ID
        )

    text = _render(projection)

    assert "requirement" in text
    assert "rate-limit per client IP" in text
    assert "0.90" in text  # high confidence
    assert "unconfirmed" in text  # drafts, never facts
    assert "adds a per-IP token-bucket limiter" in text  # literal excerpt
    assert "derives_from" in text  # edge rendered

    # edges are mappable: each endpoint's short id labels a node row in the report
    edge = next(iter(projection.edges.values()))  # type: ignore[attr-defined]
    for endpoint in (edge.from_node_id, edge.to_node_id):
        assert str(endpoint)[:8] in text
        assert endpoint in projection.nodes  # type: ignore[attr-defined]


def test_render_projection_handles_a_manually_added_node_with_no_confidence() -> None:
    """Manually-added nodes skip confidence scoring (TRD Sec6), so the report
    must render an absent score rather than crash formatting `None`."""
    node = Node(
        type=NodeType.CONSTRAINT,
        content="Must ship before the Q4 freeze.",
        created_by=CreatedBy.USER,
        status=NodeStatus.CONFIRMED,
        source_refs=[
            SourceRef(
                source_type=SourceType.GITHUB_PR,
                external_id="42",
                url="https://github.com/acme/gateway/pull/42",
                excerpt="Q4 freeze is 1 Dec.",
                workspace_id=WORKSPACE_ID,
            )
        ],
        workspace_id=WORKSPACE_ID,
        feature_scope_id=FEATURE_SCOPE_ID,
    )

    text = _render(Projection(nodes={node.id: node}))

    assert "Must ship before the Q4 freeze." in text
    assert "confirmed" in text


def test_render_projection_empty_scope_is_handled(
    session_factory: sessionmaker[Session],
) -> None:
    with session_scope(session_factory) as session:
        projection = load_projection(
            session, workspace_id=WORKSPACE_ID, feature_scope_id=uuid.uuid4()
        )
    assert "No nodes" in _render(projection)
