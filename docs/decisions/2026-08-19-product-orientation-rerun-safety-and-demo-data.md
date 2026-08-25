# Decision Log — Product Orientation, Re-run Safety, and the Demo Data That Would Have Invalidated the PM Measurement

**Date:** 2026-08-19
**Area:** product / storage / ux

## Context

A working session that began as a sanity check on the founding pitch and ended with three verified defects, all of which bear on the Phase 1 exit criterion — *a PM outside the build team, unassisted, under 20 minutes*.

The session's earlier outputs are logged separately and are **not** duplicated here: the roadmap revision and the metric replacement are in `2026-08-18-roadmap-v2-spec-export-and-proof.md`, along with the deliberate decision not to reposition toward the YC "Cursor for PMs" RFS. This entry covers what came after, which arrived as three questions from the user about what a real PM would actually experience.

All three were checked against the code rather than reasoned about. All three were confirmed.

## Findings (verified, not inferred)

**F1 — Ingestion never updates on its own, and re-running is not idempotent.**
Ingestion is pull-on-demand: a control on the Sources screen, `POST /products/{id}/runs`, 202, in-process via `BackgroundTasks`. Nothing watches a repository, polls, or receives webhooks. That much is by design — incremental sync is Phase 3 in roadmap v2.

The unintended half: **re-running the same target into the same feature duplicates every claim.** `grep -rn "idempot\|dedup" src/atlas/pipeline.py` returns nothing, node ids are minted per run, and `storage/projections.py` states plainly that "a second run against the same scope adds to" it. A reviewer could then confirm one copy of a claim and reject the other.

The 2026-08-15 de-duplication work does not cover this: `duplicate_claims()` and the "ONE CLAIM, ONE NODE" prompt rule both operate *within* a single extraction run.

**Engineering Philosophy §5 — "Idempotent, incremental ingestion. Re-running ingestion must never duplicate or corrupt existing data (binding from Phase 1's scoped/incremental sync onward)" — is therefore currently a stated principle with nothing enforcing it.** That is the most serious of the three findings, because §5 is not aspirational language; it is in the non-negotiable list.

**F2 — There is nowhere to put product context.**
`Product` carries `id` and `name`. `FeatureScope` carries `id`, `title`, `runs`, `product_id`. Neither has a description, summary, or statement of purpose, and a feature's `title` is not authored at all — it is inherited from whichever artifact opened the scope.

So a PM arriving at a product cannot learn *what the product is*, and a PM arriving at a feature cannot learn *what the feature is for*, at any layer above the individual claim. This is not a missing screen; there is no field to render.

It also names the cost of a decision made on 2026-08-16. `ProductsPage.tsx` records that the Overview "used to open a title, a one-line summary and a list of features" and was replaced with counts and a meter, because a directory-with-a-sentence answered the question a PM asks *second* without answering the one they ask *first* — how much is mine to do? That reasoning holds **for a PM who already knows the product**. It optimised for the returning reviewer and removed the only orientation a first-time visitor had.

**F3 — The demo data would have invalidated the PM measurement.**
`BurntSushi/ripgrep` is a command-line search tool written in Rust; its PRs concern `--max-depth` flag semantics and directory traversal. It was chosen as a Phase 0 **validation fixture** for good reasons — real history, known outcomes, public, decision-dense — and it discharged that job.

It has since been reused as **demo data**, and those are different jobs. The Phase 1 exit measurement is currently staged against the ripgrep product. Run as-is, it would not measure "can a non-engineer use Atlas"; it would measure "can a non-engineer follow a Rust CLI tool's PR history." **Both a pass and a failure would be uninterpretable**, which makes this a defect in the measurement design, not a matter of polish.

## Decisions

1. **Findings F1–F3 are accepted as defects, not as taste.** Each was verified against the code in-session; none rests on judgement about what a PM would prefer.

2. **The PM measurement does not run against ripgrep.** Replacing the demo data is a **prerequisite** of the Phase 1 exit criterion, and is now sequenced ahead of it. This is the highest-leverage of the three and the cheapest.

3. **The 2026-08-16 Overview decision is amended, not reversed.** Counts and the meter stay — that decision was right that a returning reviewer needs work-left at a glance. What was wrong was treating it as either/or. Orientation returns *above* the counts, which requires F2's data-model work first.

