# Product Info Page + Spec Export v0

**Status:** planned 2026-08-21. Supersedes nothing; extends slice 4 of
`docs/decisions/2026-08-19-product-orientation-rerun-safety-and-demo-data.md`.

## 1. The finding

A newcomer opening a product in Atlas gets a **work queue**. `/p/{id}` is the
worklist — *Needs your ruling* over *Settled* — and the only orientation above it
is the two-line `Orientation` strip slice 4 added. There is nowhere in the product
that answers *what is this product, what does it do, what has been decided about
it*. That is a strange gap in a tool whose entire thesis is "coding agents and
people are starved of correct context": Atlas ingests context and renders a
review queue over it, and never renders the context itself.

It is also a gap in the loop's reward. Today, confirming a claim makes it
**disappear** into *Settled*. Nothing anywhere gets better as a result. A reviewer
has no reason to believe the work accumulated into anything.

## 2. The shape: authored spine + derived body

Two halves, and the split is the whole design.

**Authored spine** — what the product is, in the PM's words. This already exists
as `Product.description` (event-sourced via `product_described`, blank-clears,
2000 chars, PM-authored per decision 4 of the 2026-08-19 doc). The info page gives
it room rather than a two-line clamp. Still authored, still not a Node, still
carries no provenance, still cannot reach an export as a claim.

**Derived body** — the features, and beneath each the **confirmed** goals,
problems, requirements, constraints, decisions, rejected alternatives and open
questions, each carrying its literal `SourceRef` excerpt and URL.

The derived half is why this is not a hand-written page that rots. It is a
projection: it updates itself as claims are confirmed. The authored half is the
part a machine should never write, for the reason `Orientation`'s header already
states — an extracted summary would be a *claim about the product*, obliged to
start unconfirmed.

## 3. Why this is spec export's little brother

Roadmap v2's Phase 2A is: confirmed nodes -> Markdown -> inline provenance, with
unresolved conflicts surfaced as open disagreements rather than silently resolved.

That is the derived body, with a different output format. Building the info page
builds ~70% of spec export's machinery — and builds it *on screen*, where being
wrong is visible, rather than inside a file nobody reads until the Phase 2 proof
run. So the two ship together, sharing one assembly step.

This is a deliberate pull-forward of Phase 2A, and the justification is that the
info page pays for the machinery regardless. **Nothing else from Phase 2 moves,
and nothing from Phases 3-4 moves at all.** In particular: doc-as-a-source stays
in Phase 3 (see §7).

## 4. The assembly module

New module `src/atlas/assembly.py`, passed the `codebase-design` gate 2026-08-21.

    assemble(projection: Projection, product_id: UUID) -> ProductDocument
    to_markdown(doc: ProductDocument) -> str

Two plain functions. **No renderer protocol, no builder class** — the skill's
flagged anti-pattern for exactly two variants. `ProductDocument` is defined in
`assembly.py` itself, matching `ConnectionView` in `connections.py` and `Run` in
`projections.py`: the module that produces a type defines it.

Why its own module rather than `api/` or `storage/projections.py`:

- **Not `api/`** — CLAUDE.md's module boundary says `api/` holds no domain logic.
  Ordering, omission and disagreement rules are domain logic.
- **Not `projections.py`** — that module replays the log into *state*. `Projection`
  is state; `for_product` and `counts_for` narrow state. A document is an
  *interpretation* of state, with editorial decisions in it.
- **The real argument is the filter, not reuse.** Assembly is the one boundary
  where unconfirmed must not pass (Philosophy Sec2). The frontend already pairs
  conflicts in TypeScript (`frontend/src/review.ts`). If the page filters in React
  and the export filters in Python, they drift — and the drift is an export
  containing drafts. One place, one test.

Assembly **consumes** a `Projection` and never extends it. Nothing is stored: the
document is derived on read like every other projection. Caching it would be a
materialized view no event invalidates.

## 5. The rules assembly enforces

1. **Confirmed only.** `CONFIRMED` and `EDITED` are both rulings and both appear;
   `UNCONFIRMED` and `REJECTED` do not. An info page showing drafts is Philosophy
   Sec2 violated on the most-read screen in the app.
2. **Every line carries its excerpt and URL.** A rendered claim without its
   `SourceRef` is the same bug class as a Node without one.
