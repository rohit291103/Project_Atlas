# Decision Log — Confirmation UI Built (`api/` + `frontend/`, Slice 1B)

**Date:** 2026-08-11
**Area:** api, frontend, models, config
**Implements:** `Phase1_Architecture.md` §5, under the gate in `docs/decisions/2026-08-11-api-frontend-module-boundary.md`, against the `docs/ux/` v1 specs

## What was built

`src/atlas/api/` (`__init__.py` / `app.py` / `deps.py` / `routes.py` — flat, as the gate required) and `frontend/` (Vite + React + TypeScript, no component library, no state library). 23 API tests; the SPA typechecks and builds.

The endpoint surface is exactly the gate's list: `GET|POST|DELETE /session`, `GET /feature-scopes`, `GET /feature-scopes/{id}`, `POST /nodes/{id}/{confirm,reject,edit}`, `POST /feature-scopes/{id}/nodes`. No ingest endpoint, so the API is synchronous and queue-free.

## Decisions this build made that the gate did not

### 1. `ApiSettings` is not a superset of `Settings` — the API holds no GitHub token

Least-privilege applies to our own processes (Philosophy §6). The API never reaches a source system and never runs the agent, so requiring `GITHUB_TOKEN` to boot it would hand the internet-facing process a credential it has no use for. `ApiSettings` is `SUPABASE_DB_URL` + `ATLAS_APP_PASSPHRASE` + `ATLAS_SESSION_SECRET`, and nothing else.

### 2. `NonBlankStr` — one definition of "not blank", reused at the wire

**Found by a test.** `min_length=1` lets `"   "` through, so `POST /nodes/{id}/edit` with whitespace passed FastAPI's validation and then raised inside the domain gate — a **500 for what is plainly a bad request**. Two fixes were possible: map domain `ValidationError` to 422 globally, or reject blanks at the boundary.

Mapping globally was rejected: a `ValidationError` raised *on replay* means a corrupt log — a Critical-tier bug — and dressing that as "your request was invalid" would hide it. So the boundary validates, and a bare `ValidationError` still surfaces as a 500, which is what it is.

Rather than restate the rule in `api/`, the check moved into `models/schema.py` as `NonBlankStr` (`Annotated[str, Field(min_length=1), AfterValidator(...)]`) and replaced **four** hand-rolled copies of the same validator across `SourceRef`, `Node`, `NodeEditPayload`, `IngestionRunPayload` and `Event`. The API's request bodies import it. One definition, net fewer lines, and the wire cannot drift from the gate behind it.

### 3. Response models: narrow envelopes, never a mirror

`Node`, `Edge` and `FeatureScope` are returned as themselves — FastAPI serializes the domain models directly, so there is no `api/schemas.py`. The only declared models are input bodies (`SignInRequest`, `EditNodeRequest`, `AddNodeRequest`) and one read envelope, `FeatureScopeDetail(feature_scope, nodes, edges)`.

The envelope lives in `routes.py`, not `models/schema.py` as the gate's §2 aside suggested. It embeds the domain models rather than re-describing them, so the drift the rule guards against is structurally impossible; placement then follows locality. `FeatureScope` similarly stayed in `storage/projections.py` next to the reducer that builds it — it is a read model, not an entity at the validation gate.

### 4. TypeScript sees "response" types, derived from the generated ones

Domain fields with server-side defaults (`id`, `created_at`, `status`) are optional in OpenAPI — true of a request, never of a response. `api.ts` narrows exactly those to required via a `Populated<T, K>` helper over the generated types. No model is re-declared in TypeScript; the generated file stays the only source.

### 5. Cookie `secure` follows the request scheme

`secure=request.url.scheme == "https"` rather than a config flag: local http dev works, and anything served over TLS ships a cookie the network can't read. `httponly` + `samesite=lax` throughout; the session carries **only** the actor's name, never `workspace_id` — the tenant boundary is a server-side fact and must not be something the client contributes to.

### 6. Existence checks are HTTP concerns, not domain logic

`add_node` 404s on an unknown feature scope. Without it, a typo'd id silently creates an orphan scope holding one hand-typed node. That is an existence check, not a branch on domain state, and it is the same check `GET /feature-scopes/{id}` already makes.

## A spec-vs-schema gap the build found: `u` cannot always undo

`confirmation-flow-spec-v1.md` §5 lists `u` = "undo last action", and the slice-1A reasoning that made it seem free was "replay is last-write-wins, so every action is trivially undoable." That is **not quite true**: there is no `node_unconfirmed` event type — deliberately, since TRD §3.1's enum has none — so a node can never return to `unconfirmed`. Confirm→undo is expressible only as "reject", which is a different statement, not an undo.

The UI implements what the log can express (restore previous content after an edit; re-confirm or re-reject to reverse a ruling) and says so plainly otherwise: *"a node can't return to 'to review'. The log only moves forward."* Inventing an unconfirm event to satisfy a UI affordance would have been the wrong trade — this is a real property of an append-only model and the UI should tell the truth about it. Worth reflecting back into the flow spec at its next revision.

## Frontend shape

Fixed section order (why → what → how), unconfirmed-first within a section, focus model (only the focused card expands; reviewed cards recede to dim rows), monospace provenance well with `↗ source`, amber conflict banner naming the counterpart, inline edit and an add composer that asks for a claim and a type and **never for a citation** (manual provenance is the person — `2026-08-03-manual-node-provenance.md`). Keyboard: `j/k/c/e/x/a/o/u`. Dark-canonical tokens with a light remap, `prefers-reduced-motion` honoured, status never encoded by colour alone.

## Verification

215 Python tests green, `src/` clean under ruff + strict mypy; `npm run build` clean. The API was driven end-to-end over real HTTP (uvicorn against a seeded local SQLite log): 401 unauthenticated, 401 on a wrong passphrase, sign-in → cookie, scope list and detail, confirm → `updated_by` = the cookie's actor, edit → `edited`, blank edit → 422, manual add → `human_assertion` provenance naming the actor, a body carrying `actor`/`workspace_id` → 422, sign-out → 401. Dev CORS preflight from `:5173` returns the origin with credentials allowed; the Vite dev server serves the app.

**Not verified:** the UI in a real browser. No browser tooling was available in this session, so layout, focus movement and keyboard flow are unexercised beyond typechecking — the `frontend-reviewer` agent's pass (real-browser defects, design-system adherence) is still outstanding and should run before this is put in front of a PM.

## Consequences

- Phase 1's primary risk is now testable: a PM can be sat in front of this. The exit criterion is *unassisted, under 20 minutes*, and that measurement has not been taken yet.
- Feature scopes ingested before slice 1A′ carry no `ingestion_run`, so they do not appear in the left rail. Re-ingest gives them a name; no backfill is planned.
- New dependencies: `fastapi`, `itsdangerous`, `uvicorn` (Python); Vite/React/TypeScript, `openapi-typescript`, and self-hosted Geist fonts (frontend). Nothing the gate ruled out was added.
