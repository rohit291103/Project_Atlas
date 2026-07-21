"""SQLAlchemy engine/session setup for the event log.

Storage is Supabase-hosted Postgres, reached over `Settings.supabase_db_url`
alone -- there is no local DB container to run (Phase0_Architecture.md Sec3, Sec5).
`Base` is the declarative base every table in storage/tables.py maps onto.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    """Declarative base for all storage/tables.py ORM models."""


def normalize_database_url(database_url: str) -> str:
    """Rewrite a bare `postgresql://` scheme to `postgresql+psycopg://`.

    Supabase connection strings use the bare scheme, which SQLAlchemy defaults
    to the psycopg2 dialect -- we install psycopg (v3), not psycopg2, so an
    unrewritten URL fails at connect time with `ModuleNotFoundError`. Any
    other scheme (sqlite, an already-qualified `postgresql+...`) passes through.

    Returns the URL with its plaintext password intact (`create_engine` needs
    the real credential) -- never log or print this return value.
    """
    url = make_url(database_url)
    if url.drivername == "postgresql":
        return url.set(drivername="postgresql+psycopg").render_as_string(hide_password=False)
    return database_url


def get_engine(database_url: str, *, echo: bool = False) -> Engine:
    """Build the engine for `database_url` (typically `Settings.supabase_db_url`).

    `pool_pre_ping` guards against the stale-connection errors hosted Postgres
    poolers are prone to after a connection has sat idle.
    """
    return create_engine(normalize_database_url(database_url), echo=echo, pool_pre_ping=True)


def get_sessionmaker(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)


@contextmanager
def session_scope(session_factory: sessionmaker[Session]) -> Iterator[Session]:
    """Yield a session; commit on success, roll back and re-raise on error."""
    session = session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