3. **An unresolved `conflicts_with` is shown as an open disagreement**, with both
   sides, never silently resolved by picking one — TRD Sec5.2, and roadmap v2's
   wording for spec export. Confirming one side does not close it.
4. **A feature with no confirmed claims still appears**, saying so. Omitting it
   would hide work from the person who has to do it.
5. **Document order is fixed and type-driven**, not log order: goal -> problem ->
   evidence -> requirement -> constraint -> decision -> architecture note ->
   rejected alternative -> open question. Evidence and architecture notes take
   **fixed positions** rather than being attached to the claims they `supports`.
   Following those edges would read better and is deliberately not built:
   edge-walking machinery for a nicety is structure ahead of a need, which the
   `codebase-design` checklist is explicit about. A test asserts the order tuple
   covers every `NodeType`, so a tenth type is given a position on purpose.

## 6. Routes and navigation

Settled 2026-08-21: **`/p/{id}` stays the worklist.** A returning reviewer's first
question is "what is mine to do", and that answer was correct.

The info page is a new route `/p/{id}/about`, added to the in-product nav as a
fourth entry (`About - Overview - Conflicts - Sources`). The `Orientation` strip on
the worklist becomes a link into it. The guided tour routes through About first,
so a newcomer meets orientation before the queue.

Rejected: making `/about` the default at `/p/{id}` (breaks the tour anchors,
`lastProduct` forwarding, existing links and the browser suite's route
assertions), and adapting the landing screen per-visitor (needs per-user-per-
product state and produces a screen that changes under you — untestable and
undemoable).

`tests/test_static.py` reads `frontend/src/router.ts` and fails when the SPA route
table and the API's explicit route list drift, so the new route must be added in
both places.

## 7. Doc upload — deliberately NOT built

The request that prompted this was "at product creation, ask for the PM's PRD and
take info from there". Taking claims from an uploaded doc **is the third source**,
which CLAUDE.md and roadmap v2 both place in Phase 3. It is not a form field: an
uploaded file has no URL, so `SourceRef` semantics need rework, plus dedup against
existing nodes and three-way conflict detection. Built under demo pressure, the
failure mode is fabricated provenance — the exact thing this product exists to
prevent.

The line: **does it produce Nodes?** If yes, Phase 3.

The permitted version, if time survives the slices below: paste a doc, get a
*drafted authored description* you then edit and own. Plain prose, no Nodes, no
provenance, no extraction path — the same category `Product.description` already
is. It is a new LLM call path, so it carries the `writing-evals` obligation before
it counts as done. Lowest priority of everything here, and largely redundant once
the derived body exists.

## 8. Slices, in order

1. ~~**`assembly.py` + `ProductDocument`, test-first.**~~ — **done 2026-08-21.**
   19 tests, one per rule in Sec5 plus the ordering and cross-feature cases.
2. ~~**`GET /products/{id}/document`**~~ — **done 2026-08-21.** Thin: load
   projection -> `assemble` -> return. Calls `load_projection` directly rather
   than via `_require_product`, which loads a projection and discards it — a
   replay is the expensive thing on this path.
3. ~~**`/p/{id}/about`**~~ — **done 2026-08-21.** Authored spine (reusing
   `Orientation`), derived body, provenance always visible, disagreements as
   objects. `app.py` needed no change: `/p/{rest:path}` already covered it.
   Added to the rail between Overview and Sources, and as the guided tour's
   closing step — the tour previously ended on the queue, which said what the
   work *is* and never what it produces.
4. ~~**`to_markdown` + export.**~~ — **done 2026-08-21.** Copy and download from
   the About page; `GET /products/{id}/spec`. Phase 2A v0.
5. **← NEXT. Slice 6, carried from the 2026-08-19 doc** — a dedicated workspace
   for the browser suite. Independent of the above and still the tracker's NEXT;
   it is a live demo risk, since the suite mutates the shared log the demo runs on.
6. *(if time)* Paste-a-doc drafting, per Sec7.

## 9. Known costs

- **A third full replay per navigation.** `/about` re-replays the whole event log,
  on top of the ~2.9s slice 4 recorded against remote Supabase. Expect About to be
  the slowest screen. Recorded here rather than solved; the fix is not a cache.
- **Demo content is written through the API, never hardcoded.** The Plausible
  Analytics description goes in via `PUT /products/{id}/description` or a script in
  `scripts/`, following the tour's rule: a feature, not a demo prop. Nothing about
  the demo product may be literal-strung into the frontend.
