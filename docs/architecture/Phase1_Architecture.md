# Phase 1 Architecture: Confirmation UI & Second Source

**Status:** Proposal — not settled truth. Per root `CLAUDE.md`, nothing AI-generated is production truth until the user validates it, and the `api/` + frontend module boundary below must pass a `codebase-design` pass before it is scaffolded. This doc is the concrete Phase 1 counterpart to `Phase0_Architecture.md`; read the Roadmap (§Phase 1) and TRD (§4.1, §5.2, §6, §9, §11) for the permanent picture.

**Roadmap weeks:** 5–9. **Primary risk being retired:** *Can a non-engineer (a PM) actually use this?* — not "does more get built." Every scope call below is subordinate to that question.

---

## 1. Goal

Make the extraction loop usable by a non-engineer, end-to-end, and prove it on a second source.

**Exit criterion (Roadmap):** a PM outside the build team can, *unassisted*, connect two sources, review extracted elements, and confirm/reject them in **under 20 minutes**. Everything here is scoped to clear that bar and nothing more — spec export, Q&A, feature-level RBAC, and incremental sync stay deferred to Phases 2–4.

---

## 2. The Three Decisions That Shaped This Doc

Settled with the user at Phase 1 entry (see `docs/decisions/2026-07-28-phase0-exit-phase1-entry.md`):

1. **UI stack: React SPA + FastAPI API.** Matches TRD §11 exactly. A CLI can't satisfy "non-engineer PM, unassisted," and a lighter server-rendered stack would likely be thrown away by Phase 2. This introduces the first two new modules since Phase 0: an `api/` layer over the event log, and a React frontend.
2. **Second source: Jira.** Aligns with the PM persona (PMs live in Jira) and the enterprise-pilot direction; accepts the messier REST/OAuth surface over Linear's cleaner GraphQL. Built behind the same read-only connector pattern as `ingestion/github.py`.
3. **Sequencing: UI-first on existing GitHub data.** Build the confirm/edit/reject event loop + UI against data we *already* extract, retiring the "can a non-engineer use this?" risk first. The Jira connector lands after the confirmation loop is proven, not before.

---

## 3. Sequencing — Four Vertical Slices

Each slice ends with something demonstrable, per the Roadmap's "no phase is infrastructure-only" principle. Slices are ordered so the primary risk is retired first.

| Slice | Delivers | Retires |
|---|---|---|
| **1A — Confirmation loop (backend)** | `node_confirmed` / `node_edited` / `node_rejected` / `node_added` event handlers in projection replay; the monotonic sequence column; `confidence_score` becomes optional; a read/write API over projected state | The two already-logged Phase-1 forward notes (below); makes the loop *writable* |
| **1B — Confirmation UI (frontend)** | React SPA: feature-scope view, unconfirmed vs. confirmed grouping, inline edit, source deep-links, conflict flags, confirm/reject actions | **The primary risk** — "can a non-engineer use this?" Demoable on existing GitHub data alone |
| **1C — Second source (Jira)** | `ingestion/jira.py` read-only connector; extraction runs over Jira tickets; cross-source `conflicts_with` detection (TRD §5.2) | "Does the loop generalize past GitHub?" |
| **1D — Scope, RBAC, audit** | Scoped ingestion by epic/label (TRD §4.2); workspace-level RBAC + RLS; tool-call audit logging (the deferred Phase 0 follow-up folds in here) | "Is it safe for a second team to touch?" |

Slices 1A+1B together are the Phase 1 exit demo on GitHub data; 1C+1D complete the phase.

---

## 4. Data Model & Storage Changes (Slice 1A)

The event log is already the source of truth; Phase 1 makes the *write* side of the confirmation layer real. These are the two forward notes the codebase already flagged, now coming due:

