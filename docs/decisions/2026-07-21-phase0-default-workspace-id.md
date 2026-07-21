# Decision Log — Phase 0 `workspace_id` Source (Default Workspace Sentinel)

**Date:** 2026-07-21
**Area:** models / config

## Context

TRD §3.1 makes `workspace_id` a required field on `SourceRef`, `Node`, and `Event`, and the `event_log` table carries it too. This is deliberate event-sourcing foresight (TRD §3.2): the field exists from day one so multi-tenancy slots in later with no schema migration.

But Phase 0 has no way to *produce* a `workspace_id`. It's explicitly one team / one internal tool, with real workspaces + RBAC deferred to Phase 4 (CLAUDE.md Non-Goals). So there's no workspace-creation flow, yet the very next modules (`storage/projections.py`, `ingestion/github.py`, `extraction/agent.py`) can't construct a Node or write an event without one. `backend-reviewer` flagged this as a blocking dependency after the schema and storage layers landed.

## Decision

Introduce a single well-known constant, `DEFAULT_WORKSPACE_ID = uuid.UUID(int=0)` (the nil UUID), in `src/atlas/config.py`. Every Phase 0 code path that constructs a Node/SourceRef/Event or writes an event stamps it with this constant. Backed by `tests/test_config.py` (asserts it's the nil sentinel and stable across imports — guards against someone changing it to a `uuid4()` factory, which would silently scatter data across phantom workspaces).

### Why the nil UUID specifically

It reads unmistakably as "the default workspace, not a provisioned one." The Phase 4 migration to real multi-tenancy becomes a trivial, greppable "reassign every nil-workspace event to the real workspace row." A random fixed UUID would work mechanically but wouldn't self-document as a sentinel.

### Why keep the schema field *required* (not a model default)

The constant is a plain application-layer value, deliberately NOT a `default=` on the Pydantic fields. If it were a field default, the single-workspace assumption would be silently baked into the schema and would wrongly persist into Phase 1+, where nodes must belong to real workspaces. Keeping the field required means the assumption lives visibly at each call site; when real workspaces arrive, `models/schema.py` is untouched — only the call sites change to pass a real id.

## Alternatives rejected

- **Make `workspace_id` nullable in Phase 0.** Diverges from TRD §3.1, weakens the validation gate, and guarantees a later migration to re-tighten it. The field being required is correct.
- **A real `workspaces` table with one seeded row.** That builds multi-tenancy infrastructure ahead of Phase 4 — a direct CLAUDE.md Non-Goal ("don't add infrastructure ahead of the phase that needs it").
- **An `ATLAS_WORKSPACE_ID` environment variable.** Implies a configurability that doesn't exist (Phase 0 is single-workspace by definition) and fakes an isolation nothing enforces. YAGNI — no call site would ever set it to anything but the default.

## Scope / not covered

- **`feature_scope_id`** (also required on `Node`, scopes a node to a specific feature/epic run) is a *separate* question with a natural Phase 0 home and is **not** covered here: each `atlas ingest` run generates its own `feature_scope_id` (a fresh `uuid4` per run), which `atlas review --feature-scope <id>` then consumes (Phase0_Architecture.md §4). It is not blocked and needs no sentinel.
- No call sites consume `DEFAULT_WORKSPACE_ID` yet — `ingestion/` and `extraction/` are still stubs. This decision unblocks them; wiring happens when those modules are built.

## Revisit trigger

Phase 4 (security/RBAC hardening), when real workspace provisioning lands. At that point: add the `workspaces` table, migrate nil-workspace events to real workspace rows, and update call sites to pass provisioned ids. `models/schema.py` should require no change.