4. **"Product context" becomes a real field on the model, not UI copy.** A description on `Product` and on `FeatureScope`, so the layering the user described — product → feature → claims → source thread — has content at every level rather than only the bottom two.
   - **Settled 2026-08-19: the PM types it.** Plain authored text, no provenance machinery. The alternative — extracting a summary — would have made the description a *claim about the feature*, obliged to carry provenance and start unconfirmed like anything else, and would have put machine-written text in the one place a first-time visitor goes to find out what they are looking at. Orientation is also the thing a PM knows better than the extractor does. `Product.description` and `FeatureScope.description` are therefore ordinary event-sourced fields, not Nodes.

5. **Re-run safety is split into a guard now and correctness later.** A warning before pulling an already-ingested target lands before the PM measurement; genuine idempotency lands with incremental sync in Phase 3. Shipping a button that silently duplicates a reviewer's queue is worse than shipping no button.
   - **Settled 2026-08-19: a hard block.** Re-pulling an already-ingested artifact is refused outright until real idempotency exists. A prompt would have preserved the legitimate case of re-pulling a genuinely updated PR, but that case is served today by ingesting into a *new* scope, whereas the illegitimate case silently doubles a reviewer's queue with no way to tell the copies apart. The block is also the smaller change, and it is removed rather than loosened when Phase 3 lands.

6. **GitHub stays, and the persona framing is corrected.** GitHub is a sound source — PRs are unusually dense in decisions, rejected alternatives and constraints. But it is the *tech lead's* surface, not the PM's. The PRD names three personas and GitHub serves the second and third better than the first. PM-facing demonstration and PM-facing measurement should lead with Jira, with a doc source arriving in Phase 3. This changes no code and no roadmap item; it changes which source a PM is shown first.

7. **Philosophy §5's status is recorded honestly rather than quietly carried.** It reads as binding from Phase 1 onward and nothing enforces it. It is not amended and not weakened — it is a real commitment with an outstanding debt against it, and the debt is now tracked (T1/T5 below) instead of being rediscovered by a PM.

## Not done (deferred)

- **Real idempotency** — deferred to Phase 3 with incremental sync, where content-addressed or externally-keyed node identity can be designed once rather than twice. The guard in decision 5 is explicitly a stopgap and is labelled as one.
- **Continuous sync, webhooks, polling** — out of scope in every currently-scheduled phase, and would require the task queue the Non-Goals rule out until a phase needs it.
- **A third (doc) source** — Phase 3 per roadmap v2, unchanged by this entry.
- **Re-titling a feature scope** — the first-run-wins rule in `projections.py` stands; a rename should be a deliberate event, not a side effect. Decision 4's `FeatureScope` description does not change that rule.
- ~~The two open questions in decisions 4 and 5~~ — **both settled 2026-08-19**, inline above.

## Postscript — the guard metric's first live reading (2026-08-19)

Migration `f9b41d7e3a52` is applied. The live log now reads **151 automated, 40 unknown, 7 human**; of 32 `node_confirmed` events, **7 are provably human and 25 are unknown**. The 25 include the six the browser suite made on 2026-08-16, and nothing will ever separate them again — which is the point of backfilling `unknown` rather than guessing `human`.

So roadmap-v2's guard metric currently reads **~22% human**, and its rule applies: no other metric may be cited off this data. That is the correct reading, not a problem to fix — the pre-migration events are genuinely ambiguous and saying so is the honest answer. The figure becomes meaningful for events written from here on.

---

## Implementation slices — product orientation, re-run safety, demo data

Ordered by dependency, not by importance. **Two are re-ideations** of decisions already shipped (marked *re-ideated*); the rest are new. Slice 0 is not from this decision doc — it is carried from 2026-08-18 and blocks everything, so it is listed first rather than tracked somewhere else.

0. [x] **The live database accepts writes again** — *done 2026-08-19* — depends on: none
   - Migration `f9b41d7e3a52` applied. Live log reads 151 automated / 40 unknown / 7 human; of 32 confirmations, 7 are provably human and 25 unknown. See the postscript above.
   - Touches: `migrations/versions/f9b41d7e3a52_event_actor_kind.py`, live Supabase

