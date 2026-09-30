# Phase 2B pre-registration: does an Atlas spec improve coding-agent output?

**Status: LOCKED on 2026-09-30** (see `proof/lock.json`). Editing this file after locking makes every result unscoreable (`verify_lock`). Any later change means deleting the lock and recording that, and why, in the write-up.

**Harness:** `scripts/proof.py`, sha256 `bf94aa89f7c3020efcf8f88cde63a8ddaa684f86eeabe83a061049ff2b1d8e96` at lock time. The curator, judge and task prompts are the constants `CURATOR_PROMPT`, `JUDGE_PROMPT` and `TASK` in that file.

## Question

On real historical features whose outcome is known, does a coding agent given the **Atlas spec** produce output closer to what was actually built than the same agent given the **raw artifacts**?

## Features (N = 5)

The five `BurntSushi/ripgrep` PRs in `proof/features.json`. Each `base_sha` was checked against a clone on 2026-09-30: it is the first parent of the merged commit, and `base..merged` is exactly the feature's change.

| Name | PR | Merged change |
|---|---|---|
| rg-111-max-depth | #111 | 3 files, +30/−1 |
| rg-706-custom-ignore-names | #706 | 3 files, +134/−13 |
| rg-723-line-number-width | #723 | 7 files, +69/−3 |
| rg-3472-incremental-ignore | #3472 | 4 files, +1355/−10 |
| rg-2957-zsh-dynamic-completion | #2957 | 2 files, +29/−4 (added 2026-09-30 as the fifth; the choice was fixed before any proof run) |

## Conditions

- **Control:** the PR's title, body and conversation comments, plus the issues it closes. **Never the commits**, because they are the answer.
- **Treatment:** the Atlas spec Markdown for that feature, produced by the product's own `assemble` and `to_markdown`. **The spec's readiness score and gaps are part of the treatment**, so an effect cannot be attributed to provenance separately from gap-flagging, and no such claim will be made.
- **Held constant:** the same task instruction, the same starting commit (`base_sha`), the same model (`claude-sonnet-5`) and the same tools. The tools are `Read`, `Glob`, `Grep`, `Edit` and `Write`, limited to the agent's own scratch checkout, with no shell and no network, and a 40-turn cap. One run per condition per feature. The prompt is the only thing that differs.

## Deviations from the roadmap's design, stated before any result

These were **decided by the user on 2026-09-30**. They weaken what a positive result can claim, and the write-up must repeat them.

1. **Claims were curated automatically, not confirmed by a human.** The product builds specs from human-confirmed claims. Here the user delegated that review. A separate Claude call (`claude-opus-5`, `CURATOR_PROMPT`) keeps or rejects each extracted claim. The curator sees **only what the control agent sees** (never the commits), and its choices are applied **in memory only**. Nothing was written to Atlas's event log, because recording an automated choice as a human ruling is exactly what `actor_kind` exists to prevent. The treatment is therefore "an Atlas spec curated by Claude". **A result says nothing directly about human-reviewed specs.**
2. **Grading is by a Claude judge only**, with no human grader or spot check. Each blinded packet is scored by `claude-opus-5` (`JUDGE_PROMPT`) against the rubric and the merged diff. The judge is never told the condition. **An LLM judged the code, and that is the result's weakest link.**
3. **The extractions are the recorded golden-set runs.** The five `extraction.json` files are single real agent runs, the same ones Tier-1 grades. `#2957` was recorded on 2026-09-30.

## Rubric (`proof/rubric.json`, locked as drafted)

A packet's score is the sum of four criteria, 0–10 in total: `behaviour` (0–4), `decisions` (0–2), `scope` (0–2) and `compiles` (0–2).

## Analysis (fixed now)

- The paired difference per feature is the treatment total minus the control total.
- **Pass:** the mean difference is at least **1.0** point **and** an exact two-sided sign test (ties excluded) gives p ≤ **0.10**, with N ≥ 5.
- With N = 5, only a 5–0 result reaches p = 0.0625. This bar is deliberately strict, and it is written down now so it cannot be loosened later.
- **A null result is a result.** If the margin isn't met, the verdict goes in `docs/research/` and the thesis is revised (roadmap v2).

## Procedure

`lock` → `curate` → `prepare` → `run` → `blind --seed 20260930` → `judge` → `score`. Every step after `lock` checks the lock.
