# Decision Log — Claude Code Tooling Adapted for Atlas

**Date:** 2026-07-13
**Area:** product / architecture (project tooling)

## Context

The project's `.claude/` folder (agents + skills) already existed when this work started, but turned out to be copied from an unrelated prior project — "OptiMILES," an Indian travel-credit-card reward optimizer with a five-engine FastAPI backend. Agents and skills referenced files, a backend structure, and domain vocabulary (transfer ratios, reward valuation) that don't exist in Atlas. This had to be resolved before `CLAUDE.md` and a tracker could be written against something coherent.

## Decisions

1. **Rewrite the mismatched agents/skills in place for Atlas**, rather than deleting them or leaving them untouched alongside new Atlas-specific ones — chosen over the alternatives (delete-and-rebuild, or leave-and-add-alongside) to keep one coherent set of tooling instead of either losing the existing role/workflow shape or ending up with two parallel, confusing sets. Rewrote: `backend-reviewer`, `frontend-reviewer`, `feature-discussion`, `prd-writer` (agents); `tracker-sync`, `docs-sync`, `domain-modeling`, `diagnosing-bugs`, `tdd`, `codebase-design`, `improve-codebase-architecture`, `to-prd`, `to-issues`, `handoff` (skills). Left untouched as already-generic: `resolving-merge-conflicts`, `greploop`, `grilling`/`grill-me`, `design-taste-frontend-v1`, `brandkit`, `supabase-postgres-best-practices`.
2. **Root `CLAUDE.md` and `docs/tracker.md` established** as new files (there was no root `CLAUDE.md` previously covering Atlas — the `.claude/` skills referenced one, but it didn't exist for this project).
3. **Domain vocabulary table built for Atlas's actual data model** (`domain-modeling` skill) — Node vs. Event vs. Edge, confidence vs. status, SourceRef vs. excerpt, feature scope vs. workspace — replacing OptiMILES's reward/finance term table.
4. **Two new skills added** (not in the inherited template, built specifically for Atlas's needs): `extraction-quality-review` (runs the extraction pipeline against the standing validation PRs and grades output) and `writing-evals` (general best practices for evaluating LLM-generated output — deterministic vs. judgment checks, golden-set discipline, statistical honesty at small N, cost asymmetry between false positives/negatives). `backend-reviewer` extended with an eval-coverage check for any change touching `extraction/`.

## Not done (deferred)

- No new agent/skill was added purely for the sake of it — considered and explicitly rejected: separate `provenance-check` and `agent-tool-safety-review` agents, folded into `backend-reviewer`'s checklist instead, since a code-review checklist item is a better fit than a whole new agent for a narrow, single-purpose check.
