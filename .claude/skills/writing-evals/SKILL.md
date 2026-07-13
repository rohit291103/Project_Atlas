---
name: writing-evals
description: Best practices for designing, running, and maintaining evals for any LLM-generated output in Project Atlas (the extraction agent now; the Q&A retrieval layer in Phase 3). Use before adding a new LLM-call code path, whenever extraction/agent.py, extraction/prompts.py, or extraction/tools.py changes, and whenever someone asks "how do we know this is actually working."
---

# writing-evals

Root `CLAUDE.md`'s Engineering Philosophy calls extraction "a draft, never a fact." Evals are how you find out, on every change, whether that draft is trending more or less trustworthy — as opposed to just discovering it later when a pilot user hits a bad output. This skill is methodology; the `extraction-quality-review` skill is where it actually gets run against Atlas's standing validation set.

Evals are not the same discipline as `tdd`. `tdd` covers code you can assert exact behavior for (schema validation, event writes, projection replay). LLM output isn't exact-match-testable — but that's not license to skip verification, it's a reason to be more deliberate about *what kind* of check each claim needs.

## Deterministic vs. judgment checks — split every eval into two tiers

**Deterministic (plain assertions, cheap, run on every extraction-pipeline change):**
- Schema validity — re-run against real agent output, not just hand-built fixtures (that's `tdd`'s job; this is the same check applied to the messier real thing).
- **Provenance verifiability** — a `SourceRef.excerpt` must appear as a substring (or whitespace-tolerant near-match) somewhere in the actual raw source text that was fetched. This is fully automatable and should never require a judge: a Node whose excerpt can't be found in the source is a bug, full stop, not a borderline case.
- Structural rubric checks — hand-authored per-fixture expectations like "this PR must yield at least one Node of type `decision` mentioning the chosen approach." Not full expected-output equality (too brittle against LLM phrasing variance) — a minimal, explicit rubric per golden example instead.

**Judgment-based (need a human, or an LLM-as-judge with real caveats, expensive, run less often):**
- Content correctness — does the Node's text accurately represent what the source claims, not just quote it?
- Completeness — did the agent miss something a human reviewer would have caught?
- Confidence calibration — are high-confidence Nodes actually more reliable than low-confidence ones in practice?

Push as much as possible into the deterministic tier over time. A judgment check that can be turned into an explicit rubric check is worth the one-time cost of writing that rubric — it's the difference between an eval that runs in CI-style discipline and one that only happens when someone remembers to eyeball it.

## Golden dataset rules

- Use real historical PRs — the same fixed validation set `extraction-quality-review` maintains — not synthetic/invented examples. Synthetic examples tend to be cleaner than reality and quietly inflate scores.
- Version the golden set's expectations alongside the prompt/agent code being evaluated. A prompt change and a rubric change should be reviewed together in the same diff, not drift independently.
- Never quietly drop a fixture that starts failing to make the pass rate look better. If a fixture turns out to be genuinely wrong or ambiguous, fix the rubric explicitly and record why (via `docs-sync`) — don't just delete it and move on.

## LLM-as-judge, if one gets used

- Prefer a differently-prompted or stronger model as judge than the one being evaluated, to reduce self-preference bias.
- Anchor the judge periodically against a small human-labeled subset. If the judge's verdicts drift from human judgment on that subset, trust the humans and recalibrate the judge prompt — not the other way around.
- Never let a judge's verdict silently gate anything (e.g. an auto-pass in CI) without a human seeing the disagreements. Same "draft, never a fact" principle, one level up.

## Statistical honesty at small N

Phase 0's validation set is 3–5 PRs. That is not enough to report a percentage and mean it. Treat every eval run at this scale as **qualitative signal** — read the actual failures, don't compute a pass rate and stop there. Don't let a "4/5 passed" framing imply more rigor than the sample size supports. The real statistical signal arrives in Phase 3 (TRD §5.3: confirmed-without-edit rate tracked over real usage) — evals before then are a smoke test, not a metric to optimize.

## Cost asymmetry

A false negative (missed extractable element) and a false positive (hallucinated or unprovenanced claim) are not equally bad — per the Engineering Philosophy, provenance is the one non-negotiable. Weight eval failures accordingly: a single fabricated excerpt is a blocker regardless of how well everything else scored; a missed element is a quality note, not a blocker.

## Before adding any new LLM-call code path

Ask: what's the deterministic-checkable subset of "correct" for this output, and what genuinely needs judgment? If the answer is "we can't check anything deterministically," that's usually a sign the output needs a stricter schema/contract, not that evals are impossible here.

## Where this connects

- `tdd` skill — deterministic unit tests for the schema/storage code itself, independent of what the LLM produces.
- `extraction-quality-review` skill — the Atlas-specific workflow that runs both tiers against the standing validation set and records results.
- `backend-reviewer` agent — flags an LLM-call code path added without any corresponding eval coverage.
