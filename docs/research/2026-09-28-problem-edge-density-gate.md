# Problem-edge density: the gate for unaddressed-problem detection

**Date:** 2026-09-28
**Gate (roadmap v2, Phase 3 `[+2026-09-02]`):** before building unaddressed-problem detection, confirm that extraction emits `supports` and `implements` edges at a useful density. If it doesn't, "this is an extraction problem first and a feature second."

## Method

The recorded `extraction.json` of every golden-set fixture in `tests/evals/golden_set/` was counted. There are 10 fixtures with a recorded extraction; `jira-SCRUM-6` is corpus-only. For each `supports` or `implements` edge, the node types at both ends were tabulated.

## Result: the gate fails

- There are **7 `problem` nodes** across 7 fixtures, and **5 `evidence` nodes**.
- **`evidence —supports→ problem`: 0.** Evidence supports goals, open questions and architecture notes, never a problem.
- **`requirement|decision —implements→ problem`: 0.** Every `implements` edge targets a `goal` (6) or a `decision` (3).
- The only edge into a problem is `decision —supports→ problem`, which occurs once.

| from | relation | to | count |
|---|---|---|---|
| requirement | implements | goal | 2 |
| decision | implements | goal | 2 |
| architecture_note | implements | decision | 2 |
| architecture_note | supports | decision | 2 |
| decision | supports | problem | 1 |
| everything else | supports/implements | not a problem | 1 each |

Built on today's extraction, the detector would report **every** problem as unaddressed. That output would look structural while carrying no information.

## What would fix it (not done)

The fix is in extraction, not in a new feature. `prompts.py` lists the edge types but says nothing about which node types each connects. It would need to say that evidence `supports` the problem it evidences, and that a requirement or decision `implements` the problem it addresses (as well as the goal). That is a prompt change, so it carries the `writing-evals` and `extraction-quality-review` obligations: re-record the golden set with live model calls, then re-grade Tier-1 and Tier-2. Only after that is this gate re-measured.

**Decision:** unaddressed-problem detection stays unbuilt, and it is not a gap in Phase 3 construction. Its precondition is unmet, and the roadmap anticipated exactly this outcome.
