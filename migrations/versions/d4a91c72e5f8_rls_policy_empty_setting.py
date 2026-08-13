"""RLS policy: treat an unset scope as "no rows", not as a cast error

Revision ID: d4a91c72e5f8
Revises: c3d8e1f60b21
Create Date: 2026-08-13

`b7c2f1a45d90` wrote the policy as::

    workspace_id = current_setting('atlas.workspace_id', true)::uuid

with the documented intent that a query which *forgets* to scope itself returns
nothing. Against the live database it does something else: it raises
``invalid input syntax for type uuid: ""``.

The reason is connection pooling. `current_setting(name, true)` returns NULL
only for a parameter the session has never seen; once a pooled backend has had
`atlas.workspace_id` set and then reset (Supavisor issues `DISCARD ALL` between
checkouts), the parameter still exists with an **empty string** value -- and
``''::uuid`` is an error, not NULL. So the behaviour depended on whether a
recycled backend happened to have been scoped before, which is exactly the kind
of thing that passes every test and then surfaces under load.

`nullif(..., '')` collapses both cases -- never set, and set-then-reset -- to
NULL, so the comparison is NULL and the row is filtered out. The policy still
fails closed; it just does it as "no rows" instead of a 500.

Unset scope was never a *safe* state and this does not make it one. It stays
unreachable in application code: `storage/rbac.py::workspace_session` is the only
way a transaction is opened.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "d4a91c72e5f8"
down_revision: str | Sequence[str] | None = "c3d8e1f60b21"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SCOPE = "nullif(current_setting('atlas.workspace_id', true), '')::uuid"
_SCOPE_OLD = "current_setting('atlas.workspace_id', true)::uuid"


def _recreate_policy(scope: str) -> None:
    op.execute("DROP POLICY IF EXISTS event_log_workspace_isolation ON event_log")
    op.execute(
        f"""
        CREATE POLICY event_log_workspace_isolation ON event_log
        USING (workspace_id = {scope})
        WITH CHECK (workspace_id = {scope})
        """
    )


def upgrade() -> None:
    _recreate_policy(_SCOPE)


def downgrade() -> None:
    _recreate_policy(_SCOPE_OLD)
