# Decision Log — Feature-Scope Identity (`ingestion_run`, slice 1A′)

**Date:** 2026-08-11
**Area:** models, storage, extraction, cli
**Implements:** `Phase1_Architecture.md` §4.4 (added by the `codebase-design` gate, `2026-08-11-api-frontend-module-boundary.md` §3)

## Context

`atlas ingest` minted a bare `uuid4()` feature scope and wrote only `node_created` / `edge_created`. `EventType.INGESTION_RUN` existed in the enum, `projections.py` listed it as a no-op, and **nothing ever emitted it**. The log therefore recorded that ten nodes shared a UUID and nothing about what that UUID *was*.

That is fine for a CLI where the engineer who ran the ingest still has the PR number in their scrollback. It is not fine for slice 1B: `docs/ux/confirmation-flow-spec-v1.md` §1 and §3.1 put a feature-scope list in the left rail and the feature's name in the page header, and neither has a data source. A PM navigating by raw UUID does not clear the 20-minute exit criterion.

## Decision

**A feature scope's identity lives in the event log, as a projection, like everything else.**

- **`IngestionRunPayload`** (`models/schema.py`) — `feature_scope_id`, `title`, `source_type`, `external_id`, `url`. It passes the same Pydantic gate as every other payload, on write *and* on replay.
- **`record_extraction` emits `ingestion_run` first**, before the nodes it produced, and the argument is **required** — a run that writes nodes under a scope nobody can name is precisely the gap being closed, so it is not an option a caller can decline.
- **`Projection` gains `feature_scopes: dict[uuid.UUID, FeatureScope]`**; `INGESTION_RUN` came out of `_NO_OP_EVENTS`. `FeatureScope` carries `id`, `title`, and `runs` — every ingestion run that fed it.
- **`extract_from_pull_request` returns `(IngestionRunPayload, ExtractionResult)`** — what was ingested alongside what was extracted from it.
- **No migration, no new event type, no new table.** The enum member already existed and nothing had ever written one, so there is no historical payload to backfill.

`atlas review` now prints the scope's title and the sources it was assembled from, which is the CLI's version of the header the UI will render — and the cheapest possible proof the projection actually works.

## Why the two shortcuts were rejected

**Put UUIDs in the URL and name scopes later.** Defers identical work into the middle of 1B, the slice whose whole job is retiring the usability risk — and the UI would be built against a shape known to be wrong.

**Keep a scope-name map in `api/`.** Puts scope identity outside the event log, breaking the rule that state is a projection of events, and hands the API domain state to own — exactly what the `codebase-design` gate's thinness rule forbids.

## `runs` accumulates rather than replaces

A feature is assembled from many sources — that is Atlas's thesis, and `confirmation-flow-spec-v1.md` already specs an "assembled from" strip. A second run against the same scope therefore **appends**. This costs one line in the reducer today and is the difference between a projection that survives slice 1C's Jira connector and one that has to be reshaped mid-slice.

**Title is last-write-wins**, matching the rule the rest of the projection already follows (a node transition supersedes in place; the last event to touch it wins). Today that means re-ingesting a retitled PR renames the scope instead of keeping a stale name — correct. **Forward note for 1C:** once a *second source* can join an existing scope, last-wins means a Jira issue silently renames a scope a GitHub PR opened. That needs an answer then — probably "the first source names the scope" or an explicit rename — and it is deliberately not guessed at now.

## `external_id` fully qualifies the artifact

`BurntSushi/ripgrep#111`, not `111`. A Node's `SourceRef` can carry a bare PR number because it is already read in the context of a known repo; a feature scope is workspace-global, so a bare number identifies nothing. The two are the same field name for a related-but-distinct job.

## Why the ingestion-run payload is built inside `extract_from_pull_request`

That is where the fetched `PullRequest` lives. Building it in the CLI instead would mean either fetching the same PR twice for its title, or hand-assembling a URL the connector already parsed off `html_url` — a second, drifting source of truth for provenance that the connector exists to own.

## Room left for slice 1D

The per-run **tool-call manifest** (`2026-07-28-extraction-tool-call-audit-logging.md`) lands here as an optional field on `IngestionRunPayload`. Optional-added-later replays cleanly over events written today, and `extra="forbid"` guarantees it arrives declared rather than smuggled through as an undeclared key.

## Verification

192 tests green (20 new), `src/` clean under ruff + strict mypy. Test-first per the `tdd` skill — schema validation and projection replay are both in its mandatory set. Covered: blank-identity rejection on write *and* on replay, per-scope isolation, multi-run accumulation, last-wins titling, pre-1A′ scopes replaying as unnamed rather than crashing, and the full `record_extraction` → `load_projection` → `render_projection` round trip.
