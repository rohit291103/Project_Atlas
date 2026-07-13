# Decision Log — Phase 0 Architecture and Storage

**Date:** 2026-07-13
**Area:** architecture

## Context

With the PRD, TRD, and Roadmap already settled, the next step was deciding *how* Phase 0 (prove the extraction loop on GitHub only) actually gets built — the TRD describes the target architecture in general terms, but Phase 0 needed a concrete stack, an extraction approach, and a storage choice.

## Decisions

1. **Python-first stack**, per explicit direction, over the TRD's "Node/TypeScript or Python/FastAPI" either-or (§11): `uv` for dependency management, Pydantic v2 for schema validation, SQLAlchemy 2.0 + Alembic, Typer for the CLI, Rich for console output, pytest for tests.
2. **Agentic extraction over single-shot structured prompting.** The TRD (§5.1) describes extraction as one Claude call per document with pre-fetched context. Phase 0 instead builds it as a **Claude Agent SDK agent** with read-only tools (`fetch_linked_issue`, `fetch_commit`, `search_repo`) that follows cross-references it discovers in the text itself, rather than ingestion code pre-fetching everything. Chosen deliberately over the simpler single-shot approach for being more AI-native and better suited to messy real-world PRs, accepting more complexity/latency/cost as the tradeoff. Guardrails: every tool call logged, ~8-call iteration cap, forced schema-validated final output (`emit_extraction`), all tools read-only.
3. **Validation target: a public open-source repository**, not a specific proprietary/company repo, for the 3–5 historical PRs Phase 0's exit criterion requires — no specific repo has been chosen yet (tracked as open in `docs/architecture/Phase0_Architecture.md` §9).
4. **Storage: Supabase (hosted Postgres) instead of local Docker Compose Postgres.** Still just Postgres underneath, so it satisfies the TRD's storage requirements unchanged, but removes the local-container setup step and ships pgvector enabled — meaning Phase 3's Q&A embeddings need zero new infrastructure when that phase arrives. Tradeoff accepted: dev now depends on a hosted external service instead of a fully offline loop, judged acceptable since Phase 0 is internal-only anyway.

## Not done (deferred)

- Choosing the actual validation repo/PRs — still open.
- The exact confidence mapping table (low/medium/high → numeric) — deterministic, to be finalized when `extraction/prompts.py` is actually written, not decided in the abstract.
- Tool-call budget (~8 calls) may need tuning once real agent behavior on messy PRs is observed.
