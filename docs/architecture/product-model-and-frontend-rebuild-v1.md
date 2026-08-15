# Products, connections, and the frontend rebuild (v1)

**Status:** proposed — this document *is* the `codebase-design` + `domain-modeling` gate CLAUDE.md requires before any of it is scaffolded. Nothing here is built.
**Date:** 2026-08-14
**Supersedes in part:** `docs/decisions/2026-08-11-api-frontend-module-boundary.md` §5 (no ingest endpoint) and the security rule "no secret ever lands in the database". Both reversals are deliberate, argued in §5 and §6, and each needs its own decision-log entry when built.

---

## 1. Why this exists

Two things forced it.

**A PM works on several products at once.** Each has its own GitHub org and its own Jira site — different accounts, different credentials, no overlap. The v1 IA (one flat list of feature scopes in one workspace) has no place to put that, and the "derive a project from `external_id`" idea from the redesign proposal is wrong: you cannot derive a container from data that only exists *after* you have ingested into it. A product has to exist before the first connection does.

**The confirmation UI is too dense to navigate and ingestion is CLI-only.** Diagnosed in the redesign proposal; the load-bearing defect is `NodeCard.tsx:195`, which renders provenance for every *unreviewed* node, so the landing state is the densest state the app can produce. Ingestion being CLI-only means the product tells its target user to open a terminal.

The Phase 1 exit criterion is unchanged and is the only thing this work serves: *a PM outside the build team can, unassisted, connect two sources, review extracted elements, and confirm/reject them in under 20 minutes.*

---

## 2. Vocabulary

Settled here so the code, the API and the UI use one set of words. UI names differ from schema names on purpose — the schema's vocabulary is not a PM's.

| Term | What it is | Where it lives | UI name |
|---|---|---|---|
| **Workspace** | The tenant. The RLS boundary, the membership boundary, the audit boundary. | `workspace` table (1D) | not shown in Phase 1 |
| **Product** | A thing the PM ships. Owns connections and features. **New.** | projection from `product_created` | "Product" |
| **Connection** | One credential bound to one source for one product, with its scope. **New.** | `connection` table | "Source" |
| **Feature scope** | One feature assembled from one or more runs. | projection from `ingestion_run` | "Feature" |
| **Node** | One extracted claim with provenance. | projection | "Claim" |
| **Ingestion run** | One deliberate pull from one connection. | projection | "Run" |

**Workspace is not a product.** Overloading it would break the meaning that the RLS policy, `workspace_member` and the audit trail are all built on — the boundary `scripts/verify_rls.py` verified 11/11 on 2026-08-14. A product is a grouping *inside* a tenant. RLS is unchanged by anything in this document.

---

## 3. What does not change

Stated up front because most of this document is additive and it should be obvious what is not in play:

- **Read-only into every source, in every phase.** Connections are read credentials. Nothing here adds a write path to GitHub or Jira.
- **The validation gate.** Extraction output still reaches storage only through `Node.model_validate`. An ingest endpoint does not get a shortcut the CLI does not have.
- **Event-sourcing for domain truth.** No Node/Edge mutation; products are a projection, not a table.
- **Provenance.** Every node still carries a literal excerpt + URL.
- **RLS and the tenant boundary.** `event_log` policy, grants, and the `atlas_app` role are untouched. The one new table inherits the same treatment (§6).

---

## 4. Data model

### 4.1 Product — a projection, not a table

`product_created { id, name }` and `product_renamed { id, name }` as new event types; `Projection.products` alongside `Projection.feature_scopes`, replayed the same way. No migration, no table, no new module — this is the pattern slice 1A′ already established for feature-scope identity.

**Binding features to products.** `IngestionRunPayload` gains `product_id` as an *optional* field, which replays cleanly over existing events exactly as 1D's tool-call manifest does. The four scopes already in the live log predate it, so they get one `feature_scope_assigned { feature_scope_id, product_id }` event each rather than a rewritten history — the log is append-only and that is not negotiable for a convenience.

A scope with no product projects into an "Unassigned" bucket rather than crashing or disappearing. Same fail-visible principle as the pre-1A′ unnamed scope.

### 4.2 Connection — a table, deliberately not an event

Credentials are the one thing in this system that **must** be deletable. Rotation and revocation are requirements, not edge cases, and an append-only log cannot express either: a revoked token's ciphertext would live forever in `event_log`. So connections are ordinary mutable rows.

This is not a new exception to event-sourcing. Slice 1D already established the precedent — `workspace` and `workspace_member` are plain tables in `storage/rbac.py`, because membership is operational state, not domain truth. A connection is the same kind of thing. The event log still records *that* a connection was created or revoked, for audit; it never records the secret.

