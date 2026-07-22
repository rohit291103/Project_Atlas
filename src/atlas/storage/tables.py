"""event_log: the append-only source of truth (TRD Sec3.1 Event, Sec3.2).

Node/Edge state is never stored directly -- only events land here.
Materialized Node/Edge projections (storage/projections.py) are replayed
from this table, never written to independently.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Enum, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, Session, mapped_column
from sqlalchemy.sql import func

# EventType lives in models/schema.py (the single source of truth for the domain
# model); importing it here keeps the Postgres enum from ever drifting from the
# schema definition. storage -> models is the correct dependency direction.
from atlas.models.schema import EventType
from atlas.storage.db import Base

__all__ = ["EventLog", "EventType", "append_event"]

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

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True, default=uuid.uuid4)
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
    so the caller gets back a row with its generated `id`/`timestamp`.

    `payload` is stored as-is with no validation -- once `models/schema.py`
    exists, callers writing `node_created`/`edge_created` events must pass
    `Node.model_dump()`/`Edge.model_dump()` from an already-validated model,
    never a hand-built dict (CLAUDE.md: nothing unvalidated reaches storage).
    """
    event = EventLog(
        event_type=event_type,
        payload=payload,
        actor=actor,
        workspace_id=workspace_id,
    )
    session.add(event)
    session.flush()
    return event
