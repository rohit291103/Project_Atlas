# Atlas confirmation UI

The React SPA a PM reviews extracted elements in — Phase 1 slice 1B. It talks
only to `api/` (`src/atlas/api/`), never to the database or a source system.

Design contract: `docs/ux/design-system-baseline-v1.md` (tokens, components) and
`docs/ux/confirmation-flow-spec-v1.md` (screens, keyboard flow). Boundary
decisions: `docs/decisions/2026-08-11-api-frontend-module-boundary.md` §6.

## Running it

Two processes. From the repo root, with `.env` filled in (see `.env.example`):

```bash
# 1. the API
ATLAS_DEV_CORS=1 uv run uvicorn atlas.api.app:app --reload --port 8000

# 2. the SPA
cd frontend && npm install && npm run dev      # http://localhost:5173
```

Ingestion stays CLI-triggered in this slice — there is no ingest endpoint. Get
data in with `uv run atlas ingest --repo owner/name --pr N`, then reload the rail.

> Feature scopes ingested **before slice 1A′** have no `ingestion_run` event and
> so no name; they don't appear in the left rail. Re-ingest to give them one.

## Types

`src/api-types.ts` is generated from the API's OpenAPI schema and is never edited
by hand. After changing any route or model:

```bash
uv run python -c "import json; from atlas.api.app import create_app; print(json.dumps(create_app().openapi()))" > ../openapi.json
npm run generate:types
```

## Checks

```bash
npm run typecheck   # tsc --noEmit
npm run build       # typecheck + production bundle
```

## The browser suite

`tests/ui-smoke.spec.ts` drives a real browser against a *running* app, because
`tsc` and `vite build` both pass on defects that are only visible once something
renders the page.

It runs in **its own workspace**, seated and rebuilt by
`scripts/seed_test_workspace.py`: `globalSetup` runs the seed before every suite,
so a run always starts from the same claims no matter what the previous run
confirmed. Nothing it does touches the demo's data. That is why the two tests
that confirm a claim are no longer excluded.

```bash
set -a && source .env && set +a          # the seed needs both database URLs
cd frontend && VITE_API_BASE="" npm run build   # same-origin, as the Dockerfile builds it
ATLAS_STATIC_DIR=frontend/dist uv run uvicorn atlas.api.app:app --port 8010   # repo root
cd frontend && ATLAS_UI_PORT=8010 npm run test:ui
```

Serving the built SPA from the API is the fastest path — same origin, no Vite,
no CORS. **`VITE_API_BASE=""` is not optional there**: the default is baked in at
build time as `http://localhost:8000`, so a build without it is served from one
port and calls another, every request is cross-origin, and the only symptom is
"Couldn't sign in. Is the API running?" on a form whose credentials are correct. `webServer.reuseExistingServer` adopts whatever is already listening on
`ATLAS_UI_PORT`, which is what makes that work, and is also why the port is
explicit: a Vite left running from another session against a *different* API is
adopted just as silently.

`ATLAS_SKIP_SEED=1` runs against a database this machine cannot seed;
`ATLAS_TEST_EDITOR` / `ATLAS_TEST_VIEWER` name the actors to sign in as there.

> **Killed runs leave zombie Chromium processes**, and the next run then hangs
> before its first test with no timeout and no output. `pkill -f playwright;
> pkill -f chrome-mac` clears it.
