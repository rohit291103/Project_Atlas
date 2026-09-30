"""Discussion on a claim (Phase 4, roadmap v2 `[+2026-09-02]`).

Confirm/reject is a thin approval: it records *that* someone ruled, not the
conversation that got them there. A comment is that conversation. It is an
event like every other write (Engineering Philosophy §3), and deliberately
**not** a ruling -- replay projects nothing from it, so a thread can never move
a claim's status or reach a spec export.

Its own small read model rather than a field on `Projection`: nothing that
reads projected state needs comments, and folding them into every replay would
make the review queue pay for a thread nobody opened.

Any member may comment, viewers included (decided 2026-09-30): a viewer asking
"is this still true?" is exactly the input the loop wants, and commenting
grants no power to rule.
"""

from __future__ import annotations

import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from atlas.models.schema import ActorKind, CommentPayload, EventType
from atlas.storage.tables import EventLog, append_event


@dataclass(frozen=True)
class Comment:
    id: uuid.UUID
    node_id: uuid.UUID
    body: str
    author: str
    actor_kind: ActorKind
    created_at: datetime


def add_comment(
    session: Session,
    *,
    workspace_id: uuid.UUID,
    node_id: uuid.UUID,
    body: str,
    actor: str,
    actor_kind: ActorKind,
) -> Comment:
    """Append one comment. Validation is `CommentPayload`'s: non-blank, bounded."""
    payload = CommentPayload(node_id=node_id, body=body)
    row = append_event(
        session,
        event_type=EventType.COMMENT_ADDED,
        payload=payload.model_dump(mode="json"),
        actor=actor,
        actor_kind=actor_kind,
        workspace_id=workspace_id,
    )
    return _comment(row)


def _rows(session: Session, workspace_id: uuid.UUID) -> list[EventLog]:
    stmt = (
        select(EventLog)
        .where(
            EventLog.workspace_id == workspace_id,
            EventLog.event_type == EventType.COMMENT_ADDED,
        )
        .order_by(EventLog.sequence)
    )
    return list(session.execute(stmt).scalars())


def comments_for_node(
    session: Session, *, workspace_id: uuid.UUID, node_id: uuid.UUID
) -> list[Comment]:
    """One claim's thread, oldest first. The node filter runs in Python because
    the node id lives in the JSON payload; the workspace and event-type filters
    run in SQL, so RLS and the tenant bound apply before any row is read."""
    return [
        comment
        for comment in (_comment(row) for row in _rows(session, workspace_id))
        if comment.node_id == node_id
    ]


def comment_counts(session: Session, *, workspace_id: uuid.UUID) -> dict[uuid.UUID, int]:
    """How many comments each claim has -- for a badge, not a thread."""
    return dict(Counter(_comment(row).node_id for row in _rows(session, workspace_id)))


def _comment(row: EventLog) -> Comment:
    payload = CommentPayload.model_validate(row.payload)
    return Comment(
        id=payload.comment_id,
        node_id=payload.node_id,
        body=payload.body,
        author=row.actor,
        actor_kind=row.actor_kind,
        created_at=row.timestamp,
    )
