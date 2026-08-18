"""Tests for storage/confirmations.py: the write side of the confirmation loop
(TRD Sec6 -- "Actions (confirm/edit/reject/add manually) each write a
corresponding Event; no direct mutation of Node table without an Event record").

Each test asserts the round trip, not just the append: write the event, replay
the log, check the projected node. That is the only assertion that proves the
write and read sides agree on a payload shape, which is where an event-sourced
system actually breaks.

In-memory SQLite, like the other storage tests -- no live Supabase, no secrets.
"""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from atlas.models.schema import (
    ActorKind,
    CreatedBy,
    EventType,
    Node,
    NodeStatus,
    NodeType,
    SourceRef,
    SourceType,
)
from atlas.storage.confirmations import add_node, confirm_node, edit_node, reject_node
from atlas.storage.db import Base, get_engine, get_sessionmaker, session_scope
from atlas.storage.projections import load_projection
from atlas.storage.tables import EventLog, append_event

WORKSPACE_ID = uuid.UUID(int=0)
FEATURE_SCOPE_ID = uuid.uuid4()
PM = "pm@acme.test"


@pytest.fixture
def session_factory() -> sessionmaker[Session]:
    engine: Engine = get_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return get_sessionmaker(engine)


def _source_ref() -> SourceRef:
    return SourceRef(
        source_type=SourceType.GITHUB_PR,
        external_id="42",
        url="https://github.com/acme/gateway/pull/42",
        excerpt="the gateway must rate-limit per client IP",
        workspace_id=WORKSPACE_ID,
    )


def _extracted_node(content: str = "The gateway must rate-limit per client IP.") -> Node:
    return Node(
        type=NodeType.REQUIREMENT,
        content=content,
        confidence_score=0.9,
        source_refs=[_source_ref()],
        workspace_id=WORKSPACE_ID,
        feature_scope_id=FEATURE_SCOPE_ID,
    )


@pytest.fixture
def stored_node(session_factory: sessionmaker[Session]) -> Node:
    """A system-extracted draft already in the log, as `atlas ingest` leaves it."""
    node = _extracted_node()
    with session_scope(session_factory) as session:
        append_event(
            session,
            event_type=EventType.NODE_CREATED,
            payload=node.model_dump(mode="json"),
            actor="system",
            actor_kind=ActorKind.AUTOMATED,
            workspace_id=WORKSPACE_ID,
        )
    return node


def _replay(session_factory: sessionmaker[Session]) -> dict[uuid.UUID, Node]:
    with session_scope(session_factory) as session:
        return load_projection(session, workspace_id=WORKSPACE_ID).nodes


# --- confirm / reject ----------------------------------------------------------


def test_confirm_node_projects_as_confirmed_by_the_acting_human(
    session_factory: sessionmaker[Session], stored_node: Node
) -> None:
    with session_scope(session_factory) as session:
        confirm_node(session, node=stored_node, actor=PM, actor_kind=ActorKind.HUMAN)

    projected = _replay(session_factory)[stored_node.id]
    assert projected.status is NodeStatus.CONFIRMED
    assert projected.updated_by == PM


def test_reject_node_projects_as_rejected(
    session_factory: sessionmaker[Session], stored_node: Node
) -> None:
    with session_scope(session_factory) as session:
        reject_node(session, node=stored_node, actor=PM, actor_kind=ActorKind.HUMAN)

    assert _replay(session_factory)[stored_node.id].status is NodeStatus.REJECTED


def test_confirm_node_writes_an_event_rather_than_mutating_state(
    session_factory: sessionmaker[Session], stored_node: Node
) -> None:
    """CLAUDE.md Engineering Philosophy Sec3: never mutate Node/Edge state --
    write an event. The confirm must show up as a second row in the log."""
    with session_scope(session_factory) as session:
        confirm_node(session, node=stored_node, actor=PM, actor_kind=ActorKind.HUMAN)

    with session_scope(session_factory) as session:
        types = [row.event_type for row in session.query(EventLog).order_by(EventLog.sequence)]
    assert types == [EventType.NODE_CREATED, EventType.NODE_CONFIRMED]


