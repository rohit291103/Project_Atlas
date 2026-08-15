# Extraction Quality Review — 2026-08-14 (Jira, first graded run)

**Validation set:** `SCRUM` (personal Atlassian Cloud site) — SCRUM-7, SCRUM-8, SCRUM-9, SCRUM-10 (seeded `maxdepth` epic), plus **SCRUM-1** (untouched Atlassian project-template content) as a restraint fixture. SCRUM-6 (the epic) is recorded as corpus only.

**Configuration:** per-issue extraction, no `known_nodes`, recorded fresh via `scripts/record_jira_golden.py`. This is deliberately *not* the configuration of the 2026-08-13 live run (which was scoped, with cross-source context) — see "Vs. last run".

**Read this first:** four of the five graded fixtures were **written by the build team**. The `writing-evals` skill is explicit that synthetic examples are cleaner than reality and inflate scores. A green run here means "extraction has not regressed against tickets we authored", not "extraction works on real Jira". SCRUM-1 is the only Jira content in this set that nobody wrote with extraction in mind, and it is the fixture that produced the most useful finding.

## Tier 1 — deterministic (`pytest tests/evals/`)

- **Schema validity:** pass. 27 nodes and 18 edges across five fixtures (24 nodes from the four feature tickets, 3 from the restraint fixture); all re-validate through the Pydantic gate.
- **Provenance verifiability:** pass, **28/28 source refs**, and under a stricter check than the GitHub half of the set uses. Excerpts are verified against the corpus of *the specific issue the ref names*, not a merged blob — see below.
- **Structural rubric:** pass, all five fixtures.

The provenance check was strengthened for Jira because Jira extraction routinely quotes an issue other than the one being ingested: both SCRUM-9 and SCRUM-10 pull background from the epic. Against a merged corpus, an excerpt lifted from SCRUM-6 but stamped with SCRUM-10's id and URL would pass — the text *is* "in the sources" somewhere. That is exactly the failure this product exists to prevent (a reviewer clicks a plausible link and lands on a page not containing the claim), so `misattributed_excerpts` checks per source and reports a ref to an unrecorded issue rather than skipping it.

Negative controls were run for every new check — re-stamping the three epic-sourced refs in SCRUM-10 onto SCRUM-10 is caught 3/3; the ceilings fire on both volume and confidence. A check that has never been made to fail is not evidence.

**No provenance defects. Every excerpt verbatim, every attribution correct, including the cross-issue ones.** The one non-negotiable held.

## Tier 2 — judgment, per fixture

### SCRUM-7 — "Ship a --maxdepth flag" (5 nodes)
- **Correctness:** pass. The flag requirement, the scope decision (replaces `.rgignore` for depth) and the *negative* boundary (does **not** replace it for path exclusion) are all captured and correctly typed.
- **Completeness:** nothing missed.
- **Note:** 2 of the 5 nodes are low-value. `goal: "Ship a --maxdepth flag"` restates the ticket title and duplicates the requirement; `problem` @0.6 asserts an inference ("limiting depth currently relies on a workaround") off an excerpt that only implies it.

### SCRUM-8 — the planted-conflict decision ticket (7 nodes)
- **Correctness:** pass, and the strongest result in the set. All six distinct source claims captured. `rejected_alternative` for GNU find semantics is a genuine judgment win — the ticket never uses the word "reject", it says "we are explicitly not matching GNU find here".
- **Completeness:** nothing missed.
- **Notes:** `constraint` for "consistency with a 1990s tool is worth less than user expectation" is a mild mistype — that is a principle/rationale, not a constraint on the system. And `goal` @0.6 is built from the *same excerpt* as the `decision` @0.9, restating it as an outcome.

### SCRUM-9 — "No regression when --maxdepth is not passed" (5 nodes)
- **Correctness:** pass. Notably it **split the compound sentence** ("depth must remain unlimited" AND "no measurable performance regression") into two requirements, which is the behaviour we want — a reviewer can confirm one and reject the other.
- **Completeness:** nothing missed. "A flag nobody passes must cost nothing" is a restatement of the regression requirement and is correctly not duplicated.

