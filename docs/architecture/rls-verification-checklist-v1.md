# Verifying the tenant boundary after a migration

**Applies to:** any migration that touches roles, GRANTs, or row-level security policies on `event_log`.
**Run:** `scripts/verify_rls.py`, against the real database, after `alembic upgrade head`.

## Why this exists as a document and a script rather than a test

`tests/` runs on SQLite. SQLite has no roles, no GRANTs and no row-level security, so **nothing in the pytest suite can fail** if the tenant boundary is removed tomorrow. Migrations `b7c2f1a45d90` (RLS), `c3d8e1f60b21` (the least-privilege `atlas_app` role) and `d4a91c72e5f8` (the empty-setting fix) are all invisible to it. That is a structural gap, not a missing test someone forgot to write.

The alternative was a Docker-backed Postgres in CI. That is real infrastructure, and root `CLAUDE.md` is explicit about not adding infrastructure ahead of the phase that needs it — there is no CI pipeline yet for it to live in. A script that runs against the actual database, in under a second, and exits non-zero, gets most of the value now and does not foreclose promoting it into a container-backed test later.

## Why a checklist run by hand is not enough

The first time these checks were performed by hand, **they passed while being wrong**. psycopg's `connection.transaction()` nests as a `SAVEPOINT`, so `set_config('atlas.workspace_id', …, is_local => true)` from an earlier block was still in force during the supposedly *unscoped* read. It returned rows, which looked like a correct answer to a different question. The script opens a fresh connection per check so that mistake cannot recur.

## What it checks

| # | Check | What breaks it |
|---|---|---|
| 1 | The application connects as `atlas_app` | `SUPABASE_DB_URL` pointed back at the owner |
| 2 | That role is not a superuser | role altered |
| 3 | That role does **not** have `rolbypassrls` | the original defect — `BYPASSRLS` outranks `FORCE ROW LEVEL SECURITY`, so the policy is decorative on such a role |
| 4 | A connection that never sets the scope reads **nothing** | policy dropped, or `USING` clause weakened |
| 5–6 | Scoped to A reads only A; scoped to B reads only B | policy predicate wrong |
| 7 | Scope reset to `''` reads nothing | the pooler's `DISCARD ALL` leaves the GUC as `''`, not absent; without `nullif` the policy raises `invalid input syntax for type uuid` instead of denying |
| 8 | Insert into *another* workspace is refused **by the policy** | missing `WITH CHECK` |
| 9–10 | `UPDATE` and `DELETE` are refused **by the grant** | someone ran `GRANT ALL` — append-only (Engineering Philosophy #3) would then rest on convention again |
| 11 | Insert into *its own* workspace is allowed | over-tight grants; a boundary that blocks everything proves nothing |

Checks 8 and 9–10 both surface as SQLSTATE `42501`, and the script distinguishes them by message. They are not interchangeable: one is the policy, the other is the grant, and a check that accepted either would still pass after one of the two mechanisms was removed.

## Confirming the script can actually fail

Point it at the owner and every guarantee should collapse:

```
SUPABASE_DB_URL="$SUPABASE_DB_ADMIN_URL" uv run python scripts/verify_rls.py
```

Expect 9 of 11 to FAIL, including the three isolation reads and all three write refusals. That output is the *original* broken state reproduced on demand — a script that cannot be made to fail is not evidence.

## Result of the last run

2026-08-14, against the live Supabase project, after `c3d8e1f60b21` and `d4a91c72e5f8`: **11/11 pass**; negative control **9/11 fail** as expected.

## Also verify by hand, once per migration touching grants

The script tests `event_log`, `workspace` and `workspace_member` because those are the tables that exist. It cannot know about a table added in the same migration you are writing. So:

- Does every new table have the narrowest GRANT the application actually needs? A new table has **no** grants to `atlas_app` by default, and the failure appears at runtime as `permission denied`, not at migration time.
- If the new table holds Node/Edge state, is it a projection rebuilt from events rather than something the application writes to directly?
- If it is workspace-scoped, does it need its own RLS policy? `event_log` having one does not protect it.
