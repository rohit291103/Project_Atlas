# Product info page + spec export v0

**Date:** 2026-08-21
**Plan:** `docs/architecture/product-info-and-spec-export-v1.md`
**Touches:** new `src/atlas/assembly.py`, two API endpoints, new `/p/{id}/about` route and page, `frontend/src/api.ts`, `styles.css`, `icons.tsx`, `router.ts`, `App.tsx`

## 1. The finding that started it

A newcomer opening a product in Atlas got a **work queue**. `/p/{id}` is the
worklist; the only orientation above it was the two-line `Orientation` strip
slice 4 added. Nothing anywhere answered *what is this product, what does it do,
what has been decided about it*.

That is a strange gap in a tool whose thesis is that people and coding agents are
starved of correct context: Atlas ingested the context and rendered a queue over
it, and never rendered the context itself.

It was also a gap in the loop's reward. Confirming a claim made it **disappear**
into *Settled*. Nothing got better as a result, so a reviewer had no evidence the
work accumulated into anything.

## 2. Authored spine + derived body

The page has two halves and the split is the design.

**Authored spine** — `Product.description` and `FeatureScope.description`, the
PM-authored fields slice 3 added. Prose, not claims: no provenance, no
confirmation loop, and nothing here can reach an export as a fact. The page gives
them room instead of a two-line clamp, and reuses the same `Orientation` control
so there is one way to write them, not two.

**Derived body** — the **confirmed** claims, grouped by feature and by type, each
carrying its literal `SourceRef` excerpt and a link to the artifact.

The derived half is what stops this being a document that rots. It is a
projection: it updates itself as claims are confirmed. The authored half is the
part a machine must never write, for the reason `Orientation`'s own header
already gives — an extracted summary would be a *claim about the product*,
obliged to start unconfirmed.

## 3. Why spec export shipped in the same change

Roadmap v2's Phase 2A is *confirmed nodes → Markdown → inline provenance, with
unresolved conflicts surfaced as open disagreements rather than silently
resolved*. That is the derived body with a different output format.

Building the page builds the export's machinery either way. Shipping both from
one assembly means the property that matters is structural rather than
aspirational: **whatever the page shows is what the file contains**, because
neither re-decides what "confirmed" means. Doing the export later would have
meant writing that filter a second time, in a second place, with the first one
already drifting.

This is a deliberate, bounded pull-forward of Phase 2A. Nothing else from Phase 2
moved and nothing from Phases 3–4 moved at all.

## 4. `assembly.py` — the `codebase-design` verdict

A new module, and the gate was run before scaffolding it.

Public surface is two plain functions:

    assemble(projection, product_id) -> ProductDocument
    to_markdown(doc) -> str

**No renderer protocol, no builder class.** The checklist is explicit that a
strategy pattern for exactly two concrete variants is the abstraction to skip; if
a third format ever appears, that is the moment to reconsider.

Why not somewhere that already exists:

- **Not `api/`** — CLAUDE.md's module boundary says `api/` holds no domain logic,
  and ordering, omission and disagreement rules are domain logic.
- **Not `storage/projections.py`** — that module replays the log into *state*.
  `Projection` is state; `for_product` and `counts_for` narrow state. A document
  is an *interpretation* of state, with editorial decisions in it.

**The load-bearing argument is the filter, not code reuse.** Assembly is the one
boundary where an unconfirmed claim must not pass (Philosophy §2). The browser
already pairs conflicts in TypeScript (`frontend/src/review.ts`); had the page
filtered there and the export filtered in Python, the two would eventually have
disagreed, and the disagreement would be an export full of drafts. One place, one
test file.

`ProductDocument` is defined in `assembly.py` itself, matching `ConnectionView`
in `connections.py` and `Run` in `projections.py`: the module that produces a
type defines it. FastAPI serializes the frozen dataclasses directly, so the
generated TypeScript types come free.

## 5. The five rules, and the two that were not obvious

1. **Confirmed only.** `CONFIRMED` and `EDITED` both appear — an edit *is* a
   ruling, and a stronger one than a bare confirm. `UNCONFIRMED` and `REJECTED`
   do not.
2. **Every line carries its excerpt and URL**, reproduced verbatim. Editing an
   excerpt for presentation corrupts provenance exactly as surely as editing it
   at extraction would.
3. **An unresolved `conflicts_with` is shown as an open disagreement**, both
   sides, never resolved by picking one.
4. **A contested claim is absent from the settled body.** ← not obvious
5. **A feature with no confirmed claims still appears**, saying how much is
   waiting. Omitting it hides work from the person who has to do it.

**Rule 4 is the interesting one.** A claim under live dispute appears *only*
inside its disagreement, never in the sections above. That makes "not silently
resolved" structural rather than editorial: a reader cannot mistake a contested
claim for settled fact, because it is not in the settled list at all.

**What makes a disagreement live** is the other non-obvious decision. Confirming
one side does not resolve a conflict (TRD §5.2) — only **rejecting** the other
side does, because rejection is the act that says which side lost. So a
disagreement stands while neither endpoint is rejected, and it is rendered with
**both** sides including an unconfirmed one, each labelled with its status.
Dropping the unruled side would silently resolve the conflict in favour of
whichever side happened to be confirmed first, which is precisely what roadmap v2
forbids of an export. A conflict between two *drafts* is not a document
disagreement at all: nobody has ruled, so it is still review work and belongs on
the Conflicts screen.

