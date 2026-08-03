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
        confirm_node(session, node=stored_node, actor=PM)

    projected = _replay(session_factory)[stored_node.id]
    assert projected.status is NodeStatus.CONFIRMED
    assert projected.updated_by == PM


def test_reject_node_projects_as_rejected(
    session_factory: sessionmaker[Session], stored_node: Node
) -> None:
    with session_scope(session_factory) as session:
        reject_node(session, node=stored_node, actor=PM)

    assert _replay(session_factory)[stored_node.id].status is NodeStatus.REJECTED


def test_confirm_node_writes_an_event_rather_than_mutating_state(
    session_factory: sessionmaker[Session], stored_node: Node
) -> None:
    """CLAUDE.md Engineering Philosophy Sec3: never mutate Node/Edge state --
    write an event. The confirm must show up as a second row in the log."""
    with session_scope(session_factory) as session:
        confirm_node(session, node=stored_node, actor=PM)

    with session_scope(session_factory) as session:
        types = [row.event_type for row in session.query(EventLog).order_by(EventLog.sequence)]
    assert types == [EventType.NODE_CREATED, EventType.NODE_CONFIRMED]


def test_confirm_node_requires_a_non_blank_actor(
    session_factory: sessionmaker[Session], stored_node: Node
) -> None:
    """Every event is an audit record (TRD Sec9) -- an anonymous confirm would
    be an audit hole, not a convenience."""
    with pytest.raises(ValueError, match="actor"), session_scope(session_factory) as session:
        confirm_node(session, node=stored_node, actor="   ")


# --- edit ----------------------------------------------------------------------


def test_edit_node_projects_the_new_content_as_edited(
    session_factory: sessionmaker[Session], stored_node: Node
) -> None:
    with session_scope(session_factory) as session:
        edit_node(
            session, node=stored_node, content="Rate-limit per API key, not per IP.", actor=PM
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
        event = edit_node(session, node=stored_node, content="Reworded.", actor=PM)
        assert event.payload["previous_content"] == stored_node.content


def test_successive_edits_chain_back_to_the_system_extracted_original(
    session_factory: sessionmaker[Session], stored_node: Node
) -> None:
    """Editing an edit records the value it actually replaced, so walking the
    chain of `node_edited` payloads back through `node_created` reconstructs the
    full history -- no step claims a before-image that was never current."""
    with session_scope(session_factory) as session:
        edit_node(session, node=stored_node, content="First revision.", actor=PM)

    once_edited = _replay(session_factory)[stored_node.id]
    with session_scope(session_factory) as session:
        edit_node(session, node=once_edited, content="Second revision.", actor=PM)

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
        edit_node(session, node=stored_node, content="   ", actor=PM)


# --- manual add ----------------------------------------------------------------


def _manual_node(content: str = "Must ship before the Q4 freeze.") -> Node:
    return Node(
        type=NodeType.CONSTRAINT,
        content=content,
        created_by=CreatedBy.USER,
        source_refs=[_source_ref()],
        workspace_id=WORKSPACE_ID,
        feature_scope_id=FEATURE_SCOPE_ID,
    )


def test_add_node_projects_a_confirmed_unscored_user_node(
    session_factory: sessionmaker[Session],
) -> None:
    """TRD Sec6: manually-added nodes skip confidence scoring and default to
    confirmed -- a human typing a claim has already affirmed it."""
    manual = _manual_node()

    with session_scope(session_factory) as session:
        add_node(session, node=manual, actor=PM)

    projected = _replay(session_factory)[manual.id]
    assert projected.created_by is CreatedBy.USER
    assert projected.status is NodeStatus.CONFIRMED
    assert projected.confidence_score is None
    assert projected.updated_by == PM


def test_add_node_refuses_a_system_created_node(
    session_factory: sessionmaker[Session],
) -> None:
    """`add_node` is the manual-entry path; routing extraction output through it
    would launder a draft into a confirmed fact without a human ever seeing it."""
    with pytest.raises(ValueError, match="created_by"), session_scope(session_factory) as session:
        add_node(session, node=_extracted_node(), actor=PM)


def test_add_node_keeps_provenance_required(
    session_factory: sessionmaker[Session],
) -> None:
    """A manual node still needs a SourceRef -- CLAUDE.md admits no exception,
    and the Node model is what enforces it, before `add_node` is ever reached."""
    with pytest.raises(ValidationError):
        Node(
            type=NodeType.CONSTRAINT,
            content="Must ship before the Q4 freeze.",
            created_by=CreatedBy.USER,
            source_refs=[],
            workspace_id=WORKSPACE_ID,
            feature_scope_id=FEATURE_SCOPE_ID,
        )
