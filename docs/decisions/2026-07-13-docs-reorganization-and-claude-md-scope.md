# Decision Log — Docs Reorganization and CLAUDE.md Scope

**Date:** 2026-07-13
**Area:** product / architecture (project tooling)

## Context

`docs-sync` already described a six-subfolder structure (`prd`, `architecture`, `research`, `ux`, `decisions`, `prompts`) for future content, but the four foundational docs (PRD, TRD, Roadmap, Phase0 Architecture) still sat flat at `docs/` root — the structure was aspirational, not real. Separately, `CLAUDE.md` leaned heavily Phase-0-specific (its Module Boundary and Tech Stack sections described only the current phase's four modules), raising the question of whether it should instead describe the whole project across all phases.

## Decisions

1. **Moved the four foundational docs into subfolders** via `git mv` (preserving history): `PRD_Product_Knowledge_Layer_MVP.md` and `MVP_Roadmap.md` → `docs/prd/`; `TRD_Context_to_Spec_Engine.md` and `Phase0_Architecture.md` → `docs/architecture/`. `docs/tracker.md` stays at the top level — the one established exception.
2. **Kept the foundational docs' existing filenames** rather than renaming to the `kebab-case-topic-v1.md` convention — moving them was already enough churn for one pass, and the original names are still descriptive and already linked from multiple places. New docs going forward (in any subfolder) follow the kebab-case convention; a major revision to a foundational doc still creates a new file (`Phase1_Architecture.md`, etc.) rather than overwriting.
3. **`docs/prompts/` replaced by `docs/handoff/`** — the folder only ever held handoff notes produced by the `handoff` skill, so the more specific name is clearer and there's no longer a folder named for a use case that was never actually distinct from handoff.
4. **`docs/decisions/`, `docs/handoff/`, `docs/research/`, `docs/ux/` created**, with `research/` and `ux/` and `handoff/` getting a one-line `README.md` placeholder each (per the existing "empty folders need a README" rule) since they have no real content yet; `decisions/` did not need one since this pass populated it immediately.
5. **`CLAUDE.md` expanded to explicitly cover the entire project across all five phases**, not just Phase 0 — added a "Roadmap — the whole story" section with the full phase summary table, and a direct statement that `CLAUDE.md` itself doesn't change phase to phase; only phase-specific architecture docs (`docs/architecture/PhaseN_Architecture.md`) do. This was a direct response to being asked whether `CLAUDE.md` told "the entire story" — it didn't, and now does.
6. **Every doc-path reference updated** across `CLAUDE.md`, `README.md`, `docs/tracker.md`, and all `.claude/` agents and skills, to point at the new subfolder locations — done as a single pass immediately after the move so nothing was left pointing at a path that no longer existed.
7. **Retroactively logged every prior decision** made so far this project into `docs/decisions/`, grouped into four thematic entries (architecture/storage, `.claude/` tooling, git/dev-tooling, this reorg) rather than one file per micro-decision, since they mostly happened within one continuous session and grouping by theme is more useful to a future reader than nine same-dated fragments.

## Not done (deferred)

- No content reorganization beyond path moves — the foundational docs' actual content was not edited in this pass, only relocated.
