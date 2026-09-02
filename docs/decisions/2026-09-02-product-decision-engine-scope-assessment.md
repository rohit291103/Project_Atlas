# Decision Log — The "Cursor for PMs" product-decision-engine spec, assessed against Atlas scope

**Date:** 2026-09-02
**Area:** product / architecture

## Context

A full product specification for an "AI-native product decision engine" was brought to
the project for assessment — the YC Spring 2026 RFS category ("Cursor for Product
Management") worked up into a concrete feature list: multi-source evidence ingestion
(interview transcripts, Intercom/Zendesk/Slack, PostHog/Amplitude/Mixpanel, NPS, churn
feedback, session-replay metadata), an insight-clustering engine, a
*"what should we build next?"* mode, an opportunity-scoring system with
revenue/retention impact estimates, a spec-and-implementation generator, conversational
spec refinement with versioning, multi-tenant collaboration (comments, mentions,
approvals, notifications), and a post-launch loop comparing predicted impact against
actual results.

`docs/decisions/2026-08-18-roadmap-v2-spec-export-and-proof.md` §55 had already recorded
**no repositioning** toward this category, in one line, on the grounds that the adjacency
is cheap but the trade is bad. That line was correct and is unchanged. It was, however,
too terse to survive contact with a concrete spec — it did not say *which* parts overlap,
which are merely out of phase, and which are structurally incompatible. Two weeks later
the question was asked again from scratch, which is precisely the rediscovery that
§55 existed to prevent. This entry records the assessment at the resolution the
question was actually asked at.

## Decisions

1. **The position is unchanged: no repositioning, and no part of the discovery side is
   scheduled.** The two spines do not line up. That spec runs *evidence in → cluster →
   score → decide what to build → spec out → measure outcome*, with its centre of gravity
   in stages 2–4. Atlas runs *delivery artifacts in → provenance-linked claims → human
   confirmation → spec out*, and begins where their stage 4 ends. Their model assumes the
   build decision has not been made; Atlas assumes it has, and that the reasoning behind
   it is scattered across artifacts nobody can reconstruct.

2. **Roughly a quarter of the spec is already built, and two items of it are stronger in
   Atlas than in the spec.** Structured insight objects with citations — Atlas enforces a
   literal excerpt plus URL on every Node at the schema boundary, which the spec asks for
   only as an output feature. "Highlight contradictions or conflicting signals" — Atlas
   has `CONFLICTS_WITH` edges and surfaces unresolved disagreements on the About page as
   objects with both sides, rather than silently resolving them. Also already present:
   multi-tenant workspaces with admin/editor/viewer roles and applied RLS under a
   least-privilege `atlas_app` role; a full audit log by construction (append-only
   `event_log`, every event carrying an actor *and* an actor kind); and spec generation
   (`assembly.py`, `GET /products/{id}/spec`).

3. **A further quarter is already on roadmap v2, in Atlas's idiom and narrower.** Spec
   versioning with diff/rollback is Phase 3, gated on incremental sync. The post-launch
   feedback loop exists as Phase 3's feedback-loop instrumentation — edits and rejections
   captured as prompt signal — and as the spec-acceptance-rate metric. Approvals,
   comments, mentions and notifications are unbuilt; confirm/reject is a thin approval and
   nothing measured so far needs the rest.

4. **Opportunity scoring is rejected on the Engineering Philosophy, not on sequencing —
   and this is the substantive finding.** The spec's centre is a per-initiative score:
   frequency, revenue impact estimate, retention impact estimate, strategic alignment,
   effort, confidence, with customisable weights. There is no source excerpt for
   "this will lift retention 8%." It is an LLM producing a number that drives a decision,
   which root `CLAUDE.md`'s **What NOT to do** places at the same severity tier as
   hallucinated provenance. Philosophy §2 (extraction is a draft, never a fact) and §4
   (provenance is non-negotiable) do not bend for it: an estimate cannot be confirmed
   against a source, so it can never be a Node.

   It could be built as an explicitly-unprovenanced layer sitting beside the graph. That
   is rejected too, for a reason worth stating rather than leaving implicit: Atlas's one
   differentiated claim is that *every statement here is checkable*. A design in which the
   headline feature is the exception to that claim does not survive its own positioning.

5. **One idea is worth keeping: the readiness score plus automated gap detection.** Kept
   because it is the only item in the spec that fits Atlas as it stands:
   - It reads data already held — confirmed vs. unconfirmed ratio, live `CONFLICTS_WITH`
     edges, `OPEN_QUESTION` nodes, absent `REQUIREMENT` / `CONSTRAINT` coverage.
   - It needs no new ingestion and no new source.
   - It is **deterministic** — a computed read over the projection, not a judgment call —
     so it does not inherit decision 4's objection.
   - It is a plausible *mechanism* for Phase 2's proof. If a spec improves coding-agent
     output, "fewer unresolved gaps at handoff" is the likely reason, and a readiness
     score would make that measurable rather than inferred.

   Logged as a **Phase 2C / Phase 3 candidate**, not scheduled. See "Not done" for why it
   must not be built before the Phase 2 measurement runs.

6. **Support tickets are named as the cheapest bridge to the discovery side, if it is ever
   wanted.** `NodeType.EVIDENCE` and `NodeType.PROBLEM` exist and `prompts.py` extracts
   evidence today, so an Intercom/Zendesk connector is a connector plus a view rather than
   a rewrite. This restates §55's "cheap adjacency" concretely so the cost estimate does
   not have to be re-derived a third time. Product analytics, NPS and session-replay
   metadata are *not* in this category — they carry no excerpt-bearing text, so they
   cannot produce a Node under Philosophy §4 and would need a different structure
   entirely.

7. **The spec's design instruction — "choose one bright primary color," YC-style — is
   declined as a reopening of a closed decision.** The brand pass closed 2026-08-22
   (`docs/ux/brand-and-logo-brief-v1.md`): the mark is drawn and in the product, the
   wordmark is set in type, and `--brand-1` / `--brand-2` stay magenta → violet after four
   ramps were built into the real hero and reviewed in both themes. The known cost of the
   kept ramp is recorded in brief §6.1 rather than argued away.

8. **A stale line in `docs/tracker.md` was corrected.** Its *Next up* section claimed
   `--brand-1`/`--brand-2` had "moved from magenta→violet to cyan→blue" — contradicting
   both its own earlier paragraph, the brand brief, and
   `frontend/src/styles.css:136-137` (`#ff4d9d` → `#a855f7`). The tracker is disposable
   and overwritten in place, so this is a correction, not a rewrite of history.
   Confirmed with the user: violet is what was chosen and what shipped.

## Not done (deferred)

- **The readiness score is not scheduled, and must not be built before Phase 2's
  measurement runs.** Phase 2's exit criterion is a blind, pre-registered, N≥5
  measurement — evidence, not a feature. Adding a readiness score first would change the
  artifact under test partway through the experiment. It is a candidate for after the
  proof, when it can be evaluated against a baseline that exists.
- **Nothing else from the spec is scheduled.** Clustering, opportunity scoring,
  "what should we build next?" mode, impact estimation, analytics/NPS/session-replay
  ingestion: out of scope, per decisions 1 and 4.
- **Comment threads on a claim** are noted as a real gap in the collaboration story but
  are not queued; no measurement currently blocked on them.
- **Phase 1 is unchanged and still open.** Its exit criterion — a PM outside the build
  team, unassisted, under 20 minutes — remains unmeasured, blocked only on the PM's exact
  name. Neither this assessment nor anything in it changes that ordering.
- **`roadmap-v2.md` is not edited in substance.** Per the no-silent-overwrite rule it
  gains a one-line cross-reference to this entry under Phase 3 rather than absorbing the
  candidate into its committed scope.

---

## Amendment — same day, after further discussion

The original entry logged the readiness score as a *candidate, not scheduled*, and left the
rest unplaced. On review that was the wrong resting place: an unplaced candidate is exactly
what §55 of the 2026-08-18 entry turned out to be, and it got re-litigated within two weeks.
The items are now **placed in phases** in `docs/prd/roadmap-v2.md`, marked `[+2026-09-02]`.
The decisions above are unchanged — in particular decision 4 (opportunity scoring rejected
on the Philosophy) stands exactly as written. What changed is scheduling, not scope.

1. **Phase 2A — spec readiness score, and evidence density on a claim.** Both are functions
   over `assembly.ProductDocument`, which already carries `unreviewed`, `disagreements` and
   `Claim.sources`. No migration, no new event type.

2. **Phase 2B gains a constraint that did not exist before.** Both 2A additions must land
   **before the rubric is pre-registered**, or not during Phase 2 at all — otherwise the
   artifact under test changes partway through a pre-registered experiment. Pre-registration
   must also state that the readiness score is part of the treatment. The phase asks
   *"does an Atlas spec help"*, which one treatment against one control answers; but
   attribution between provenance and gap-flagging is then unavailable, and claiming it
   afterwards would be reading a result the design cannot support. This supersedes the
   original "must not be built before Phase 2's measurement runs" — that wording protected
   the experiment, and *ship it before pre-registration* protects it better while still
   letting the feature exist.

3. **Phase 3 — unaddressed-problem detection**, gated on a precondition: verify that
   extraction emits `supports` and `implements` edges at useful density in the golden set.
   If it does not, this is an extraction problem before it is a feature. Placed in Phase 3
   rather than 2 because it compounds with breadth, which is the risk Phase 3 retires.

4. **Phase 3 — the third source's purpose is stated, and a cost is attached.** Interview
   notes are why the doc connector matters, and they need a golden set of their own: rule 5
   and the tool-call budget were tuned on PR threads, and a transcript is mostly not claims.
   An open `domain-modeling` question is recorded with it — where an unscoped interview
   attaches, given Atlas's unit is a feature_scope. Support-desk sources (Zendesk/Intercom)
   are listed below the doc tool; analytics, NPS and session-replay are excluded by
   Philosophy §4, since none carries excerpt-bearing text.

5. **Phase 4 — comment threads on a claim.**

6. **Nothing was added to Phase 1, and the roadmap now says why.** Evidence density is small
   enough to have landed there. It went to 2A instead: Phase 1 construction closed
   2026-08-25, everything still open needs a person rather than a commit, and any commit
   landing in Phase 1 moves the PM measurement further out — which is the actual bottleneck.

**Not changed by the amendment:** every exit criterion, every phase boundary, and the
Engineering Philosophy. Nothing was removed. A phase is still closed by a measurement, never
by a shipped feature — which is why this is an amendment to v2 rather than a v3.