**Say what is missing.** Both outputs state the count of claims withheld for want
of a ruling, and state the one exception (a draft contradicting a confirmed claim
does appear, as a disagreement). A document that silently omits half its material
is worse than a short one that says how short it is.

**Cross-feature disagreements are not dropped.** `counts_for` keeps an edge only
when both endpoints are in the scope, which is right for a badge and wrong for a
document. A disagreement files under the from-side's feature and names the other
side's, so nothing is lost.

**Document order is type-driven, not log order:** goal → problem → evidence →
requirement → constraint → decision → architecture note → rejected alternative →
open question. It reads as an argument. A test asserts the tuple covers every
`NodeType`, so a tenth type has to be given a position deliberately rather than
sorting to the end by accident. Evidence and architecture notes take fixed
positions rather than being attached to the claims they `supports` — edge-walking
for a nicety is structure ahead of a need.

## 6. Routes

**`/p/{id}` stays the worklist.** A returning reviewer's first question is "what
is mine to do", and that answer was correct. About is a new route
`/p/{id}/about`, added to the rail as a fourth entry between Overview and
Sources — the two *reading* destinations together, leaving connect-then-review as
the order of everything below.

Rejected: making About the default at `/p/{id}` (breaks the tour anchors,
`lastProduct` forwarding, existing links and the suite's route assertions), and
adapting per-visitor (per-user-per-product state, and a screen that changes under
you is neither testable nor demoable).

`app.py` needed no change: `/p/{rest:path}` already covers the new URL, and
`tests/test_static.py` confirms the two route tables still agree.

## 7. Two defects found by looking at the rendered output

Both were wording, both were caught by reading real output rather than by a test:

- **The banner repeated per pair.** One claim can be in several disagreements at
  once — it really can contradict two different things — so the explanatory line
  appeared six times in one section and buried the claims it was meant to frame.
  It now sits once under the heading, with the pairs numbered. Fixed in the
  Markdown first and then, after a screenshot, in the page.
- **"Nobody has ruled yet" was false.** On the live data both sides of most
  disagreements are confirmed. What makes them unresolved is §5's rule, not an
  absence of rulings. Reworded in both renderers.

Also corrected: the header claiming withheld claims "are not included" while the
disputed one *was*.

## 8. The download filename is a security surface

The product name is user-supplied and lands in a `Content-Disposition` header,
where a quote or a newline is a header-injection primitive rather than a cosmetic
problem. `_spec_filename` builds the name from a **whitelist** (alphanumerics,
everything else to `-`), and a test creates a product literally named
`evil"; filename="x.sh` and asserts the header still carries exactly two quotes,
no newlines and no second directive.

## 9. Verification

- **521 Python tests** (up from 488), `mypy src scripts tests` clean, ruff clean.
  19 new tests in `tests/test_assembly.py` covering all five rules; 13 new in
  `tests/test_api.py` covering auth, 404, the confirmed-only rule over the wire,
  page-and-export agreement, and the header-injection case.
- **Verified live against Supabase, read-only.** The `ripgrep` product assembles
  into 17 confirmed claims and 6 disagreements across 4 features, and the
  Markdown export is 133 lines carrying real cross-source disagreement — the
  GitHub PR asking to *stay consistent with GNU find* against the Jira decision
  *explicitly not to*. That is the product's whole thesis, rendered from real
  public text.
- **Rendered in a real browser, both themes**, against the built SPA served from
  the API's own origin. The demo product shows the honest empty state (0
  confirmed, 55 awaiting review) with `Review 55 claims →` as the next action.

**What is NOT verified:** the four new Playwright tests have never run. The
browser suite does not complete in this environment — a **pre-existing** test
hangs identically, so this is not a regression from this change, but it does mean
the new browser coverage is unexercised. See § Open.

## 10. Doc upload — deliberately not built

The request that prompted this work was "at product creation, ask for the PM's
PRD and take info from there". Extracting claims from an uploaded doc **is the
third source**, which CLAUDE.md and roadmap v2 both place in Phase 3. It is not a
form field: an uploaded file has no URL, so `SourceRef` semantics need rework,
plus dedup against existing nodes and three-way conflict detection. Built under
demo pressure, the failure mode is fabricated provenance.

The line: **does it produce Nodes?** If yes, Phase 3.

The permitted version, still unbuilt and lowest priority: paste a doc, get a
*drafted authored description* you then edit and own. Plain prose, no Nodes — the
same category `Product.description` already is. It is a new LLM call path, so it
carries the `writing-evals` obligation before it counts as done, and it is
largely redundant now that the derived body exists.

## 11. Open

- **The four browser tests are unrun**, and so is the rest of the suite, in this
  environment. Worth diagnosing before the demo, independently of this change.
- **`/about` is a third full log replay per navigation.** Measured at ~1.2s
  against remote Supabase for the demo product, on top of the ~2.9s slice 4
  recorded for a describe round-trip. Recorded, not solved — the fix is not a
  cache, because a stored document is a materialized view no event invalidates.
- **The demo's About page is empty until claims are confirmed.** That is correct
  behaviour and a good narrative (review → the page fills → export it), but it is
  a *choice* whether to pre-confirm a subset so the page is populated when the
  demo opens. Needs the user; nothing was pre-confirmed, because a confirmation
  is real, irreversible and attributed.
- **A stale API process on :8000** predates this change and lacks both new
  endpoints. Anything demoed against it will 404 on About.