### SCRUM-10 — "Do we also need a --mindepth counterpart?" (7 nodes)
- **Correctness:** pass. Correctly typed as `open_question` rather than flattened into a requirement, with the user demand as `evidence` and the find-consistency argument as `constraint`.
- **Completeness:** nothing missed.
- **Note:** "a decision must be made before GA" is typed `requirement` — a process requirement rather than a product one. Defensible; flagging it as the kind of thing the type taxonomy does not currently distinguish.

### SCRUM-1 — the restraint fixture (3 nodes)
Onboarding marketing copy with no product claim about any feature Atlas would spec. Extraction produced **3 nodes, all at 0.6, all with verbatim correctly-attributed excerpts** — and all restating onboarding tips as product requirements ("Users should be able to import existing work from a CSV").

Nothing is fabricated. But **extraction has no notion of "this ticket contains no feature claims"** — it will always find something. On a real backlog full of chores, stubs and template issues, a PM would get cards like these for every one of them and would have to reject them individually. The mitigation is the confidence signal, not suppression.

## Confidence calibration

**The clearest positive finding of this run.** The 0.9/0.6 split tracks claim quality closely and consistently:

| | 0.9 | 0.6 |
|---|---|---|
| Claims stated outright in the source | 19 | 0 |
| Inferences, restatements, paraphrase-plus-inference | 0 | 5 |
| Everything on the content-free template ticket | 0 | 3 |

Only two values were ever emitted across all 27 nodes — there is no middle. Whether that is calibration or a two-way switch is not answerable at this sample size; what is checkable is that the switch lands on the right side every time here.

No prompt instructs this distinction. Because it is real and load-bearing, it is now pinned deterministically: `jira-SCRUM-1/rubric.yaml` carries `max_confidence: 0.6`, so a prompt change that flattens confidence into uniform 0.9 fails a test rather than silently making every card look equally trustworthy. That is a Tier-2 observation promoted into Tier 1, which is the direction `writing-evals` asks for.

## The one real quality issue: goal/requirement duplication

In **three of four** feature tickets, the agent emitted a `goal` carrying the same claim as a `requirement` or `decision` it had already emitted — in SCRUM-8, off the *identical excerpt*. This is the "is 17 nodes from 4 short tickets richness or noise" question left open on 2026-08-13, and the answer is **partly noise**.

It matters more than it looks. A duplicate pair means a PM confirms the same claim twice, and can confirm one while rejecting the other, leaving the scope self-contradictory. Highest-leverage next fix: instruct the agent that a claim already emitted as a `requirement` or `decision` must not be re-emitted as a `goal` from the same excerpt. That is a prompt change, so it needs a re-record and a re-read of the diff.

## Vs. last run (2026-08-13 live run)

**Not directly comparable, and the difference is configuration, not quality.** The live run was scoped with `known_nodes` from the GitHub side and produced 17 nodes across SCRUM-7..10 plus 5 cross-source conflicts. This run is per-issue with no context and produced 24 nodes for the same four tickets. The gap is almost entirely the epic background being re-extracted independently for SCRUM-9 and SCRUM-10, which `known_nodes` suppresses in a real scoped run. **24 vs 17 is not a regression.**

Consistency across the two runs is good: every claim graded above appears in both. No previously-passing behaviour regressed.

## Verdict

Phase 0's exit criterion was met on GitHub in July and is not what is being tested here. For **Phase 1's second source**, extraction quality on Jira is now evidenced rather than asserted: Tier 1 is automated and re-runnable with no API key, Tier 2 is recorded, and both tiers have negative controls.

What is still **not** settled, stated plainly:

1. **The sample is mostly self-authored.** One genuinely untouched fixture is not enough. The honest next step is graded fixtures from a real Jira project with real tickets — which nobody on this project has yet.
2. **Cross-source conflict quality has no Tier-1 coverage.** The five conflicts from 2026-08-13 were judged by eye and never re-recorded as a graded fixture. That is the most valuable behaviour in the product and the least tested.
3. **Single-fixture over-extraction ceiling.** Only SCRUM-1 has one. Ceilings on the feature fixtures would need a defensible number, and there is not enough data to pick one.

Single highest-leverage next fix: the goal/requirement duplication prompt change (§ above).
