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
