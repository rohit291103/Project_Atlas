# Extraction Quality Review — 2026-07-28

**Validation set:** `BurntSushi/ripgrep`, PRs #111, #723, #706, #3472 (the standing golden set).
**Run context:** First live extraction run of the Phase 0 agent, executed on the **Claude Pro subscription** (Claude Agent SDK → Claude Code CLI login, no `ANTHROPIC_API_KEY`, model `claude-opus-4-8`). This run also fixed a live-only bug (the `can_use_tool` gate requires streaming-input mode; see `docs/decisions`/tracker) — so it is both the first quality run *and* the first proof the safety gate engages in practice. Recorded outputs: `tests/evals/golden_set/pr-<n>/extraction.json`.

## Tier 1 — deterministic (`pytest tests/evals/`)

- **Schema validity:** pass — all 4 PRs re-validate through the Pydantic gate.
- **Provenance verifiability:** **pass — zero fabricated/unprovenanced excerpts across all 4 PRs.** Every `SourceRef.excerpt` is found (whitespace-tolerant) in the actual fetched corpus. This is the load-bearing check; it is clean.
- **Structural rubric:** pass per fixture (all `required_node_types` + `must_mention` floors met).

All 12 previously-skipped extraction-dependent checks are now green (28/28 in `test_golden_set.py`).

## Tier 2 — judgment, per PR

Node counts: #3472 → 5, #706 → 9, #111 → 10, #723 → 11.

### PR #3472 — "ignore: add incremental checking" (thinnest fixture, body-only)
- **Correctness:** pass. goal / requirement / problem / architecture_note / evidence, each accurately typed and verbatim-sourced. The file-watcher rationale correctly typed as `problem`; the "reuses existing gitignore logic" note correctly `architecture_note`.
- **Completeness:** complete for what the connector captured. (The design edge-case debate lives in *review* comments, which the Phase 0 connector does not fetch — a known scope limit, not a miss.)

### PR #111 — "Max depth option" (rich thread; forces `fetch_linked_issue`)
- **Correctness:** pass. Followed the `Closes #109` link, extracted the originating problem (`.rgignore` inconvenient) and goal from the issue, the GNU-find consistency decision, the docs-wording decision, the integration-test requirement, and the GNU-find `evidence`. All correctly typed.
- **Completeness:** good. Minor miss: the "off-by-one" resolution (maintainer initially thought the impl wrong, then confirmed the original was correct) wasn't captured as its own node.
- **Notes:** (a) slight redundancy — two `goal` nodes for the same feature, one from the PR title and one from the issue phrasing (distinctly sourced, edge-linked; acceptable). (b) Extracted the transient "CI failure was unrelated" chatter as `evidence` (0.6) — accurate but ephemeral; borderline noise.

### PR #706 — "Support ignore files with custom names" (**standout**)
- **Correctness:** pass, and notably sophisticated. The source *contradicts itself*: the PR body asserts "`.ignore` … has the highest precedence," but the discussion reverses it (custom ignore files rank higher). The agent:
  - gave the body's superseded claim **0.6** confidence and hedged the content with "(per the PR description)",
  - captured the corrected final behavior at 0.9,
  - and wired a **`conflicts_with` edge** between the two — explicitly modeling the contradiction rather than silently picking one.
  This is exactly the provenance-honest, nuance-preserving behavior the product exists to produce.
- **Completeness:** good. The cross-repo `sharkdp/fd#156` reference is out of the repo-scoped tools' reach (expected).

### PR #723 — "fixed width line number display" (widest vocabulary)
- **Correctness:** pass. Exercised goal / `constraint` (the `format!`-macro padding-char limitation — a real technical constraint) / architecture_note / `rejected_alternative` / decision / requirement / open_question. The rejected "arbitrary padding char via `format!`" approach is captured as `rejected_alternative` with a **`rejects`** edge from the "start with spaces" decision.
- **Completeness:** good — and it *correctly skipped* the ephemeral commit-message-noise chatter at the end of the thread (contrast with #111's CI-noise node).

## Confidence calibration

**This is the strongest positive signal of the run.** Across all 4 PRs, confidence tracks reliability in the right direction, without being told to per-PR:
- Direct assertions from PR body / maintainer decisions → **0.9**.
- Suggestions, open questions, "already-holds" nuances, and content inferred from a *question* rather than a statement → **0.6**.
- The weakest edges (a tentative "not important" suggestion; a loose `walkdir` inference) → **0.3**.
The superseded/contested claim in #706 landing at 0.6 (not 0.9) is the clearest evidence the mapping is meaningful, not decorative.

## Vs. last run

First run — no prior baseline. This file *is* the baseline future runs compare against.

## Verdict

**Phase 0's exit criterion is met on both the Tier-1 (deterministic) and Tier-2 (manual judgment) axes:** usable, mostly-correct, fully-provenanced structured output on 4 real historical PRs, validated manually. No blockers. At N=4 this is qualitative signal, not a pass rate.

Highest-leverage next improvements (all *polish*, none blocking):
1. **Ephemeral-noise threshold** — the agent is inconsistent about transient CI/commit chatter (#111 extracted it, #723 didn't). A prompt nudge to prefer durable knowledge over thread-logistics would tighten output. Lowest-risk, highest-signal tweak.
2. **Review-comment connector gap** (already logged) — the biggest *content* limiter is that inline review comments aren't fetched; #3472's real design debate is invisible. Worth a connector-enhancement decision if richer design context is wanted.
3. **Minor same-feature `goal` redundancy** (#111) — could collapse duplicate goals sourced from linked issue vs PR, or leave it (they're edge-linked and separately provenanced).

Any prompt change made in response to (1)/(2) must be re-graded against this same golden set (that's what this file is for) and must not regress the #706 conflict-modeling or the calibration behavior — both are load-bearing wins to protect.
