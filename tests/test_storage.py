"""Tests for storage/db.py + storage/tables.py: engine/session setup and the
append-only event_log table (TRD Sec3.1 Event, Sec3.2 event-sourcing).

Uses an in-memory SQLite engine rather than live Supabase/Postgres so these
run with no network access and no secrets -- they assert table shape and
write/read behavior, which is dialect-independent (the JSONB variant and
Postgres-only DDL are exercised by the Alembic migration instead).
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import Engine, inspect
from sqlalchemy.orm import Session, sessionmaker

from atlas.storage.db import Base, get_engine, get_sessionmaker, session_scope
from atlas.storage.tables import EventLog, EventType, append_event


@pytest.fixture
def engine() -> Engine:
    engine = get_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def session_factory(engine: Engine) -> sessionmaker[Session]:
    return get_sessionmaker(engine)


def test_event_log_table_matches_trd_event_shape(engine: Engine) -> None:
    columns = {col["name"] for col in inspect(engine).get_columns("event_log")}
    assert columns == {"id", "event_type", "payload", "actor", "timestamp", "workspace_id"}


def test_append_event_writes_a_readable_row(session_factory: sessionmaker[Session]) -> None:
    workspace_id = uuid.uuid4()

    with session_scope(session_factory) as session:
        append_event(
            session,
            event_type=EventType.NODE_CREATED,
            payload={"node_id": "abc", "type": "goal"},
            actor="system",
            workspace_id=workspace_id,
        )

    with session_scope(session_factory) as session:
        rows = session.query(EventLog).all()
        assert len(rows) == 1
        row = rows[0]
        assert row.event_type == EventType.NODE_CREATED
        assert row.payload == {"node_id": "abc", "type": "goal"}
        assert row.actor == "system"
        assert row.workspace_id == workspace_id
        assert row.timestamp is not None


def test_event_type_is_stored_as_its_string_value_not_member_name(
    engine: Engine, session_factory: sessionmaker[Session]
) -> None:
    """Regression test: SQLAlchemy's Enum() defaults to storing the Python
    member *name* ("INGESTION_RUN"), but the Postgres enum type created by
    the Alembic migration only has the lowercase `.value`s ("ingestion_run").
    SQLite has no native enum constraint so it silently accepts either --
    this test reads the raw stored string to catch the mismatch that only
    surfaces against real Postgres."""
    from sqlalchemy import text

    with session_scope(session_factory) as session:
        append_event(
            session,
            event_type=EventType.INGESTION_RUN,
            payload={},
            actor="system",
            workspace_id=uuid.uuid4(),
        )

    with engine.connect() as conn:
        raw_value = conn.execute(text("select event_type from event_log")).scalar_one()
        assert raw_value == "ingestion_run"


def test_session_scope_rolls_back_on_error(session_factory: sessionmaker[Session]) -> None:
    with pytest.raises(RuntimeError), session_scope(session_factory) as session:
        append_event(
            session,
            event_type=EventType.INGESTION_RUN,
            payload={},
            actor="system",
            workspace_id=uuid.uuid4(),
        )
        raise RuntimeError("boom")

    with session_scope(session_factory) as session:
        assert session.query(EventLog).count() == 0


def test_get_engine_rewrites_bare_postgres_scheme_to_psycopg() -> None:
    """Supabase hands out `postgresql://...` connection strings verbatim; we
    install `psycopg` (v3), not `psycopg2`, so the bare scheme must be
    rewritten or SQLAlchemy tries to load a driver that isn't installed."""
    engine = get_engine("postgresql://user:pw@example.supabase.co:5432/postgres")
    assert engine.url.drivername == "postgresql+psycopg"
    assert engine.url.host == "example.supabase.co"


def test_get_engine_leaves_explicit_driver_scheme_untouched() -> None:
    engine = get_engine("postgresql+psycopg://user:pw@example.supabase.co:5432/postgres")
    assert engine.url.drivername == "postgresql+psycopg"


def test_get_engine_leaves_non_postgres_schemes_untouched() -> None:
    engine = get_engine("sqlite:///:memory:")
    assert engine.url.drivername == "sqlite"


def test_event_log_is_append_only_by_convention() -> None:
    """No update/delete helper is exposed -- corrections are new events, never
    a mutation of an existing row (CLAUDE.md: 'never mutate a Node/Edge table
    directly -- write an event')."""
    import atlas.storage.tables as tables_module

    assert not hasattr(tables_module, "update_event")
    assert not hasattr(tables_module, "delete_event")
