# Decision Log — Product as a context, and the work-left count that feeds three surfaces

**Date:** 2026-08-16
**Area:** product / architecture / storage
**Amends:** `src/atlas/api/routes.py`'s module docstring rule *"still absent: grouping, **counting** and progress endpoints"* — see §3.

---

## Context

The screen a PM lands on after signing in was an inventory, not a worklist. It listed the products that exist — a fact the PM already knows — and listed them twice, because the left rail already carried every product *and* every feature underneath it. Roughly 85% of the viewport was empty, and nothing on screen answered the only question someone opens this app to answer: **what needs my judgement today?**

The data to answer it already existed. On `Max depth option` alone there were 27 claims, 10 unreviewed and 8 caught in disagreements — none of it visible until two clicks down.

The shaping question was settled by an example from the user: a PM who owns **Google Meet and Google Keep**. Those are not two rows of one list. They are two different jobs — different repos, different Jira sites, different teams, different stakeholders. That observation killed the first proposal (a flat cross-product worklist), because it would have put a Meet conflict next to a Keep conflict and forced a re-orientation on every row.

---

## Decisions

### 1. A product is a context you are inside, not an item in a list

The rail now scopes to exactly one product. Switching is a deliberate act, not an ambient condition.

This is what the product model already claimed and the UI contradicted. `ProductsPage` says out loud: *"Each product has its own sources — its own GitHub org, its own Jira site — and its own features. Nothing crosses between them."* The rail crossed between them, permanently, by listing ripgrep's four features and Slice 2B's three interleaved in one column.

Concretely:

- **`ProductSwitcher`** (`frontend/src/components/ProductSwitcher.tsx`) sits at the top of the rail, above everything it scopes. It is a menu rather than a `<select>` because entries carry state a native select cannot render; Escape, click-outside and focus-return are therefore implemented deliberately.
- **In-product nav** — Overview · Conflicts · Sources — sits above the feature list. **Conflicts previously had no link anywhere in the UI** and was reachable only by typing the URL, which for the product's headline capability was a strange place to hide it.
- **Cross-product remains reachable but secondary.** "All products" is a real screen, not a redirect target.

### 2. Sign-in reopens the product you left, and `/app` is never hijacked

`frontend/src/lastProduct.ts` remembers the active product per browser and restores it on the next sign-in. With one product a chooser is never shown; with two and no history the chooser is the honest answer, because guessing drops the PM into the wrong job half the time.

Two constraints that are load-bearing rather than incidental:

- The remembered id is **re-checked against the products that actually came back**. A deleted product degrades to the chooser, never to a screen pointed at something gone.
- **Only a fresh sign-in forwards.** Visiting `/app` directly always shows All products. Redirecting unconditionally would make the helpful default a cage with no way out — the failure mode that turns "smart" navigation into a trap.

It is `localStorage`, deliberately not the session cookie: which product you were reading is a per-browser convenience, not a fact about identity, and it must never be something the client can use to influence what the server shows it. The workspace boundary stays the server's business.

### 3. Work-left counts live in the projection, which amends the "no counting" rule

`ScopeCounts` (`total` / `unreviewed` / `conflicts`) and `Projection.counts_for()` now live in `storage/projections.py`, surfaced as `FeatureScopeRow.counts` on `GET /feature-scopes`.

`routes.py` explicitly listed counting as deliberately absent, on the grounds that it would move a UX decision into the backend. **That rule is amended rather than waved away, and the line it draws is narrower than it read:**

> *How many claims are unreviewed* is a fact about stored state — the same kind of fact as a node's status. *How to group, order and draw them* is a choice about a screen. The first belongs in `storage/`; the second stays in the frontend, where `docs/ux/confirmation-flow-spec-v1.md` §3.2–3.3 already fixes it.

What forced the change: three surfaces need the identical figure — the rail's per-row badge, the `Conflicts (n)` nav entry, and the product dashboard. The alternative was shipping every claim and excerpt of every feature to the browser purely to count them, with the definition of "unreviewed" copied into three components that would drift.

