"""Tests for `storage/comments.py` -- discussion on a claim (Phase 4).

A comment is an event like everything else: appended, never edited in place,
carrying its author and whether a person wrote it. It is *not* a ruling: it
changes nothing about a node's status, and replay treats it as such.
"""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError
from sqlalchemy.orm import Session

from atlas.models.schema import ActorKind, CommentPayload, EventType
from atlas.storage.comments import add_comment, comment_counts, comments_for_node
from atlas.storage.db import Base, get_engine, get_sessionmaker
from atlas.storage.projections import load_log, load_projection

WORKSPACE = uuid.UUID(int=0)
OTHER_WORKSPACE = uuid.UUID(int=9)
NODE = uuid.uuid4()
OTHER_NODE = uuid.uuid4()


@pytest.fixture
def session() -> Session:
    engine = get_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return get_sessionmaker(engine)()


def _add(session: Session, body: str = "Is this still true?", **overrides: object) -> None:
    fields: dict[str, object] = {
        "workspace_id": WORKSPACE,
        "node_id": NODE,
        "body": body,
        "actor": "Sam (observer)",
        "actor_kind": ActorKind.HUMAN,
    }
    fields.update(overrides)
    add_comment(session, **fields)  # type: ignore[arg-type]


def test_comments_come_back_in_order_with_their_author(session: Session) -> None:
    _add(session, "Is this still true?")
    _add(session, "Yes, per the Sept planning doc.", actor="Priya (PM)")

    comments = comments_for_node(session, workspace_id=WORKSPACE, node_id=NODE)

    assert [(c.author, c.body) for c in comments] == [
        ("Sam (observer)", "Is this still true?"),
        ("Priya (PM)", "Yes, per the Sept planning doc."),
    ]
    assert all(c.actor_kind is ActorKind.HUMAN for c in comments)


def test_comments_are_per_node_and_per_workspace(session: Session) -> None:
    _add(session, "on node")
    _add(session, "on another node", node_id=OTHER_NODE)
    _add(session, "in another workspace", workspace_id=OTHER_WORKSPACE)

    assert [c.body for c in comments_for_node(session, workspace_id=WORKSPACE, node_id=NODE)] == [
        "on node"
    ]


def test_counts_are_per_node(session: Session) -> None:
    _add(session)
    _add(session)
    _add(session, node_id=OTHER_NODE)

    assert comment_counts(session, workspace_id=WORKSPACE) == {NODE: 2, OTHER_NODE: 1}


def test_a_comment_is_an_append_only_event(session: Session) -> None:
    _add(session)

    (event,) = load_log(session, workspace_id=WORKSPACE)
    assert event.event_type is EventType.COMMENT_ADDED
    assert event.actor == "Sam (observer)"


def test_a_comment_is_not_a_ruling(session: Session) -> None:
    """Replay must accept the event and change nothing it projects."""
    _add(session)

    projection = load_projection(session, workspace_id=WORKSPACE)

    assert projection.nodes == {}


@pytest.mark.parametrize("body", ["", "   ", "x" * 2001])
def test_a_blank_or_oversized_comment_is_refused(body: str) -> None:
    with pytest.raises(ValidationError):
        CommentPayload(node_id=NODE, body=body)
