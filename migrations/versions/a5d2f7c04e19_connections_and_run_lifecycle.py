"""Connections table, its RLS/grants, and the run-lifecycle event types

Revision ID: a5d2f7c04e19
Revises: e6f3b8a20c47
Create Date: 2026-08-15

Slice 2B. Two independent things land together because the feature needs both:
ingestion triggered from the browser needs somewhere to keep the credential, and
a way to say whether the job it started is still going.

**1. Five new `event_type` values.** `ingestion_run_started` /
`ingestion_run_finished` / `ingestion_run_failed` bracket a run;
`connection_created` / `connection_revoked` are the audit record for a source
being connected or cut off. `event_log.event_type` is a real Postgres enum, so
adding a member to `EventType` without this migration fails at runtime with
``invalid input value for enum event_type`` -- and **no Python test can catch
it**, because `tests/` runs on SQLite, which has no enum type. That rule was
learned the hard way in `e6f3b8a20c47`; it is restated here because it will keep
being true.

**2. The `connection` table.** One credential, bound to one source, for one
product. Unlike `event_log` this table **is** mutable and, crucially,
**deletable**: revoking a credential has to actually remove the ciphertext, and
an append-only log cannot express that (see
`docs/architecture/product-model-and-frontend-rebuild-v1.md` §4.2). The secret is
stored as a Fernet ciphertext with the key held in `ATLAS_SECRET_KEY`, outside
the database -- the deliberate amendment to CLAUDE.md's "no secret ever lands in
the database" rule, argued in
`docs/decisions/2026-08-15-connections-and-ui-ingestion.md`.

Per `script.py.mako`'s header, the grants are written *in the same revision as
the table*, and they are the narrowest set the code actually needs. This table
gets `UPDATE` and `DELETE` where `event_log` deliberately does not: `UPDATE` for
`last_used_at`, `DELETE` because that is what revocation is. It carries the same
`workspace_id` RLS policy `event_log` does, in its `nullif(...)` form so an
unscoped query is "no rows" rather than a cast error (`d4a91c72e5f8`).

After applying: run `scripts/verify_rls.py`, which gained connection-table checks
in this slice. SQLite cannot exercise a single line of the security below.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a5d2f7c04e19"
down_revision: str | Sequence[str] | None = "e6f3b8a20c47"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "atlas_app"

_NEW_EVENT_TYPES = (
    "ingestion_run_started",
    "ingestion_run_finished",
    "ingestion_run_failed",
    "connection_created",
    "connection_revoked",
)

# Mirrors `models.schema.SourceType`. `create_type=False` so the CREATE is issued
# explicitly below rather than as a side effect of the column definition, which
# is what makes the downgrade able to drop it.
source_type_enum = postgresql.ENUM(
    "github_pr",
    "github_issue",
    "github_commit",
    "jira_ticket",
    "notion_page",
    "gdoc",
    "human_assertion",
    name="source_type",
    create_type=False,
)

_SCOPE = "nullif(current_setting('atlas.workspace_id', true), '')::uuid"


def upgrade() -> None:
    # Autocommit: ADD VALUE is not transactional on PostgreSQL < 12, and Alembic
    # opens a transaction for every migration.
    with op.get_context().autocommit_block():
        for value in _NEW_EVENT_TYPES:
            op.execute(f"ALTER TYPE event_type ADD VALUE IF NOT EXISTS '{value}'")

    source_type_enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "connection",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "workspace_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workspace.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # Not a foreign key: a product is a projection of the event log, so there
        # is no table to point at. The application checks the product exists in
        # the caller's own projection before writing a row here.
        sa.Column("product_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_type", source_type_enum, nullable=False),
        sa.Column("account", sa.Text(), nullable=False),
        sa.Column("host", sa.Text(), nullable=False),
        sa.Column("scope", sa.Text(), nullable=False),
        # The credential, encrypted. The key lives in ATLAS_SECRET_KEY, in the
        # environment -- a dump of this table alone yields nothing usable.
        sa.Column("secret_ciphertext", sa.LargeBinary(), nullable=False),
        # Last four characters only: enough to tell two tokens apart, far too
        # little to be one. Stored rather than derived so rendering a list never
        # decrypts anything.
        sa.Column("secret_hint", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_connection_workspace_product", "connection", ["workspace_id", "product_id"])

    # --- row-level security, from day one --------------------------------------
    op.execute("ALTER TABLE connection ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE connection FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY connection_workspace_isolation ON connection
        USING (workspace_id = {_SCOPE})
        WITH CHECK (workspace_id = {_SCOPE})
        """
    )

    # --- grants ----------------------------------------------------------------
    # Narrowest set the code needs. UPDATE is for `last_used_at` and nothing
    # else; DELETE is revocation, which must be a real delete or the ciphertext
    # outlives the revoking of it.
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE connection TO {APP_ROLE}")


def downgrade() -> None:
    """Drops the table; leaves the enum values, which Postgres cannot remove.

    Same reasoning as `e6f3b8a20c47`: there is no `ALTER TYPE ... DROP VALUE`,
    and every way to fake one rewrites rows in an append-only log. An unused enum
    member is inert.
    """
    op.execute(f"REVOKE ALL ON TABLE connection FROM {APP_ROLE}")
    op.execute("DROP POLICY IF EXISTS connection_workspace_isolation ON connection")
    op.drop_index("ix_connection_workspace_product", table_name="connection")
    op.drop_table("connection")
    source_type_enum.drop(op.get_bind(), checkfirst=True)
