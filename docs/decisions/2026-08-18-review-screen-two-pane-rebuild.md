# Review screen: three fixed panes → one bar, two panes, a reflowing workspace

**Date:** 2026-08-18
**Scope:** `frontend/` only — the rail (`App.tsx`), the review screen (`ReviewPage.tsx`), the product overview (`ProductsPage.tsx`), and `styles.css`. No API, storage, extraction or schema change. One type-level fix in `api.ts` (below).
**Trigger:** user review of the running app, with screenshots. Four defects, none of which `tsc`, `vite build` or the 26-test smoke suite could see.

---

## 1. What was wrong

**(a) The rail drew no hierarchy.** Each of `Sources` and `Conflicts` sat under its own mono all-caps group heading (`CONNECT`, `REVIEW`). Every group held exactly one item, so the rail rendered as a single column of alternating type sizes — an 11px all-caps label one row above a 13px link reads as its *sibling*, not its parent. The grouping vocabulary was real (it matches the landing page and the sign-in panel); the visual encoding of it was not.

**(b) Three panes, three headers, three treatments.** The queue's header was Geist Sans 13/550 in full-strength ink. The two beside it — at the same y, at the same level of the hierarchy — were 11px mono all-caps in `--text-faint`. Three headings styled as though they came from three different applications.

**(c) The claim sat above a hole.** `.claim` was capped at `36ch` inside a ~950px pane, with `.actions` `position: sticky; bottom: 0` and a gradient over whatever it covered. On a tall display that put several hundred pixels of empty column between a claim and the buttons that rule on it — a void in the middle of the screen's one job. The evidence column ran the opposite way: a fixed 360px that was mostly empty on short excerpts and cramped on long ones.

**(d) Nothing was adjustable.** `--queue-width: 300px` and `--evidence-width: 360px` are guesses about claim length made once for every display the product will ever run on. Claims are whole sentences; the queue clipped each to two lines at 300px whether the display was 1280px or 3440px.

**(e) The product overview answered the second question, never the first.** "Overview" was a title, a one-line summary and a list of features. That answers *which feature do I open?* without ever answering *how much is there, and how much of it is mine to do?*

---

## 2. What replaced it

### 2.1 The rail
The one-item groups are gone. The three destinations are one flat block, each with a **leading glyph** (`components/icons.tsx`, six inline SVGs sharing one stroke width — not a dependency). A row with an icon reads as a destination on sight, which is the distinction the labels were failing to draw. The loop those labels named — connect, then review — survives in the **order**, which the smoke suite still asserts.

One section label is left, `FEATURES`, and it is the only one that ever had a list under it. It reads as a heading because of what surrounds it (a hairline above, its filter directly below, no sibling row wearing the same type) rather than by being smaller and fainter than everything else. It carries a count; the nav block and the feature list are pinned above the scroll so a product with forty features never scrolls its own navigation out of reach.

Each feature row gained a low-contrast **progress hairline**. The badge says how much is left, which is a different question: "20 to go" means one thing on an untouched feature and another on one nearly through.

### 2.2 The review screen
```
┌──────────────────────────────────────────────────────────────────┐
│ bar   [⧉]  feature title · assembled from gh jr   25/27 ▓▓▓░  ⚠ 8│
├──────────────┬───────────────────────────────────────────────────┤
│ queue        │ workspace — a card stack that reflows             │
│ (resizable,  │  ┌─ THE CLAIM ─────────┐  ┌─ WHERE IT CAME FROM ┐ │
│  collapsible)│  │ claim (hero)        │  │ excerpt (paper)     │ │
│              │  │ ✓ Confirm ✎ ✕       │  └─────────────────────┘ │
│              │  └─────────────────────┘  ┌─ ALSO FROM THIS SRC ┐ │
│              │  ┌─ ⚠ conflict ────────┐  │ …                   │ │
│              │  └─────────────────────┘  └─────────────────────┘ │
│              │  ┌─ RELATED ───────────┐                          │
├──────────────┴───────────────────────────────────────────────────┤
│ j/k move · o open source · c confirm · e edit …      [ hide list  │
└──────────────────────────────────────────────────────────────────┘
```

