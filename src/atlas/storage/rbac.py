"""Workspace membership lookup and the row-level-security scope (slice 1D).

Two jobs, both about the tenant boundary:

* `find_membership` answers "which workspace is this person in, and what may
  they do there" -- the query behind `api/deps.py::get_principal`. Authorization
  data lives in the database rather than in the session cookie for the reason
  §4 of the boundary decision gives: the tenant boundary must be a server-side
  fact, so revoking someone takes effect on their next request rather than
  whenever their cookie happens to expire.

* `scope_to_workspace` sets the Postgres session variable the RLS policies read.
  Application code already filters by `workspace_id` in SQL; RLS is the second
  lock, so that a query that *forgets* the filter returns nothing instead of
  another tenant's rows. Defense in depth is the whole point -- the day it
  matters is the day someone writes a query without the WHERE clause.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from sqlalchemy import select, text
from sqlalchemy.orm import Session, sessionmaker

from atlas.models.schema import Role
from atlas.storage.db import session_scope
from atlas.storage.tables import Workspace, WorkspaceMember

__all__ = [
    "Membership",
    "MembershipError",
    "create_workspace",
    "find_membership",
    "scope_to_workspace",
    "seat_member",
    "workspace_session",
]

#: Read by the RLS policies in migration `b7c2f1a45d90`. Namespaced so it cannot
#: collide with anything Postgres or Supabase sets.
WORKSPACE_SETTING = "atlas.workspace_id"


@dataclass(frozen=True)
class Membership:
    workspace_id: uuid.UUID
    actor: str
    role: Role


def find_membership(session: Session, actor: str) -> Membership | None:
    """The workspace `actor` belongs to, or None if they belong to none.

    A person in more than one workspace resolves to their earliest membership.
    Phase 1 has no workspace switcher (one workspace, one PM) and inventing one
    here would be building Phase 4's surface early -- but picking *deterministic-
    ally* means the answer never changes between two requests, which a `LIMIT 1`
    over an unordered query would not guarantee.
    """
    stmt = (
        select(WorkspaceMember)
        .where(WorkspaceMember.actor == actor)
        .order_by(WorkspaceMember.created_at, WorkspaceMember.workspace_id)
        .limit(1)
    )
    row = session.execute(stmt).scalar_one_or_none()
    if row is None:
        return None
    return Membership(workspace_id=row.workspace_id, actor=row.actor, role=row.role)


class MembershipError(ValueError):
    """A seat that would not work as intended -- refused rather than written."""


def create_workspace(session: Session, name: str) -> uuid.UUID:
    """Provision a new, empty workspace. Operator-only: `atlas_app` cannot write
    `workspace` (`c3d8e1f60b21`), so this runs over the owner connection."""
    workspace = Workspace(id=uuid.uuid4(), name=name)
    session.add(workspace)
    session.flush()
    return workspace.id


def seat_member(session: Session, workspace_id: uuid.UUID, actor: str, role: Role) -> None:
    """Seat `actor` in `workspace_id`, or change their role if already seated there.

    Refuses what would silently not work: a name with surrounding whitespace
    (membership matches the sign-in name exactly, so it could never be typed),
    a workspace that does not exist, and a person already seated elsewhere --
    `find_membership` resolves to the earliest membership, so a second seat
    would sign them in to the other workspace without a word.
    """
    if not actor.strip() or actor != actor.strip():
        raise MembershipError(f"{actor!r} must be the exact name typed at sign-in")
    if session.get(Workspace, workspace_id) is None:
        raise MembershipError(f"no workspace {workspace_id}")
    existing = find_membership(session, actor)
    if existing is not None and existing.workspace_id != workspace_id:
        raise MembershipError(f"{actor} is already a member of workspace {existing.workspace_id}")
    row = session.get(WorkspaceMember, (workspace_id, actor))
    if row is None:
        session.add(WorkspaceMember(workspace_id=workspace_id, actor=actor, role=role))
    else:
        row.role = role
    session.flush()


def scope_to_workspace(session: Session, workspace_id: uuid.UUID) -> None:
    """Pin this transaction to one workspace for the RLS policies to enforce.

    `SET LOCAL` is transaction-scoped, so the setting cannot leak to the next
    request that borrows the same pooled connection -- which is exactly the bug
    a session-scoped `SET` would introduce under a connection pool.

    A no-op on any dialect without RLS: SQLite is the test harness only, and
    production is Postgres. That split is the same test-fidelity trade as the
    `event_log.sequence` shim in conftest, and it has the same consequence --
    **the policies themselves are not exercised by the test suite** and are only
    live once the migration has been applied to the real database.
    """
    bind = session.get_bind()
    if bind.dialect.name != "postgresql":
        return
    session.execute(
        text(f"SELECT set_config('{WORKSPACE_SETTING}', :workspace_id, true)"),
        {"workspace_id": str(workspace_id)},
    )


@contextmanager
def workspace_session(
    session_factory: sessionmaker[Session], workspace_id: uuid.UUID
) -> Iterator[Session]:
    """A transaction already scoped to one workspace -- the only way non-API code
    should open one once RLS is enabled.

    This exists because the policy is `FORCE`d, which means it binds the
    application's own role: a transaction that never sets the setting reads
    **zero rows** and fails every insert's `WITH CHECK`. So `session_scope` alone
    is no longer sufficient for anything that touches `event_log`, and pairing the
    two here makes forgetting structurally hard rather than a thing to remember.

    The API cannot use this -- it does not know the workspace until it has read
    the session cookie, so `deps.get_principal` scopes the transaction after
    resolving membership instead.
    """
    with session_scope(session_factory) as session:
        scope_to_workspace(session, workspace_id)
        yield session


@contextmanager
def owner_session(session_factory: sessionmaker[Session]) -> Iterator[Session]:
    """A transaction that deliberately crosses workspaces.

    For operator tasks only -- `rotate-secrets`, `workspace-create`,
    `member-seat` -- and only over the
    *owner* connection (`SUPABASE_DB_ADMIN_URL`), which RLS does not narrow. It
    is named, rather than being a bare `session_scope`, so that crossing the
    tenant boundary is always a visible choice: under the app role a bare
    session reads zero rows, which is the bug `workspace_session` exists to
    prevent, and `tests/test_cli.py` keeps `session_scope(` out of the CLI.
    """
    with session_scope(session_factory) as session:
        yield session
