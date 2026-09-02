# MVP Roadmap v2 — Context-to-Spec Engine

**Status:** **Ratified 2026-08-18** by the user. Decision entry: `docs/decisions/2026-08-18-roadmap-v2-spec-export-and-proof.md`. `CLAUDE.md`'s phase table and Current Development Phase section updated to match.
**Date:** 2026-08-18
**Supersedes:** `docs/prd/MVP_Roadmap.md` (v1, retained unchanged — the original sequencing is part of the record)
**Phase numbering is unchanged (0–4).** Only the *contents* of Phases 2 and 3 move, so every existing decision doc that cites a phase number stays correct.

---

> **Amended 2026-09-02.** Four features were added to Phases 2–4 — readiness score,
> evidence density, unaddressed-problem detection, comment threads — plus a transcript
> eval attached to Phase 3's third source. They are marked **[+2026-09-02]** where they
> appear. **No exit criterion changed, no phase boundary moved, and nothing was removed**,
> so this is an amendment rather than a v3. Origin and the rejected alternatives:
> `docs/decisions/2026-09-02-product-decision-engine-scope-assessment.md`.

## Why this revision exists

v1 was sequenced to de-risk extraction quality before breadth, and that worked — Phase 0 and Phase 1 both retired their stated risk. But four defects have surfaced that v1 cannot absorb by editing a line:

**1. The value unit lands too late.** The original external critique that shaped this project named the atomic unit of value as *ingest → generate a spec → show provenance → approve it → hand it to the coding agent*. v1 scheduled that for Phase 2, weeks 10–13. Five real weeks in, with Phase 1 construction complete, `find src -iname "*spec*"` returns nothing. The loop currently ends at *"a human confirmed some claims"* — the middle of the value chain, not the end. A PM who completes the Phase 1 exit criterion walks away with rows in a database.

**2. The thesis is currently unfalsifiable.** PRD §6's third metric — *"coding agent output quality with spec vs. without"* — is the only evidence that Atlas is not a nicer wiki. It cannot be measured until spec export exists. We have spent five weeks unable to test our own core claim.

**3. Phase 2 bundled two unrelated risks.** v1's Phase 2 was spec export **plus a third source (Notion/Google Docs)**. Adding a doc source retires *"does breadth help?"*. It contributes nothing to *"does the spec improve agent output?"* and delays it. These separate.

**4. The proof was designed as an opinion poll.** v1's Phase 2 exit criterion: *"a design-partner team ... **reports whether** output quality improved vs. their normal workflow."* Self-reported, n=1, no baseline, no blinding, no rubric — to validate the single most important claim in the product. This is a lower evidentiary bar than we already hold *extraction* to, where `tests/evals/` grades against a golden set with pre-registered Tier-1/Tier-2 checks. The proof must meet the standard the rest of the project already meets.

**A fifth item is a defect, not a sequencing question, and it gates the metrics below.** `Event.actor` is a single free-text string (`schema.py:500`) with nothing separating a person from an automated agent. On 2026-08-16 the browser suite confirmed 6 real claims as `Rohit` that no human ruled on, irreversibly. Every metric that reads confirmation data is unsound until this is fixed — see Phase 1 close-out.

---

## A note on weeks

v1's week numbers no longer describe reality. Nominal Phases 0–1 budgeted 9 weeks; actual elapsed from first commit (2026-07-13) to Phase 1 construction complete (2026-08-16) is **5 weeks** — roughly 1.8× nominal pace.

**v2 drops week ranges as commitments.** Phases are gated by evidence, not calendar. Estimates are given as rough ranges and are explicitly not deadlines. A phase ends when its exit criterion is met and not before, and a phase that meets its criterion early ends early.

**Guiding principle (sharpened from v1).** v1: *"every phase must end with something a real team can use."* v2: **every phase must end with evidence about a claim, not with software.** Working software that produces no evidence does not close a phase.

---

## Phase 1 close-out — finish what is open

Not a new phase. Phase 1 *construction* is complete; the exit criterion is not met, because it was never a construction criterion.

