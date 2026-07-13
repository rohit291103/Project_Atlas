---
name: extraction-quality-review
description: Runs the extraction pipeline's eval suite (deterministic checks in tests/evals/ + judgment-based grading) against the fixed set of historical validation PRs, and grades output against the Roadmap's Phase 0 exit criteria — usable, mostly-correct structured output, every claim traceable to a literal source excerpt. Use whenever extraction/agent.py, extraction/tools.py, or extraction/prompts.py changes, and any time someone asks "is extraction actually working."
---

# extraction-quality-review

The Roadmap's Phase 0 exit criterion isn't "the code runs" — it's "extraction produces usable, mostly-correct structured output for at least 3 real past features, validated manually" (`docs/prd/MVP_Roadmap.md`). Nothing else in Phase 0 matters if this loop doesn't hold up, so this skill exists as the repeatable check, instead of re-deriving a manual eyeball process every time the extraction agent changes.

This is a quality/output-correctness check, distinct from `backend-reviewer` (which reviews the *code* for architectural/safety violations) and `tdd` (which covers schema/storage unit tests in isolation from real agent output). Run this one whenever the *agent's behavior* changes, not just its code shape. Read `.claude/skills/writing-evals/SKILL.md` first — it's the methodology this skill applies; this file is the Atlas-specific execution of it.

## Before running

Read `docs/tracker.md` (via `tracker-sync`) to confirm the validation repo has actually been picked (`docs/architecture/Phase0_Architecture.md` §9 — this is an open question until someone chooses one) and which PRs are the standing golden set (`tests/evals/golden_set/`, once scaffolded). If neither exists yet, this skill isn't runnable — say so and point back to that open question instead of inventing a repo choice.

## Two-tier workflow (per `writing-evals`)

### Tier 1 — deterministic (run first, every time, via `pytest tests/evals/`)

- **Schema validity** — every emitted Node/Edge passes Pydantic validation.
- **Provenance verifiability** — every `SourceRef.excerpt` is found as a substring/near-match in the actual fetched source text. Any failure here is an automatic Critical, no judgment call needed.
- **Structural rubric** — each golden-set fixture's hand-authored minimum expectations (e.g. "must yield ≥1 `decision` Node") are met.

If Tier 1 fails, stop and fix before spending time on Tier 2 — a provenance or schema failure is a blocker regardless of how good the qualitative read is.

### Tier 2 — judgment-based (run after Tier 1 passes, manual or via a calibrated LLM-judge)

1. **Run** `atlas ingest` + `atlas review` against each of the 3–5 standing validation PRs (the same set every time, so results are comparable run to run — don't silently swap in different PRs).
2. **Grade each run**:
   - **Correctness**: does the Node's `content` accurately represent what the source says, and is it typed correctly (goal vs. requirement vs. decision vs. open question, per TRD §3.1)?
   - **Completeness**: does the run miss an obviously-extractable element a human reviewer would expect (e.g. an explicit rejected alternative mentioned in PR discussion that never became a Node)?
   - **Confidence calibration** — spot-check whether high-confidence Nodes are actually more reliable than low-confidence ones. If low-confidence Nodes are just as often correct, the mapping (TRD §5.1) isn't calibrated yet — note it, don't silently "fix" it without discussing.
3. **Compare against the last recorded run** (`docs/research/`, if one exists) — did this change improve, regress, or leave quality unchanged? A regression on a previously-passing PR is a blocker, not a tradeoff to accept silently.
4. **Report honestly at this sample size** — per `writing-evals`, 3–5 PRs is qualitative signal, not a percentage. Describe what failed and why, don't lead with "N/5 passed."

## After running

5. **Record the result** — save a dated note to `docs/research/<date>-extraction-quality-run.md` (via `docs-sync` Mode C) with: which PRs were run, Tier 1 pass/fail, Tier 2 pass/fail per check above, and any patterns noticed. This is what future runs compare against — don't skip it just because the run "looked fine."
6. **Refresh the tracker** if this run changes whether Phase 0's exit criterion is met (`tracker-sync` Mode B).

## Output shape

```
## Extraction Quality Review — <date>

**Validation set:** <repo>, PRs #<n>, #<n>, #<n>

### Tier 1 — deterministic (pytest tests/evals/)
- Schema validity: pass/fail
- Provenance verifiability: pass/fail — <which excerpt(s) failed, if any>
- Structural rubric: pass/fail per fixture

### Tier 2 — judgment, per PR
#### PR #<n>
- Correctness: pass/fail — <detail if fail>
- Completeness: <what was missed, if anything>

### Confidence calibration
<observation>

### Vs. last run (<date> or "first run")
<improved / regressed / unchanged, specifics>

### Verdict
<Does this meet the Phase 0 exit criterion yet? What's the single highest-leverage next fix?>
```

## What this skill does not do

It doesn't fix the extraction agent itself — findings go back to the user (or into a `diagnosing-bugs` loop for anything Critical-tier, like fabricated provenance). It doesn't grade UI/CLI presentation — that's `frontend-reviewer`'s territory once there's a UI. It doesn't replace `backend-reviewer`'s code-level review of the same files, or `writing-evals`' general methodology guidance.