1. [x] **Re-ingesting an artifact is provably shown to duplicate its claims** — *done 2026-08-19* — depends on: none
   - A failing-then-passing regression test that runs the same target into the same scope twice and asserts what actually happens today. Locks the defect (F1) in place as a known, tested fact before Phase 3 changes it, per the `tdd` skill's rule that a Critical-tier finding gets a regression test. Ships **red-documented**, not fixed — the fix is real idempotency and it is deliberately Phase 3.
   - Touches: `tests/test_pipeline.py`, `src/atlas/pipeline.py` (no behaviour change)

2. [x] **Re-pulling an already-ingested artifact is refused** — *done 2026-08-19* — depends on: 1
   - Hard block, per decision 5. `artifact_external_id()` in `pipeline.py` derives the id a target would be stored under; `Projection.scope_holding()` finds the scope already holding it; the endpoint returns **409 naming that feature**, so a PM can go look rather than guess. Epics and labels are deliberately not blocked — they name no single artifact — and a test asserts that gap so it stays a decision.
   - Touches: `src/atlas/api/routes.py` (runs endpoint), `frontend/src/pages/SourcesPage.tsx`, `storage/projections.py` (read only)

3. [x] **A product and a feature can say what they are** — *done 2026-08-20* — depends on: 0 ✅
   - `description` on `Product` and `FeatureScope`, event-sourced like everything else (a new event type per the `product_renamed` precedent, never a mutated projection). **PM-authored**, per decision 4 — plain text, not a Node, no provenance machinery.
   - Touches: `models/schema.py`, `storage/products.py`, `storage/projections.py`, a migration, `api/routes.py`
   - Gate: new event type ⇒ a migration is mandatory (see `e6f3b8a20c47` — SQLite cannot catch this)
   - **What it turned out to require, beyond the plan:**
     - **Two event types, not a field on `ProductPayload`.** `product_described` and `feature_scope_described`. A rename restates a product's whole identity; a description says something else about it. Sharing one payload would mean either event silently overwriting the other's field, or an optional field whose absence is ambiguous between *unchanged* and *cleared*. The split immediately caught a real bug class: `product_renamed` rebuilt the projected `Product` wholesale, which would have blanked a description on every rename — it now supersedes only the name, and a test pins that.
     - **Blank is allowed, and means cleared.** `DescriptionStr` is deliberately *not* `NonBlankStr` — the rule the rest of the schema uses. In a log that only moves forward, refusing an empty description would make a wrong one permanent. Empty and `None` collapse at the projection, so no reader special-cases `""`. Text is trimmed rather than kept verbatim, which is the line between authored prose and a `SourceRef.excerpt`: an excerpt is evidence and must stay literal.
     - **Bounded at 2000 characters.** The payload lands in JSONB in an append-only log, so there is no later opportunity to trim it — and orientation past a paragraph is a spec, which is what the claims are for.
     - **A description for a feature scope the log never opened is inert, not fatal.** It resolves at the end of `replay` alongside `product_id`, so it is order-independent (a person may say what a feature is for before ingestion opens it) and a description naming a scope with no `ingestion_run` is dropped — exactly as an assignment to such a scope already is. Raising there, the rule products follow, would make an append-only workspace unreadable *forever* over a piece of orientation text. Products keep the strict rule: a product cannot exist without a `product_created`, so an unknown one is genuinely a corrupt log. The API closes the gap from the other side — `PUT /feature-scopes/{id}/description` is a 404 unless the scope has a projected identity, so the sanctioned path never writes an event the replay would drop.
     - **`PUT`, not `POST`.** The body states the field's whole value: sending it twice leaves the same description, even though each send appends its own audit event. Every other write in `routes.py` is a `POST` because every other write is a genuinely new act (a ruling, an edit carrying its own before-image).
     - **`FeatureScopeRow` carries the description**, so a product's feature list can show it without fetching every feature's full detail to read one sentence — the same reasoning that put `counts` there.
   - **Applied live and checked, 2026-08-20.** Migration `b41c9d0e7f38` (the two enum values) is applied to Supabase; `alembic current` reads `b41c9d0e7f38 (head)`. The check the migration's docstring demands was then run **as the `atlas_app` role, not the owner**, so it exercised the grants and the RLS scope as well as the enum: both event types wrote, replayed back through the projection, and cleared. Four events, all `actor='cli'` / `actor_kind=automated` — a machine wrote them and the log says so, which is the only claimable direction. Nothing was left asserting anything about the live products: the descriptions were written, verified and then cleared, and the two live products (`ripgrep`, `Slice 2B verification`) and seven feature scopes all read `description = None` again afterwards.
   - **Nothing renders it yet** — that is slice 4.