def test_confirm_node_requires_a_non_blank_actor(
    session_factory: sessionmaker[Session], stored_node: Node
) -> None:
    """Every event is an audit record (TRD Sec9) -- an anonymous confirm would
    be an audit hole, not a convenience."""
    with pytest.raises(ValueError, match="actor"), session_scope(session_factory) as session:
        confirm_node(session, node=stored_node, actor="   ", actor_kind=ActorKind.HUMAN)


# --- edit ----------------------------------------------------------------------


def test_edit_node_projects_the_new_content_as_edited(
    session_factory: sessionmaker[Session], stored_node: Node
) -> None:
    with session_scope(session_factory) as session:
        edit_node(
            session,
            node=stored_node,
            content="Rate-limit per API key, not per IP.",
            actor=PM,
            actor_kind=ActorKind.HUMAN,
        )

    projected = _replay(session_factory)[stored_node.id]
    assert projected.content == "Rate-limit per API key, not per IP."
    assert projected.status is NodeStatus.EDITED
    assert projected.updated_by == PM


def test_edit_node_records_the_content_it_replaced(
    session_factory: sessionmaker[Session], stored_node: Node
) -> None:
    """TRD Sec6: an edited node retains a link to what it replaced. The
    projection holds only current state, so the before-image lives in the event
    -- and the caller can't get it wrong, because `edit_node` reads it off the
    node rather than taking it as an argument."""
    with session_scope(session_factory) as session:
        event = edit_node(
            session, node=stored_node, content="Reworded.", actor=PM, actor_kind=ActorKind.HUMAN
        )
        assert event.payload["previous_content"] == stored_node.content


def test_successive_edits_chain_back_to_the_system_extracted_original(
    session_factory: sessionmaker[Session], stored_node: Node
) -> None:
    """Editing an edit records the value it actually replaced, so walking the
    chain of `node_edited` payloads back through `node_created` reconstructs the
    full history -- no step claims a before-image that was never current."""
    with session_scope(session_factory) as session:
        edit_node(
            session,
            node=stored_node,
            content="First revision.",
            actor=PM,
            actor_kind=ActorKind.HUMAN,
        )

    once_edited = _replay(session_factory)[stored_node.id]
    with session_scope(session_factory) as session:
        edit_node(
            session,
            node=once_edited,
            content="Second revision.",
            actor=PM,
            actor_kind=ActorKind.HUMAN,
        )

    with session_scope(session_factory) as session:
        edits = [
            row.payload
            for row in session.query(EventLog)
            .filter(EventLog.event_type == EventType.NODE_EDITED)
            .order_by(EventLog.sequence)
        ]

    assert [e["previous_content"] for e in edits] == [stored_node.content, "First revision."]
    assert _replay(session_factory)[stored_node.id].content == "Second revision."


def test_edit_node_rejects_blank_content(
    session_factory: sessionmaker[Session], stored_node: Node
) -> None:
    with pytest.raises(ValidationError), session_scope(session_factory) as session:
        edit_node(session, node=stored_node, content="   ", actor=PM, actor_kind=ActorKind.HUMAN)


# --- manual add ----------------------------------------------------------------


FREEZE = "Must ship before the Q4 freeze."


def _add(session: Session, *, content: str = FREEZE, actor: str = PM) -> EventLog:
    return add_node(
        session,
        node_type=NodeType.CONSTRAINT,
        content=content,
        actor=actor,
        actor_kind=ActorKind.HUMAN,
        workspace_id=WORKSPACE_ID,
        feature_scope_id=FEATURE_SCOPE_ID,
    )


