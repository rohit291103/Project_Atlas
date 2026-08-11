# Decision Log — `api/` + Frontend Module Boundary (`codebase-design` gate, Phase 1 Slice 1B)

**Date:** 2026-08-11
**Area:** architecture, api, frontend, storage
**Gate:** This is the `codebase-design` pass root `CLAUDE.md` requires before the `api/` module or the frontend is scaffolded, and that `Phase1_Architecture.md` §5 explicitly defers to. It **resolves §10 Q1 and §10 Q2**. No code was written in this pass.

## Context

Phase 1 slice 1B is the slice that retires the phase's primary risk — *can a non-engineer actually use this?* It adds the first two modules since Phase 0: a FastAPI `api/` layer and a React SPA. `Phase1_Architecture.md` §5 proposed that decomposition but marked it a proposal pending this gate; the two `docs/ux/` v1 specs (`design-system-baseline-v1.md`, `confirmation-flow-spec-v1.md`) are inputs to it.

The skill's question is narrow and worth stating plainly: **does the API deserve its own module, and how thin can it stay** — with the standing warning that most new abstractions in a project this young are premature.

## Decisions

### 1. `api/` is justified as a fifth module — it is a delivery surface, not an abstraction

Run against the skill's deep-module checklist:

- **Does it hide real complexity?** Yes, and specifically security complexity. The CLI is local and single-user, so `workspace_id` and `actor` are trivially trustworthy. Over HTTP they are attacker-controlled unless something translates a session into them. That translation is real work with a real failure mode, not a renamed function call.
- **Could it be a plain function in an existing module?** No. `cli/` is a Typer entrypoint carrying Rich/console dependencies and a synchronous local lifecycle; the API is an ASGI app with a different dependency set, lifecycle, and consumer. Folding one into the other couples two unrelated deployment shapes.
- **Is there a second concrete caller?** Only the frontend. This is the checklist item `api/` formally fails — and it passes anyway, because `api/` is not an abstraction layer *over* something (the thing the checklist guards against), it is a **transport boundary**. Its "one caller" is a browser across a network, which is exactly what makes the boundary load-bearing.
- **Does it cross a boundary that needs to be a boundary?** Yes — the network trust boundary, the first one this project has had.

**Verdict: yes, with a thinness rule (§2) that is the actual output of this gate.**

### 2. The thinness rule — `api/` owns HTTP, auth, and serialization. It owns no domain logic.

The realistic failure mode is not "the wrong number of modules"; it is `api/` quietly growing a service layer that reimplements `storage/confirmations.py` behind route handlers, at which point there are two write paths and only one of them is tested.

**The rule:** every write endpoint is *authenticate → load projection → call exactly one `storage/confirmations.py` function → return*. If an endpoint needs logic that isn't already in `storage/`, **that logic belongs in `storage/`**, not in the route handler. A route handler that contains a branch on domain state is a design bug in this module.

This is enforceable by reading, which is the point: any route body longer than a few lines is the smell.

Specifically **not** built:

- No repository/unit-of-work pattern over SQLAlchemy — `session_scope` is already the seam.
- No service classes. `storage/confirmations.py` is deliberately plain functions ("not a service class", per its own docstring and the slice-1A decision doc §5) and the API is the second consumer it was written for. Wrapping them would defeat the reason they exist.
- No DI container beyond FastAPI's own `Depends`.
- **No `api/schemas.py` in v1.** The domain models are already Pydantic v2, so FastAPI serializes `Node`/`Edge` natively. Re-declaring them at the wire boundary would create a second model layer that can drift from the validation gate — the one thing this codebase most needs not to happen. The one exception is the feature-scope summary (§3), which has no domain model yet and gets one *in `models/schema.py`*, not in `api/`.
- No `/v1` prefix, no pagination, no websockets/polling/realtime. One in-repo consumer, ~10 nodes per scope, one PM.

**Layout — flat, four files, no `routers/` package:**

```
src/atlas/api/
  __init__.py
  app.py       # FastAPI() + router include + exception handlers
  deps.py      # get_session, get_principal  ← the auth seam (§4)
  routes.py    # every endpoint; split only when it is actually long
```

