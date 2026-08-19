"""Add the description event types to the event_type enum

Revision ID: b41c9d0e7f38
Revises: f9b41d7e3a52
Create Date: 2026-08-20

Slice 3 gives a product and a feature somewhere to say what they *are*
(`docs/decisions/2026-08-19-product-orientation-rerun-safety-and-demo-data.md`
decision 4). Orientation is PM-authored text, so it is an ordinary event-sourced
field rather than a Node -- but it is still two new members of `EventType`, and
`event_log.event_type` is a real Postgres enum. Writing one without this
migration fails at runtime with ``invalid input value for enum event_type``.

**Nothing in the Python test suite can catch that**, which is why this file
exists rather than being judged unnecessary: `tests/` runs on SQLite, which has
no enum type and stores whatever string it is handed, so a new member passes
every test and then fails on the first live write. Same shape as `e6f3b8a20c47`,
which added the product event types and says the same thing at more length. The
check is to write one event of each new type against a real database.

`ALTER TYPE ... ADD VALUE` cannot run inside a transaction block on older
PostgreSQL and Alembic wraps migrations in one, so the values are added in an
autocommit block. `IF NOT EXISTS` makes the migration re-runnable.

There is no downgrade, for the reason `e6f3b8a20c47` gives: PostgreSQL cannot
remove a value from an enum, and every way to fake it means rewriting rows in an
append-only log.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "b41c9d0e7f38"
down_revision: str | Sequence[str] | None = "f9b41d7e3a52"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NEW_VALUES = ("product_described", "feature_scope_described")


def upgrade() -> None:
    # Autocommit: ADD VALUE is not transactional on PostgreSQL < 12 and Alembic
    # opens a transaction for every migration.
    with op.get_context().autocommit_block():
        for value in _NEW_VALUES:
            op.execute(f"ALTER TYPE event_type ADD VALUE IF NOT EXISTS '{value}'")


def downgrade() -> None:
    """Deliberately empty -- see the module docstring and `e6f3b8a20c47`.

    An unused enum member is inert: no code writes it after a downgrade, and
    removing it would mean rewriting an append-only table.
    """
