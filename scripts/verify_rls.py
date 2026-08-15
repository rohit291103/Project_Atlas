"""Prove, against a live Postgres, that the tenant boundary actually holds.

The test suite cannot do this. `tests/` runs on SQLite, which has no roles, no
GRANTs and no row-level security -- so every guarantee in
`b7c2f1a45d90` (RLS), `c3d8e1f60b21` (the least-privilege `atlas_app` role) and
`d4a91c72e5f8` (the empty-setting fix) is invisible to pytest. That gap is not
an oversight to be papered over with a mock: mocking a policy engine tests the
mock. This script is the substitute -- run it against the real database after
any migration touching roles, grants or policies on `event_log`.

Why this is worth having as code rather than a list of psql commands: the first
time these checks were run by hand they *passed while being wrong*. psycopg's
`connection.transaction()` nests as a SAVEPOINT, so a `set_config(..., is_local
=> true)` from an earlier block was still in force during the supposedly
"unscoped" read, which duly returned rows and looked like a correct result. Every
check below therefore opens its **own connection** and never nests.

Usage:

    set -a && source .env && set +a
    uv run python scripts/verify_rls.py

Reads `SUPABASE_DB_ADMIN_URL` (owner: seeds and removes the probe rows) and
`SUPABASE_DB_URL` (the `atlas_app` role: the thing under test). Exit status is 0
only if every check passes. The probe rows it creates are removed in a `finally`,
including on failure.
"""

from __future__ import annotations

import os
import sys
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import psycopg

APP_ROLE = "atlas_app"
SCOPE = "atlas.workspace_id"

#: `sequence` is deliberately omitted so the identity column assigns it, which is
#: what `storage.tables.append_event` does. Supplying `max(sequence) + 1` instead
#: -- the obvious hand-written form -- is wrong for a reason worth recording: as
#: `atlas_app` the subquery only sees rows *inside the current scope*, so it
#: computes a value the rest of the table already used and the insert dies on
#: `uq_event_log_sequence`. Under RLS an aggregate is an aggregate over what you
#: can see, and that is easy to forget when writing a query as the owner.
_INSERT = (
    "INSERT INTO event_log (id, event_type, payload, actor, workspace_id) "
    "VALUES (gen_random_uuid(), 'ingestion_run', '{}'::jsonb, 'rls-probe', %s)"
)

#: The `connection` table (slice 2B) holds encrypted source credentials, so its
#: isolation matters more than `event_log`'s, not less: a leak across the tenant
#: boundary here is a leak of someone else's GitHub token. Unlike `event_log`
#: this table is legitimately mutable and deletable -- revocation must be a real
#: delete -- so the checks differ: **the policy** must refuse a cross-workspace
#: read, insert, update and delete, where for `event_log` the last two are
#: refused by the *grant*.
_CONNECTION_INSERT = (
    "INSERT INTO connection "
    "(id, workspace_id, product_id, source_type, account, host, scope, "
    " secret_ciphertext, secret_hint, created_by) "
    "VALUES (gen_random_uuid(), %s, gen_random_uuid(), 'github_pr', 'probe', "
    "'github.com', 'acme/probe', '\\x00'::bytea, 'xxxx', 'rls-probe')"
)


def _dsn(name: str) -> str:
    url = os.environ.get(name)
    if not url:
        raise SystemExit(f"{name} is not set -- `set -a && source .env && set +a` first.")
    # storage/db.py normalizes to SQLAlchemy's `postgresql+psycopg://`; libpq wants
    # the bare scheme.
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


@contextmanager
def app_connection() -> Iterator[psycopg.Connection]:
    """A fresh `atlas_app` connection, used for exactly one check.

    Fresh because a scope set with `is_local => true` outlives its block when
    blocks nest as savepoints -- see the module docstring. One connection per
    check makes that structurally impossible rather than merely avoided.
    """
    conn = psycopg.connect(_dsn("SUPABASE_DB_URL"))
    try:
        yield conn
    finally:
        conn.close()


def scoped_read(workspace_id: str | None) -> set[str]:
    """Workspace ids visible to `atlas_app` under the given scope.

    `None` means "never set the GUC at all" (a connection straight from the
    pooler); `""` means "set it to empty", which is what the pooler's `DISCARD
    ALL` leaves behind and what `d4a91c72e5f8` had to make safe -- `''::uuid`
    raises rather than yielding NULL, so the policy has to `nullif` it.
    """
    with app_connection() as conn, conn.transaction():
        cur = conn.cursor()
        if workspace_id is not None:
            cur.execute("SELECT set_config(%s, %s, true)", (SCOPE, workspace_id))
        cur.execute("SELECT DISTINCT workspace_id::text FROM event_log")
        return {row[0] for row in cur.fetchall()}