4. [x] **A PM landing on a product learns what it is before learning how much is left** — *re-ideated* — *done 2026-08-20* — depends on: 3
   - Orientation returns **above** the counts, not instead of them. Amends the 2026-08-16 Overview decision, which was right for the returning reviewer and removed the only orientation a first-time visitor had. Same layering one level down: a feature says what it is above its claim list.
   - Touches: `frontend/src/pages/ProductsPage.tsx`, `ReviewPage.tsx`, `styles.css`
   - Cross-reference into `docs/ux/entry-and-sources-spec-v1.md` when done
   - **Built as one shared component** (`frontend/src/components/Orientation.tsx`) used at both layers, because the behaviour is identical and the *layering* is the point — product → feature → claims → source thread, with something to read at every level. Three placements: above the counts on a product, a full-width strip under the review bar (outside `rv__bar`, which is a fixed-height row of facts — a wrapping paragraph in there would shove the progress meter and the conflict link around), and a two-line clamp on each portfolio card.
   - **The empty state is an affordance, not a placeholder.** With nothing written, a writer sees `+ Say what this product is` and a viewer sees nothing at all — a permanently empty slot is worse than silence for the reader who cannot fill it. The editor states that saving an empty box removes the description, which is the only way to discover a behaviour the API allows deliberately.
   - **Verified against the live database through the real UI, in both themes**: wrote a product description and a feature description from the browser, watched each render above its counts / above its claim list, then cleared both. Every live product and feature reads `description = None` again; the four events are `actor_kind = automated` (`X-Atlas-Automated`), so the guard metric is untouched.
   - **One measurement worth keeping:** a description took **~2.9s** to appear after clicking into the empty state, against remote Supabase. Nothing is wrong with the write — the refresh re-replays the whole event log for the rail. It is invisible at 200 events and it is the first place a demo will feel slow.

