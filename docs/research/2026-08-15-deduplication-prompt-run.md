# De-duplication prompt change: what it fixed, and what it cost

**Date:** 2026-08-15
**Answers:** the highest-leverage finding from `docs/research/2026-08-14-jira-extraction-quality-run.md` — goal/requirement duplication in three of four Jira tickets.
**Method:** `writing-evals` (Tier 1 deterministic + a read of the recorded diff), then `extraction-quality-review` against the golden set.

---

## 1. The defect

The 2026-08-14 run found the agent emitting a `goal` that restated a `requirement` or `decision` it had **already emitted** — in three of four graded Jira tickets, and once off the **byte-identical excerpt**.

Why this matters more than it sounds: a reviewer is asked to rule twice on one idea. Nothing stops them confirming one copy and rejecting the other, which leaves the feature holding two contradictory answers *citing the same sentence*. That is worse than a missed claim, because it looks like corroboration.

---

## 2. The change

Two edits to the **shared** system prompt (`extraction/prompts.py`) — shared because the defect is a property of the extraction task, not of Jira:

1. **A sharper type distinction.** `goal` is now "the outcome the work is meant to achieve — *why* it is being done"; `requirement` is "something the solution must do — *what* it must do". The originals ("an intended outcome or objective" / "something the solution must do") did not tell the two apart for a sentence that states both.
2. **A new rule 5, "ONE CLAIM, ONE NODE."** States the prohibition, names the specific failure (`a goal that restates a requirement or decision you have already emitted is a duplicate, not a second claim`), and says the consequence (`it forces a reviewer to rule twice on one idea`).

### The cost: the Phase 0 prompt baseline moved

`tests/test_jira_extraction.py` froze the GitHub system prompt byte-for-byte against the version Phase 0's evals validated. That guard now describes a different string, and **the honest response was to move the baseline and move the evidence with it**, not to exempt the change. Exempting it would have made the guard decorative — its whole job is to fail when the prompt drifts from the version the recorded evidence describes.

So the golden set was re-recorded in the same change, and this document is the evidence that moved with it.

---

## 3. A deterministic check the finding earned

`duplicate_claims()` in `tests/evals/test_golden_set.py`: **no two Nodes may cite the identical excerpt.** Applied to both the PR and Jira halves of the golden set.

It grades only the deterministic half of the finding. Restating *in different words* is real duplication too and is deliberately **not** checked here — it needs judgement, and a checker guessing at paraphrase would be grading its own similarity threshold rather than the extraction. That stays Tier 2.

A fixture may opt out with `allow_shared_excerpts: true` when one long quote genuinely carries two different claims. None currently does.

**It is a check that can fail:** run against the *pre-change* recording, it fails on `jira-SCRUM-7` with

> `2 nodes (decision, problem) cite the same excerpt: 'This replaces the .rgignore workaround for the depth use case.'`

---

## 4. Results after re-recording

Re-recorded live via `scripts/record_jira_golden.py` and read as a diff, per the script's own instruction.

| Fixture | Nodes | Type mix |
|---|---|---|
| `jira-SCRUM-7` | 6 | requirement, decision, constraint, goal, problem, open_question |
| `jira-SCRUM-8` | 7 | decision, requirement ×2, rejected_alternative, goal ×2, problem |
| `jira-SCRUM-9` | 5 | goal, problem, requirement ×2, constraint |
| `jira-SCRUM-10` | 6 | open_question, evidence, requirement, architecture_note, goal, problem |
| `jira-SCRUM-1` | 3 | requirement ×2, goal *(unchanged — the content-free restraint fixture)* |

- **Zero shared excerpts** across every graded fixture. The duplication check passes on all of them.
- **Every rubric floor and ceiling still met**, including `jira-SCRUM-1`'s `max_nodes` / `max_confidence` ceilings — the change did not buy de-duplication by making the agent more talkative elsewhere.
- **Provenance: unchanged and still per-issue.** No excerpt is attributed to an issue it does not appear in.
- **Read of the `SCRUM-7` diff** (the fixture that carried the identical-excerpt defect): the `decision` and `problem` that shared a sentence are now one `decision`; the `goal` that remains is genuinely distinct — it is about engineers in large monorepos, where the `requirement` is about the flag itself.

---

## 5. Cross-source conflicts now have Tier-1 coverage

The 2026-08-14 review's second finding: *cross-source `conflicts_with` is the most valuable behaviour in the product and the least tested* — the five conflicts found live on 2026-08-13 were judged by eye and never recorded, so a prompt change that quietly stopped finding them would have passed every test. **This change was exactly such a prompt change**, which made the gap urgent rather than theoretical.

`golden_set/cross-SCRUM-8/` closes it. It holds three files rather than two: `known.json` is the claims the *other* source already produced — read from `pr-111/extraction.json`, i.e. **real recorded agent output**, because a hand-built set would let the fixture pose a conflict the live path would never see. The pairing is not arbitrary: ripgrep PR #111 ("Max depth option") and the seeded SCRUM epic describe the same feature.

**Recorded result: 4 nodes, 5 edges, 3 of them `conflicts_with` pointing at a GitHub claim, all at 0.9 and all genuine.**

| Jira (SCRUM-8) says | GitHub (PR #111) says |
|---|---|
| `--maxdepth` counts from the user's **current working directory** | max depth semantics should be **consistent with GNU find** |
| `--maxdepth 0` must still return matches in the current directory | GNU find descends *at most* N levels, with 0 meaning the starting points only |
| Docs must say "current directory" throughout | Docs should say "starting points", as find does |

Four checks grade it: the fixture is well-formed; the new claims still quote **their own** issue; **no edge endpoint was ever fabricated** (checked here as well as at the gate, because a fabricated relationship is indistinguishable from a real one once stored); and at least `min_cross_source_conflicts` are found.

**The floor is 2, below the observed 3, deliberately.** A floor set at the observed number grades this sample rather than the behaviour, and would fail a run that found two genuine conflicts instead of three. What must not happen is finding none. Verified as a check that can fail: raised to 9, it fails as expected.

---

## 6. Still open

- **Four of five Jira fixtures were authored by the build team.** Unchanged by this work, and `writing-evals` is explicit that synthetic examples inflate scores. Not fixable with more code — it needs a real Jira project.
- **Semantic duplication is ungraded.** Only identical-excerpt duplication is deterministic. The next Tier-2 pass should look for it specifically, now that the obvious form is gone.
- **N is still small.** Five Jira fixtures, four PRs, one cross-source pairing. This is a smoke test, not a pass rate.
