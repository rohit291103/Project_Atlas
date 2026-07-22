"""Tests for storage/projections.py: replaying the append-only event_log into
materialized Node/Edge state (TRD Sec3.1 "All Node/Edge state is a materialized
projection derived by replaying Events", Sec3.2 event-sourcing).

The pure `replay()` reducer is exercised with in-memory `Event` models (no DB,
no network); `load_projection()` is exercised against in-memory SQLite exactly
like test_storage.py, so nothing here needs live Supabase or secrets.

Note the validation gate is re-asserted on the *read* path too: a `node_created`
payload that doesn't satisfy the Node schema must fail to materialize, so a Node
without provenance can't sneak back in via the event log any more than it can go
in (CLAUDE.md: a Node without a SourceRef is a bug, not an edge case).
"""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from atlas.models.schema import (
    CreatedBy,
    Edge,
    Event,
    EventType,
    Node,
    NodeStatus,
    NodeType,
    RelationType,
    SourceRef,
    SourceType,
)
from atlas.storage.db import Base, get_engine, get_sessionmaker, session_scope
from atlas.storage.projections import Projection, load_projection, replay
from atlas.storage.tables import append_event

WORKSPACE_ID = uuid.UUID(int=0)
FEATURE_SCOPE_ID = uuid.uuid4()


# --- builders ------------------------------------------------------------------


def make_node(
    *,
    node_type: NodeType = NodeType.GOAL,
    content: str = "Ship the thing",
    feature_scope_id: uuid.UUID = FEATURE_SCOPE_ID,
    workspace_id: uuid.UUID = WORKSPACE_ID,
) -> Node:
    return Node(
        type=node_type,
        content=content,
        confidence_score=0.9,
        source_refs=[
            SourceRef(
                source_type=SourceType.GITHUB_PR,
                external_id="42",
                url="https://github.com/acme/repo/pull/42",
                excerpt="We want to ship the thing.",
                workspace_id=workspace_id,
            )
        ],
        workspace_id=workspace_id,
        feature_scope_id=feature_scope_id,
    )


def node_created(node: Node) -> Event:
    return Event(
        event_type=EventType.NODE_CREATED,
        payload=node.model_dump(mode="json"),
        actor="system",
        workspace_id=node.workspace_id,
    )


def edge_created(edge: Edge, *, workspace_id: uuid.UUID = WORKSPACE_ID) -> Event:
    return Event(
        event_type=EventType.EDGE_CREATED,
        payload=edge.model_dump(mode="json"),
        actor="system",
        workspace_id=workspace_id,
    )


# --- pure replay ---------------------------------------------------------------


def test_replay_empty_returns_empty_projection() -> None:
    projection = replay([])
    assert projection.nodes == {}
    assert projection.edges == {}


def test_replay_node_created_materializes_the_node() -> None:
    node = make_node()

    projection = replay([node_created(node)])

    assert list(projection.nodes) == [node.id]
    assert projection.nodes[node.id] == node


def test_replay_edge_created_materializes_the_edge() -> None:
    a, b = make_node(), make_node()
    edge = Edge(
        from_node_id=a.id,
        to_node_id=b.id,
        relation_type=RelationType.SUPPORTS,
        confidence_score=0.8,
    )

    projection = replay([node_created(a), node_created(b), edge_created(edge)])

    assert projection.nodes.keys() == {a.id, b.id}
    assert projection.edges[edge.id] == edge


def test_replay_preserves_all_distinct_nodes() -> None:
    nodes = [make_node(content=f"goal {i}") for i in range(3)]

    projection = replay([node_created(n) for n in nodes])

    assert projection.nodes.keys() == {n.id for n in nodes}


def test_replay_ingestion_run_event_has_no_node_edge_effect() -> None:
    audit = Event(
        event_type=EventType.INGESTION_RUN,
        payload={"pr": 42},
        actor="system",
        workspace_id=WORKSPACE_ID,
    )

    projection = replay([audit])

    assert projection.nodes == {}
    assert projection.edges == {}


def test_replay_spec_exported_event_has_no_node_edge_effect() -> None:
    export = Event(
        event_type=EventType.SPEC_EXPORTED,
        payload={"spec_version": 1},
        actor="system",
        workspace_id=WORKSPACE_ID,
    )

    projection = replay([export])

    assert projection.nodes == {}
    assert projection.edges == {}


@pytest.mark.parametrize(
    "event_type",
    [EventType.NODE_CONFIRMED, EventType.NODE_EDITED, EventType.NODE_REJECTED],
)
def test_replay_status_transition_events_are_phase_1(event_type: EventType) -> None:
    """confirm/edit/reject are emitted by Phase 1's confirmation UI, which does
    not exist yet. Rather than silently ignore them (which would let a rejected
    node still read as unconfirmed once those events arrive), replay fails loud
    so the gap is impossible to depend on by accident."""
    event = Event(
        event_type=event_type,
        payload={"node_id": str(uuid.uuid4())},
        actor="user",
        workspace_id=WORKSPACE_ID,
    )

    with pytest.raises(NotImplementedError):
        replay([event])