### 4.1 Confirmation events + replay handlers
`storage/projections.py` currently **raises `NotImplementedError`** on `node_confirmed` / `node_edited` / `node_rejected` (deliberately fail-loud, per `docs/decisions/2026-07-22-projections-event-replay.md`). Phase 1 implements those handlers and folds them into `replay()`:
- **confirm** → set `status = confirmed`.
- **edit** → apply the edited content, set `status = edited`, and **retain a link to the version it replaced** (TRD §6) — the edit event payload carries both, so audit/comparison is reconstructable from the log.
- **reject** → set `status = rejected` (kept in the log, filtered out of any future spec assembly).
- **add** → a new `created_by = user` node, `status = confirmed`, **no confidence score** (TRD §6).

> **Amended 2026-08-03** (built — `docs/decisions/2026-08-03-confirmation-loop-backend.md`). Two things this section originally got wrong:
> - There is **no `node_added` event type.** TRD §3.1's `event_type` enum has no such member, and `node_created` with `created_by = user` describes a manual node completely, so adding one would have cost a Postgres enum migration and a divergence from the data model of record in exchange for nothing.
> - The edit payload carries **`previous_content`** — the value the edit replaced — not the system-extracted original. Storing the original on every edit means an edit-of-an-edit records a before-image that was never current at that point; the chain back through `node_created` recovers the original and every link in it is true.

### 4.2 Monotonic sequence column
Once confirm/edit/reject exist, **replay order becomes load-bearing** (an edit after a confirm must win). Add a monotonic sequence to `event_log` (append-time, gap-tolerant) and order replay by it, not by `timestamp` (wall-clock ties/skew are unsafe). This is a migration on the existing table.