def scoped_connection_read(workspace_id: str | None) -> set[str]:
    """Connection rows visible to `atlas_app` under the given scope.

    The credential table's version of `scoped_read`. A cross-tenant read here
    would expose ciphertext plus the host and scope naming exactly what it opens.
    """
    with app_connection() as conn, conn.transaction():
        cur = conn.cursor()
        if workspace_id is not None:
            cur.execute("SELECT set_config(%s, %s, true)", (SCOPE, workspace_id))
        cur.execute("SELECT DISTINCT workspace_id::text FROM connection")
        return {row[0] for row in cur.fetchall()}


def rows_touched(sql: str, params: tuple[Any, ...], *, scope: str) -> int:
    """Run a statement under `scope` and report how many rows it changed.

    `connection` holds all four grants, so a cross-workspace UPDATE or DELETE
    does **not** raise the way `event_log`'s does -- the policy simply filters
    the rows out and the statement succeeds affecting nothing. "Refused" and
    "reached nothing" are different mechanisms with the same consequence, and
    asserting the wrong one would pass while testing nothing. Always rolled back.
    """
    with app_connection() as conn:
        try:
            with conn.transaction() as tx:
                cur = conn.cursor()
                cur.execute("SELECT set_config(%s, %s, true)", (SCOPE, scope))
                cur.execute(sql, params)
                touched = cur.rowcount
                raise psycopg.Rollback(tx)
        except psycopg.Error as exc:  # a denial is also "reached nothing"
            return 0 if isinstance(exc, psycopg.errors.InsufficientPrivilege) else -1
        return touched


def expect_denied(sql: str, params: tuple[Any, ...], *, scope: str, contains: str) -> str | None:
    """Run a statement that must fail, and check it failed for the right reason.

    `contains` is why this takes an argument rather than just catching the error:
    `permission denied for table` and `new row violates row-level security policy`
    share SQLSTATE 42501, and they are *not* interchangeable. The first means the
    grant refused it, the second means the policy did. A check that accepted
    either would still pass after one of the two mechanisms was removed.

    Returns None on success (denied as expected) or a description of what went
    wrong. The transaction is rolled back either way, so a statement that wrongly
    *succeeds* still leaves no trace.
    """
    with app_connection() as conn:
        try:
            with conn.transaction() as tx:
                cur = conn.cursor()
                cur.execute("SELECT set_config(%s, %s, true)", (SCOPE, scope))
                cur.execute(sql, params)
                # Caught and swallowed by the transaction block itself: the
                # statement was allowed, so undo it before reporting that.
                raise psycopg.Rollback(tx)
        except psycopg.errors.InsufficientPrivilege as exc:
            message = str(exc).splitlines()[0]
            if contains not in str(exc):
                return f"denied, but not by the expected mechanism: {message}"
            return None
        except psycopg.Error as exc:
            return f"failed with an unrelated error ({exc.sqlstate}): {str(exc).splitlines()[0]}"
        return "NOT DENIED -- the statement was allowed to run"