def test_replay_revalidates_node_payload_provenance_gate() -> None:
    """A node_created payload with no source_refs must fail to materialize --
    the provenance gate holds on the read path, not just the write path."""
    node = make_node()
    payload = node.model_dump(mode="json")
    payload["source_refs"] = []
    bad_event = Event(
        event_type=EventType.NODE_CREATED,
        payload=payload,
        actor="system",
        workspace_id=WORKSPACE_ID,
    )

    with pytest.raises(ValidationError):
        replay([bad_event])


# --- feature-scope filtering ---------------------------------------------------


def test_for_feature_scope_keeps_only_matching_nodes() -> None:
    other_scope = uuid.uuid4()
    in_scope = make_node(feature_scope_id=FEATURE_SCOPE_ID)
    out_scope = make_node(feature_scope_id=other_scope)

    projection = replay([node_created(in_scope), node_created(out_scope)])
    scoped = projection.for_feature_scope(FEATURE_SCOPE_ID)

    assert scoped.nodes.keys() == {in_scope.id}


def test_for_feature_scope_drops_edges_with_an_endpoint_outside_scope() -> None:
    other_scope = uuid.uuid4()
    a = make_node(feature_scope_id=FEATURE_SCOPE_ID)
    b = make_node(feature_scope_id=FEATURE_SCOPE_ID)
    outside = make_node(feature_scope_id=other_scope)
    internal_edge = Edge(
        from_node_id=a.id,
        to_node_id=b.id,
        relation_type=RelationType.SUPPORTS,
        confidence_score=0.8,
    )
    crossing_edge = Edge(
        from_node_id=a.id,
        to_node_id=outside.id,
        relation_type=RelationType.DEPENDS_ON,
        confidence_score=0.8,
    )

    projection = replay(
        [
            node_created(a),
            node_created(b),
            node_created(outside),
            edge_created(internal_edge),
            edge_created(crossing_edge),
        ]
    )
    scoped = projection.for_feature_scope(FEATURE_SCOPE_ID)

    assert scoped.edges.keys() == {internal_edge.id}


# --- DB-backed load_projection -------------------------------------------------


@pytest.fixture
def engine() -> Engine:
    engine = get_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def session_factory(engine: Engine) -> sessionmaker[Session]:
    return get_sessionmaker(engine)


def _write(session: Session, event: Event) -> None:
    append_event(
        session,
        event_type=event.event_type,
        payload=event.payload,
        actor=event.actor,
        workspace_id=event.workspace_id,
    )


def test_load_projection_replays_events_from_the_log(
    session_factory: sessionmaker[Session],
) -> None:
    a, b = make_node(), make_node()
    edge = Edge(
        from_node_id=a.id,
        to_node_id=b.id,
        relation_type=RelationType.SUPPORTS,
        confidence_score=0.8,
    )
    with session_scope(session_factory) as session:
        _write(session, node_created(a))
        _write(session, node_created(b))
        _write(session, edge_created(edge))

    with session_scope(session_factory) as session:
        projection = load_projection(session, workspace_id=WORKSPACE_ID)

    assert projection.nodes.keys() == {a.id, b.id}
    assert projection.edges.keys() == {edge.id}
    assert projection.nodes[a.id].status is NodeStatus.UNCONFIRMED
    assert projection.nodes[a.id].created_by is CreatedBy.SYSTEM


def test_load_projection_excludes_other_workspaces(
    session_factory: sessionmaker[Session],
) -> None:
    mine = make_node(workspace_id=WORKSPACE_ID)
    theirs_ws = uuid.uuid4()
    theirs = make_node(workspace_id=theirs_ws)
    with session_scope(session_factory) as session:
        _write(session, node_created(mine))
        _write(session, node_created(theirs))

    with session_scope(session_factory) as session:
        projection = load_projection(session, workspace_id=WORKSPACE_ID)

    assert projection.nodes.keys() == {mine.id}


def test_load_projection_filters_by_feature_scope(
    session_factory: sessionmaker[Session],
) -> None:
    scope_a = uuid.uuid4()
    scope_b = uuid.uuid4()
    in_a = make_node(feature_scope_id=scope_a)
    in_b = make_node(feature_scope_id=scope_b)
    with session_scope(session_factory) as session:
        _write(session, node_created(in_a))
        _write(session, node_created(in_b))

    with session_scope(session_factory) as session:
        projection = load_projection(session, workspace_id=WORKSPACE_ID, feature_scope_id=scope_a)

    assert projection.nodes.keys() == {in_a.id}


def test_load_projection_empty_log_is_empty(
    session_factory: sessionmaker[Session],
) -> None:
    with session_scope(session_factory) as session:
        projection = load_projection(session, workspace_id=WORKSPACE_ID)

    assert isinstance(projection, Projection)
    assert projection.nodes == {}
    assert projection.edges == {}
