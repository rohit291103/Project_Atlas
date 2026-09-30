"""Add the comment_added event type to the event_type enum

Revision ID: d2f8b6a17c35
Revises: c7e2a9d41f06
Create Date: 2026-09-30

Comment threads on a claim (Phase 4, roadmap v2 `[+2026-09-02]`) are events
like every other write, so `EventType` gains `comment_added` -- and
`event_log.event_type` is a real Postgres enum. SQLite, which the test suite
runs on, has no enum type, so nothing in `tests/` can catch a missing value;
the check is one live write. Same shape as `b41c9d0e7f38`: added in an
autocommit block, `IF NOT EXISTS` so it re-runs, and no downgrade, because
PostgreSQL cannot remove an enum value without rewriting an append-only log.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "d2f8b6a17c35"
down_revision: str | Sequence[str] | None = "c7e2a9d41f06"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE event_type ADD VALUE IF NOT EXISTS 'comment_added'")


def downgrade() -> None:
    """Deliberately empty -- an unused enum member is inert (see `b41c9d0e7f38`)."""