```
connection
  id, workspace_id, product_id
  source_type          github | jira
  account              display only: "acme-bot", "you@acme.com"
  host                 "github.com", "acme.atlassian.net"
  scope                "acme/web", "PROJ"
  secret_ciphertext    bytea  — never returned by any endpoint, never logged
  created_at, created_by, last_used_at
```

No `secret` field exists on any Pydantic response model, so it cannot leak by forgetting to exclude it — the same reasoning that made `NonBlankStr` one definition instead of four.

---

## 5. Module boundary (the `codebase-design` verdict)

Checked against the skill's four-module boundary and its "does this hide real complexity" test. Result is deliberately small, and what was **not** built matters as much as what was:

**Rejected — `storage/products.py`.** A product projection is a handful of lines next to the feature-scope projection it mirrors. It goes in `storage/projections.py`. A file per entity would be a shallow module.

**Rejected — a `crypto/` module or a `SecretStore` abstraction.** Two functions (`seal`, `unseal`) with one caller. They live in `storage/connections.py` until something else needs them.

**Rejected — a generic connector-credential interface.** `GitHubClient(token)` and `JiraClient(email, token)` already take credentials as arguments; `ingestion/` is credential-agnostic today. The env coupling is entirely in `Settings.from_env()` at the composition root. Nothing in `ingestion/` changes.

**Added — `storage/connections.py`.** The table, its CRUD, and encryption at the boundary. Real complexity, one clear interface.

**Added, and this one is a genuine fifth thing — `src/atlas/pipeline.py`.** Today `cli.py` holds the orchestration: parse target → build client → `extract_from_*` → open a workspace session → `record_extraction`. The API now needs the identical sequence. Two concrete callers exist *today*, which is the skill's own bar for extracting an abstraction — and duplicating it would let the two drift, which for a system whose one non-negotiable is "extraction never reaches storage unvalidated" is a correctness risk, not a style preference. `cli.py` and `api/routes.py` both become thin callers of it.

It does not fit `ingestion/` (read-only connectors), `extraction/` (the agent), or `storage/` (persistence) because it spans all three. Naming it explicitly rather than hiding it inside one of them is the honest option.

**`api/` keeps its thinness rule** — authenticate → load → call one function → return — with the ingest endpoint calling `pipeline.start_run` as its one function.

---

## 6. Credentials: the security change, stated plainly

CLAUDE.md's security-review rule reads "no secret ever lands in the database (env/secrets manager only)." That rule holds when there is one GitHub token and one Jira token in `.env`. It cannot hold when a PM connects five products' worth of separate orgs and sites through a browser. **This is a real amendment to a stated non-negotiable and gets its own decision-log entry and a `security-review` pass before it ships.**

The posture that replaces it:

