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
from collections.abc import Callable

import httpx
import pytest
import typer
from rich.console import Console
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from atlas.cli import _parse_repo, record_extraction, render_projection, resolve_jira_keys
from atlas.extraction.agent import build_result
from atlas.ingestion.jira import JiraClient
from atlas.models.schema import (
    CreatedBy,
    IngestionRunPayload,
    Node,
    NodeStatus,
    NodeType,
    SourceRef,
    SourceType,
)
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


def _sample_run() -> IngestionRunPayload:
    return IngestionRunPayload(
        feature_scope_id=FEATURE_SCOPE_ID,
        title="Rate-limit the gateway per client IP",
        source_type=SourceType.GITHUB_PR,
        external_id="acme/gateway#42",
        url="https://github.com/acme/gateway/pull/42",
    )


# --- _parse_repo ---------------------------------------------------------------


def test_parse_repo_splits_owner_and_name() -> None:
    assert _parse_repo("acme/gateway") == ("acme", "gateway")


@pytest.mark.parametrize("bad", ["gateway", "acme/", "/gateway", ""])
def test_parse_repo_rejects_malformed(bad: str) -> None:
    with pytest.raises(typer.BadParameter):
        _parse_repo(bad)


# --- scoped Jira ingestion (slice 1D, TRD Sec4.2) ------------------------------


def _jira_client(handler: Callable[[httpx.Request], httpx.Response]) -> JiraClient:
    return JiraClient(
        base_url="https://acme.atlassian.net",
        email="pm@acme.test",
        api_token="t",
        transport=httpx.MockTransport(handler),
    )


def _capture_jql() -> tuple[dict[str, str], Callable[[httpx.Request], httpx.Response]]:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(request.url.params)
        return httpx.Response(200, json={"issues": [{"key": "GATE-43", "fields": {}}]})

    return seen, handler


def test_resolve_jira_keys_for_a_single_issue_makes_no_request() -> None:
    """`--issue` is already a scope of one; searching for it would be a wasted
    round trip and a wider read than asked for."""

    def refuse(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no search should be issued for --issue")

    keys = resolve_jira_keys(_jira_client(refuse), issue="GATE-42", epic=None, label=None, limit=10)

    assert keys == ["GATE-42"]


def test_resolve_jira_keys_scopes_by_epic() -> None:
    seen, handler = _capture_jql()

    keys = resolve_jira_keys(_jira_client(handler), issue=None, epic="GATE-1", label=None, limit=10)

    assert keys == ["GATE-43"]
    assert 'parent = "GATE-1"' in seen["jql"]


def test_resolve_jira_keys_scopes_by_label() -> None:
    seen, handler = _capture_jql()

    keys = resolve_jira_keys(
        _jira_client(handler), issue=None, epic=None, label="gateway", limit=10
    )

    assert 'labels = "gateway"' in seen["jql"]
    assert keys == ["GATE-43"]


def test_resolve_jira_keys_passes_the_limit_as_a_hard_ceiling() -> None:
    """A mistyped label must not start an unbounded ingestion run."""
    seen, handler = _capture_jql()

    resolve_jira_keys(_jira_client(handler), issue=None, epic=None, label="typo", limit=3)

    assert seen["maxResults"] == "3"


def test_resolve_jira_keys_requires_a_scope() -> None:
    with pytest.raises(typer.BadParameter):
        resolve_jira_keys(
            _jira_client(lambda request: httpx.Response(200, json={})),
            issue=None,
            epic=None,
            label=None,
            limit=10,
        )


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
        record_extraction(
            session,
            result,  # type: ignore[arg-type]
            workspace_id=WORKSPACE_ID,
            ingestion_run=_sample_run(),
        )

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


def test_record_extraction_gives_the_feature_scope_an_identity(
    session_factory: sessionmaker[Session],
) -> None:
    """Slice 1A': an ingestion run records *what* was ingested, so a scope is
    something a PM can recognize rather than a bare UUID."""
    with session_scope(session_factory) as session:
        record_extraction(
            session,
            _sample_result(),  # type: ignore[arg-type]
            workspace_id=WORKSPACE_ID,
            ingestion_run=_sample_run(),
        )

    with session_scope(session_factory) as session:
        projection = load_projection(
            session, workspace_id=WORKSPACE_ID, feature_scope_id=FEATURE_SCOPE_ID
        )

    scope = projection.feature_scopes[FEATURE_SCOPE_ID]
    assert scope.title == "Rate-limit the gateway per client IP"
    assert scope.runs[0].url == "https://github.com/acme/gateway/pull/42"


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
        record_extraction(
            session,
            result,  # type: ignore[arg-type]
            workspace_id=WORKSPACE_ID,
            ingestion_run=_sample_run(),
        )
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


def test_render_projection_titles_the_report_with_the_feature_scope(
    session_factory: sessionmaker[Session],
) -> None:
    """`atlas review` is the engineer-facing read path for the same projection
    the UI's header will use -- it names the scope rather than echoing a UUID."""
    with session_scope(session_factory) as session:
        record_extraction(
            session,
            _sample_result(),  # type: ignore[arg-type]
            workspace_id=WORKSPACE_ID,
            ingestion_run=_sample_run(),
        )
    with session_scope(session_factory) as session:
        projection = load_projection(
            session, workspace_id=WORKSPACE_ID, feature_scope_id=FEATURE_SCOPE_ID
        )

    text = _render(projection)

    assert "Rate-limit the gateway per client IP" in text
    assert "acme/gateway#42" in text


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
