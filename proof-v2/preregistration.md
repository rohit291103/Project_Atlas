# Proof v2 pre-registration: does an Atlas spec help when context is scattered?

**Status: DRAFT, not locked.** Written 2026-10-03, after the null result in `docs/research/phase2b-proof-ripgrep-v1.md`. **Nothing here has been run.** Before locking, the features (§3) and the decisions marked **DECIDE** must be filled in. The harness then hashes this file exactly as it hashed v1 (`uv run python -m scripts.proof --root proof-v2 lock`), and the file is not edited afterwards.

## 1. Why a second proof, and what it changes

v1 asked whether a spec helps on single, well-written PRs. It didn't (mean difference 0.00, 1 win, 1 loss, 3 ties). The controls averaged 8.2/10, and each spec compressed the one artifact the control had already read. v2 tests the narrower thesis the v1 write-up proposed:

> **When the decisions behind a feature are spread across more than one system, and at least two of those sources disagree, a coding agent given the Atlas spec builds something closer to what was actually decided than the same agent given every raw artifact.**

The changes from v1 are each aimed at a named weakness of v1:

| v1 weakness | v2 change |
|---|---|
| One artifact per feature: the spec only restated the control's input | **Inclusion criteria (§3):** ≥ 2 systems and ≥ 1 real disagreement per feature |
| Claims curated by Claude, not a person | **A person on the design partner's team confirms the claims**, through the product, as a real reviewer would. The spec is the product's own export of what they confirmed. |
| A Claude judge only | Claude judge, **plus a blinded human spot check** of a pre-set sample (§6) |
| Ceiling: controls averaged 8.2/10 | A rubric criterion that rewards following the decision **actually taken** where sources disagree. That's where a raw-artifact control has to guess. |
| N = 5: only a 5–0 sweep could pass | **N = 8**, so a 7–1 result passes (p = 0.070). |
| Turn use observed but not pre-registered | **Turns used is a pre-registered secondary outcome** |

## 2. Question

On real features whose outcome is known, and whose decisions are spread across ≥ 2 systems with ≥ 1 disagreement, does a coding agent given the **Atlas spec** (claims confirmed by a person) produce output closer to what was built than the same agent given **all the raw artifacts**?

## 3. Features (N = 8): inclusion criteria, fixed before any are picked

A feature is eligible only if **all** of these hold. Each is checked and written down before any agent runs:

1. It was **merged**, and the merged change is identifiable as one diff from a parent commit (as in v1).
2. Its decisions are recorded in **at least two systems**: for example a ticket and a PR, or a design doc and a PR.
3. At least **one disagreement** exists between those sources: one source says X, a later source decided not-X. **The merged code settles which side won**, and that is what the rubric's `conflict` criterion scores.
4. The merged change is **≤ 600 changed lines**. v1's 1,355-line feature couldn't fit in 40 turns under either condition.
5. The design partner agrees to its use, and **no source artifact was written for this test**.

Features (fill in, then lock): **DECIDE**, with a design partner.

| Name | Sources | The disagreement | Merged diff size | base → merged |
|---|---|---|---|---|
| | | | | |

The only candidate in the existing golden set is `pr-111` with `cross-SCRUM-8` (the `--maxdepth` dispute). One example isn't enough on its own, and its Jira half was written by the team, so it fails criterion 5.

## 4. Conditions

- **Control:** every raw artifact for the feature: ticket text and comments, PR title, body and comments, doc text. Commits are never included, since they're the answer. Artifacts are given **in chronological order**, so the control has the same chance as the spec to see which decision came last.
- **Treatment:** the Atlas spec Markdown, exported by the product from claims **confirmed by the design partner's reviewer**, including the readiness score, gaps and open disagreements. As in v1, an effect can't be attributed to any one of those parts.
- **Held constant (unchanged from v1):**
  - the same task text;
  - the same `base_sha`;
  - `claude-sonnet-5`;
  - `Read`/`Glob`/`Grep`/`Edit`/`Write` only, inside the checkout;
  - a 40-turn cap;
  - one run per condition per feature;
  - the retry rule for infrastructure errors (v1 deviations #4 and #5).

## 5. Rubric (0–12)

v1's four criteria are kept, so the two runs can be compared, plus one new criterion:

| Criterion | Scale | Question |
|---|---|---|
| behaviour | 0–4 | As v1 |
| decisions | 0–2 | As v1 |
| scope | 0–2 | As v1 |
| compiles | 0–2 | As v1 |
| **conflict** | 0–2 | **Where the sources disagreed, does the output follow the side the merged change took?** 0 = took the losing side, 1 = unclear or both, 2 = took the winning side |

The judge is given the merged diff and a one-line statement of each disagreement, **written from the merged code** before any agent runs. The judge isn't told which side either condition saw emphasised.

## 6. Grading

- **Primary:** a blind Claude judge (`claude-opus-5`, v1's `JUDGE_PROMPT` plus the `conflict` criterion), one call per packet.
- **Spot check:** a person outside the build team grades **4 packets**, chosen by the seed before grading, blind to condition. **DECIDE: who.** If the human and judge totals differ by more than **2 points on 2 or more of the 4**, the judge result is reported as unreliable, and the verdict rests on the human grades of those packets alone. That's why the threshold is fixed now.

## 7. Analysis (fixed now)

- **Primary:** paired difference (treatment − control) on the 0–12 total.
- **Pass:** mean difference **≥ 1.0** *and* an exact two-sided sign test (ties excluded) with **p ≤ 0.10**, at N = 8.
- **Secondary, pre-registered** (reported whether or not the primary passes, never used to rescue it):
  - the `conflict` criterion on its own;
  - the number of sessions that hit the turn cap in each condition;
  - turns used per session.
- **A null result is a result again.** If v2 is also null, the claim that a spec improves agent output is dropped from the product's argument altogether. What remains is the review tooling Phase 1 measures.

## 8. Harness work needed before this can run

- `scripts/proof.py prepare` builds the control from `raw.json` with a PR and its linked issues. It has to accept a feature with **several artifacts across sources, in chronological order**.
- The treatment comes from a **product export** (`/products/{id}/spec`) of the partner's confirmed claims, not from `curate`/`build_spec`. Add a step that copies the exported spec into `proof-v2/specs/<name>.md`, with the export's timestamp.
- Add the `conflict` criterion and the per-feature disagreement statement to the judge's input.
- Seeded selection of the 4 packets for the human spot check, and a sheet for the human grades.
- Record turns used per session in `meta.json`. v1 recorded only whether the cap was hit.

None of this is built yet. It's worth building only once features that pass §3 exist.