def main() -> int:
    admin = psycopg.connect(_dsn("SUPABASE_DB_ADMIN_URL"), autocommit=True)
    ws_a, ws_b = str(uuid.uuid4()), str(uuid.uuid4())
    results: list[tuple[bool, str, str]] = []

    def check(name: str, passed: bool, detail: str = "") -> None:
        results.append((passed, name, detail))

    try:
        with admin.cursor() as cur:
            for ws, label in ((ws_a, "A"), (ws_b, "B")):
                cur.execute(
                    "INSERT INTO workspace (id, name) VALUES (%s, %s)", (ws, f"RLS probe {label}")
                )
                cur.execute(_INSERT, (ws,))

        # -- the role itself ---------------------------------------------------
        with app_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT current_user, rolsuper, rolbypassrls "
                "FROM pg_roles WHERE rolname = current_user"
            )
            row = cur.fetchone()
        if row is None:
            raise SystemExit("connected, but current_user has no row in pg_roles")
        user, is_super, bypasses = row
        check(f"application connects as {APP_ROLE}", user == APP_ROLE, f"connected as {user!r}")
        check("application role is not superuser", not is_super)
        # The whole reason c3d8e1f60b21 exists: BYPASSRLS outranks FORCE ROW LEVEL
        # SECURITY, so a policy on a BYPASSRLS role is decorative.
        check("application role does not bypass RLS", not bypasses)

        # -- reads -------------------------------------------------------------
        for label, scope, expected in (
            ("unscoped read returns nothing", None, set()),
            ("read scoped to A returns only A", ws_a, {ws_a}),
            ("read scoped to B returns only B", ws_b, {ws_b}),
            ("read with the scope reset to '' returns nothing", "", set()),
        ):
            seen = scoped_read(scope)
            check(label, seen == expected, f"saw {seen or '{}'}")

        # -- writes ------------------------------------------------------------
        check(
            "insert into another workspace is blocked by the policy",
            (why := expect_denied(_INSERT, (ws_b,), scope=ws_a, contains="row-level security"))
            is None,
            why or "",
        )
        # UPDATE/DELETE are blocked by the *grant*, not the policy -- that is what
        # makes event_log append-only in the database rather than by convention.
        check(
            "update is blocked by the grant",
            (
                why := expect_denied(
                    "UPDATE event_log SET actor = 'tampered' WHERE workspace_id = %s",
                    (ws_a,),
                    scope=ws_a,
                    contains="permission denied",
                )
            )
            is None,
            why or "",
        )
        check(
            "delete is blocked by the grant",
            (
                why := expect_denied(
                    "DELETE FROM event_log WHERE workspace_id = %s",
                    (ws_a,),
                    scope=ws_a,
                    contains="permission denied",
                )
            )
            is None,
            why or "",
        )

        # An insert *into its own scope* must still work, or the application is
        # simply broken -- a boundary that blocks everything proves nothing.
        allowed, why = True, ""
        with app_connection() as conn:
            try:
                with conn.transaction() as tx:
                    cur = conn.cursor()
                    cur.execute("SELECT set_config(%s, %s, true)", (SCOPE, ws_a))
                    cur.execute(_INSERT, (ws_a,))
                    raise psycopg.Rollback(tx)  # it worked; don't keep the row
            except psycopg.Error as exc:
                allowed, why = False, f"{exc.sqlstate}: {str(exc).splitlines()[0]}"
        check("insert into its own workspace is allowed", allowed, why)

        # -- the connection table (slice 2B) -----------------------------------
        # Seeded here rather than at the top so a failure above still reports
        # every earlier check before this section runs.
        with admin.cursor() as cur:
            for ws in (ws_a, ws_b):
                cur.execute(_CONNECTION_INSERT, (ws,))

        for label, scope, expected in (
            ("connections: unscoped read returns nothing", None, set()),
            ("connections: read scoped to A returns only A", ws_a, {ws_a}),
            ("connections: read scoped to B returns only B", ws_b, {ws_b}),
        ):
            seen = scoped_connection_read(scope)
            check(label, seen == expected, f"saw {seen or '{}'}")

        # Every write verb, because this table *has* all four grants -- so the
        # only thing standing between workspace A and workspace B's credentials
        # is the policy. If it were removed, `event_log`'s missing UPDATE/DELETE
        # grants would not save this table.
        check(
            "connections: cross-workspace insert is blocked by the policy",
            (
                why := expect_denied(
                    _CONNECTION_INSERT, (ws_b,), scope=ws_a, contains="row-level security"
                )
            )
            is None,
            why or "",
        )
        for verb, sql in (
            ("update", "UPDATE connection SET scope = 'stolen' WHERE workspace_id = %s"),
            ("delete", "DELETE FROM connection WHERE workspace_id = %s"),
        ):
            touched = rows_touched(sql, (ws_b,), scope=ws_a)
            check(
                f"connections: cross-workspace {verb} reaches nothing",
                touched == 0,
                f"{verb} touched {touched} row(s) in workspace B",
            )

    finally:
        with admin.cursor() as cur:
            cur.execute("DELETE FROM connection WHERE workspace_id = ANY(%s)", ([ws_a, ws_b],))
            cur.execute("DELETE FROM event_log WHERE workspace_id = ANY(%s)", ([ws_a, ws_b],))
            cur.execute("DELETE FROM workspace WHERE id = ANY(%s)", ([ws_a, ws_b],))
        admin.close()

    for passed, name, detail in results:
        suffix = f"  -- {detail}" if detail and not passed else ""
        print(f"{'PASS' if passed else 'FAIL'}  {name}{suffix}")

    failed = [name for passed, name, _ in results if not passed]
    print()
    if failed:
        print(f"{len(failed)} of {len(results)} checks FAILED. The tenant boundary is not sound.")
        return 1
    print(f"All {len(results)} checks passed. The tenant boundary holds as {APP_ROLE}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
