"""event_log: the append-only source of truth (TRD Sec3.1 Event, Sec3.2).

Node/Edge state is never stored directly -- only events land here.
Materialized Node/Edge projections (storage/projections.py) are replayed
from this table, never written to independently.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    DateTime,
    Enum,
    ForeignKey,
    Identity,
    Index,
    PrimaryKeyConstraint,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, Session, mapped_column
from sqlalchemy.sql import func

# EventType lives in models/schema.py (the single source of truth for the domain
# model); importing it here keeps the Postgres enum from ever drifting from the
# schema definition. storage -> models is the correct dependency direction.
from atlas.models.schema import EventType, Role
from atlas.storage.db import Base

__all__ = ["EventLog", "EventType", "Workspace", "WorkspaceMember", "append_event"]

# On Postgres, native `uuid`; on SQLite (tests only), CHAR(32). The variant is
# not cosmetic: SQLite gives an unrecognized `UUID` type name NUMERIC affinity,
# which coerces an all-digit hex string -- notably the nil DEFAULT_WORKSPACE_ID
# ("000...0") -- to the integer 0 and then crashes on read. CHAR(32) has TEXT
# affinity, so the value round-trips intact. Postgres DDL is unchanged.
_UUID = PG_UUID(as_uuid=True).with_variant(Uuid(as_uuid=True), "sqlite")


class EventLog(Base):
    """One row per event (TRD Sec3.1).

    Append-only: this module exposes no update/delete helper. A correction is
    always a new event, never a mutation of an existing row.
    """

    __tablename__ = "event_log"
    __table_args__ = (
        # Identity is BY DEFAULT (not ALWAYS), so an explicit insert could still
        # duplicate a value; the constraint makes the total order actually total.
        UniqueConstraint("sequence", name="uq_event_log_sequence"),
        # The replay query is `where workspace_id = :w order by sequence`.
        Index("ix_event_log_workspace_sequence", "workspace_id", "sequence"),
    )

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True, default=uuid.uuid4)
    #: Total order of appends -- the key projection replay folds events in.
    #: Database-assigned (Postgres identity) rather than client-assigned, and
    #: deliberately *not* part of the domain `Event` model (TRD Sec3.1): it is a
    #: storage concern, not something the extraction or API layers reason about.
    #: Gap-tolerant by design; only the relative order matters.
    #:
    #: `timestamp` is not a safe substitute -- events appended in one
    #: transaction can share a wall-clock value, and clock skew or adjustment
    #: could reorder them outright.
    sequence: Mapped[int] = mapped_column(BigInteger, Identity(always=False), nullable=False)
    event_type: Mapped[EventType] = mapped_column(
        Enum(
            EventType,
            name="event_type",
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
    )
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), nullable=False
    )
    actor: Mapped[str] = mapped_column(Text, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(_UUID, nullable=False)


class Workspace(Base):
    """A provisioned workspace -- the tenant boundary (TRD Sec9, slice 1D).

    The nil-UUID sentinel `DEFAULT_WORKSPACE_ID` that Phase 0 stamped on every
    event becomes a **real row here**, keeping its id
    (`docs/decisions/2026-07-21-phase0-default-workspace-id.md` planned to
    "reassign every nil-workspace event to the real workspace"; seeding the row
    with the sentinel's own id reaches the same place without rewriting a single
    append-only event, which is the better outcome for a log that is the source
    of truth).

    Unlike `event_log`, this is ordinary mutable state: a workspace is
    configuration, not a claim about the world, so it has no reason to be
    event-sourced.
    """

    __tablename__ = "workspace"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class WorkspaceMember(Base):
    """Who may act in a workspace, and in what capacity.

    `actor` is the same string that lands on every Event's `actor` column -- the
    person's name as they signed in. That is deliberate: membership and the audit
    trail must key on the same identity, or "who confirmed this" and "who is
    allowed to confirm" become two different questions about two different
    people. Phase 4 replaces the string with a real user id when SSO arrives; the
    column is the seam that makes that a migration rather than a redesign.
    """

    __tablename__ = "workspace_member"
    __table_args__ = (
        PrimaryKeyConstraint("workspace_id", "actor", name="pk_workspace_member"),
        Index("ix_workspace_member_actor", "actor"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        _UUID, ForeignKey("workspace.id", ondelete="CASCADE"), nullable=False
    )
    actor: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[Role] = mapped_column(
        Enum(
            Role,
            name="workspace_role",
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


def append_event(
    session: Session,
    *,
    event_type: EventType,
    payload: dict[str, Any],
    actor: str,
    workspace_id: uuid.UUID,
) -> EventLog:
    """The one sanctioned way to add a row to event_log.

    Callers commit (see `storage.db.session_scope`); this only stages + flushes
    so the caller gets back a row with its generated `id`/`timestamp`/`sequence`.

    `payload` is stored as-is with no validation -- callers writing
    `node_created`/`edge_created` events must pass `Node.model_dump()` /
    `Edge.model_dump()` from an already-validated model, and confirmation events
    the dump of a `NodeStatusChangePayload`/`NodeEditPayload`, never a hand-built
    dict (CLAUDE.md: nothing unvalidated reaches storage).

    `actor` *is* checked here, because it is the one field this function owns
    outright: every event is the audit record for who did what (TRD Sec9), and a
    blank actor is an audit hole rather than a missing convenience. The column's
    NOT NULL doesn't catch `""`, and the `Event.actor` rule in models/schema.py
    only guards the domain model, which this write path doesn't construct.
    """
    if not actor.strip():
        raise ValueError("actor must not be blank or whitespace-only")
    event = EventLog(
        event_type=event_type,
        payload=payload,
        actor=actor,
        workspace_id=workspace_id,
    )
    session.add(event)
    session.flush()
    return event
