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

---

## 5. New Module Boundary (Slices 1A/1B) — *pending `codebase-design`*

Phase 0's four modules (`ingestion/`, `extraction/`, `storage/`, `cli/`) stay. Phase 1 adds:

5. **`api/`** — FastAPI. A thin read/write HTTP layer over the existing `storage/` projections and event log. `GET` endpoints replay projected Node/Edge state for a feature scope (reusing `load_projection`); action endpoints (`POST` confirm/edit/reject/add) validate through the **same Pydantic gate** and call `append_event` — the API never mutates Node/Edge state directly, exactly like the CLI. It reuses, not reimplements, `storage/` and `ingestion/`.
6. **Frontend (React SPA)** — the confirmation UI. Talks only to `api/`. Design-system baseline + page/flow specs live in `docs/ux/` (empty until now); built with the dormant `brandkit` + `design-taste-frontend-v1` skills and reviewed by the `frontend-reviewer` agent.

**The CLI (`atlas review`) is not thrown away** — it stays as the engineer-facing/debug read path and as the thing that already proves the projection→render flow. The API is a second consumer of the same projections, not a replacement.

> **Gate:** this decomposition (a new `api/` module + a frontend) is a new abstraction, so per `CLAUDE.md`'s Module Boundary rule it must go through the `codebase-design` skill before scaffolding. Treat §5 as the proposal that skill pressure-tests, not a settled boundary.

---

## 6. Second Source — Jira (Slice 1C)

- **`ingestion/jira.py`**, same shape as `ingestion/github.py`: a read-only connector that owns *all* Jira HTTP + JSON parsing, returns transient frozen-dataclass DTOs carrying the provenance handles a `SourceRef` needs (issue key, URL, literal text), and exposes read-only fetches (issue by key, comments, linked issues, epic/label-scoped search). Read-only + least-privilege (TRD §9, Philosophy §6) — the connecting credential only ever sees what it already could in Jira.
- **Extraction is source-agnostic already** — `build_result` and the agent tools work on any corpus; Jira mainly needs its own connector + `SourceType.jira` provenance and its own tool wrappers.
- **Cross-source conflict detection (TRD §5.2):** when GitHub and Jira produce same-type nodes for the same feature scope with materially different content, emit a `conflicts_with` edge and surface both — never auto-resolve. (Phase 0 already proved the agent *can* model a self-contradicting single source via `conflicts_with` on PR #706; Phase 1 extends that across sources.)
- **Scoped ingestion (TRD §4.2):** pull by epic/label, not a full-workspace crawl. `last_synced_at` / incremental sync stays deferred to Phase 4 — Phase 1 scopes but still re-pulls.

---

## 7. Access Control, RBAC & Audit (Slice 1D)

- **Workspace-level RBAC (TRD §9).** Phase 0's `DEFAULT_WORKSPACE_ID` nil sentinel was designed to "disappear cleanly" when real workspaces arrive (`docs/decisions/2026-07-21-phase0-default-workspace-id.md`) — that time is now. RLS enters here: the `supabase-postgres-best-practices` skill's `security-*` rules become binding, and the `security-review` workflow's RLS cross-check goes live.
- **Audit logging.** Every Event is already an audit record (actor, timestamp, action) — TRD §9 says no separate audit system is needed. The one gap is the deferred **tool-call audit logging** (`docs/decisions/2026-07-28-extraction-tool-call-audit-logging.md`): record the per-run tool-call manifest in the `ingestion_run` event. This folds into slice 1D rather than being a standalone task, and should be done before the extraction module is extended for Jira if practical.
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

1. **`api/` + frontend module boundary** — must pass `codebase-design` before scaffolding (§5). Chiefly: does the API deserve its own module or live under an existing one, and how thin can it stay.
2. **Auth for the app itself** — the exit criterion says a PM connects sources "unassisted." How does that PM authenticate *into the product* (as opposed to OAuth-ing a source)? Minimal viable answer needed before slice 1B ships; full SSO stays Phase 4.
3. **Confirmation UX** — the actual page/flow design (`docs/ux/`) is unwritten. Needs a `feature-discussion` / design pass before slice 1B; the 20-minute exit criterion is a UX bar, not just a functional one.
4. **Jira OAuth vs API token** for the alpha (TRD §4.1 allows either) — decide at slice 1C against the design partner's setup.
