# Phase 2B pre-registration: does an Atlas spec improve coding-agent output?

**Status: DRAFT, not locked.** Nothing here binds until a person ratifies it and runs `python -m scripts.proof lock`. After that, editing this file makes every result unscoreable (`verify_lock`). A change after locking means deleting `proof/lock.json` and recording that you did so, and why, in the write-up.

## Question

On real historical features whose outcome is known, does a coding agent given the **Atlas spec** produce output closer to what was actually built than the same agent given the **raw artifacts**?

## Design

- **Features.** `proof/features.json` lists the four `BurntSushi/ripgrep` golden-set PRs. **The roadmap requires N ≥ 5, so a fifth must be added before locking.** Below 5, the harness reports "inconclusive" whatever the numbers.
- **Control.** The PR title, body and comments, plus its linked issues. **Never the commits**, because they are the answer.
- **Treatment.** The Atlas spec Markdown export for that feature (`proof/specs/<name>.md`). It is exported only **after a person has reviewed and confirmed the feature's claims in Atlas**, because an unconfirmed claim never reaches an export. **The spec's readiness score and gaps are part of the treatment.** This design therefore cannot attribute an effect to provenance separately from gap-flagging, and no such claim will be made.
- **Held constant.** The same model, tools (`Read`, `Glob`, `Grep`, `Edit`, `Write`; no shell, no network), 40-turn budget, task instruction (`scripts/proof.py::TASK`), and starting commit (`base_sha`, the parent of the merge). The prompt is the only thing that differs.
- **Model.** `claude-sonnet-5`, one run per condition per feature.

## Grading

- **Blind.** `blind --seed <n>` shuffles the diffs into packets with opaque ids. The grader sees only the feature, the packet and the merged diff. `key.json` stays sealed until every packet has a grade.
- **Rubric.** `proof/rubric.json` has four criteria, and a packet's score is their sum (0–10).
- **Grader.** One person who did not write the treatment specs. If possible, a second grader scores independently, and the pre-registered analysis uses the mean of the two.

## Analysis (fixed now)

- The paired difference per feature is treatment total minus control total.
- **Pass:** the mean difference is at least **1.0** point **and** an exact two-sided sign test (ties excluded) gives p ≤ **0.10**, over N ≥ 5.
- With N = 5, only 5–0 reaches p = 0.0625. That bar is deliberately strict, and it is written down now so it can't be relaxed after the results are in.
- **A null result is a result.** If the margin isn't met, the verdict is written into `docs/research/` and the thesis is revised (roadmap v2).

## Checklist before locking

- [ ] Add a fifth feature: a ripgrep PR with discussion and a known merge, plus its golden-set fixture.
- [ ] Check each `base_sha` against `git log` (PRs 706 and 3472 were squash-merged from multi-commit PRs).
- [ ] Review and confirm each feature's claims in Atlas, then export each spec to `proof/specs/<name>.md`.
- [ ] Ratify the rubric wording and the margin above.
- [ ] `python -m scripts.proof lock`