- **Encrypted at rest, key outside the database.** Authenticated symmetric encryption (`cryptography`'s Fernet — already-vetted, no new primitives hand-rolled), key from `ATLAS_SECRET_KEY` in env/secrets manager. Database compromise alone yields ciphertext.
- **Write-only through the API.** No endpoint returns a secret, in any form, ever. The UI shows `account`, `host`, `scope` and a last-4 fingerprint.
- **Never logged.** Same discipline as the `ALTER ROLE` redaction fix — a driver exception must not carry it, and no exception path formats it.
- **Still least privilege.** The credential carries exactly its owner's permissions; the connect flow *shows the PM what it can see* before saving, which is the trust moment the flow spec §8 asked for.
- **Revocation is a delete.** One row, immediate, no cache.
- **The new table gets RLS and grants from day one.** `SELECT/INSERT/UPDATE/DELETE` for `atlas_app` on `connection` only (unlike `event_log`, this one *is* mutable), plus a `workspace_id` policy. `migrations/script.py.mako`'s header exists precisely to stop this being forgotten, and `scripts/verify_rls.py` gains checks for it — including that a connection in workspace A is invisible from workspace B.

---

## 7. Ingestion from the UI, without a task queue

The 2026-08-11 boundary decision refused an ingest endpoint on the grounds that a long-running request creates pressure for a task queue, an explicit CLAUDE.md non-goal. That reasoning was correct and is not being waved away — it is being solved.

```
POST /products/{id}/runs        → 202 { run_id }      returns immediately
GET  /runs/{run_id}             → { status, steps }   client polls
```

The work runs in-process via FastAPI's `BackgroundTasks`. **No queue, no broker, no worker, no new deployable, no new dependency.**

**Run status is a projection, not a status column.** Two new event types — `ingestion_run_started` and `ingestion_run_failed` — bracket the existing `ingestion_run`, which is still emitted first-and-mandatorily on success. A run's state is derived by replay, like everything else: started with no terminal event = running; `ingestion_run` = succeeded; `ingestion_run_failed` = failed.

**The honest cost.** An in-process run dies with the process, leaving a start event with no terminal event — indistinguishable from a slow run. Mitigation: the projection reports a run older than a threshold with no terminal event as **interrupted**, not "running". Fail-visible, no infrastructure, and the same instinct as making an unscoped query return zero rows rather than an error.

**When this stops being enough:** more than one API worker process, or runs that need to survive a deploy. Neither is true in Phase 1. When either becomes true, that is the phase that needs a queue.

---

## 8. Frontend

### 8.1 Routes — the fix for "hard to navigate"

The current SPA has no URL: `selected` is component state in `App.tsx:21`, so there is no back button, refresh drops you on whichever feature loaded first, and no view can be linked to anyone. Real routes fix navigation, deep-linking, and browser history in one change.

```
/signin
/                          → product list (or straight through if only one)
/p/:product                → product home: what needs you
/p/:product/sources        → connections + runs
/p/:product/f/:feature     → review (the core screen)
/p/:product/conflicts      → conflicts across the product
```

`react-router-dom` — one dependency, boring, standard. (A hand-rolled History API hook would avoid the dep at ~50 lines; not worth owning.) This does not reopen "no component library, no state library" — both still hold.

### 8.2 The review screen

Four zones — **projects → queue → one claim → its source** — as demonstrated in the interactive proposal. The substantive changes:

- **Provenance leaves the card** into its own always-visible column. Density falls and trust rises together; the excerpt stops being the buried element.
- **Nine `NodeType` sections become four groups** — Why / What / How / Unresolved — with the precise type kept as a tag. The storage taxonomy stops being the navigation.
- **Confirm auto-advances** to the next unreviewed claim. Speced in flow spec §5, never built; it is what makes 20 minutes plausible.
- **Conflicts become objects**, both sides and both excerpts together, instead of one banner drawn on each of two endpoints.

### 8.3 Theme

`--accent` and `--status-edited` are currently the same hex (`styles.css:24,28`), so the focus ring, primary button and "edited" badge are one signal doing three jobs. Split them. Light mode becomes an explicit toggle rather than only a `prefers-color-scheme` remap — the target user lives in Jira and Confluence, not a dark IDE. Source excerpts get the one warm surface in the product, so quoted material differs from Atlas's own prose in temperature, not only typeface.

---

## 9. Slices

Ordered so the risk-retiring screen is reviewable before the credential work lands.

### Slice 2A — login to review, on seeded data
Product projection + `product_created` / `feature_scope_assigned` events · `IngestionRunPayload.product_id` · `GET /products`, `GET /products/{id}/feature-scopes` · router + all routes · sign-in → product picker → product home → feature → review → conflicts · four-zone review, four groups, auto-advance, provenance column · theme token split + light toggle · the four existing live scopes assigned to a seeded product.

**Exit:** a PM can sign in, pick a product, review a feature end-to-end and see its conflicts, with every view deep-linkable. **No credential work, no new table, no ingest endpoint.** This alone is enough for a usability review of the loop.

### Slice 2B — sources and ingestion from the UI
`connection` table + migration + grants + RLS · encryption at the boundary · `pipeline.py` extracted, `cli.py` becomes a caller · connect flow showing what the credential can see · `POST /products/{id}/runs` + `GET /runs/{id}` · run status projection with the interrupted rule · Sources screen with run history · `verify_rls.py` extended.

**Exit:** a PM connects a GitHub repo and a Jira project to a product themselves and watches a run finish. This is the literal reading of "connect two sources" in the exit criterion.

### Slice 2C — only if wanted
Cross-product home, member management, ⌘K palette.

---

## 10. Tests

Per the `tdd` skill, test-first is mandatory for: the product projection and replay, the `feature_scope_assigned` handler, `IngestionRunPayload.product_id` replaying over events that lack it, run-status derivation **including the interrupted case**, and the encryption round-trip.

Two that are worth naming because they encode the rules rather than the behaviour:

- **A test that fails if any API response model can serialize a secret** — the structural version of the rule, in the spirit of `source_refs` having `min_length=1`.
- **A test that fails if `cli.py` regains its own orchestration** rather than calling `pipeline` — the same shape as the existing test that fails if a bare `session_scope` returns to `cli.py`.

`verify_rls.py` gains connection-table checks; SQLite still cannot see any of it, which is why that script exists.

---

## 11. Open, and deliberately not decided here

1. **Which product a cross-source feature belongs to** when a GitHub PR and a Jira epic are ingested into one scope from two connections. Proposed: the product owns the feature, and both connections belong to that product, so the question dissolves. Confirm when 2B is built.
2. **Whether the PM creates products or an admin does.** Assumed: any editor can, in Phase 1.
3. **Key rotation for `ATLAS_SECRET_KEY`.** Re-encrypting every connection is straightforward but unbuilt; flagged so it is not discovered during an incident.
4. **The extraction quality issue is untouched by all of this** — goal/requirement duplication (2026-08-14 review) still ships duplicate claims into whatever UI reviews them, and a better UI makes it more visible, not less.
