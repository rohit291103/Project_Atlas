---
name: diagnosing-bugs
description: Disciplined reproduce-minimize-hypothesize-instrument-fix-test debugging loop, with hallucinated/unprovenanced extraction bugs (wrong Node content, missing or fabricated SourceRef, silently-resolved conflicts) treated as highest severity. Use proactively whenever investigating a reported bug, an unexpected extraction result, or a test failure — before jumping to a fix.
---

# diagnosing-bugs

Guessing at a fix before understanding the failure wastes more time than it saves, and in Project Atlas a guessed "fix" to extraction output is worse than a slow correct one — root `CLAUDE.md` names provenance and schema validation the project's non-negotiable core. This skill is the loop to run before editing code in response to a bug report.

Check `docs/tracker.md` (via the `tracker-sync` skill) before diagnosing — if the affected module is marked "Next up" rather than "Done," the bug may simply be that the code doesn't exist yet, not a logic error.

## Severity triage first

Before debugging mechanics, classify the bug:

- **Critical** — extraction produces a Node without a valid `SourceRef` (or with a fabricated/paraphrased one presented as a literal excerpt), a Node's content doesn't match what the source actually says, a real conflict between sources gets silently resolved instead of surfaced, or an agent tool call performs (or could perform) a write against a source system. These are silent-failure-prone — the output still "looks" plausible. Stop and fix before doing anything else.
- **Important** — extraction runs but produces poorly-calibrated confidence, misses an extractable element it should have caught, or CLI/review output misrepresents correct underlying data (e.g. a correct Node rendered under the wrong type).
- **Minor** — cosmetic, no data/provenance/logic implication.

## The loop

1. **Reproduce** — get a minimal, deterministic repro before touching code. For extraction bugs: the exact source input (which PR/issue/commit, which repo) and the exact expected vs. actual Node/Edge output. If it's not reproducible, that itself is the finding — don't fix what you can't observe. Recorded API fixtures (per `docs/Phase0_Architecture.md`'s test strategy) make this a replay, not a live re-fetch.
2. **Minimize** — strip the repro to the smallest input that still triggers it. For extraction, this usually means isolating one PR/comment/linked-issue rather than a full multi-source ingestion run.
3. **Hypothesize** — state a specific, falsifiable cause before reading further code ("the agent is quoting a paraphrase instead of the literal PR text into the excerpt field"), not "extraction is off."
4. **Instrument** — add the minimum logging/assertions to confirm or kill the hypothesis. Prefer reading values at module boundaries (raw content in, `Node`/`Edge` out of `extraction/`; event in, projection out of `storage/`) over scattering prints everywhere. The agent's per-tool-call log (required by the Engineering Philosophy's audit trail) is often the fastest way to see what happened.
5. **Fix** — the smallest change that addresses the confirmed root cause. Don't bundle unrelated cleanup into a bug-fix commit.
6. **Test** — for any Critical-tier bug, the fix isn't done until there's a regression test pinning the previously-wrong case to the correct value (see the `tdd` skill). A provenance or schema-validation bug fixed without a test is the same bug waiting to come back.

## Anti-patterns to avoid

- Patching symptoms in the CLI/review-output layer when the root cause is in extraction or storage — presentation code must never become a workaround for incorrect upstream data (Engineering Philosophy: "provenance is non-negotiable").
- Declaring a fix done because the one reported case now works, without checking adjacent cases (a different PR shape, an issue with no linked commits, a conflicting-sources scenario).
- Loosening schema validation to make an error go away, instead of fixing why the agent produced invalid output. Malformed output should retry once, then surface as an ingestion error (TRD §5.1) — it should never be silently coerced into something schema-valid.
