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

import uuid

from sqlalchemy.orm import Session

from atlas.models.schema import (
    CreatedBy,
    EventType,
    Node,
    NodeEditPayload,
    NodeStatus,
    NodeStatusChangePayload,
    NodeType,
    SourceRef,
    SourceType,
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


def add_node(
    session: Session,
    *,
    node_type: NodeType,
    content: str,
    actor: str,
    workspace_id: uuid.UUID,
    feature_scope_id: uuid.UUID,
) -> EventLog:
    """Record a claim a human typed directly into Atlas (PRD R10).

    Builds the Node rather than accepting one. That is the whole design: a
    caller cannot hand this an extraction draft to launder into a confirmed
    fact, and an API cannot let a request body choose its own `workspace_id`.
    Both are unreachable rather than guarded against. `workspace_id` and
    `actor` must come from the authenticated session.

    There is no `node_added` event type -- TRD Sec3.1's enum has none -- so this
    is a plain `node_created` distinguished by `created_by = user`. The node is
    stored `confirmed` (a human typing a claim has already affirmed it) with no
    confidence score, because there was no extraction to score.

    Its provenance is the person: a `human_assertion` SourceRef naming the actor
    and quoting the claim as typed. PRD R10's example -- "a constraint mentioned
    verbally in a meeting" -- has no artifact to cite, so demanding an external
    URL here would only produce fabricated ones. The excerpt is deliberately a
    snapshot: a later `edit_node` changes `content` and leaves it alone, so the
    record of what was originally asserted survives being revised, exactly as an
    extracted node's excerpt does.

    Returns the appended event; its `payload` is the created Node.
    """
    if not actor.strip():
        # Checked before the SourceRef is built so the error names the actor
        # rather than surfacing as a confusing `external_id` validation failure.
        # Here the actor is not merely the audit record -- it *is* the node's
        # provenance, so an anonymous manual node would have none at all.
        raise ValueError("actor must not be blank or whitespace-only")

    node_id = uuid.uuid4()
    node = Node(
        id=node_id,
        type=node_type,
        content=content,
        status=NodeStatus.CONFIRMED,
        created_by=CreatedBy.USER,
        updated_by=actor,
        source_refs=[
            SourceRef(
                source_type=SourceType.HUMAN_ASSERTION,
                external_id=actor,
                # A URN, not an http URL: the claim's source is this node itself,
                # as asserted. There is no external page to link, and inventing a
                # host would be a lie the UI would then have to render.
                url=f"atlas:node/{node_id}",
                excerpt=content,
                workspace_id=workspace_id,
            )
        ],
        workspace_id=workspace_id,
        feature_scope_id=feature_scope_id,
    )
    return append_event(
        session,
        event_type=EventType.NODE_CREATED,
        payload=node.model_dump(mode="json"),
        actor=actor,
        workspace_id=workspace_id,
    )
