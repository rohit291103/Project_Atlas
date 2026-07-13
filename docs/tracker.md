# Project Atlas — Tracker

**Last updated:** 2026-07-13 — CLAUDE.md + .claude tooling setup + evals design

## Snapshot

Project Atlas is pre-code. The PRD, TRD, Roadmap, and Phase 0 Architecture are written and settled; the repo itself isn't scaffolded yet — no `git init`, no `pyproject.toml`, no `src/atlas/`. This session finished the project's Claude Code tooling (root `CLAUDE.md`, `docs/tracker.md`, adapting the `.claude/` agents/skills — previously copied from an unrelated project — to Atlas's actual product, and designing the `tests/evals/` eval-harness approach for grading the extraction agent's LLM output). Next real work is scaffolding Phase 0.

## Docs

### Done
- PRD, TRD, Roadmap written (`docs/PRD_Product_Knowledge_Layer_MVP.md`, `docs/TRD_Context_to_Spec_Engine.md`, `docs/MVP_Roadmap.md`).
- Phase 0 implementation architecture written (`docs/Phase0_Architecture.md`): Python + Claude Agent SDK agentic extraction, Supabase for storage.
- Root `CLAUDE.md` and `docs/tracker.md` established.
- `.claude/` agents and skills adapted from an inherited "OptiMILES" template to Atlas's actual data model, architecture, and phase.
- Eval strategy designed: new `writing-evals` skill (general LLM-eval best practices) + `extraction-quality-review` extended with a two-tier deterministic/judgment split; `tests/evals/golden_set/` structure added to `docs/Phase0_Architecture.md` §5.

### In progress
Nothing active.

### Next up
- Pick the public OSS repo to validate extraction against (Phase 0 exit criterion needs 3–5 real historical PRs with substantive descriptions/linked issues).

## Engineering (Phase 0 build)

### Done
Nothing yet — repo isn't scaffolded.

### In progress
Nothing active.

### Next up
- `git init` + `pyproject.toml` + `src/atlas/` skeleton per `docs/Phase0_Architecture.md` §5.
- Supabase project + `event_log` table.
- GitHub ingestion connector (read-only PR/issue/commit fetch).
- Extraction agent (Claude Agent SDK, tools: `fetch_linked_issue`, `fetch_commit`, `search_repo`).
- CLI (`atlas ingest`, `atlas review`).
- `tests/evals/golden_set/` scaffolding (per PR: recorded raw fetch + hand-authored rubric) once the validation repo/PRs are chosen.
- `tests/evals/test_golden_set.py` — Tier 1 deterministic checks (schema validity, provenance-excerpt verification, rubric).
- Validate against 3–5 historical PRs from the chosen public repo — this is Phase 0's actual exit criterion.

## Last session notes

Planned Phase 0 architecture (agentic extraction via Claude Agent SDK, Python-first stack), switched storage from local Docker Postgres to Supabase, rewrote the project's `.claude/` agents and skills — which turned out to be copied from an unrelated "OptiMILES" project — to reference Atlas's actual docs and architecture, and designed the eval strategy for the extraction agent's LLM output (new `writing-evals` skill, two-tier deterministic/judgment split, `tests/evals/golden_set/` structure). No application code written yet.
