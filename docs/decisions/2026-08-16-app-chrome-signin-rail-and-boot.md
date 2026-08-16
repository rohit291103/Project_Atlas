# App chrome: the sign-in split, the grouped rail, and a boot screen

**Date:** 2026-08-16
**Touches:** `frontend/src/pages/SignInPage.tsx`, `frontend/src/App.tsx`, `frontend/src/components/Loading.tsx` (new), `frontend/src/styles.css`, `frontend/tests/ui-smoke.spec.ts`
**Prompted by:** the user, pointing at Arize AX's sign-in page, its post-login sidebar, and its branded loading state.
**Follows:** `2026-08-16-landing-brand-identity-and-loop-diagram.md`, which introduced the brand ramp on the marketing page only.

## 1. The brand ramp moved from `.landing` to `:root`

The previous decision scoped `--brand-*` to `.landing` and said so in a comment, because nothing behind the sign-in wall had a use for it. Three surfaces now do — the sign-in panel, the boot screen, and the rail's mark — so the tokens are declared once at `:root` and the light overrides sit in both light blocks alongside every other token.

**What did not move is the discipline, which is the part that mattered.** The rule is now stated in the token block itself:

> Brand appears in **chrome** — the mark, the rail's group labels and selected rule, the sign-in panel, the boot screen. It never encodes a **claim, status, confidence pip or conflict**. Those families own the content area and their colours are load-bearing (design-system-baseline-v1 §2.3–2.5).

That line was tested against a real case immediately: the rail's new "Work left" meter reports *reviewed*, which is a status fact, so it is painted `--status-confirmed` and not the ramp — even though the ramp would have looked better there. The rail's *selected nav* rule did move from `--accent-soft` to a brand inset bar, which is the opposite case: a selected row in the chrome is not a status, and freeing `--accent` there stops the rail competing with the primary button on the screen it just opened.

## 2. Sign-in

A brand panel beside a form column. The panel is not decoration — it carries the three promises (read-only, provenance, draft-not-fact) that the previous version put in a right-hand rail, because the moment before someone hands over a source credential is the moment to state them. The restyle compressed them to a line each; it did not drop them.

Two things the reference layout wanted and Atlas will not fake:

- **An OAuth row.** There is no Google or GitHub sign-in — the only credential is the shared passphrase (`Phase1_Architecture.md` §10). Buttons that don't work are worse than buttons that aren't there.
- **A customer logo wall.** The bottom strip lists *sources* instead, with the unbuilt ones marked "soon" — the same rule the landing page runs on.

## 3. The rail

Grouped by the loop the product actually runs, rather than as a flat list of three screens:

```
Atlas
[product switcher]
[filter features            ⌘K]
  Overview
CONNECT   → Sources
REVIEW    → Conflicts (n)
FEATURES  → the feature list
─────────────────────────────
WORK LEFT   Reviewed 21 / 51
            Conflicts 8 unresolved
─────────────────────────────
[avatar] Rohit / editor      ☾
All products         Sign out
```

Three decisions inside that:

**No third "Extract" group.** The loop has three verbs and the rail has two groups, which is deliberate: extraction is triggered from the Sources screen and has no screen of its own. A nav heading over nothing is a promise of a screen that doesn't exist — the same constraint that made the landing page's fourth loop node "Hand off" instead of spec assembly.

**The filter is a filter, not a command palette.** `design-system-baseline-v1` §8 defers ⌘K-as-command-surface to v1.x and that still holds. What the rail needed once a product holds more features than fit on screen is a filter over the list, and ⌘K focuses it — a shortcut that lands somewhere real beats one that opens a surface we haven't built. Escape clears it.

**The work block replaces a usage meter.** Same placement a SaaS rail gives "Spans 0/25k", but the number a PM opens Atlas to find. Every figure comes from `ScopeCounts` on the projection — the same source the badges and the Conflicts screen read — so the rail cannot disagree with the screen it opens.

## 4. Boot screen

`App` rendered `<div className="entry" />` while the session check was in flight. That was a *correct* decision (don't bounce a returning reviewer to `/signin` during the moment we don't yet know who they are) rendered as a blank page — and on a cold load against a remote database, that blank is the entire first impression and is indistinguishable from a broken one. It is now the Atlas mark stroked in the ramp inside a travelling-arc ring, the same visual language as the landing page's loop diagram. The dash geometry lives in CSS so the global `prefers-reduced-motion` rule can stop it; when it does, the ring is still a ring and the label still says what is happening.

## 5. Verification

- Typecheck + build clean; no page errors; no horizontal overflow at 1440px or 430px.
- Sign-in, rail, and boot inspected in a real browser in dark **and** light. The boot state was captured by delaying `/session`, since it is otherwise on screen for ~200ms.
- Browsing was done as **`Viewer (demo)`** deliberately: a viewer cannot confirm, edit or reject, so inspecting the live workspace could not mutate the event log.
- Smoke suite: one existing assertion needed updating (nav order is now Overview / Sources / Conflicts, because the groups reordered it), and one test was added covering the filter and the ⌘K binding.

## 6. Not done

- **The main content area is still mostly empty** on the product home — the pre-existing finding already deferred in `2026-08-16-product-context-and-work-left-counts.md`. The rail got denser; the screen beside it did not.
- No `frontend-reviewer` pass over any of this.
- The `brandkit` pass proper: `.rail__glyph` is still the placeholder mark, and there is still no wordmark.
- **The suite's environment is a trap and was hit here.** With `ATLAS_TEST_EDITOR` / `ATLAS_APP_PASSPHRASE` unset, it silently falls back to the *local seed's* actors (`Priya (PM)` / `letmein`) and runs them against whatever database `.env` points at — which produced 20 failures that looked like page defects and were an unseated name. The fallback should fail loudly instead of guessing, and the suite still needs its own workspace (already tracked).
