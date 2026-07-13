# Project Atlas — Context-to-Spec Engine

AI coding agents can implement software faster than teams can supply them with correct context. The context an agent actually needs — *why* a feature exists, *what* was decided, *what* was rejected, *what constraints apply* — is scattered across PRDs, tickets, threads, and pull requests, with no canonical, machine-readable representation.

Project Atlas ingests existing artifacts for a feature (GitHub PRs/issues today; Jira/Linear and a doc tool later), extracts structured, provenance-linked claims — goals, requirements, decisions, constraints, rejected alternatives, open questions — and assembles them into a spec that a coding agent (or a human) can execute against with confidence. Every claim in that spec traces back to the literal source that supports it.

This is the wedge for a longer-term Product Graph vision, scoped deliberately narrow: prove the extraction-trust loop works before building anything broader.

## Status

**Phase 0** (of 5 — see the roadmap): proving the extraction loop end-to-end on GitHub only, for one team, as an internal tool. No UI, no RBAC, no second source yet — those are later phases. The product/architecture docs are settled; the codebase itself hasn't been scaffolded yet.

Current state in detail: [`docs/tracker.md`](docs/tracker.md).

## Documentation

| Doc | Contents |
|---|---|
| [`docs/PRD_Product_Knowledge_Layer_MVP.md`](docs/PRD_Product_Knowledge_Layer_MVP.md) | Product requirements, target users, success metrics, non-goals |
| [`docs/TRD_Context_to_Spec_Engine.md`](docs/TRD_Context_to_Spec_Engine.md) | Full technical architecture, data model, all phases |
| [`docs/MVP_Roadmap.md`](docs/MVP_Roadmap.md) | Phased roadmap (Phase 0–4) with exit criteria per phase |
| [`docs/Phase0_Architecture.md`](docs/Phase0_Architecture.md) | Current phase's concrete implementation plan (stack, repo layout, data flow) |
| [`docs/tracker.md`](docs/tracker.md) | Living snapshot of what's done / in progress / next |
| [`CLAUDE.md`](CLAUDE.md) | Engineering philosophy, module boundaries, and the workflow AI agents follow in this repo |

## How it works (Phase 0)

```
GitHub PR/issue/commit
      │
      ▼
ingestion — read-only fetch
      │
      ▼
extraction — a Claude Agent SDK agent, with tools to follow
             cross-references (linked issues, commits) it finds
             in the text, emits schema-validated Node/Edge output
      │
      ▼
storage — append-only event log (Supabase/Postgres); Node/Edge
          state is a projection replayed from events, never
          mutated directly
      │
      ▼
review — CLI + console report, grouped by type, showing
         confidence and the literal source excerpt for every claim
```

## Engineering principles

Non-negotiable, per [`CLAUDE.md`](CLAUDE.md):

1. **Read-only by default** — no write-back to any source system.
2. **Extraction is a draft, never a fact** — nothing extracted is treated as settled until a human confirms it.
3. **Event-sourced, not fixed-schema** — the event log is the source of truth; everything else is a projection.
4. **Provenance is non-negotiable** — every extracted claim carries a literal source excerpt, not a paraphrase.
5. **Idempotent, incremental ingestion** — re-running never duplicates or corrupts existing data.
6. **Least-privilege data access** — the system only ever sees what the connecting credential already has access to.

## Tech stack (Phase 0)

Python 3.12 + `uv` · Claude Agent SDK · `httpx` · Pydantic v2 · Supabase (Postgres) · SQLAlchemy 2.0 + Alembic · Typer · Rich · pytest.

## Working in this repo

If you're an AI agent (or a human) picking this up, read [`CLAUDE.md`](CLAUDE.md) first, then [`docs/tracker.md`](docs/tracker.md) for current state. `.claude/` contains project-specific agents and skills covering the standard workflows here (new feature, bug fix, security review, extraction-quality evals, etc.).
