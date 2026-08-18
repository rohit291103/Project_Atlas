# Decision Log — Roadmap v2: Spec Export Pulled Forward, and the Proof Made Measurable

**Date:** 2026-08-18
**Area:** product / architecture

## Context

A sanity-check pass over the original pitch, the external CEO/CTO/PM critique that shaped this project, and the actual repo state raised a gap the roadmap could not absorb by editing a line.

The critique that seeded Atlas named the atomic unit of value explicitly: *ingest → generate a spec → show provenance → approve it → hand it to the coding agent*, described as "shippable in a focused MVP, testable against real teams within weeks." Six accompanying engineering prescriptions (draft-not-fact, event log over rigid taxonomy, read-only, provenance, prove-propagation-before-promising, security-first) were all adopted and are enforced in code — that half of the advice was followed unusually faithfully.

The sequencing half was not. `MVP_Roadmap.md` v1 placed spec generation in Phase 2 (weeks 10–13). As of today:

- **Elapsed from first commit (2026-07-13) to Phase 1 construction complete (2026-08-16) is 5 weeks**, against a nominal 9 — roughly 1.8× pace.
- `find src -iname "*spec*" -o -iname "*export*"` returns **nothing**.
- The loop therefore ends at *"a human confirmed some claims"* — the middle of the value chain. A PM completing the Phase 1 exit criterion receives rows in a database, not an artifact.
- Consequently **PRD §6's third metric — agent output quality with spec vs. without — has been unmeasurable for the entire project to date.** That metric is the only evidence Atlas is not a nicer wiki.

Two further defects surfaced in the same pass:

- v1's Phase 2 **bundled spec export with a third source (Notion/Google Docs)**, which retires a different risk and only delays the first.
- v1's Phase 2 exit criterion — *"a design-partner team reports whether output quality improved"* — is self-reported, n=1, unblinded, with no baseline and no rubric. **This is a lower evidentiary bar than the project already applies to extraction**, where `tests/evals/` grades a golden set against pre-registered Tier-1/Tier-2 checks.

Separately, `Event.actor` (`src/atlas/models/schema.py:500`) is a single free-text `NonBlankStr` with nothing distinguishing a human from an automated agent. On 2026-08-16 the browser suite confirmed 6 real claims as `Rohit` that no person ruled on, irreversibly. This is not a roadmap question but it gates the roadmap's metrics, all of which read confirmation data.

## Decisions

1. **`docs/prd/roadmap-v2.md` supersedes `docs/prd/MVP_Roadmap.md`.** v1 is retained unchanged (its sequencing is part of the record) and gains a superseded-by pointer at its head. Per the Documentation Rules a major revision creates a new file rather than overwriting.

2. **Phase numbering stays 0–4; only the contents of Phases 2 and 3 move.** This was a deliberate constraint on the revision: 27 existing decision docs cite phase numbers, and renumbering would invalidate them all for no gain.

3. **Spec export moves into Phase 2 as the first deliverable, narrowed to the minimum that closes the loop** — confirmed nodes → Markdown → inline provenance. JSON export is cut (no programmatic consumer exists yet); spec versioning is cut and moved to Phase 3 (it needs a second sync over changed sources to mean anything); the third source moves to Phase 3.

4. **Unresolved conflicts must appear in the exported spec as open disagreements, never silently resolved.** Elevated from an implied behaviour to a hard requirement with a test. Silently picking a side is the exact failure Philosophy §2 and PRD R8 exist to prevent, and cross-source conflict is where the product is most differentiated.

5. **Phase 2's exit criterion is replaced with a measured experiment** — blind grading, N≥5 features, rubric pre-registered before any result is seen, to the standard `writing-evals` already imposes on extraction. **The first signal is generated internally against the `BurntSushi/ripgrep` golden set**, whose real outcome is known: run a coding agent against the raw PR alone vs. against the Atlas spec, grade both against what was actually built. v1 made the core proof hostage to recruiting a design partner; it is not. The design-partner run follows the internal one rather than replacing it.

6. **A null result closes Phase 2 legitimately.** The criterion reads "it improves, or it does not and that is written down and the thesis is revised." A phase that can only end in success is not measuring anything.

7. **Metrics replaced (PRD §6).** One guard, one primary, three supporting:
   - **Guard: % of confirmations made by a human actor must be 100%.** Below that, no other metric may be cited.
   - **Primary: agent output quality, spec vs. no-spec**, blind, N≥5, pre-registered rubric.
   - **"% confirmed without edit" is retired as confounded** and replaced by **spec acceptance rate**, counted only over human-actor confirmations at first read. A bored reviewer rubber-stamping and a perfect extractor produce the identical number under the old form.
   - **Conflict yield is new** — conflicts a human confirms as real disagreements they did not already know about. The most differentiated behaviour in the product was entirely unmeasured; a conflict the team already knew about is not value delivered.
   - **Dropped:** weekly active spec-runs (meaningless at n=1), self-reported time saved (retained as interview colour, not as a metric).

8. **Incremental sync moves from Phase 4 to Phase 3.** Philosophy §5 declares idempotent/incremental ingestion binding "from Phase 1's scoped/incremental sync onward," so v1's Phase 4 placement contradicted the Engineering Philosophy. It also unblocks the spec versioning deferred out of Phase 2.

9. **Actor provenance is scheduled into Phase 1 close-out, before the PM measurement, not after.** Two parts: `Event.actor` gains an actor *kind* separating human from automated, enforced at the schema boundary; and the browser suite gets its own workspace. The ordering is a real dependency, not tidiness — the PM session produces the first genuine confirmation data, every v2 metric reads confirmation data, and spec export reads *confirmed* nodes. Building the export on an unverified confirmation record would embed the "silent bad context" failure into the artifact the product exists to produce. Per the `tdd` skill this is event-log/schema logic and is mandatory test-first.

10. **Week ranges are dropped as commitments.** Nominal weeks no longer describe reality (5 elapsed vs 9 budgeted). Phases are gated by evidence; estimates are not deadlines. The guiding principle is sharpened from v1's *"every phase must end with something a real team can use"* to **"every phase must end with evidence about a claim, not with software."**

## Not done (deferred)

- **No repositioning.** The YC Spring 2026 RFS entry ("Cursor for PMs") is discovery-side — customer interviews in, *what to build next* out. Atlas is delivery-side. The adjacency is real and cheap to reach later (`NodeType.EVIDENCE` and `PROBLEM` already exist and `prompts.py` extracts evidence today, so it is a connector and a view, not a rewrite), but chasing it would trade a proven bet for an unproven one. Recorded here so the option is not rediscovered as a surprise.
- **The Engineering Philosophy, the Non-Goals, and Phase 0/1 scope and exit criteria are unchanged.**
- **PRD §6 is not edited in place.** The replacement metric set lives in `roadmap-v2.md`; §6 gains a pointer rather than being rewritten, per the no-silent-overwrite rule.
- **The two open Phase 1 items still need a person:** the user's frontend review, and the PM measurement — whose only outstanding input remains the PM's exact name, so membership can be seated under the string they will type at sign-in.