**Open (both need a person, not a commit):**
- **Frontend review by the user** — the whole UI, landing through conflicts, dark and light.
- **The PM measurement** — a PM outside the build team, unassisted, under 20 minutes. *This is the exit criterion.* Blocked only on the PM's exact name, so workspace membership can be seated under the string they will type at sign-in.

**One engineering item, added here rather than deferred — actor provenance.** It belongs before the PM measurement, not after, for a specific reason: that session produces the first real confirmation data, and every metric in v2 reads confirmation data. Two parts:
- `Event.actor` gains an actor *kind* distinguishing human from automated, enforced at the schema boundary. A confirmation currently carries less provenance than a claim does, in a product whose pitch is provenance.
- The browser suite gets its own workspace. The tracker already names this as the real fix; until it lands, the two mutating tests stay excluded.

Per the `tdd` skill this is event-log/schema logic, so it is mandatory test-first.

**Nothing was added to this phase in the 2026-09-02 amendment, deliberately.** Placement
was considered for evidence density, which is small enough to land here. It was put in 2A
instead: Phase 1 construction closed 2026-08-25 and everything still open needs a person,
so any commit landing here moves the measurement further out — and the measurement *is*
the bottleneck. Reopening construction is the failure this phase has already been through
once.

**Exit criterion (unchanged from v1):** a PM outside the build team can, unassisted, connect two sources, review extracted elements, and confirm/reject them in under 20 minutes.

---

## Phase 2 (revised) — Spec Export & The Proof

**Risk retired:** does a generated spec actually improve what a coding agent produces?

This is the thesis. It is one phase, not two, because the export exists in order to be measured — shipping the export and declaring victory is exactly the failure v1 permitted.

### 2A — Spec Export v0 (narrowed to the smallest thing that closes the loop)

**In scope:**
- Assemble **confirmed** nodes into a structured spec: Context/Why, Requirements, Constraints, Architecture Notes, Open Questions.
- **Markdown export** with inline provenance links back to source artifacts.
- **Conflicts must be visible in the spec, never silently resolved.** An unresolved `conflicts_with` between two confirmed claims appears in the output as an open disagreement. This is a hard requirement, not a nicety — silently picking a side is the exact failure mode Philosophy §2 and PRD R8 exist to prevent, and it is where the product is most differentiated.
- Nothing unconfirmed reaches an export (Philosophy §2, PRD R9) — enforced in code, with a test.
- **[+2026-09-02] Spec readiness score + named gap detection.** A deterministic function over
  `assembly.ProductDocument` — which already carries `unreviewed` per section, `disagreements`,
  and the claim `type` distribution — emitting a score plus *named* gaps: claims unreviewed,
  disagreements unsettled, a feature with no `constraint`, a confirmed `open_question` still
  unanswered. Rendered on the About page and at the head of the Markdown export, so an agent
  receiving the spec is told what the spec is missing. **Predicts nothing**: every component
  clicks back to a real node, which is what separates it from the impact/urgency scoring
  rejected in the decision doc §4. No migration, no new event type.
- **[+2026-09-02] Evidence density on a claim.** Show how many independent sources back each
  confirmed claim — "3 sources across 2 systems." `assembly.Claim.sources` already carries the
  data; it is simply not surfaced. Countable fact, no new storage, and the cheapest available
  expression of the product's central argument.

**Cut from v1's Phase 2, with reasons:**
- **JSON export** — Markdown is what goes into a coding agent's context. JSON is for programmatic consumers who do not exist yet. Defer.
- **Spec versioning / v1-vs-v2 diff** — needs a second ingestion run over changed sources to mean anything. Defer to Phase 3, where incremental sync makes it natural.
- **Third source (Notion/Google Docs)** — moves to Phase 3. Different risk.

### 2B — The Proof

Designed to the standard `writing-evals` already imposes on extraction.

