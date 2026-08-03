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
from datetime import UTC, datetime, timedelta

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
    NodeEditPayload,
    NodeStatus,
    NodeStatusChangePayload,
    NodeType,
    RelationType,
    SourceRef,
    SourceType,
)
from atlas.storage.db import Base, get_engine, get_sessionmaker, session_scope
from atlas.storage.projections import Projection, load_projection, replay
from atlas.storage.tables import EventLog, append_event

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
        actor="system" if node.created_by is CreatedBy.SYSTEM else "pm@acme.test",
        workspace_id=node.workspace_id,
    )


def status_change(event_type: EventType, node: Node, *, actor: str = "pm@acme.test") -> Event:
    payload = NodeStatusChangePayload(node_id=node.id)
    return Event(
        event_type=event_type,
        payload=payload.model_dump(mode="json"),
        actor=actor,
        workspace_id=node.workspace_id,
    )


def node_edited(node: Node, *, content: str, actor: str = "pm@acme.test") -> Event:
    payload = NodeEditPayload(node_id=node.id, content=content, previous_content=node.content)
    return Event(
        event_type=EventType.NODE_EDITED,
        payload=payload.model_dump(mode="json"),
        actor=actor,
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


# --- confirmation events (TRD Sec6) --------------------------------------------


def test_replay_confirm_sets_status_and_records_the_human_actor() -> None:
    node = make_node()
    event = status_change(EventType.NODE_CONFIRMED, node, actor="pm@acme.test")

    projection = replay([node_created(node), event])

    confirmed = projection.nodes[node.id]
    assert confirmed.status is NodeStatus.CONFIRMED
    assert confirmed.updated_by == "pm@acme.test"
    assert confirmed.updated_at == event.timestamp


def test_replay_reject_sets_status_rejected_and_keeps_the_node() -> None:
    """A rejected node stays in the projection (the log is append-only and
    nothing is deleted); Phase 2's spec assembly filters it out by status."""
    node = make_node()

    projection = replay([node_created(node), status_change(EventType.NODE_REJECTED, node)])

    assert projection.nodes[node.id].status is NodeStatus.REJECTED


def test_replay_edit_applies_the_new_content_and_marks_it_edited() -> None:
    node = make_node(content="Ship the thing")

    projection = replay([node_created(node), node_edited(node, content="Ship the thing by Q4")])

    edited = projection.nodes[node.id]
    assert edited.content == "Ship the thing by Q4"
    assert edited.status is NodeStatus.EDITED
    assert edited.updated_by == "pm@acme.test"


def test_replay_edit_preserves_provenance_and_extraction_origin() -> None:
    """An edit changes what the claim says, not where it came from: the source
    excerpt, the confidence the extractor earned, and `created_by = system` all
    survive so the edit stays auditable against the original."""
    node = make_node()

    projection = replay([node_created(node), node_edited(node, content="Reworded")])

    edited = projection.nodes[node.id]
    assert edited.source_refs == node.source_refs
    assert edited.created_by is CreatedBy.SYSTEM
    assert edited.confidence_score == node.confidence_score


def test_edit_event_payload_retains_the_previous_content() -> None:
    """TRD Sec6: edited nodes retain a link to the version they replaced. The
    projection holds only current state, so the before-image has to be
    reconstructable from the event itself. (The chain of these back to
    `node_created` is what recovers the system-extracted original -- see
    tests/test_confirmations.py.)"""
    node = make_node(content="Ship the thing")

    event = node_edited(node, content="Ship the thing by Q4")

    assert event.payload["previous_content"] == "Ship the thing"


def test_replay_edit_rejects_blank_content() -> None:
    """The write-side gate holds on the read path for edits too -- an edit
    payload can't blank out a node's content any more than a create can."""
    node = make_node()
    blank_edit = Event(
        event_type=EventType.NODE_EDITED,
        payload={"node_id": str(node.id), "content": "   ", "previous_content": node.content},
        actor="pm@acme.test",
        workspace_id=WORKSPACE_ID,
    )

    with pytest.raises(ValidationError):
        replay([node_created(node), blank_edit])


@pytest.mark.parametrize(
    "event_type",
    [EventType.NODE_CONFIRMED, EventType.NODE_EDITED, EventType.NODE_REJECTED],
)
def test_replay_status_event_for_an_unknown_node_fails_loud(event_type: EventType) -> None:
    """A transition referencing a node the log never created means a corrupt log
    or a bug upstream. Silently ignoring it would let a confirm quietly vanish."""
    missing = make_node()
    event = (
        node_edited(missing, content="x")
        if event_type is EventType.NODE_EDITED
        else status_change(event_type, missing)
    )

    with pytest.raises(ValueError, match="unknown node"):
        replay([event])


def test_replay_applies_transitions_in_order_last_one_wins() -> None:
    """An edit after a confirm must win -- this is why append order is
    load-bearing and `load_projection` orders by `sequence`."""
    node = make_node()

    projection = replay(
        [
            node_created(node),
            status_change(EventType.NODE_CONFIRMED, node),
            node_edited(node, content="Actually, ship it by Q3"),
        ]
    )

    assert projection.nodes[node.id].status is NodeStatus.EDITED
    assert projection.nodes[node.id].content == "Actually, ship it by Q3"


def test_replay_confirm_after_reject_reinstates_the_node() -> None:
    """Undo comes free from the event log (TRD Sec3.1): reversing a decision is
    a new event, never a rewrite of an old one."""
    node = make_node()

    projection = replay(
        [
            node_created(node),
            status_change(EventType.NODE_REJECTED, node),
            status_change(EventType.NODE_CONFIRMED, node),
        ]
    )

    assert projection.nodes[node.id].status is NodeStatus.CONFIRMED


def test_replay_materializes_a_manually_added_node() -> None:
    """Manual creation reuses `node_created` with `created_by = user` -- TRD
    Sec3.1's event_type enum has no separate `node_added` member."""
    manual = Node(
        type=NodeType.CONSTRAINT,
        content="Must ship before the Q4 freeze.",
        created_by=CreatedBy.USER,
        status=NodeStatus.CONFIRMED,
        source_refs=[
            SourceRef(
                source_type=SourceType.GITHUB_PR,
                external_id="42",
                url="https://github.com/acme/repo/pull/42",
                excerpt="Q4 freeze is 1 Dec.",
                workspace_id=WORKSPACE_ID,
            )
        ],
        workspace_id=WORKSPACE_ID,
        feature_scope_id=FEATURE_SCOPE_ID,
    )

    projection = replay([node_created(manual)])

    materialized = projection.nodes[manual.id]
    assert materialized.created_by is CreatedBy.USER
    assert materialized.status is NodeStatus.CONFIRMED
    assert materialized.confidence_score is None


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


def _write(session: Session, event: Event) -> EventLog:
    return append_event(
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


def test_load_projection_orders_by_sequence_not_wall_clock_timestamp(
    session_factory: sessionmaker[Session],
) -> None:
    """Regression guard for the ordering key. Wall-clock `timestamp` is not a
    safe total order -- events appended in one transaction can share it, and a
    clock adjustment can invert two of them. Here the confirm is stamped an hour
    *before* the create; ordering by `sequence` still applies it second."""
    node = make_node()
    confirm = status_change(EventType.NODE_CONFIRMED, node)

    with session_scope(session_factory) as session:
        _write(session, node_created(node))
        confirm_row = _write(session, confirm)
        confirm_row.timestamp = datetime.now(UTC) - timedelta(hours=1)

    with session_scope(session_factory) as session:
        projection = load_projection(session, workspace_id=WORKSPACE_ID)

    assert projection.nodes[node.id].status is NodeStatus.CONFIRMED


def test_load_projection_empty_log_is_empty(
    session_factory: sessionmaker[Session],
) -> None:
    with session_scope(session_factory) as session:
        projection = load_projection(session, workspace_id=WORKSPACE_ID)

    assert isinstance(projection, Projection)
    assert projection.nodes == {}
    assert projection.edges == {}