- **One bar, one sans heading.** The feature's name, the "assembled from" source strip (speced in `design-system-baseline-v1` §6.6a and never built — the screen whose argument is cross-source assembly never said what it had been assembled from), the progress meter, and the conflict count as an amber pill. Progress moved here from the queue's foot because it is a fact about the *feature*, not about the list's current filter.
- **Every card wears one head treatment.** `THE CLAIM`, `WHERE IT CAME FROM`, `RELATED`, `ALSO FROM THIS SOURCE` all resolve to `.card__title`, via one `CardHead` component. This is the structural fix for (b): a heading is no longer something each pane styles for itself, so they cannot drift apart again by anyone forgetting to match them. Colour is the one thing that varies, and only on the paper card, whose label takes the `--paper-*` family to stay legible on the product's one warm surface.
- **Claim and evidence are grid siblings, not fixed panes.** On a wide workspace they sit abreast — the adjacency the entire trust model rests on — and on a narrow one they stack. Driven by a **container query** on the workspace (`container-name: work`), not a viewport media query, because the workspace's width is now something the reviewer sets by dragging. A media query would have held the two-column spread while someone squeezed the pane to 400px.
- **The rulings follow the claim.** `.actions` is inside the claim card. `.claim` also carries `min-height: 4.14em` (three lines): a one-line claim stops rendering as a snippet in a shrink-wrapped card, and — the reason it is there — the buttons stay put while you walk the queue with `j`.
- **Edges sit with the claim, not with the receipts.** What a claim rests on is a fact *about* the claim; the excerpt is the evidence *behind* it. Left column is the claim and its neighbourhood, right column is the paper trail.
- **The queue is resizable (220–620px, drag or ← →, double-click to reset) and collapsible (`[`).** Both persist to `localStorage` — a width you re-drag on every navigation is a worse default than the constant it replaced. `--queue-width` and `--evidence-width` are deleted.
- The group headers in the queue are `position: sticky` inside their `.qsection` wrapper, and claims clamp at three lines rather than two.

### 2.3 The product overview
Four figures and a meter above the worklist: **Features · Claims extracted · Needs review · Unresolved conflicts**, then `N of M claims reviewed` with a `Review next →` into the most urgent feature, then the existing worklist as the dive-in.

Every number is `ScopeCounts` off the projection — the same datum the rail badges, the Conflicts nav entry and the review bar read. Nothing is derived a second way, which is the failure mode a dashboard invites; the smoke suite asserts the conflict tile and the rail badge agree.

Colour goes on the **figure**, never on the tile. A tinted panel reads as an alert, and a backlog is not an alert: a draft awaiting a person is this product's normal resting state (Engineering Philosophy §2). Amber stays reserved for the one thing that really is a decision nobody has made.

The one-line summary (`4 features · 8 conflicts · 26 claims to review.`) restated all four tiles immediately above it and now renders only when there are no figures to show.

---

## 3. Type scale

One addition: **`--text-2xl: 30px`**, for the dashboard's stat figures and nothing else. A count meant to be taken in at a glance is not a heading, and borrowing `--text-xl` for it made four figures read as four small headings. The 11px floor from `2026-08-16-typography-drift-correction.md` is unchanged and still asserted.

---

## 4. One type-level fix outside the UI

`api.ts` declared `Node` as `Populated<schemas["Node"], …> & { source_refs: SourceRef[] }`. Intersecting leaves the property as `RawSourceRef[] & SourceRef[]`, and `.map` over that resolves to the *first* signature — so a ref read back off a node arrived un-narrowed and every consumer had to re-assert `id`. Now `Omit`-ed before being re-declared, matching the shape `FeatureScopeDetail` was already using for `nodes`/`edges`.

---

## 5. What this deliberately did **not** do

No graph canvas (explicit non-goal in three documents; `RELATED` stays a clickable list). No ⌘K command surface (still v1.x — ⌘K still focuses the rail filter). No new endpoint, no new state library, no spec-export or Q&A surface. Nothing about the extraction agent, the event log or the projections.

---

## 6. Verification

`tsc --noEmit` and `vite build` clean. **30/30 Playwright tests pass** against the live API, including four new ones that guard exactly the defects above:

| Test | Guards |
|---|---|
| `every label on the review screen belongs to one type system` | (b) — asserts every `.card__title` shares one computed size/weight/tracking/transform/family, and that there is exactly one `.rv__title` |
| `the claim and its evidence are adjacent, and the rulings follow the claim` | (c) — evidence starts to the right of the claim card at 1600px, and `.actions` sits inside the claim card's box |
| `the claim list can be resized and got out of the way` | (d) — ← → widens it, `[` removes it, and the width survives a reload |
| `the product overview says how much there is before which one to open` | (e) — four tiles in order, and the conflict tile equals the rail's badge |

Two pre-existing tests were **excluded from this run** (`confirming advances…`, `…recedes in the queue`): they click Confirm, and this database is the shared one — the same warning `docs/tracker.md` already carries. Their assertions (`.claim` text changes, `.qitem--confirmed`, `.status--confirmed`) all target markup that survived the rebuild unchanged.

Checked by hand in both themes, at 1180px and 1680px, with the queue expanded and collapsed: no console errors, and the light theme's palette verified by sampling rendered pixels (`rail: rgb(241,242,245)`) rather than by eye.

## 7. Still open

- `docs/ux/confirmation-flow-spec-v1.md` and `design-system-baseline-v1.md` §6.9 describe the three-zone layout and should be re-read against this before the next UI change; the baseline's §6.6a "assembled from" strip is now actually built.
- `docs/tracker.md` was **not** refreshed in this session: another session was concurrently editing `CLAUDE.md`, `docs/prd/` and `src/atlas/`, and overwriting the tracker in place mid-flight would have clobbered it.
