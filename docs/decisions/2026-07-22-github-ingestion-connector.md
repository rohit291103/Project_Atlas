# Decision Log — Read-Only GitHub Ingestion Connector (`ingestion/github.py`)

**Date:** 2026-07-22
**Area:** ingestion

## Context

With the storage layer complete, the first real code in `ingestion/` was next (tracker: "GitHub ingestion connector, read-only PR/issue/commit fetch"). TRD §4.1 scopes the GitHub source to "PRs (title, description, comments), linked issues, commit messages"; Phase0_Architecture.md §2/§4 splits the work: `ingestion/github.py` fetches the seed PR, while the extraction agent follows cross-references itself via its own tools (`fetch_linked_issue`, `fetch_commit`, `search_repo`). The connector is the read-only HTTP + parsing layer those tools will call.

## Decisions

### 1. The connector owns *all* GitHub HTTP and parsing; extraction tools wrap it thinly

`GitHubClient` is the single place that talks to GitHub. The coming `extraction/tools.py` agent tools are adapters that call `GitHubClient` methods, format the result for the agent, and log the call for provenance — they contain no HTTP. This keeps the **read-only guarantee** (CLAUDE.md Philosophy §1/§6, TRD §9) auditable in one module: `GitHubClient` only ever issues GET requests, enforced by a test (`test_client_only_ever_issues_get_requests`) rather than by convention.

### 2. Transient frozen-dataclass DTOs, not domain models

`PullRequest`/`Issue`/`Commit`/`IssueComment` are plain frozen dataclasses, deliberately *not* Pydantic domain models. Rationale: this is transient raw content (TRD §4.2 — kept only long enough for extraction to run, never persisted), and it comes from GitHub, not from an LLM, so it needs no validation gate. Each DTO carries exactly the provenance handles a `SourceRef` needs — the number/sha (`external_id`), the html url, and the literal text — and nothing more. Parsing is explicit (per-field extraction in `_parse_*` helpers) rather than Pydantic alias-mapping, so the exact fields we read from GitHub's verbose, deeply-nested payloads are transparent and greppable (`extra` fields are simply ignored).

### 3. Rate limiting is surfaced, not auto-retried

`GitHubError` carries `is_rate_limited` (set on 403/429 + `X-RateLimit-Remaining: 0`) so a caller can decide, but the connector does **not** retry/backoff automatically. TRD §4.2 lists backoff as a requirement, but at Phase 0 scale (one team, 3–5 historical PRs) automatic retry is robustness ahead of need; surfacing the condition clearly is enough. Noted for a later phase.

### 4. VCR-style tests via `httpx.MockTransport`, no new dependency

Tests replay recorded JSON fixtures (`tests/fixtures/github/*.json`) through `httpx.MockTransport` — the Phase0_Architecture.md §3 "recorded GitHub API fixtures" decision — with **no live API, token, or network**. `MockTransport` ships with httpx, so no `respx`/`vcrpy` dependency was added (scope discipline). Fixtures include unmodeled extra fields to prove parse tolerance.

## Scope — deferred, not built ahead (CLAUDE.md Non-Goals)

- **Incremental sync / `last_synced_at` deltas** — Phase 1. Phase 0 fetches fresh each run.
- **`search_repo`** — the connector has no search primitive yet. It lands with `extraction/tools.py`, which is the only consumer; adding it now would be building an unused API. (Noted in the tracker's extraction "Next up.")
- **Auto-backoff/retry** — see decision 3.
- **GraphQL** — REST is sufficient for the fields in scope.

## Security cross-check (CLAUDE.md: change touches ingestion + credentials)

- **Read-only preserved** — GET-only, test-enforced. No write scope requested or used.
- **Least-privilege credential** — token supplied by the caller (from `GITHUB_TOKEN` via `Settings`), used only to build the `Authorization: Bearer` header; the connector assumes a token scoped to the repos being read.
- **No secret leakage** — the token is never logged or included in any DTO; `GitHubError` messages come from GitHub's own `message` field, not from the request.
- **No persistence** — the connector touches no database and persists nothing; DTOs are returned to the caller and discarded after extraction.

The formal `security-review` skill and the `backend-reviewer` agent have **not** been run on this change yet — recommended before commit.

## Revisit trigger

- Phase 1: incremental sync (`last_synced_at`), and a second source connector joining `ingestion/` (the connector-per-source boundary should generalize cleanly — revisit if a shared connector interface is warranted then, via `codebase-design`).
- When `extraction/tools.py` is built: add the read-only `search_repo` primitive here.
