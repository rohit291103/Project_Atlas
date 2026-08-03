"""The write side of the confirmation loop (TRD Sec6).

Four actions -- confirm, reject, edit, add manually -- each of which "writes a
corresponding Event; no direct mutation of Node table without an Event record"
(TRD Sec6). This module is where that rule is *implemented* rather than merely
observed: it is the only sanctioned way to change a Node's status or content,
and every function here bottoms out in `append_event`.

These are deliberately plain functions over a `Session`, not a service class:
they are the shared write path for both consumers of the projection layer --
Phase 1's FastAPI `api/` and the CLI -- so neither reimplements the payload
shapes, and a payload change lands in one place. The read side
(`storage/projections.py`) holds the matching reducer; the two are only ever
correct together, which is why the tests assert the round trip.

Every action takes the `Node` it acts on, not a bare id. That is the point: the
caller must have loaded the projection, so an action can't name a node that
doesn't exist, and `workspace_id` comes off the node instead of being passed
alongside where the two could disagree.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from atlas.models.schema import (
    CreatedBy,
    EventType,
    Node,
    NodeEditPayload,
    NodeStatus,
    NodeStatusChangePayload,
)
from atlas.storage.tables import EventLog, append_event

__all__ = ["add_node", "confirm_node", "edit_node", "reject_node"]


def _append_status_change(
    session: Session, *, event_type: EventType, node: Node, actor: str
) -> EventLog:
    payload = NodeStatusChangePayload(node_id=node.id)
    return append_event(
        session,
        event_type=event_type,
        payload=payload.model_dump(mode="json"),
        actor=actor,
        workspace_id=node.workspace_id,
    )


def confirm_node(session: Session, *, node: Node, actor: str) -> EventLog:
    """Record that `actor` accepted `node` as extracted.

    Confirming a rejected node is allowed and reinstates it -- reversing a
    ruling is a new event, never a rewrite of the old one (TRD Sec3.1).
    """
    return _append_status_change(
        session, event_type=EventType.NODE_CONFIRMED, node=node, actor=actor
    )


def reject_node(session: Session, *, node: Node, actor: str) -> EventLog:
    """Record that `actor` rejected `node`.

    Nothing is deleted: the node stays in the projection with
    `status = rejected`, and spec assembly (Phase 2) filters on status.
    """
    return _append_status_change(
        session, event_type=EventType.NODE_REJECTED, node=node, actor=actor
    )


def edit_node(session: Session, *, node: Node, content: str, actor: str) -> EventLog:
    """Record that `actor` rewrote `node`'s content.

    The event carries the content it replaced, read off `node` rather than taken
    as an argument so the recorded before-image is always what was actually
    current. Successive edits therefore chain: walking `node_edited` payloads
    back to the `node_created` that started them reconstructs the full history,
    including the original system-extracted version (TRD Sec6).

    Only `content` changes. `source_refs`, `confidence_score` and `created_by`
    survive an edit untouched -- an edit changes what a claim says, not where it
    came from or that a machine proposed it.
    """
    payload = NodeEditPayload(node_id=node.id, content=content, previous_content=node.content)
    return append_event(
        session,
        event_type=EventType.NODE_EDITED,
        payload=payload.model_dump(mode="json"),
        actor=actor,
        workspace_id=node.workspace_id,
    )


def add_node(session: Session, *, node: Node, actor: str) -> EventLog:
    """Record a node a human wrote by hand.

    There is no `node_added` event type -- TRD Sec3.1's enum has none -- so a
    manual node is a plain `node_created` distinguished by `created_by = user`.
    It is stored `confirmed` and `updated_by = actor`: a human typing a claim has
    already affirmed it, and `created_by` is only an enum, so `updated_by` is the
    one field that records *which* human. It carries no confidence score (the
    Node schema forbids one here) because there was no extraction to score.

    Refuses a system-created node: routing extraction output through this path
    would launder a draft into a confirmed fact without a human ever seeing it,
    which is precisely what "extraction is a draft, never a fact" forbids.
    """
    if node.created_by is not CreatedBy.USER:
        raise ValueError(
            "add_node is the manual-entry path: created_by must be 'user', "
            f"got {node.created_by.value!r}"
        )
    affirmed = node.model_copy(update={"status": NodeStatus.CONFIRMED, "updated_by": actor})
    return append_event(
        session,
        event_type=EventType.NODE_CREATED,
        payload=affirmed.model_dump(mode="json"),
        actor=actor,
        workspace_id=affirmed.workspace_id,
    )