5. [x] **The measurement environment is a product a PM recognises** — *re-ideated* — *done 2026-08-21* — depends on: 0, 3
   - Replaces ripgrep as the PM-facing environment, led by Jira rather than GitHub (decision 6). **Prerequisite of the Phase 1 exit measurement**, not a follow-up to it. ripgrep is *retained unchanged* as the Phase 0 validation fixture and the Phase 2 proof set — this replaces the demo, not the golden set.
   - Touches: seed scripts (outside `src/`, so Atlas stays read-only into every source), a real Jira project
   - ~~**Needs the user:** which product, and a Jira site to pull from~~ — **settled 2026-08-21: the user delegated the choice.** The product is **Plausible Analytics**; the Jira site is the existing one, in a **new `PA` project** rather than mixed into `SCRUM` beside the ripgrep epic, so the demo scope is unambiguous and deletable as a unit.
   - **Why this product.** The GitHub half had to be real, public, and *legible to a PM*, and those pull against each other: the repos a PM understands are modern enough that their PR threads are mostly bot noise. `TryGhost/Ghost#29967` (gift subscriptions) was the first pick and was dropped after reading it — a decision-dense body, but **all 11 comments are Codecov, CodeRabbit and CI failures**, so the demo would have shown claims extracted from a coverage report. `plausible/analytics` **#1364** (which metric the main graph plots) and **#1574** (the graph's time detail) have **49 and 22 human comments** arguing about UX tradeoffs, and web analytics needs no translation for a product audience.
   - **The Jira half is authored, and says so.** `scripts/seed_demo_jira.py` creates one epic and five children in a PM's voice. Its docstring states plainly that these are demo tickets and not Plausible's real backlog, and the product's own `description` (slice 3/4) repeats it inside the app, where a demo audience will actually see it.
   - **Three acceptance criteria deliberately disagree with what the PRs decided** — conversion rate selectable at launch (PR: conversion and time-on-page excluded, "not well supported (at all) in the new timeseries interface"); a shared link reproduces the sender's view including interval (PR: interval deliberately held at graph level, not in the query object); the graph stays on screen (PR: deselecting the plotted stat hides the graph). These are real disagreements with real public text, not strawmen — which is the difference between demonstrating cross-source conflict detection and staging it.
   - **The script writes to Jira; Atlas still does not.** It lives in `scripts/` for the same reason `verify_rls.py` does: standing up an environment is an operator task, and Philosophy §1's read-only rule is about the product. Nothing importable from `atlas.*` gained a write path. It is idempotent by summary, so a re-run repairs a partial seed rather than doubling it, and `--dry-run` prints the content without credentials.
   - **Both PRs are pulled, and the reason is a demo-design one.** The plan was to leave #1574 un-pulled so a demo had a live action to perform. Timing killed that: the epic's five children took ~7 minutes and one PR ~4, because each artifact is its own agent run. A four-minute progress spinner is the worst possible thing to put in front of an audience, and the product's actual argument — *a reviewer ruling on claims, with two sources disagreeing in front of them* — needs no live ingest to make. So the environment is seeded complete and the demo is the review loop.
   - **What it produced, live:** one feature assembled from **7 artifacts** (5 Jira issues + PRs #1364 and #1574) — **55 claims and 4 cross-source conflicts**. All three planted disagreements were caught, plus a fourth the extractor found on its own (PA-4's "plot the default metric" against the same hide-the-graph decision). The Conflicts screen reads *"GitHub disagrees with Jira"* with both literal excerpts side by side, which is the product's argument in one screenshot.
   - **Page timings on this data, worth knowing before standing in front of someone:** overview ~2.8s, conflicts ~3.9s, review ~2.3s to first content, against remote Supabase. Every screen replays the whole event log; at 55 claims and ~250 events that is a visible pause, not a hang. It is the same cost slice 4 measured on a description write, and it is the first thing that will need attention if the demo grows.
   - **A behaviour worth knowing before demoing it:** ingesting the epic names the feature after **the first child that opened the scope** (`Choose which metric the main graph plots`), not after the epic. That is the documented first-run-wins title rule and re-titling is deliberately deferred — so the feature's *description* is what says it is the dashboard-graph epic. The title says what it was called; the description says what it is for. Slice 4 doing the job it was built for.

6. [x] **The browser suite stops mutating the workspace it measures** — *done 2026-08-25* — depends on: 0
   - Its own workspace. `X-Atlas-Automated` (2026-08-18) fixed *attribution* — its writes no longer masquerade as a person's rulings — but not *mutation*: a confirmation it makes is still real and still irreversible. ~~Until this lands, the two mutating tests stay excluded.~~ **They are no longer excluded: 42/42 pass.**
   - Touches: seed scripts, `frontend/playwright.config.ts`, CI env
   - **Outcome:** `scripts/seed_test_workspace.py` provisions one workspace (a constant `uuid5`, never an argument), seats two actors who are members of nothing else, and rebuilds its contents before every run via Playwright's `globalSetup`. Its claims are *recorded* extraction output from `tests/evals/golden_set/`, re-stamped and re-validated — a hand-written fixture would have put fabricated `SourceRef`s in the database of a product whose whole argument is that provenance is real. Clearing needs the owner credential (`atlas_app` cannot delete from `event_log` by grant) and refuses to delete anything a human actor wrote.
   - **Verified:** two consecutive 42/42 runs against live Supabase, with the demo workspace's newest event still dated 2026-08-20 afterwards. 16 pytest tests assert the fixture's shape without a browser.
   - **Not done, deliberately:** the suite still does not run in CI. That needs a Supabase *owner* credential in GitHub Actions secrets — a security decision belonging with Phase 4 hardening, not a wiring change.
   - Full argument: `docs/decisions/2026-08-25-browser-suite-fixture-workspace.md`

**Then, and only then, the Phase 1 exit criterion:** the PM measurement itself — still blocked on the PM's exact name, so membership can be seated under the string they type at sign-in.

**After Phase 1 closes**, per roadmap v2: Phase 2A Spec Export v0 (confirmed nodes → Markdown → inline provenance, conflicts surfaced as open disagreements), then Phase 2B The Proof (blind, pre-registered, N≥5, internal golden set first).
