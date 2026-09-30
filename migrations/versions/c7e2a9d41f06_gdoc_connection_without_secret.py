"""Let a Google Docs connection hold no secret

Revision ID: c7e2a9d41f06
Revises: b41c9d0e7f38
Create Date: 2026-09-28

Google Docs is ingested under "share with Atlas"
(`docs/decisions/2026-09-28-google-docs-source.md`): the credential is Atlas's
own service account, held in the environment, and a docs connection records
only that a product reads docs shared with it. So `secret_ciphertext` and
`secret_hint` become nullable -- and a check constraint makes the nullability
exact: NULL for `gdoc`, NOT NULL for every other source. Without the constraint,
"nullable" would quietly allow a GitHub or Jira row with no credential, which
is the shape of a connection that fails on its first run.

The `source_type` enum already has `gdoc` (`a5d2f7c04e19` created it with every
`SourceType` member), so no enum change is needed. Existing rows are GitHub and
Jira rows with secrets, so they satisfy the constraint as they stand.

Downgrade restores NOT NULL, which fails loudly if any docs connection exists --
deliberately, rather than deleting them.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c7e2a9d41f06"
down_revision: str | Sequence[str] | None = "b41c9d0e7f38"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CHECK = "ck_connection_secret_matches_source"


def upgrade() -> None:
    op.alter_column(
        "connection", "secret_ciphertext", existing_type=sa.LargeBinary(), nullable=True
    )
    op.alter_column("connection", "secret_hint", existing_type=sa.Text(), nullable=True)
    op.create_check_constraint(
        _CHECK, "connection", "(source_type = 'gdoc') = (secret_ciphertext IS NULL)"
    )


def downgrade() -> None:
    op.drop_constraint(_CHECK, "connection", type_="check")
    op.alter_column("connection", "secret_hint", existing_type=sa.Text(), nullable=False)
    op.alter_column(
        "connection", "secret_ciphertext", existing_type=sa.LargeBinary(), nullable=False
    )