A `routers/` package for one screen's worth of endpoints is the microservice-shaped anti-pattern at file scale.

### 3. The gate's main finding: **feature scopes have no identity** — fixed first, as slice 1A′

This is the finding that mattered more than the boundary question, and it is a `storage/` gap surfacing as an API problem.

`atlas ingest` mints a bare `uuid.uuid4()` as `feature_scope_id`, writes `node_created`/`edge_created` events, and prints the UUID (`cli.py:150`, `cli.py:177`). **No `ingestion_run` event is ever written** — the `EventType.INGESTION_RUN` member exists and `projections.py` skips it as a no-op, but nothing in `src/` emits one. So the log records that ten nodes exist under some UUID and nothing whatsoever about what that UUID *is*.

Consequences for slice 1B, all fatal to the exit criterion:

- The UX spec's left rail (`confirmation-flow-spec-v1.md` §1, §3.1 — "Features: › #111, #723, #706 ⚠") has nothing to enumerate. Distinct scope ids are only recoverable by replaying every event and collecting UUIDs off nodes.
- The review page header ("ripgrep #111 · Add --pre preprocessor flag") has no title to render.
- A PM navigating by raw UUID does not clear "unassisted, under 20 minutes."

**Decided: fix it before `api/` is scaffolded**, as a small backend task ahead of 1B (call it **slice 1A′**). Rejected alternatives: having the UI address scopes by raw UUID (defers the same work into the middle of 1B and makes the demo require pasting UUIDs), and giving `api/` its own name mapping in config or a side table (puts scope identity **outside the event log**, breaking the event-sourcing guarantee for the convenience of one screen — precisely the "convenience direct-write path" the skill names as a bug, not a shortcut).

Shape, all of it inside the existing four-module boundary and event-sourced:

- **`ingestion_run` becomes a real, emitted event.** The enum member already exists, so there is **no Postgres enum migration and no new event type** — the same reasoning that killed `node_added` in slice 1A.
- **`IngestionRunPayload` in `models/schema.py`** — `feature_scope_id`, `title`, `source_type`, `external_id`, `url`. Validated at the same gate as everything else; no hand-built dicts reach `append_event`.
- **`Projection` gains `feature_scopes`** alongside `nodes`/`edges`, replayed by removing `INGESTION_RUN` from `_NO_OP_EVENTS` and adding a handler. No new table, no registry — a feature scope is a projection like everything else.
- `record_extraction` writes it; `atlas ingest` derives the title from the PR it already fetched.

Built test-first per the `tdd` skill — this is projection replay and schema validation, squarely in its mandatory set.

**Forward note:** this also gives the deferred **tool-call audit logging** (`docs/decisions/2026-07-28-extraction-tool-call-audit-logging.md`) an event to live in. That work stays in slice 1D as planned; the payload shape should simply not preclude adding the manifest later. Adding an optional field to `IngestionRunPayload` replays cleanly over events written today.

### 4. The auth seam is fixed now; the auth *implementation* is minimal — §10 Q2 resolved

`Phase1_Architecture.md` §10 Q2 (how does the PM authenticate into the product?) was the tracker's listed pre-build blocker. It is not one, and separating the two halves is why:

**The seam (fixed, survives Phase 4):** `deps.py` exposes `get_principal()` returning a frozen `Principal(workspace_id, actor)`. Every route depends on it. **No route ever reads `workspace_id` or `actor` from a request body, query string, or header of its own choosing.** This is the forward constraint the slice-1A decision doc recorded, made structural: `add_node` already builds its Node from fields precisely so an API body cannot choose its own `workspace_id`, and `Principal` is the other half of that design.

**The implementation (minimal, Phase 1 only):** a signed session cookie behind a shared passphrase. Phase 1 has exactly one workspace (`DEFAULT_WORKSPACE_ID` until slice 1D) and one user, so a login page takes a passphrase plus the PM's name; the name becomes `actor` on every event — so the audit record is a real person, not a placeholder — and `workspace_id` is the sentinel. One new dependency (`itsdangerous`).

