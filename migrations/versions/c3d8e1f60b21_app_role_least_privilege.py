"""least-privilege application role (makes RLS actually bind)

Revision ID: c3d8e1f60b21
Revises: b7c2f1a45d90
Create Date: 2026-08-13

`b7c2f1a45d90` enabled and FORCEd row-level security on `event_log`, and on a
fresh Supabase project the policy was **provably inert**: connected as the
default `postgres` role, a session scoped to workspace A still read workspace
B's rows and could still INSERT into B.

The reason is `rolbypassrls`. Supabase grants the `postgres` role BYPASSRLS, and
BYPASSRLS outranks `FORCE ROW LEVEL SECURITY` -- FORCE only closes the loophole
where a table's *owner* is exempt, it does nothing about a role that is exempt
from RLS globally. So the second lock was installed on a door the application
was walking around.

The fix is not a different policy, it is a different role. `atlas_app` is
NOBYPASSRLS and NOSUPERUSER, so the existing policy binds to it normally, and
its grants are the least privilege the application actually needs:

* `event_log` -- SELECT and INSERT only. No UPDATE, no DELETE. The append-only
  event log stops depending on the application choosing not to mutate it and
  starts being enforced by the database (Engineering Philosophy #3).
* `workspace` / `workspace_member` -- SELECT only. Membership is provisioned
  out-of-band; nothing in the request path should be able to grant itself a role.

Migrations keep running as `postgres` via `SUPABASE_DB_ADMIN_URL`; the
application connects as `atlas_app` via `SUPABASE_DB_URL`. The password comes
from `ATLAS_DB_APP_PASSWORD` in the environment and is never written to this
file, the repo, or the migration's log output.
"""

import os
from collections.abc import Sequence

from alembic import op
from sqlalchemy.engine import Connection

revision: str = "c3d8e1f60b21"
down_revision: str | Sequence[str] | None = "b7c2f1a45d90"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "atlas_app"


def _set_password(conn: Connection, password: str) -> None:
    """Set the role's password without the plaintext ever reaching an error path.

    `ALTER ROLE ... PASSWORD` takes no bind parameter, so the literal has to be
    inlined into the statement text -- quoted by the server via `quote_literal`
    rather than by string formatting here, so a password containing a quote can
    neither break out nor be mis-escaped.

    The statement text is therefore a secret. A driver exception carries the
    statement that failed, so an unwrapped failure (role renamed, permission
    revoked, connection dropped mid-statement) would print the cleartext password
    to stderr and into whatever captured it -- CI log, scrollback, error tracker.
    Both statements are wrapped so the original exception is dropped, not
    chained: `from None` matters, because a chained cause prints too.
    """
    try:
        quoted = conn.exec_driver_sql("SELECT quote_literal(%s)", (password,)).scalar()
    except Exception as exc:
        raise RuntimeError(
            f"Failed to quote the {APP_ROLE} password (error text withheld: it may "
            f"echo the value). Original exception type: {type(exc).__name__}"
        ) from None
    try:
        conn.exec_driver_sql(f"ALTER ROLE {APP_ROLE} PASSWORD {quoted}")
    except Exception as exc:
        raise RuntimeError(
            f"ALTER ROLE {APP_ROLE} PASSWORD failed (error text withheld: it would "
            f"contain the password in cleartext). Original exception type: "
            f"{type(exc).__name__}. Re-run with a psql session to diagnose."
        ) from None


def upgrade() -> None:
    password = os.environ.get("ATLAS_DB_APP_PASSWORD")
    if not password:
        raise RuntimeError(
            "ATLAS_DB_APP_PASSWORD is not set. This migration creates the "
            f"least-privilege {APP_ROLE} role the application connects as -- see .env.example."
        )

    conn = op.get_bind()
    conn.exec_driver_sql(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
                CREATE ROLE {APP_ROLE} LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
            END IF;
        END
        $$
        """
    )

    _set_password(conn, password)

    conn.exec_driver_sql(f"GRANT USAGE ON SCHEMA public TO {APP_ROLE}")
    # Append-only, enforced by the grant and not by convention.
    conn.exec_driver_sql(f"GRANT SELECT, INSERT ON TABLE event_log TO {APP_ROLE}")
    conn.exec_driver_sql(f"GRANT SELECT ON TABLE workspace, workspace_member TO {APP_ROLE}")


def downgrade() -> None:
    conn = op.get_bind()
    conn.exec_driver_sql(f"REVOKE ALL ON TABLE event_log FROM {APP_ROLE}")
    conn.exec_driver_sql(f"REVOKE ALL ON TABLE workspace, workspace_member FROM {APP_ROLE}")
    conn.exec_driver_sql(f"REVOKE USAGE ON SCHEMA public FROM {APP_ROLE}")
    conn.exec_driver_sql(f"DROP ROLE IF EXISTS {APP_ROLE}")
