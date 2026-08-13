# RLS applied for real — and the three reasons it wasn't working

**Date:** 2026-08-13
**Status:** Applied to the live Supabase project. Migrations `8c41a0b7e2d5` → `d4a91c72e5f8` are at head.
**Supersedes nothing; amends** `docs/decisions/2026-08-11-scope-rbac-audit-slice-1d.md` (§ row-level security) and `Phase1_Architecture.md` §7.

## What happened

Slice 1D wrote migration `b7c2f1a45d90` — RLS on `event_log`, `FORCE`d — and shipped it unapplied, because there was no reachable database. Applying it turned up three defects, each of which would have left the project believing it had a tenant boundary it did not have. Two of them are the kind that only a live Postgres can show you; **none of them would ever fail a test on SQLite**, which is the entire test suite.

The migration is now applied and isolation is **verified empirically**, not asserted.

## 1. The host was never the problem the tracker said it was

The previous session recorded "`db.<ref>.supabase.co` does not resolve → paused or deleted project." Half right, wrong cause, and the wrong cause pointed at the wrong fix.

The project was fine. `db.<ref>.supabase.co` publishes **only an AAAA record** — Supabase moved direct connections to IPv6-only, with IPv4 reachability via the connection pooler. This machine has a global IPv6 address and no working IPv6 route, so the name resolved to something it could never reach, which looks exactly like a dead host.

**Fix:** connect through the pooler — `aws-1-ap-northeast-2.pooler.supabase.com:5432`, username `<role>.<project-ref>`. Recorded in `.env.example` so the next person doesn't spend the same hour. Session mode (5432), not transaction mode (6543), because migrations and SQLAlchemy's pooling both want a real session.

## 2. `FORCE ROW LEVEL SECURITY` did nothing, because BYPASSRLS outranks it

This is the one that mattered. The policy was applied, `relrowsecurity` and `relforcerowsecurity` were both true, and the isolation test still came back:

```
scoped to A -> 3 row(s): [workspace A, workspace B]      # both
cross-workspace INSERT while scoped to A -> ALLOWED
```

Supabase grants its default `postgres` role `rolbypassrls`. **`FORCE` does not override `BYPASSRLS`** — `FORCE` only closes the narrower loophole where a table's *owner* is exempt from its own policies. A role with `BYPASSRLS` skips row security everywhere, forced or not. So the second lock was installed on a door the application walked around.

1D's reasoning was right in shape and wrong in fact: it identified that the app connects as the table owner and reached for `FORCE`. The actual exemption was one level up.

**Fix — migration `c3d8e1f60b21`:** the application stops connecting as `postgres`. A new `atlas_app` role, `NOSUPERUSER NOBYPASSRLS`, holds the least privilege the application needs and nothing else:

| Table | Grant | Why |
|---|---|---|
| `event_log` | `SELECT`, `INSERT` | No `UPDATE`, no `DELETE`. **Append-only stops being a convention the application observes and becomes something the database enforces** (Engineering Philosophy #3). |
| `workspace`, `workspace_member` | `SELECT` | Membership is provisioned out-of-band. Nothing in the request path can grant itself a role. |

The credentials split accordingly: `SUPABASE_DB_ADMIN_URL` (owner, DDL, Alembic only) and `SUPABASE_DB_URL` (the app, least privilege). `migrations/env.py` prefers the admin URL and falls back, so nothing breaks for a setup that predates the split.

That the app role cannot `DELETE` was confirmed the practical way: cleaning up the probe rows required the admin URL.

## 3. An unscoped query raised a cast error instead of returning nothing

With the policy finally binding, the documented fail-closed behaviour — "a query that forgets the filter returns nothing" — turned out to be:

```
psycopg.errors.InvalidTextRepresentation: invalid input syntax for type uuid: ""
```

`current_setting(name, true)` returns NULL only for a parameter the session has **never seen**. Once a pooled backend has had `atlas.workspace_id` set and then reset — Supavisor issues `DISCARD ALL` between checkouts — the parameter still exists holding an **empty string**, and `''::uuid` is an error, not NULL.

So the behaviour depended on whether a recycled backend happened to have been scoped before. It fails closed either way, but "500" and "zero rows" are very different things to debug, and which one you got was luck.

**Fix — migration `d4a91c72e5f8`:** `nullif(current_setting('atlas.workspace_id', true), '')::uuid` collapses never-set and set-then-reset to the same NULL. Unset scope stays unreachable from application code regardless — `workspace_session` is the only way a transaction is opened.

## Verified, as the application's own role

```
connected as: atlas_app        bypassrls: False

unscoped (fresh connection)                 -> 0 row(s)
scoped to A                                 -> 2 row(s)  [only A]
scoped to B                                 -> 2 row(s)  [only B]
scope reset to ''                           -> 0 row(s)
cross-workspace INSERT (scoped A, write B)  -> BLOCKED
UPDATE on event_log                         -> BLOCKED
DELETE on event_log                         -> BLOCKED
```

Probe rows were removed afterwards; the live log holds only real ingestion.

## Also fixed on the way

`b7c2f1a45d90` failed on first execution: `INSERT INTO workspace (id, name) VALUES (:id, ...)` binds a Python `str` as VARCHAR, which Postgres will not implicitly coerce to `uuid`. Now `CAST(:id AS uuid)`. Hand-written migrations are not exercised by anything until they run — worth remembering that the suite's green does not cover `migrations/`.

## What this does not cover

- `workspace` and `workspace_member` remain outside RLS, deliberately and unchanged from 1D: they are what resolve a request *to* a workspace, so gating them behind a setting that isn't known yet is circular. They are `SELECT`-only for the app role, which is the containment that matters.
- **A second connecting role is now a thing that exists.** Rotating `ATLAS_DB_APP_PASSWORD` means updating it in two places (the role and `SUPABASE_DB_URL`). Cheap now, worth automating if a third environment appears.
- SQLite still cannot exercise any of this. The suite tests the *seam* (`workspace_session` is used, `scope_to_workspace` is called); the policy itself is only ever evidenced by a run against Postgres like the one above.
