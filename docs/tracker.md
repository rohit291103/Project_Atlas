# Project Atlas — Tracker

**Last updated:** 2026-07-13 — docs/ reorganized into subfolders; CLAUDE.md expanded to cover all phases

## Snapshot

Project Atlas has a scaffolded but unimplemented Phase 0 repo with a full industry-standard dev-tooling layer around it, and a docs tree now organized to scale past Phase 0. The PRD, TRD, Roadmap, and Phase 0 Architecture are written, settled, and filed under `docs/prd/` and `docs/architecture/`; `docs/decisions/`, `docs/handoff/`, `docs/research/`, and `docs/ux/` exist as the permanent-record subfolders going forward. `pyproject.toml` and the full `src/atlas/` + `tests/` directory layout exist, with the CLI and config wired up, plus ruff/mypy/pytest config, pre-commit hooks, GitHub Actions CI — all verified working. Every module beyond `cli.py`/`config.py` (schema, storage, ingestion, extraction) is still an empty stub with no real logic. Next real work is implementing those modules, starting with the schema (via `tdd`).

## Docs

### Done
- PRD, TRD, Roadmap written (`docs/prd/PRD_Product_Knowledge_Layer_MVP.md`, `docs/architecture/TRD_Context_to_Spec_Engine.md`, `docs/prd/MVP_Roadmap.md`).
- Phase 0 implementation architecture written (`docs/architecture/Phase0_Architecture.md`): Python + Claude Agent SDK agentic extraction, Supabase for storage.
- Root `CLAUDE.md` and `docs/tracker.md` established; `CLAUDE.md` now explicitly covers the entire project across all 5 phases (a "Roadmap — the whole story" section + summary table), not just Phase 0 — Phase-specific detail stays in `docs/architecture/PhaseN_Architecture.md` docs instead.
- `.claude/` agents and skills adapted from an inherited "OptiMILES" template to Atlas's actual data model, architecture, and phase.
- Eval strategy designed: new `writing-evals` skill (general LLM-eval best practices) + `extraction-quality-review` extended with a two-tier deterministic/judgment split; `tests/evals/golden_set/` structure added to `docs/architecture/Phase0_Architecture.md` §5.
- `docs/` reorganized into the six-subfolder structure (`prd/`, `architecture/`, `decisions/`, `handoff/`, `research/`, `ux/`) plus `tracker.md` as the sole top-level exception. Master docs kept their existing filenames (grandfathered) rather than renamed to the kebab-case convention; `docs/prompts/` concept replaced by `docs/handoff/` (more precise — that was its only actual use). `docs-sync` and `handoff` skills, and every doc-path reference across `.claude/` + `CLAUDE.md` + `README.md`, updated to match. 4 retroactive decision logs written to `docs/decisions/` covering everything decided so far.

### In progress
Nothing active.

### Next up
- Pick the public OSS repo to validate extraction against (Phase 0 exit criterion needs 3–5 real historical PRs with substantive descriptions/linked issues).

## Engineering (Phase 0 build)

### Done
- Repo scaffolded per `docs/architecture/Phase0_Architecture.md` §5: `pyproject.toml` (Python 3.12, `uv`, deps installed, `uv.lock` committed), full `src/atlas/` package layout (`config.py`, `models/schema.py`, `storage/{db,tables,projections}.py`, `ingestion/github.py`, `extraction/{agent,tools,prompts}.py`, `cli.py`), and `tests/` + `tests/evals/` directories. `config.py` reads `ANTHROPIC_API_KEY` / `GITHUB_TOKEN` / `SUPABASE_DB_URL` from env; `cli.py` has a working Typer `atlas` entrypoint with `ingest`/`review` stub commands (`NotImplementedError`). `.env.example` added.
- All other files (`models/schema.py`, `storage/*.py`, `ingestion/github.py`, `extraction/*.py`) are empty stubs — structure only, no logic yet.
- Dev-tooling layer added: ruff (lint + format, `select = [E, F, I, UP, B, C4, SIM]`) and mypy (`strict = true`) configured in `pyproject.toml`; `pytest` config section added; `.pre-commit-config.yaml` (ruff, mypy, basic hygiene hooks) installed into `.git/hooks/pre-commit`; `.github/workflows/ci.yml` runs lint + format-check + mypy + pytest on every push/PR to `main`; `.editorconfig` added; `.python-version` pinned to 3.12 and `.venv` recreated on it (was previously 3.13 from system Python). Verified end-to-end: `ruff check`, `ruff format --check`, `mypy src`, `pytest`, and `atlas --help` all pass clean.
- Deliberately not added yet (would be premature at this stage): LICENSE (commercial product, undecided), Makefile (README documents the `uv run` commands directly), Dependabot/renovate, issue/PR templates, CODEOWNERS, Docker/devcontainer (contradicts the no-local-container decision already made for Supabase).

### In progress
Nothing active.

### Next up
- Pydantic schema (`Node`, `Edge`, `SourceRef`, `Event`) in `models/schema.py` — go through `tdd` skill first (mandatory test-first for schema validation).
- Supabase project + `event_log` table, then `storage/db.py` + `storage/tables.py` + `storage/projections.py` (event replay logic — also `tdd`-first).
- GitHub ingestion connector (`ingestion/github.py`, read-only PR/issue/commit fetch).
- Extraction agent (`extraction/agent.py` + `tools.py` + `prompts.py`, Claude Agent SDK, tools: `fetch_linked_issue`, `fetch_commit`, `search_repo`) — run `writing-evals` + `extraction-quality-review` once this exists.
- Wire real logic into `cli.py`'s `ingest`/`review` commands once the above exist.
- Pick the public OSS repo + 3–5 PRs to validate against (still undecided — see selection criteria discussed 2026-07-13).
- `tests/evals/golden_set/` scaffolding (per-PR recorded fetch + rubric) once that repo/PRs are chosen.
- `tests/evals/test_golden_set.py` — Tier 1 deterministic checks (schema validity, provenance-excerpt verification, rubric).
- Validate against 3–5 historical PRs — Phase 0's actual exit criterion.

## Last session notes

Reorganized `docs/` into subfolders (`prd/`, `architecture/`, `decisions/`, `handoff/`, `research/`, `ux/`) via `git mv`, so the structure `docs-sync` already described is now actually real instead of aspirational. Replaced the `docs/prompts/` concept with `docs/handoff/` (that folder only ever held handoff notes, so the more specific name is clearer). Updated every path reference across `CLAUDE.md`, `README.md`, `docs/tracker.md`, and all `.claude/` agents/skills. Expanded `CLAUDE.md` with a "Roadmap — the whole story" section (all 5 phases, summary table) and an explicit statement that `CLAUDE.md` itself covers the entire project, not just the current phase — answering a direct question about whether it did. Wrote 4 retroactive decision logs to `docs/decisions/` capturing everything decided this project so far (Phase 0 architecture/storage, `.claude/` tooling adaptation, git/dev-tooling setup, this docs reorg). No application code touched this session.
