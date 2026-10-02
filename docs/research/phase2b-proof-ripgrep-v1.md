# Phase 2B proof, ripgrep: the result is null

**Date:** 2026-10-02
**Question (pre-registered 2026-09-30, `proof/preregistration.md`):** on real historical features whose outcome is known, does a coding agent given the **Atlas spec** produce output closer to what was actually built than the same agent given the **raw artifacts**?

**Answer: not on this set.** Mean paired difference **0.00**, with 1 win, 1 loss and 3 ties, sign test p = 1.000. The pre-registered bar was a mean of at least 1.0 *and* p ≤ 0.10. Per roadmap v2 this closes Phase 2 legitimately and requires the thesis to be revised (see the last section).

## The scores

Each output was graded blind by `claude-opus-5` against the merged diff. Each total is out of 10: behaviour 0–4, decisions 0–2, scope 0–2, compiles 0–2.

| Feature | Control (raw PR) | Treatment (Atlas spec) | Difference |
|---|---|---|---|
| rg-111 `--maxdepth` | 9 (4/2/2/1) | 9 (4/2/2/1) | 0 |
| rg-706 custom ignore filenames | 10 (4/2/2/2) | 10 (4/2/2/2) | 0 |
| rg-723 line-number width | 8 (3/1/2/2) | 9 (3/2/2/2) | **+1** |
| rg-3472 incremental ignore | 7 (2/1/2/2) | 7 (2/1/2/2) | 0 |
| rg-2957 zsh dynamic completion | 7 (3/2/1/1) | 6 (3/1/1/1) | **−1** |

Three features scored identically on every criterion. The two that moved did so by one point, on `decisions`, in opposite directions. The judge records scores but not its reasons, so neither movement can be explained. Both are within what one judge sample of one agent run can plausibly vary by.

## Why it came out null

These are readings of the result, not findings. Nothing here was pre-registered.

1. **Ceiling.** The control averaged **8.2 of 10**, and two features scored 9 and 10 without the spec. On rg-706, no treatment could have won.
2. **The spec had nothing to add that the control lacked.** Each feature is **one PR plus the issues it closes**, written by the maintainer, and both conditions draw on it. The spec is a curated compression of exactly what the control already read. **Atlas's argument is about context that is scattered**: across a ticket, a PR, a design doc and a discussion, often disagreeing. That case was not in this set. This set tested the weakest version of the claim: whether rewriting one well-written PR as a spec helps.
3. **Coarse instrument, small N.** Integer scores on a 10-point scale, one agent run per condition, one judge sample per packet, N = 5. With N = 5, only a 5–0 sweep could have passed, by design.

## What was observed but not pre-registered

This is **not evidence**. It's recorded so a future pre-registration can decide whether to test it.

- **Turn cap reached:** **4 of 5** control sessions versus **2 of 5** treatment sessions. The two treatment sessions that hit it were on rg-706 and rg-723.
- **Diff size:** the treatment diff was smaller on all five features (94 vs 103, 283 vs 307, 135 vs 148, 368 vs 392, 73 vs 99 lines). It was not scored better for that.
- Possible reading: with the spec, the agent reaches the same result in fewer turns. Another reading: the treatment prompt is shorter, and that's the whole effect. This set can't tell the two apart.

## Limits that apply to any reading of this result

These are repeated from the pre-registration as it requires.

- **Claims were curated by Claude, not confirmed by a person.** `claude-opus-5` used `CURATOR_PROMPT`, applied in memory only, and nothing went to the event log. The treatment was "an Atlas spec curated by Claude". **This says nothing directly about human-reviewed specs.**
- **Only a Claude judge graded the output.** There was no human grader and no spot check. The judge (Opus) and the coding agent (`claude-sonnet-5`) are from the same model family.
- **The readiness score and gaps are part of the treatment.** No effect could have been attributed to provenance separately, and no effect was found to attribute.
- **One recorded extraction per feature.** These are the golden-set runs.

## How the run went

- **Ten agent sessions, all on their first attempt.** `scripts/proof.py` ran with a 40-turn cap and `Read`/`Glob`/`Grep`/`Edit`/`Write` only, inside a scratch checkout at each `base_sha`.
- **Blinding:** seed `20260930`. The key stayed sealed until all ten grades existed (`proof/grades.json`, every grade on its first attempt per `grades.meta.json`).
- **Five deviations after the lock**, all recorded with the results that existed at the time in `proof/deviations.md`. None was made after any grade existed.
  1. Reaching the turn cap ends the agent's run rather than crashing the experiment.
  2. Pre-commit hooks stripped trailing whitespace from three control prompts (immaterial; hooks now exclude `proof/`).
  3. The first harness could not edit files ("Stream closed"). Its two empty rg-111 diffs were discarded in both conditions, and all runs were repeated.
  4. API-side error results are retried from scratch, at most twice.
  5. The same retry applies to judge *calls* only (an invalid reply still stops the run), and grades are saved one at a time. A judge call failed before any grade had been saved.
- **Artifacts:** `proof/runs/*`, `proof/packets.json`, `proof/key.json`, `proof/grades.json` and `proof/result.json`.

## Revising the thesis

Roadmap v2 requires the thesis to be revised after a null result. **What the revised thesis says is the user's decision.** This section proposes; it doesn't decide.

- **What Atlas can no longer claim:** that an Atlas spec measurably improves a coding agent's output. Nothing in the product or on the landing page claims it today, and the landing page's `loop.tsx` deliberately never did. That must stay true.
- **What the result doesn't touch:** provenance and surfaced disagreements as review tooling for people, which is what Phase 1's measurement asks about. Feedback, Q&A and versioning are also untouched.
- **Proposed narrower thesis, untested:** a spec helps when the control's context is scattered or contradictory, and doesn't help when one good PR already says everything. A second pre-registered run could test this. It would use features whose decisions are spread across at least two systems (PR + ticket or design doc) with at least one real disagreement, give the control *all* the raw artifacts, and pre-register turns used as a secondary outcome. The `cross-SCRUM-8` / `pr-111` pair is the only such case in the golden set today, so this needs new material, most likely a design partner's.
- **Paid pilot:** roadmap v2 made "ready for a small paid pilot cohort" conditional on a positive result, so that deliverable doesn't follow from Phase 2.