`ScopeCounts` is deliberately **not** a field on the `FeatureScope` dataclass: that dataclass is the scope's *identity* — what its UUID means — and identity does not change when someone confirms a claim.

### 4. A conflict is counted once, not once per side

Two rules, both chosen so a badge agrees with the screen it links to:

1. **Count edges, not endpoints.** The review screen intentionally reports both endpoints so either card can raise a banner (`review.ts::conflictMap`). A count doing the same renders five disagreements as ten — the same double-counting that made conflicts read as noise in the pre-slice-2B build.
2. **An edge belongs to a scope only when both endpoints do**, matching the rule `for_feature_scope` already applies. A conflict reaching a node in another feature is real, but it is not this feature's number, and showing it would send a reviewer to a screen where it does not appear.

**Rejected claims drop out of the conflict count.** Rejecting one side is how a person settles a disagreement; a number that no action can ever clear is worse than no number.

This surfaced a live inconsistency: the review footer said "8 in conflict" (claims) while the new rail badge said "6 conflicts" (disagreements). Both were correct and the pair was confusing. The footer now reads **"8 claims in 6 conflicts"**, naming both figures rather than showing one that silently contradicts the other.

### 5. The product home is a worklist, ordered by what is owed

`Needs your ruling` leads, sorted **conflicts first, then backlog size**; everything already reviewed drops to a quiet `Settled` list underneath. A conflict outranks a backlog because an unreviewed claim is work, whereas a conflict is a decision nobody has made — and it is the one thing no single source tool could have shown you (TRD §5.2).

Two consequences elsewhere:

- Rail rows swapped source badges (`gh·jr`) for work state. What a PM navigates on is how much is left, not which tool fed it; the sources are still named on the feature and its cards, and the swap gave the title ~30px back before it truncates.
- The product-home header lost its `Sources & runs` and `Conflicts across this product` links, which the rail nav now supersedes — keeping them meant Conflicts appeared twice on one screen with two independently-derived counts.

---

## Not done (deferred)

- **Breadcrumb and a per-screen primary action.** The switcher already names the active product persistently, which was the urgent half; a `Product › Feature` breadcrumb on the review screen is still worth having and is not built.
- **Icons on the nav triple.** Cheap, low risk, modest payoff — not attempted.
- **⌘K command surface.** `docs/ux/design-system-baseline-v1.md` §1 already calls it a v1.x target. It solves a scale problem Atlas does not have at a handful of features per product, and Phase 1's risk is comprehension, not navigation speed.
- **A setup checklist on the product home** (Connect · Ingest · Review as stateful cards). Considered and rejected: it is onboarding furniture that is permanently complete after week one, occupying the most valuable band of a screen the PM opens every day. If built, it should appear only while setup is genuinely incomplete.
- **A "recent runs" section.** Runs are machine activity; the PM's question is what needs *them*. Failed runs and runs that produced new claims belong in the worklist as exceptions, with a quiet "last synced" line — not a peer section mirroring a log.
- **Cross-product signals.** "One of my other products has a failed run" is worth knowing without switching, and is intended as a badge on the switcher rather than a merged list. Not built.
- **The review screen's empty space.** Roughly 600px of dead vertical space remains in both the claim pane and the evidence column. Layout, not data — untouched by this pass.

---

## Incident recorded during this work

Running the Playwright UI suite against the **live** Supabase workspace confirmed **6 real claims** as `Rohit` that no human had ruled on. `Max depth option` went from 15-of-27 reviewed to 21-of-27.

This is not reversible, by design — `ReviewPage` states it: *"a claim can't return to 'to review'. The log only moves forward."* Nothing was fabricated or deleted; real claims were marked confirmed without a person deciding, which is precisely the guarantee this product exists to make trustworthy.

**The suite drives a shared, mutable event log** (`playwright.config.ts` says so) and needs its own workspace before it runs again. Until then the two mutating tests — `confirming advances…` and `a reviewed claim recedes…` — must be excluded when pointing the suite at live data.
