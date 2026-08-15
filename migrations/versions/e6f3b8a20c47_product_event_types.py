"""Add the product event types to the event_type enum

Revision ID: e6f3b8a20c47
Revises: d4a91c72e5f8
Create Date: 2026-08-14

The product layer introduces three event types -- `product_created`,
`product_renamed`, `feature_scope_assigned` -- and `event_log.event_type` is a
real Postgres enum, so writing one without this migration fails at runtime with
``invalid input value for enum event_type``.

**Worth reading if you are adding an EventType.** Nothing in the Python test
suite can catch this. `tests/` runs on SQLite, which has no enum type at all and
stores whatever string it is handed, so a new member passes every test and then
fails on the first live write. That is the same shape as the RLS gap
(`docs/architecture/rls-verification-checklist-v1.md`): a guarantee that only
exists in Postgres is invisible to a SQLite suite. Adding a member to
`EventType` therefore always means adding a migration, and the check is to write
one event of the new type against a real database.

`ALTER TYPE ... ADD VALUE` cannot run inside a transaction block on older
PostgreSQL, and Alembic wraps migrations in one, so each value is added with an
autocommit block. `IF NOT EXISTS` makes the migration re-runnable.

There is no downgrade. PostgreSQL cannot remove a value from an enum, and the
honest options -- rewriting the type, or rewriting rows that already use these
values -- both mean touching an append-only log. The log does not get rewritten
to undo a schema convenience.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "e6f3b8a20c47"
down_revision: str | Sequence[str] | None = "d4a91c72e5f8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NEW_VALUES = ("product_created", "product_renamed", "feature_scope_assigned")


def upgrade() -> None:
    # Autocommit: ADD VALUE is not transactional on PostgreSQL < 12 and Alembic
    # opens a transaction for every migration.
    with op.get_context().autocommit_block():
        for value in _NEW_VALUES:
            op.execute(f"ALTER TYPE event_type ADD VALUE IF NOT EXISTS '{value}'")


def downgrade() -> None:
    """Deliberately empty -- see the module docstring.

    PostgreSQL has no `ALTER TYPE ... DROP VALUE`, and every way to fake one
    involves rewriting rows in an append-only table. Leaving the values in place
    is inert: no code writes them after a downgrade, and an unused enum member
    costs nothing.
    """
