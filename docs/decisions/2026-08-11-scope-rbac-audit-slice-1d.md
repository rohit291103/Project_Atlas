# Decision Log — Scoped Ingestion, Workspace RBAC & Tool-Call Audit (Slice 1D)

**Date:** 2026-08-11
**Area:** storage, api, extraction, cli
**Implements:** `Phase1_Architecture.md` §7. **Closes** `docs/decisions/2026-07-28-extraction-tool-call-audit-logging.md`. **Supersedes the revisit trigger in** `docs/decisions/2026-07-21-phase0-default-workspace-id.md`.

## 1. Scoped ingestion (TRD §4.2)

`atlas ingest-jira` takes exactly one of `--issue`, `--epic` or `--label`, plus a `--limit` that is a hard ceiling. A scope is pulled *deliberately*, never by crawling a site, and a mistyped label cannot start an unbounded run. GitHub needs no equivalent — `atlas ingest` is already per-PR.

## 2. Workspace RBAC — the sentinel becomes a real row rather than a rewritten log

`workspace` and `workspace_member` tables; three roles (`admin`, `editor`, `viewer`).

The `DEFAULT_WORKSPACE_ID` decision planned to "reassign every nil-workspace event to the real workspace" at this point. **We seeded the workspace row with the nil UUID as its id instead.** Every event ever written already carries that id, so they all become rows of a provisioned workspace with no data rewritten — and rewriting history to tidy an identifier would be a bad trade for a log that is the system's source of truth. The sentinel stops being a sentinel by becoming real, not by being erased.

**Three decisions inside this:**

- **Membership is read from the database on every request, never from the cookie.** The cookie carries the actor's name only. So removing someone takes effect on their next request rather than whenever their session happens to expire — and the tenant boundary stays a server-side fact, which is the same rule §4 of the boundary decision set for `workspace_id`.
- **`workspace_member.actor` is the same string that lands on every Event's `actor`.** Membership and the audit trail key on one identity, or else "who confirmed this" and "who may confirm" become questions about two different people. Phase 4's SSO replaces the string with a user id; the column is the seam that makes that a migration rather than a redesign.
- **The role split that matters is viewer vs. the rest.** A viewer reads the draft but cannot rule on it. "Extraction is a draft until a human acts on it" means very little if every reader can act. `admin` differs from `editor` only in managing the workspace itself — nothing in Phase 1 uses that difference yet, and it is not pretended otherwise.

401 vs. 403 is kept honest: no valid session is 401 ("prove who you are"); a valid session with no membership is 403 ("we know who you are, and that is not enough"). Sign-in checks membership too, so a non-member fails at the door rather than getting a session that 403s on everything.

## 3. Row-level security — and what is *not* verified

Migration `b7c2f1a45d90` enables RLS on `event_log` with a policy reading `current_setting('atlas.workspace_id')`, which `storage/rbac.py::scope_to_workspace` sets per transaction (`SET LOCAL`-style, so it cannot leak to the next request borrowing that pooled connection). `FORCE ROW LEVEL SECURITY` is set, because without it the policy is decorative for the table owner — which is the role the application connects as on hosted Postgres.

Application code already filters by `workspace_id`; the policy is the **second lock**, so a query that forgets the filter returns nothing instead of another tenant's rows.

**Honest limits, stated plainly:**

- **The policies are not exercised by the test suite.** The suite runs on SQLite, which has neither `set_config` nor RLS. What is tested is the seam — `scope_to_workspace` issues the statement on Postgres and stays silent elsewhere. The policy itself is DDL that has been *written* and not *run*.
- **The migration has not been applied.** It needs `alembic upgrade head` against the real Supabase database, which is the user's call, not something to do unasked. Until then RLS is inert and workspace isolation rests on the application-level filter alone (which is where it already rested, so this is not a regression — but it is not yet the improvement it will be).
- `workspace` and `workspace_member` are deliberately **not** under RLS: they are what resolve a request to a workspace in the first place, so gating them behind a setting that isn't known yet is circular.

## 4. Tool-call audit logging — the Phase 0 follow-up, closed

`Phase0_Architecture.md` §2 listed "every tool call is logged" as a guardrail next to the call cap, and it was the one guardrail that existed only on paper. The permission gate now appends a `ToolCallRecord` for every decision it makes, and the manifest lands on the run's `ingestion_run` event — in the event log, replayable, exactly the shape the deferral doc argued for.

- **Denied calls are recorded too**, and they are the valuable half: they are the record of the boundary actually holding, which is what an auditor would want to see.
- **`emit_extraction` is excluded.** It is the run's own result, not a read of a source system, so it belongs in neither the budget nor a record of what was accessed.
- **The payload built after the run, not before**, so the event records what the agent actually did rather than what it was about to be permitted to do.
- `IngestionRunPayload.tool_calls` is optional with an empty default — the forward-compatibility slice 1A′ deliberately left room for. Events written before this slice replay unchanged, and nothing backfills tool calls that were never made.

Arguments are recorded as the agent supplied them (an issue number, a search string). Credentials live in the connector and never pass through a tool call, so there is nothing to redact — the redaction review the deferral doc asked for concluded there.

## Consequences

- Phase 1's four slices are built. **What remains is not construction**: the exit criterion is a measurement — a PM outside the build team, unassisted, under 20 minutes — and it has not been taken.
- `atlas ingest`/`ingest-jira` still stamp `DEFAULT_WORKSPACE_ID`: the CLI is the engineer path and Phase 1 has one workspace. A `--workspace` option is the obvious follow-on when a second workspace exists.
- New env: `JIRA_BASE_URL`, `JIRA_EMAIL`, `JIRA_API_TOKEN`.
