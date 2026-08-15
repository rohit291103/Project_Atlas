"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}

READ BEFORE ADDING A TABLE OR CHANGING event_log:

Migrations run as the *owner* (`SUPABASE_DB_ADMIN_URL`); the application runs as
the least-privilege `atlas_app` role (`SUPABASE_DB_URL`), which is NOBYPASSRLS so
row-level security actually binds to it. Two consequences that are silent until
they bite:

1. A new table has **no grants to `atlas_app`** by default. Adding one without a
   `GRANT` leaves the application with `permission denied` at runtime, not at
   migration time. Add the narrowest grant the code needs, in the same revision.
2. `event_log` is append-only *because of its grants* -- SELECT and INSERT, no
   UPDATE, no DELETE (Engineering Philosophy #3). `GRANT ALL` on it, or a new
   table holding Node/Edge state that is granted UPDATE, quietly removes that
   guarantee. If a table is meant to be a projection, it is rebuilt from events;
   it is not written to directly.

The authoritative grant list lives in `c3d8e1f60b21_app_role_least_privilege.py`.
Anything touching roles, grants, or RLS policies on `event_log` must be verified
against `docs/architecture/rls-verification-checklist-v1.md` after it is applied
-- SQLite cannot exercise Postgres roles, so the test suite will not catch it.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
${imports if imports else ""}

# revision identifiers, used by Alembic.
revision: str = ${repr(up_revision)}
down_revision: Union[str, Sequence[str], None] = ${repr(down_revision)}
branch_labels: Union[str, Sequence[str], None] = ${repr(branch_labels)}
depends_on: Union[str, Sequence[str], None] = ${repr(depends_on)}


def upgrade() -> None:
    """Upgrade schema."""
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    """Downgrade schema."""
    ${downgrades if downgrades else "pass"}