Rejected: a `users` table with hashed passwords (introduces user identity as a data-model concept ahead of slice 1D's RBAC, for one user), and third-party auth (a hosted dependency and config surface added to the exit-criterion demo; CLAUDE.md defers SSO/SAML to Phase 4).

Because the seam is fixed independently of the implementation, **Q2 never blocked scaffolding — it blocks shipping**, and slice 1D's real RBAC replaces the body of one function.

### 5. Endpoint surface for 1B — read + the four confirmation actions, nothing else

```
GET  /feature-scopes                    → [FeatureScope]        (left rail; needs §3)
GET  /feature-scopes/{id}               → nodes + edges         (load_projection)
POST /nodes/{id}/confirm                → confirm_node
POST /nodes/{id}/reject                 → reject_node
POST /nodes/{id}/edit                   → edit_node
POST /feature-scopes/{id}/nodes         → add_node
POST /session  /  DELETE /session       → login / logout (§4)
```

Two deliberate omissions:

- **No ingest/"connect a source" endpoint in 1B.** The UX spec (§8) puts connect-sources in slice 1C/1D and proves 1B on existing GitHub data. This is load-bearing for the design: an ingest endpoint means a long-running request, which means pressure for a task queue — an explicit CLAUDE.md Non-Goal. Keeping ingestion CLI-triggered in 1B means the API stays synchronous and queue-free with no argument required.
- **No grouping/counting endpoints.** Node-type ordering (`why → what → how`), unconfirmed-first sort, and the progress meter are presentation decisions already fixed in `confirmation-flow-spec-v1.md` §3.2–3.3. The API returns flat `nodes` + `edges`; the frontend groups. Adding a `GET /feature-scopes/{id}/progress` would put a UX decision in the backend.

**Conflicts need no new backend work.** `conflicts_with` edges already exist — Phase 0 proved the agent emits them (PR #706) — and `Projection.for_feature_scope` already keeps only edges whose endpoints both survive the filter. The UX spec's headline feature renders from data 1B already has.

### 6. Frontend — `frontend/` at the repo root, Vite + React + TypeScript, no component library

- **Location: `frontend/` at repo root, not under `src/atlas/`.** It is not a Python package; putting it there breaks hatchling's wheel packaging (`packages = ["src/atlas"]`) and pollutes `mypy_path`.
- **Vite + React + TypeScript. No Next.js** — SSR, file-based routing, and server actions are all weight this needs none of, and the API already exists as a separate process.
- **Types are generated from the OpenAPI schema FastAPI already emits**, never hand-written. A hand-maintained TS mirror of `Node`/`Edge` is the same drift risk as `api/schemas.py` (§2), one language further away.
- **No component library** (MUI/Chakra/shadcn). `design-system-baseline-v1.md` specifies Geist tokens, an 8px scale, and named components (source badge, provenance well, conflict banner); a library would be fought at every step. CSS custom properties for tokens, and the four concrete components the spec names — no generic `<DataTable>`/`<Card>` framework.
- **No state-management library at scaffold time.** Server state arrives via `fetch` + local state until the undo/optimistic-update requirement (`confirmation-flow-spec-v1.md` §4.1, §5 `u`) actually demands cache invalidation — at which point React Query earns its place on evidence rather than by default.
- **Dev:** Vite dev server + CORS in dev; single-origin static mount in prod. No reverse-proxy setup.
- Reviewed by the `frontend-reviewer` agent, built with `design-taste-frontend-v1`; brand tokens (accent, logo) stay deferred to the `brandkit` pass.

## What this gate did *not* approve

No task queue, no realtime layer, no graph database, no vector store, no generic connector-plugin interface (Jira is slice 1C and will be the *second* concrete connector — the point at which a shared shape can be observed rather than guessed). Nothing in `docs/architecture/Phase0_Architecture.md`'s tech stack is displaced; the additions are FastAPI + `itsdangerous` on the Python side and the Vite/React toolchain on the frontend side.

## Consequences

- `Phase1_Architecture.md` §5 stops being a proposal; §10 Q1 and Q2 are resolved (amended in place, pointing here).
- Slice 1B's immediate next step is **slice 1A′** (§3), test-first, before any scaffolding.
- The remaining `Phase1_Architecture.md` §10 open questions are Q3 (settled by `docs/ux/`) and Q4 (Jira OAuth vs API token — slice 1C).
