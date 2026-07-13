# Decision Log — Git and Dev Tooling Setup

**Date:** 2026-07-13
**Area:** architecture (project tooling)

## Context

The project had no git repository and no scaffolded codebase — only settled planning docs. Two separate passes established, first, git + a real repo skeleton, then an industry-standard dev-tooling layer around that skeleton.

## Decisions

1. **`git init`, first commit includes the entire existing project state**, not just `README.md` — the user's initial command sequence only staged `README.md`, which would have left `docs/`, `CLAUDE.md`, and `.claude/` untracked; staged everything instead (`git add .`) so the first commit actually reflects the project as it stood.
2. **`.gitignore` added before the first commit**, excluding `.DS_Store`, `.claude/settings.local.json` and `.claude/scheduled_tasks.lock` (machine-local session state — not meant to be shared), and standard Python/`.env` artifacts pre-emptively, ahead of any code existing, so secrets can never land in git by accident once Phase 0 implementation starts.
3. **Pushed to `github.com/rohit291103/Project_Atlas`, branch `main`.**
4. **Dev tooling layer**, added on top of an already-scaffolded (by a separate session) `src/atlas/` skeleton: ruff (lint + format, `select = [E, F, I, UP, B, C4, SIM]`, 100-char lines), mypy in `strict` mode, pytest config, `.pre-commit-config.yaml`, GitHub Actions CI (`.github/workflows/ci.yml`) running all four checks on every push/PR, `.editorconfig`, and a `.python-version` pin to 3.12 (the `.venv` had drifted to system Python 3.13 — recreated to match `docs/architecture/Phase0_Architecture.md`'s documented target).
5. **mypy `disallow_untyped_decorators` disabled**, as a targeted, commented exception rather than weakening `strict` mode broadly — Typer's `@app.command()` decorator isn't typed in a way strict mode recognizes; this is a known Typer/Click ecosystem limitation, not a gap in Atlas's own code. Caught by the pre-commit hook on the first real commit attempt, which is exactly what the hook is for.
6. **Everything verified end-to-end before committing** (`ruff check`, `ruff format --check`, `mypy src`, `pytest`, `atlas --help`), not just assumed to work from the config alone.

## Not done (deferred)

- **LICENSE** — commercial product, not open-sourced; a real legal decision left to the user rather than assumed. Add one if that changes.
- **Makefile** — the `uv run` commands documented in `README.md`'s Development section are the whole workflow; a Makefile would just duplicate that.
- **Dependabot/renovate, issue/PR templates, CODEOWNERS** — premature process for a solo, pre-launch project; revisit once there's a real dependency surface or more than one contributor.
- **Docker/devcontainer** — would contradict the Supabase decision (no local database container needed).
