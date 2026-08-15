# The product layer, and rebuilding the review screen around one claim

**Date:** 2026-08-14
**Slice:** 2A of `docs/architecture/product-model-and-frontend-rebuild-v1.md`
**Context:** the confirmation UI was too dense to navigate and had no notion of a PM working across several products. This is what got built and what changed while building it.

---

## 1. A product is a projection, and it could not have been derived

The redesign proposal first suggested deriving a "project" from `external_id` — `BurntSushi/ripgrep` and `SCRUM` are already in the data. That was wrong, and the reason is ordering: **a product has to exist before the first connection is made to it.** You cannot infer a container from the results of ingestion that has not happened yet, and a PM's first act on a new product is connecting a source to it, not ingesting.

So `product_created` / `product_renamed` are event types and `Projection.products` is a projection — the pattern slice 1A′ established for feature-scope identity. No table, no migration for storage, no state outside the log.

**Workspace stays the tenant.** A product is a grouping *inside* one. Making a product a workspace would have carried isolation for free but broken the meaning that the RLS policy, `workspace_member` and the audit trail are all built on — the boundary `scripts/verify_rls.py` proves 11/11. RLS is untouched by any of this, and still passes.

## 2. An assignment beats a run's default, in either order

A feature learns its product two ways: `IngestionRunPayload.product_id` (optional, a default supplied by whatever triggered ingestion) and `feature_scope_assigned` (a deliberate act by a person). The rule is that **the assignment wins regardless of which event is later**, resolved after the fold rather than during it.

Last-write-wins would have meant a re-ingestion silently moving a feature out of the product someone filed it under — the same class of bug slice 1C fixed for titles, where a Jira ticket must not rename a feature a GitHub PR named mid-review. Two tests pin both orders, and a third pins the subtler half: a later run carrying `product_id = None` must **not** clear an assignment, because `None` is an absence rather than a claim that the feature belongs nowhere.

The four scopes already in the live database got one `feature_scope_assigned` event each. The `ingestion_run` events that opened them were not touched; the log is append-only and that is not negotiable for a convenience.

## 3. Adding an EventType needs a migration, and no Python test can tell you

`atlas product-create` failed on the live database with `invalid input value for enum event_type`. `event_log.event_type` is a real PostgreSQL enum, and the three new members did not exist in it.

**Nothing in the test suite could have caught this.** `tests/` runs on SQLite, which has no enum type and stores whatever string it is handed — so all 330 tests passed against a database that would reject every one of these events. That is the same shape as the RLS gap recorded in `rls-verification-checklist-v1.md`: a guarantee that only exists in Postgres is invisible to a SQLite suite, and the failure surfaces on first contact with the real thing rather than in CI.

Migration `e6f3b8a20c47` adds the values, in an `autocommit_block` because `ALTER TYPE ... ADD VALUE` is not transactional. It has **no downgrade**: PostgreSQL cannot remove an enum value, and every way to fake one means rewriting rows in an append-only table.

The rule this establishes, now in the migration's own docstring: **adding a member to `EventType` always means adding a migration, and the check is to write one event of the new type against a real database.**

A second-order note worth having: while the stale API process was still up, it raised `LookupError: 'product_created' is not among the defined enum values` when *reading* the log, because SQLAlchemy validates enum values on read. Any process running older code breaks on a log containing newer event types. That is inherent to adding one, not a defect — but it means event-type additions are a deploy-order concern.

## 4. The frontend: what was actually wrong

Diagnosed from the code, not from taste:

- **`NodeCard.tsx:195` rendered provenance for every *unreviewed* node.** Nothing is reviewed when you arrive, so the landing state was the densest state the app could produce. The focus model existed in the spec and in the comments but not in the render.
- **`App.tsx:21` held the selected feature in component state.** No route, no back button, refresh dropped you on whichever feature loaded first, and no view could be linked to anyone.
- **Nine section headers straight off the `NodeType` enum**, including "rejected alternative" and "architecture note" — the storage schema shown to a PM.
- **`conflictMap` reports both endpoints**, correct for the review screen and wrong for a conflicts view: five conflicts drew ten banners and never put the two claims on screen together.
- **`--accent` and `--status-edited` were the same hex.** Focus ring, primary button and "edited" badge were one signal doing three jobs.
- **No auto-advance**, though flow spec §5 called for it — a progress meter that reported but nothing that carried the reviewer forward.

What replaced them: four zones (products → queue → one claim → its source), four groups instead of nine (Why / What / How / Unresolved, with the precise type kept as a tag), conflicts as objects showing both sides, real routes, auto-advance, and a token split that gives status its own family.

**Provenance leaving the card is the load-bearing change.** It now lives in its own always-visible column on a warm "paper" surface — the one warm thing in the product, so quoted material differs from Atlas's own prose in temperature and not only in typeface. Density falls and trust rises together, because the excerpt stops being the thing you have to go looking for.

## 5. Deviations from the plan

**Hand-rolled router instead of `react-router-dom`.** Four routes, no nesting, no guards, no loaders — the library would have been more surface than the problem. `router.ts` deliberately exposes the subset react-router would (`parse`, `href`, `useRoute`, `linkProps`), so swapping it in is mechanical if the route table grows teeth.

**`storage/products.py` exists after all.** The plan's `codebase-design` pass rejected it for the *projection* (a handful of lines belonging next to the feature-scope reducer, which is where they went). The write path is a different thing and mirrors `storage/confirmations.py`: three plain functions over a `Session`, shared by the CLI and the API so neither reimplements a payload shape.

## 6. Verification

330 Python tests (up from 324 — 16 new product tests, 6 new API tests), ruff and strict mypy clean across `src` and `scripts`, `verify_rls.py` still 11/11 after the migration, frontend typechecks and builds.

**12 of 13 real-browser tests pass against the live database** (the 13th needs a viewer actor, and only one member is seated). The suite was rewritten for the new screens; its actors now come from the environment, because membership is per-database and hardcoding them meant it could only ever run against the local seed — silently the one nobody was using.

Two defects the browser found that typecheck and build both called clean, continuing that suite's record:

- The `Atlas` brand is an `<a>`, and with no `color`/`text-decoration` of its own it rendered in the UA's default link blue — the one thing on screen not using the palette.
- The feature link in a conflict header sat mid-sentence instead of at the far end, reading as part of the prose rather than as the pair's identifier.

## 7. Open

- **The credential decision is not built.** Encrypted-at-rest per-product connections, the ingest endpoint, and `pipeline.py` are slice 2B, and the security amendment gets its own decision entry and a `security-review` pass then.
- **`SourceRef.external_id` is not fully qualified for GitHub nodes** — the evidence column shows `gh 111` where it should read `BurntSushi/ripgrep#111`. `IngestionRunPayload.external_id` was fixed for this in 1A′; the node-level ref was not. Pre-existing, now visible because provenance is on screen permanently.
- **Goal/requirement duplication** (2026-08-14 eval) is untouched and is now *more* visible, not less: a duplicate pair is two adjacent lines in the queue.
