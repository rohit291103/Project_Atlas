# Decision Log — A Guided First Run, and What It Cost to Add

**Date:** 2026-08-21
**Area:** ux / frontend

## Context

Slice 5 gave the demo a product a PM recognises. Watching it, the gap that
remained was not the data: a first-time visitor lands on a rail, a grid of four
numbers and a three-pane review screen, and nothing on any of them says which
part matters first, or why the two quotes side by side are the point.

The user asked for a step-by-step highlight walkthrough — "after logging in, the
highlighted part goes to our product, some info, then the user clicks that, then
it shows around the page" — covering the storyline of the new demo product.

## Decisions

1. **It is a product feature, not a demo prop.** Offered the choice between
   hardcoding it to the Plausible product ids (faster, sharper copy) and
   anchoring it to the UI so it runs anywhere, the user chose the latter. Every
   step names a `data-tour` attribute and a route; no step names a product or
   feature id. The same tour runs on the demo, on ripgrep, and on the first
   product a PM connects themselves.

2. **The storyline is the product's argument, in order.** A product → what it is
   → how much is waiting → one feature → one claim → *where that claim came
   from* → the two sources that disagree → your ruling. Ten steps. The order is
   not arbitrary: it is the same order the PRD makes its case in, and each step
   only makes sense once the one before it has landed.

3. **A missing anchor skips the step.** Plenty of products have no conflict to
   show and no description written yet. Pointing at nothing, or waiting forever,
   are both worse than moving on — and this is what makes "runs on any product"
   true rather than aspirational.

4. **The spotlight does not capture clicks.** `pointer-events: none` on the
   cut-out, so the highlighted control is still usable and clicking it advances
   the tour exactly as *Next* does. Being shown a button you cannot press is a
   strange way to learn an interface.

5. **Shown once per browser, replayable from the rail.** localStorage, like
   `lastProduct` — whether *this browser* has seen it is not a fact about the
   workspace. Replayable because a demo is given more than once, and a PM being
   measured may want a second look.

6. **The browser suite opts out, explicitly.** See below.

## What it cost, and what that revealed

Three defects, each of which is a fact about this codebase rather than about
tours:

- **A conditional hook (React #310).** The tour's target was computed with
  `useMemo` placed after `App`'s early returns, so the hook count varied between
  renders and the tour never opened at all. Fixed by making it a plain
  expression: everything below those returns is hook-free territory, and that is
  now stated in a comment where the next person will hit it.

- **An effect keyed on an object that is rebuilt every render.** `tourSteps()`
  returns fresh step objects, so an effect depending on `step` restarted the
  anchor hunt — and blanked the spotlight — on every parent re-render, which
  happens whenever the rail refreshes. Keyed on `id|anchor|route` instead.

- **The tour broke all 23 existing browser tests.** Every Playwright context
  starts with empty storage, so the tour opened in each of them and navigated to
  the product chooser, breaking the shared `signIn` helper. The suite now marks
  the tour seen in a `beforeEach` — the same move it already makes with
  `X-Atlas-Automated`: a machine declaring what it is. Onboarding is for people.
  The two tour tests clear the flag themselves, so the behaviour is tested
  rather than hidden.

**The anchors are the fragile part**, and deliberately so: a step whose element
is missing skips itself, which means deleting a `data-tour` during a refactor
silently shortens the tour and nobody notices until a demo. `ui-smoke.spec.ts`
therefore walks every step and asserts each one found something to point at.

**A behaviour worth knowing:** the first step lives on the product *chooser*, so
the tour navigates there — which cleared the active product and silently
switched the walkthrough to whichever product was first in the list. The tour now
holds the product it was opened from and adopts whichever card the reviewer
actually clicks.

## Bearing on the Phase 1 exit criterion

The criterion is *a PM outside the build team, unassisted, under 20 minutes*.
An in-product tour is not a person helping — it is the product explaining
itself, and shipping onboarding is the ordinary answer to "a new user does not
know where to look". But it does change what is being measured, and the honest
thing is to say so **before** the measurement rather than after: the run should
record whether the PM took the tour, and the 20 minutes should include it.

## Not done

- **No tour on the Sources screen.** Connecting a source is the other half of
  the exit criterion, and it has no walkthrough. Deferred deliberately: the
  storyline asked for was about reading the assembled result, and a tour that
  tried to cover both would be twice as long at the moment attention is
  shortest.
- **No copy variation by role.** A viewer sees the same steps as an editor,
  including the ruling step, which they cannot act on.
