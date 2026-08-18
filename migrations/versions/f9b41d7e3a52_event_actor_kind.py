"""Add event_log.actor_kind -- was a person behind this event?

Revision ID: f9b41d7e3a52
Revises: a5d2f7c04e19
Create Date: 2026-08-18

`actor` names *who* acted; it could never answer *whether it was a human*. A PM
signing in and a test harness driving the same UI write the same string, which
is how the browser suite confirmed 6 real claims under a person's name on
2026-08-16 -- irreversibly, because the log only moves forward.

roadmap-v2 makes "% of confirmations made by a human actor" a **guard** metric
that invalidates every other number when it is below 100%, and Phase 2 assembles
the exported spec from confirmed nodes. So the distinction has to live in the
log, not in a convention
(`docs/decisions/2026-08-18-roadmap-v2-spec-export-and-proof.md`).

**The backfill is deliberately not uniform.** Rows written by `pipeline.py` and
`cli.py` carry `actor` values of `system` or `cli`, and no person could ever have
written those: a signed-in actor must match a `workspace_member` row, and neither
string is seatable as a member. Those become `automated` because we genuinely
know what they were. Everything else becomes `unknown` -- not `human`, which
would be a guess, and a guess in exactly the direction that makes the guard
metric falsely reassuring. `append_event` refuses to write `unknown`, so the
ambiguous set is closed at this migration and can never grow.

The column takes **no server default**. A default would let a raw INSERT bypass
the decision `append_event` exists to force.

**No downgrade.** Dropping the column would destroy audit data -- which rulings
a person actually made -- and this project does not rewrite the log to undo a
schema change (same reasoning as `e6f3b8a20c47`).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f9b41d7e3a52"
down_revision: str | Sequence[str] | None = "a5d2f7c04e19"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Only `pipeline.py` and `cli.py` ever wrote these, and neither is seatable as a
#: workspace member, so no sign-in could have produced one.
_KNOWN_MACHINE_ACTORS = ("system", "cli")


def upgrade() -> None:
    actor_kind = sa.Enum("human", "automated", "unknown", name="actor_kind")
    actor_kind.create(op.get_bind(), checkfirst=True)

    op.add_column("event_log", sa.Column("actor_kind", actor_kind, nullable=True))

    op.execute(
        sa.text(
            "UPDATE event_log SET actor_kind = 'automated' WHERE actor IN :machine"
        ).bindparams(sa.bindparam("machine", value=_KNOWN_MACHINE_ACTORS, expanding=True))
    )
    op.execute("UPDATE event_log SET actor_kind = 'unknown' WHERE actor_kind IS NULL")

    op.alter_column("event_log", "actor_kind", nullable=False)


def downgrade() -> None:
    raise NotImplementedError(
        "actor_kind is audit data: dropping it would destroy the record of which "
        "rulings a person actually made. See this revision's docstring."
    )