### 4.3 `confidence_score` becomes optional
TRD §6: manually-added nodes skip scoring. `Node.confidence_score` moves from required to `float | None`, or a validator that requires it only when `created_by = system`. This is a schema change with a decision doc of its own when built (flagged in the tracker's forward notes).

### 4.4 Feature-scope identity — slice 1A′
> **Added 2026-08-11** by the `codebase-design` gate (`docs/decisions/2026-08-11-api-frontend-module-boundary.md` §3), which surfaced this as a prerequisite to 1B.

`atlas ingest` mints a bare `uuid4()` feature scope and writes only `node_created`/`edge_created`. **`EventType.INGESTION_RUN` exists but is never emitted**, so the log records that nodes exist under some UUID and nothing about what that UUID *is*. The confirmation UI's left rail and page header (`docs/ux/confirmation-flow-spec-v1.md` §1, §3.1) therefore have no data source, and a PM navigating by raw UUID cannot clear the 20-minute exit criterion.

Fixed before 1B is scaffolded, entirely inside the existing module boundary and event-sourced:
- **Emit `ingestion_run`.** The enum member already exists — **no Postgres enum migration, no new event type** (same reasoning that killed `node_added` in §4.1).
- **`IngestionRunPayload`** in `models/schema.py` — `feature_scope_id`, `title`, `source_type`, `external_id`, `url` — so it passes the same gate everything else does.
- **`Projection` gains `feature_scopes`**: remove `INGESTION_RUN` from `_NO_OP_EVENTS` and add a handler. A feature scope is a projection, not a registry or a new table.
- `record_extraction` writes it; `atlas ingest` takes the title from the PR it already fetched.

Test-first (`tdd` skill — projection replay and schema validation are both in its mandatory set). Leave room in the payload for slice 1D's deferred tool-call manifest (`docs/decisions/2026-07-28-extraction-tool-call-audit-logging.md`); an optional field added later replays cleanly over events written today.

> **Built 2026-08-11** — `docs/decisions/2026-08-11-feature-scope-identity.md`. Shipped as described, with three things this section did not say: `Projection.feature_scopes` holds a `FeatureScope` whose `runs` **accumulate** (a feature is assembled from many sources — §6's Jira connector appends rather than replaces), its **title is last-write-wins** like the rest of the projection (with a flagged 1C question: a second *source* should probably not rename a scope), and `external_id` **fully qualifies** the artifact (`owner/repo#111`, not `111`) because a feature scope is workspace-global. `extract_from_pull_request` now returns `(IngestionRunPayload, ExtractionResult)`, and `atlas review` prints the scope title + its sources.

---

## 5. New Module Boundary (Slices 1A/1B) — *settled 2026-08-11*

Phase 0's four modules (`ingestion/`, `extraction/`, `storage/`, `cli/`) stay. Phase 1 adds:

5. **`api/`** — FastAPI. A thin read/write HTTP layer over the existing `storage/` projections and event log. `GET` endpoints replay projected Node/Edge state for a feature scope (reusing `load_projection`); action endpoints (`POST` confirm/edit/reject/add) validate through the **same Pydantic gate** and call `append_event` — the API never mutates Node/Edge state directly, exactly like the CLI. It reuses, not reimplements, `storage/` and `ingestion/`.
6. **Frontend (React SPA)** — the confirmation UI. Talks only to `api/`. Design-system baseline + page/flow specs live in `docs/ux/` (empty until now); built with the dormant `brandkit` + `design-taste-frontend-v1` skills and reviewed by the `frontend-reviewer` agent.

**The CLI (`atlas review`) is not thrown away** — it stays as the engineer-facing/debug read path and as the thing that already proves the projection→render flow. The API is a second consumer of the same projections, not a replacement.

> **Gate passed 2026-08-11** — `docs/decisions/2026-08-11-api-frontend-module-boundary.md`. The decomposition above is approved as written, with four things this section did not say:
>
> - **`api/` owns HTTP, auth, and serialization — and no domain logic.** Every write endpoint is *authenticate → load projection → call exactly one `storage/confirmations.py` function → return*. Logic that isn't already in `storage/` belongs *in* `storage/`, not in a route handler. Flat layout — `app.py` / `deps.py` / `routes.py`, no `routers/` package, **no `api/schemas.py`** (the domain models are already Pydantic v2; a second wire-level model layer could drift from the validation gate).
> - **A prerequisite came out of the pass: feature scopes have no identity** — no `ingestion_run` event is ever emitted, so nothing records that a scope *is* "ripgrep #111." The UX spec's left rail and page header have no data source. Fixed **before** scaffolding, as **slice 1A′** (see §4.4 below).
> - **The auth seam is fixed independently of the auth implementation** (`deps.py::get_principal()` → frozen `Principal(workspace_id, actor)`; no route ever reads either from a request). So **§10 Q2 never blocked scaffolding — it blocks shipping.** Resolved below.
> - **No ingest endpoint in slice 1B**, which is what keeps the API synchronous and free of any task-queue pressure. Ingestion stays CLI-triggered; connect-sources is 1C/1D surface (`docs/ux/confirmation-flow-spec-v1.md` §8).
>
> Frontend: `frontend/` at the **repo root** (not under `src/atlas/` — it is not a Python package and would break hatchling packaging), Vite + React + TypeScript, TS types generated from FastAPI's OpenAPI schema, no component library, no state-management library until undo/optimistic updates actually demand one.

> **Built 2026-08-11** — `docs/decisions/2026-08-11-confirmation-ui-slice-1b.md`. Shipped to the shape above. Additions this section did not specify: **`ApiSettings`** is not a superset of `Settings` (the API holds no GitHub token — least privilege for our own processes); **`NonBlankStr`** in `models/schema.py` replaced four copies of the same blank-check and is reused by the API's request bodies, so a whitespace claim is a 422 at the wire rather than a 500 from the gate behind it; the one read envelope (`FeatureScopeDetail`) lives in `routes.py` and embeds the domain models rather than mirroring them. **A spec gap was found:** `confirmation-flow-spec-v1.md` §5's `u` = undo cannot fully hold — there is no `node_unconfirmed` event by design, so a node can never return to `unconfirmed`; the UI does what the log can express and says so. **Not yet done:** a real-browser pass (`frontend-reviewer`) and the actual 20-minute exit-criterion measurement with a PM.

---

## 6. Second Source — Jira (Slice 1C)

- **`ingestion/jira.py`**, same shape as `ingestion/github.py`: a read-only connector that owns *all* Jira HTTP + JSON parsing, returns transient frozen-dataclass DTOs carrying the provenance handles a `SourceRef` needs (issue key, URL, literal text), and exposes read-only fetches (issue by key, comments, linked issues, epic/label-scoped search). Read-only + least-privilege (TRD §9, Philosophy §6) — the connecting credential only ever sees what it already could in Jira.
- **Extraction is source-agnostic already** — `build_result` and the agent tools work on any corpus; Jira mainly needs its own connector + `SourceType.jira` provenance and its own tool wrappers.
- **Cross-source conflict detection (TRD §5.2):** when GitHub and Jira produce same-type nodes for the same feature scope with materially different content, emit a `conflicts_with` edge and surface both — never auto-resolve. (Phase 0 already proved the agent *can* model a self-contradicting single source via `conflicts_with` on PR #706; Phase 1 extends that across sources.)
- **Scoped ingestion (TRD §4.2):** pull by epic/label, not a full-workspace crawl. `last_synced_at` / incremental sync stays deferred to Phase 4 — Phase 1 scopes but still re-pulls.

> **Built 2026-08-11** — `docs/decisions/2026-08-11-jira-second-source-slice-1c.md`. **§10 Q4 resolved: email + API token, not OAuth 3LO** (the token carries exactly its owner's permissions — least privilege with no scope negotiation). Four things this section did not say: **ADF flattening** is a provenance problem (Jira returns rich text as a JSON tree; the excerpt must stay literal, so unknown node types are descended into rather than skipped); the **GitHub system prompt is frozen by a golden test**, so adding a source cannot silently re-word the prompt the Phase 0 eval evidence was gathered against; **cross-source `conflicts_with` required extending the gate** — a run is handed the claims other sources already produced and may point an edge at one of their ids, but *only* at an id it was actually offered, so a fabricated relationship fails the gate; and a feature scope now **keeps the title of the run that opened it** (the deliberate exception to last-write-wins, resolving the question slice 1A′ deferred here). **Not done: the Jira extraction path has no eval evidence and has never run against a real Jira site.**

---

## 7. Access Control, RBAC & Audit (Slice 1D)

- **Workspace-level RBAC (TRD §9).** Phase 0's `DEFAULT_WORKSPACE_ID` nil sentinel was designed to "disappear cleanly" when real workspaces arrive (`docs/decisions/2026-07-21-phase0-default-workspace-id.md`) — that time is now. RLS enters here: the `supabase-postgres-best-practices` skill's `security-*` rules become binding, and the `security-review` workflow's RLS cross-check goes live.
- **Audit logging.** Every Event is already an audit record (actor, timestamp, action) — TRD §9 says no separate audit system is needed. The one gap is the deferred **tool-call audit logging** (`docs/decisions/2026-07-28-extraction-tool-call-audit-logging.md`): record the per-run tool-call manifest in the `ingestion_run` event. This folds into slice 1D rather than being a standalone task, and should be done before the extraction module is extended for Jira if practical.

> **Built 2026-08-11** — `docs/decisions/2026-08-11-scope-rbac-audit-slice-1d.md`. The `DEFAULT_WORKSPACE_ID` sentinel **became a real workspace row keeping its own id**, so no append-only event had to be rewritten (better than the "reassign every nil-workspace event" the 2026-07-21 decision anticipated). Membership is read from the database per request, never from the cookie; `workspace_member.actor` is the same string every Event's `actor` carries, so authorization and audit key on one identity. Roles are `admin`/`editor`/`viewer`, and the split that matters is viewer vs. the rest. Tool-call audit logging is **closed**: the permission gate records every decision including **denials**, and the manifest lands on the `ingestion_run` event as an optional field, replaying cleanly over older events. **RLS is written but not verified** — the policies are DDL in migration `b7c2f1a45d90`, the test suite runs on SQLite (which has neither `set_config` nor RLS), and **the migration has not been applied to Supabase**. Until it is, workspace isolation rests on the application-level filter alone.
- **Least privilege / permissions mirror source (TRD §9):** a user must not see ingested content they couldn't already access at the source.

---

## 8. How This Maps to TRD Principles & the Engineering Philosophy

- **Read-only by default (Philosophy §1):** the Jira connector is GET-only like GitHub's; the API writes only to the event log via `append_event`, never to source systems.
- **Extraction is a draft, never a fact (§2):** the confirmation UI is the literal embodiment of this — `unconfirmed` is the default, and only a human confirm/edit/reject changes status. Nothing reaches an export (Phase 2) unconfirmed.
- **Event-sourced (§3):** every confirm/edit/reject/add is an Event; Node/Edge state stays a projection. No direct mutation — the API obeys the same rule the CLI does.
- **Provenance non-negotiable (§4):** system nodes keep their `SourceRef`; the UI surfaces the literal excerpt + deep-link. Manual `created_by=user` nodes are the one node type without *extraction* provenance — their evidence is the person, recorded as a `human_assertion` `SourceRef` naming the actor and quoting the claim as typed (`docs/decisions/2026-08-03-manual-node-provenance.md`). So the rule holds with **no exception clause**: every Node still carries a `SourceRef`, and the UI can still show where every claim came from — for these, a named human rather than a URL.

  > **Amended 2026-08-03.** This section originally read "the one node type without provenance — their provenance is the human actor + Event, which the log records." That was a relaxation of CLAUDE.md's zero-exception rule, and it would have made "a Node with no `SourceRef`" expressible, forcing every downstream consumer to handle the empty case forever. The `human_assertion` source type keeps the invariant literally true instead.
- **Idempotent/incremental (§5):** binding from Phase 1's scoped ingestion onward; re-running ingestion must not duplicate. (Full incremental delta-sync still Phase 4.)

---

## 9. Explicit Phase 1 Simplifications (don't build ahead)

- **No spec assembly/export** (Phase 2) — the UI confirms elements; it does not yet generate or export a spec.
- **No Q&A / retrieval / pgvector usage** (Phase 3).
- **No feature-level RBAC, no incremental delta-sync, no third (doc) source** (Phase 2/4).
- **No third-party auth/SSO** beyond what connecting a source and workspace-level RBAC require (SSO/SAML is Phase 4).
- **No MCP-based connector rearchitecture** — direct API integration for Jira, revisit MCP only past 3–4 sources (TRD §11).

---

## 10. Open Questions Carried Into Phase 1

1. ~~**`api/` + frontend module boundary**~~ — **RESOLVED 2026-08-11** (`docs/decisions/2026-08-11-api-frontend-module-boundary.md`). `api/` earns its own module as a *transport boundary*, not an abstraction layer, held thin by the rule in §5's amendment. Frontend lives at `frontend/`, repo root.
2. ~~**Auth for the app itself**~~ — **RESOLVED 2026-08-11** (same doc, §4). Seam and implementation were separated: the seam is `deps.py::get_principal()` → frozen `Principal(workspace_id, actor)`, fixed now and surviving Phase 4's RBAC; the Phase 1 implementation is a signed session cookie behind a shared passphrase, where the PM's typed name becomes `actor` on every event and `workspace_id` is `DEFAULT_WORKSPACE_ID` until slice 1D. Rejected: a `users` table (user identity ahead of 1D's RBAC, for one user) and third-party auth (hosted dependency in the exit-criterion demo; SSO is Phase 4).
3. ~~**Confirmation UX**~~ — **RESOLVED 2026-08-11**: speced in `docs/ux/design-system-baseline-v1.md` + `docs/ux/confirmation-flow-spec-v1.md` (direction settled in `docs/decisions/2026-08-11-confirmation-ui-design-direction.md`).
4. **Jira OAuth vs API token** for the alpha (TRD §4.1 allows either) — decide at slice 1C against the design partner's setup.
