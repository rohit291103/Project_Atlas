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
from dataclasses import dataclass

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from atlas.models.schema import Role
from atlas.storage.tables import WorkspaceMember

__all__ = ["Membership", "find_membership", "scope_to_workspace"]

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