def test_add_node_projects_a_confirmed_unscored_user_node(
    session_factory: sessionmaker[Session],
) -> None:
    """TRD Sec6: manually-added nodes skip confidence scoring and default to
    confirmed -- a human typing a claim has already affirmed it."""
    with session_scope(session_factory) as session:
        node_id = Node.model_validate(_add(session).payload).id

    projected = _replay(session_factory)[node_id]
    assert projected.content == FREEZE
    assert projected.created_by is CreatedBy.USER
    assert projected.status is NodeStatus.CONFIRMED
    assert projected.confidence_score is None
    assert projected.updated_by == PM


def test_add_node_attributes_the_claim_to_the_human_who_asserted_it(
    session_factory: sessionmaker[Session],
) -> None:
    """PRD R10 covers knowledge with no artifact behind it ("a constraint
    mentioned verbally in a meeting"), so there is no external URL to cite. The
    honest provenance is the person: `source_type = human_assertion`, the actor
    as `external_id`, and the claim as they typed it as the excerpt.

    This is what lets the Node schema keep requiring a SourceRef with no
    exception clause (CLAUDE.md) -- and what keeps a hand-typed claim
    machine-distinguishable from an extracted one downstream."""
    with session_scope(session_factory) as session:
        node_id = Node.model_validate(_add(session).payload).id

    (ref,) = _replay(session_factory)[node_id].source_refs
    assert ref.source_type is SourceType.HUMAN_ASSERTION
    assert ref.external_id == PM
    assert ref.excerpt == FREEZE
    assert ref.url == f"atlas:node/{node_id}"
    assert ref.workspace_id == WORKSPACE_ID


def test_add_node_excerpt_survives_a_later_edit_of_the_content(
    session_factory: sessionmaker[Session],
) -> None:
    """Provenance is what was *asserted*, not what the claim currently says --
    exactly as an extracted node's excerpt stays fixed while its content is
    edited. Without this an edit would rewrite its own evidence."""
    with session_scope(session_factory) as session:
        node_id = Node.model_validate(_add(session).payload).id

    added = _replay(session_factory)[node_id]
    with session_scope(session_factory) as session:
        edit_node(
            session,
            node=added,
            content="Must ship before the Q3 freeze.",
            actor=PM,
            actor_kind=ActorKind.HUMAN,
        )

    edited = _replay(session_factory)[node_id]
    assert edited.content == "Must ship before the Q3 freeze."
    assert edited.source_refs[0].excerpt == FREEZE


def test_add_node_cannot_be_handed_a_system_node_or_a_foreign_workspace(
    session_factory: sessionmaker[Session],
) -> None:
    """`add_node` builds the Node rather than accepting one, so extraction output
    can't be laundered through the manual path into a confirmed fact, and an API
    caller can't smuggle another workspace's id in a request body -- both are
    structurally unreachable, not guarded against."""
    import inspect

    parameters = inspect.signature(add_node).parameters
    assert "node" not in parameters
    assert {"node_type", "content", "actor", "workspace_id", "feature_scope_id"} <= set(parameters)


@pytest.mark.parametrize("blank", ["", "   "])
def test_add_node_rejects_blank_content(session_factory: sessionmaker[Session], blank: str) -> None:
    with pytest.raises(ValidationError), session_scope(session_factory) as session:
        _add(session, content=blank)


@pytest.mark.parametrize("blank", ["", "   "])
def test_add_node_rejects_a_blank_actor(session_factory: sessionmaker[Session], blank: str) -> None:
    """The actor isn't just the audit record here -- it *is* the node's
    provenance, so an anonymous manual node would have none."""
    with pytest.raises(ValueError, match="actor"), session_scope(session_factory) as session:
        _add(session, actor=blank)


def test_node_still_cannot_be_constructed_without_provenance() -> None:
    """The invariant `add_node` is written to satisfy, restated: CLAUDE.md admits
    no exception, and `human_assertion` is what makes that survivable for manual
    entry rather than forcing a fabricated citation."""
    with pytest.raises(ValidationError):
        Node(
            type=NodeType.CONSTRAINT,
            content=FREEZE,
            created_by=CreatedBy.USER,
            source_refs=[],
            workspace_id=WORKSPACE_ID,
            feature_scope_id=FEATURE_SCOPE_ID,
        )