- **Internal first, design partner second.** v1 made the core proof dependent on recruiting a design partner. It is not. The `BurntSushi/ripgrep` golden set is real historical work whose actual outcome is known — a coding agent can be run against (a) the raw PR/tickets alone and (b) the Atlas spec, and both outputs graded against what was really built. First signal costs no recruiting.
- **Pre-register the rubric before seeing any result.** Non-negotiable, same as a Tier-1 eval check.
- **[+2026-09-02] Both 2A additions must be in the artifact *before* pre-registration, or not
  during Phase 2 at all.** They ship in 2A precisely so the thing measured in 2B is fixed before
  the rubric is written. Pre-registration must state explicitly that the readiness score is part
  of the treatment: the phase asks "does an Atlas spec help," so one treatment against one control
  answers it — but attribution *between* provenance and gap-flagging is then not available, and
  claiming it afterwards would be reading a result the design cannot support.
- **Blind grading**, N ≥ 5 features.
- Then, and only then, repeat with a design-partner team on their own material.

**Exit criterion (replaces v1's):** on ≥5 features, blind-graded agent output scores meaningfully higher against a pre-registered rubric with the Atlas spec than without it — **or** it does not, and that result is written down and the thesis is revised. A null result closes this phase legitimately. That is the point of running it.

**Deliverable:** MVP v1 — ready for a small paid pilot cohort, *if* the proof came back positive.

---

## Phase 3 (revised) — Compounding: breadth, Q&A, feedback loop

**Risk retired:** does this get better with usage and breadth, or does it plateau?

Absorbs v1's Phase 3 unchanged, plus the third source displaced from Phase 2.

- **Third source:** one doc tool (Notion or Google Docs — whichever the design partner actually uses).
  - **[+2026-09-02] Interview notes are the reason this matters, and they need their own eval.**
    A PM's interview notes usually already live in the doc tool, and `prompts.py` is source-agnostic
    by construction with `problem` and `evidence` already in its taxonomy — so a transcript yields
    claims whose excerpt is *the customer's literal words*, linked to the page. That is evidence
    provenance for specs, not a move to the discovery side. **The connector is cheap; the quality is
    not:** rule 5 (one claim, one node) and the tool-call budget were tuned on PR threads, and a
    45-minute transcript is thousands of words that are mostly not claims. Needs a golden set of its
    own before it counts as working (`writing-evals`).
  - **[+2026-09-02] Open modelling question, to settle before building:** Atlas's unit is a
    feature_scope, and many interviews predate any feature. Where an unscoped interview attaches is
    a `domain-modeling` question, not an implementation detail.
- **Contextual Q&A** over ingested content with citations; confidence-aware answers that flag thin or conflicting evidence rather than asserting.
- **Incremental sync** — moved up from v1's Phase 4. Philosophy §5 already declares idempotent/incremental ingestion binding "from Phase 1's scoped/incremental sync onward," so v1's placement in Phase 4 contradicted the Engineering Philosophy. It also unblocks spec versioning, deferred out of 2A.
- **Spec versioning** — now meaningful, since sources can change and re-sync.
- **Feedback loop instrumentation** — capture edits and rejections as signal for prompt improvement.
- **[+2026-09-02] Unaddressed-problem detection.** `problem` nodes carrying confirmed `evidence` via
  `supports`, which **no** `requirement` or `decision` reaches via `implements`. Ranked by evidence
  count and distinct source count — both countable facts about the graph. This is the only form of
  "what should we build next" that survives Philosophy §4: it reports a structural gap in evidence
  the team confirmed themselves, and **estimates no impact**. Belongs here rather than in Phase 2
  because it compounds with breadth — more sources make the gaps meaningful — which is exactly the
  risk this phase retires. **Gated on a precondition:** confirm that extraction actually emits
  `supports` and `implements` edges at useful density in the golden set. If it does not, this is an
  extraction problem first and a feature second.
- **[+2026-09-02] Support-desk source (Zendesk/Intercom), lower priority than the doc tool.** Same
  machinery, excerpt-bearing text, so it is a connector rather than a rewrite. Listed for sequencing,
  not committed ahead of the doc tool. Note the boundary: product analytics, NPS scores and
  session-replay metadata are **not** in this category — they carry no excerpt-bearing text, so they
  cannot produce a Node under Philosophy §4.

**Exit criterion:** pilot teams use Q&A weekly without prompting, **and** spec acceptance rate (below) trends upward across two consecutive weeks — measured only over human-actor confirmations.

---

## Phase 4 — Hardening for broader pilot

**Unchanged from v1 in substance**, less incremental sync (moved to Phase 3).

- Feature-level RBAC and admin controls over what can be ingested.
- Data retention and encryption review; security-questionnaire readiness.
- **Key rotation for `ATLAS_SECRET_KEY`**, currently unbuilt and tracked — named here so it stops being a footnote.
- Basic admin usage analytics.
- **[+2026-09-02] Comment threads on a claim.** A real gap in the collaboration story — confirm/reject
  is a thin approval and carries no discussion. Placed here rather than earlier because nothing
  measured in Phases 1–3 is blocked on it, and it is a broader-pilot concern.

**Exit criterion:** passes a basic security review from at least one prospective enterprise pilot's IT/security team.

---

## Metrics (replaces PRD §6)

**Guard metric — check this before reading any other number.**

| Guard | Target |
|---|---|
| **% of confirmations made by a human actor** | **100%.** If this is not 100%, every metric below is unsound and must not be cited. |

**Primary — the thesis.**

| Metric | Target |
|---|---|
| **Agent output quality, spec vs. no-spec** | Blind-graded, N≥5, pre-registered rubric, meaningful margin. This is the only metric that decides whether the product is real. |

**Supporting.**

| Metric | Target | Change from v1 |
|---|---|---|
| **Spec acceptance rate** — % of a spec's claims kept unedited at first read | Trend upward | Renamed and tightened from "% confirmed without edit." Counted **only over human-actor confirmations, at first read**, because the old form is confounded by reviewer fatigue and rubber-stamping — a bored reviewer and a perfect extractor produce the same number. |
| **Conflict yield** — surfaced conflicts a human confirms as *real disagreements they did not already know about*, per feature | Establish a baseline; no target yet | **New.** The most differentiated behaviour in the product was completely unmeasured. A conflict the team already knew about is not value delivered. |
| **Time-to-first-spec for a new team** | < 15 min | Unchanged, but only measurable once 2A exists. |

**Dropped.**

| Metric | Why |
|---|---|
| Weekly active spec-runs per team | Meaningless at a one-team pilot; re-add when there is a cohort. |
| Manual context-assembly time saved (self-reported) | Keep as interview colour, not as a metric. Self-report cannot carry a claim this load-bearing. |

Retained from v1: no vanity metrics. "Nodes in graph" and "documents ingested" remain explicitly rejected.

---

## What did NOT change

Stated plainly, because a revision is easier to trust when its blast radius is bounded:

- **The Engineering Philosophy** — all six points stand, untouched.
- **Phase numbering (0–4)** — every existing decision doc that cites a phase number remains correct.
- **The Non-Goals** — no queue, no graph DB, no write-back, no fine-tuning, no cross-org querying.
- **Phase 0 and Phase 1 scope and exit criteria** — both as originally written. Phase 0 is met; Phase 1's is not yet measured.
- **The positioning** — delivery-side, not discovery-side. v2 does not reposition toward the YC RFS or anything else.
- **[+2026-09-02] Every exit criterion, and every phase boundary.** The amendment adds features to
  Phases 2–4 and removes nothing. No phase closes on a different piece of evidence than it did
  before — a phase is still gated by a measurement, never by a shipped feature.

---

## Summary table

| Phase | Core deliverable | Risk retired | State |
|---|---|---|---|
| 0 | Internal extraction proof (GitHub only) | Does extraction work? | **Met** 2026-07-28 |
| 1 | Confirmation UI + 2nd source | Can a non-engineer use this? | Built; **criterion not yet measured** |
| 2 | **Spec export + the proof** | **Does this improve agent output?** | Not started |
| 3 | Third source + Q&A + incremental sync + feedback loop | Does it compound with usage? | Not started |
| 4 | Security / RBAC hardening | Will enterprises pilot this? | Not started |
