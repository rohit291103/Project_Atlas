# The landing page's demos, rebuilt against the screen they claim to be

**Date:** 2026-08-22
**Touches:** `frontend/src/components/landing/demos.tsx` (rebuilt), `loop.tsx`,
`pages/LandingPage.tsx`, `styles.css`, `tests/ui-smoke.spec.ts`

## 1. The finding

The landing page's demos are **live DOM**, not screenshots, and the header
comment in `demos.tsx` gives three good reasons: the app has three themes and a
PNG has one; every value is a token from the same stylesheet, so the demo cannot
drift from the product's palette; and it stays sharp at any width.

All three are true and all three are about **colour**. Nothing in that argument
stops a demo drifting on **layout**, and it had — three times over:

1. **The review screen was rebuilt** (`ReviewPage.tsx`, "the shape now"): one
   title bar over a queue and a reflowing card stack, with evidence a *card
   beside the claim* rather than a fixed third column. The demo still drew the
   three fixed panes that rebuild replaced.
2. **The rail's one-item group labels were deleted** — `CONNECT` over `Sources`,
   `REVIEW` over `Conflicts` — in favour of glyph-led destinations. `icons.tsx`
   argues the case at length. The demo still drew the labels.
3. **`About` was added to the rail** on 2026-08-21 and was missing from the demo
   entirely, so the page showed a loop with no output.

A landing page showing a layout the product no longer has is *worse* than one
showing a still: the still at least dates itself.

## 2. What the frame now mirrors, structure for structure

| Demo | Real screen |
|---|---|
| `ld-rail` — Overview · About · Sources · Conflicts, glyph-led, no group labels | `App.tsx` §rail |
| `ld-rvbar` — feature, what it was assembled from, progress, conflicts | `ReviewPage.tsx` §`rv__bar` |
| `ld-queue` — three views, then claims under plain-English group headings | `QUEUE_VIEWS` and `GROUPS` in `review.ts`, verbatim |
| `ld-work` — the card stack: claim + rulings, the disagreement, opposite them the receipt and the rest of the thread | `ReviewPage.tsx` §`rv__stack` |

Two things the demo *stopped* drawing: the fake window title carrying the
feature name (the application has no such bar; it has `rv__bar`, which the demo
now draws instead), and the bottom fade. The fade existed because the old
three-pane layout was genuinely taller than the box; the card stack ends where
its content ends and the shortcut row is pinned with `margin-top: auto`, so
there is nothing left to crop — and the shortcut row, which the crop used to eat
on narrow displays, is now always on screen.

The chrome bar survives, minus its title, because the play/pause control has to
live somewhere. It carries the **route the app really serves** —
`atlas.app/p/ripgrep/f/preprocessor-flag` — which is a claim worth making: every
screen in Atlas has an address you can send someone.

## 3. Four tabs that argue four different things

The strip has always named the four claim types. Every tab opened the same
picture with a different sentence in it — four screenshots of one screenshot. A
reader who clicks **Constraint** is asking what a constraint *is* and why Atlas
bothers typing it, and showing them the same frame answers neither.

Each claim now carries a **`lens`** (one sentence: what this type is, ending at
what is worth looking at) and a **`spot`** naming the region of the frame that
makes the point. The named region gets `is-spot` — a ring in `--brand-2` rather
than `--accent`, because the accent means *interactive* everywhere else in the
app and nothing in the demo is.

| Tab | Spotlight | The argument |
|---|---|---|
| Requirement | the receipt | typed as a requirement only because a source says it outright — so it arrives with the sentence |
| Decision | the disagreement | a choice in a thread nobody re-reads, contradicting the ticket; both held up, neither picked |
| Constraint | *Also from this source* | a limit mentioned in passing, one line deep in a 34-comment thread — here is what else that thread held |
| Open question | the *Unresolved* group | Atlas will not answer it; it lifts it out of the thread and keeps it |

Four tabs, four different arguments, one screen.

## 4. The page now shows what confirming is *for*

Until `/p/{id}/about` and `GET /products/{id}/spec` shipped on 2026-08-21,
confirming a claim made it disappear into a settled list and the product had no
output — so the page honestly stopped at "confirm". It doesn't stop there now.

New full-width section `#spec`, after the three acts. Two panes: the About page,
which is a projection over confirmed claims and therefore writes itself, and the
same assembly as Markdown, which is what an agent is handed. Full width rather
than a fourth act, because the two panes *are* the argument and an act column is
~420px — at that width the Markdown wraps every line twice and stops looking
like a file.

**`#how` stays "Three steps, about twenty minutes".** Connect / extract /
confirm is the twenty-minute loop; the export is not a fourth thing you do, it
is what you are left with, and the section is titled accordingly.

## 5. What is deliberately still not claimed

`loop.tsx`'s fourth node used to describe only what the confirmed set *was*,
because spec assembly was Phase 2 and unbuilt — a node reading "Atlas generates
your spec" would have completed the circle more neatly and been a lie. It
shipped, so the node now says what the product does: confirmed claims assemble
into a page and a Markdown spec, quotes and links intact.

**The effect is still not claimed, anywhere.** That handing an agent this file
measurably improves what it writes is Phase 2's proof and has not been run. The
node and the section describe the artifact, never the outcome. The counts in the
demo (17 confirmed of 43, 26 awaiting, 6 open disagreements) are the real export
of the ripgrep validation product, not invented.

## 6. Defects found by looking at the render

- **The frame inherited `.showcase`'s centring**, so the claim, the excerpt and
  the edges all set centred — which no screen in the application does. A
  screenshot that centres its body text is the tell that it is not a screenshot.
  `.ld-frame { text-align: left }`.
- **`.ld-rail { display: none }` never applied.** The hide rule sat in a media
  query *above* the base `display: flex` at equal specificity, so source order
  won and the rail stacked itself full-width above the review screen below
  1180px — a pre-existing bug, visible only once the frame was measured at seven
  widths. Now qualified as `.ld-app .ld-rail`.
- **"0 settled claims hidden"** on the opening frame: the app renders that row
  on `hidden > 0` and the demo rendered it unconditionally.
- The rail's work row ran its label into its figure (`Reviewed0 / 4`).

## 7. Responsive behaviour, in the order things are given up

Measured at 1600 / 1440 / 1280 / 1100 / 900 / 700 / 480; frame height stays
between 605 and 756px and the page never scrolls horizontally.

1. **≤1180** the rail goes — it is context, and context is what you drop first.
2. **≤900** the queue goes, and the shortcut row with it.
3. **≤780** the stack collapses to one column and the two `aux` cards (*Related*,
   *Also from this source*) go: five cards in a column is a frame taller than
   the phone reading it.

The claim and its receipt side by side is the last thing to be given up, because
it is the product's whole trust argument.

## 8. Tests

One existing assertion was **legitimately** invalidated: it clicked the queue's
second row to reach the conflicting claim, and the queue is now grouped the way
the app groups it, so a claim's position is a property of its *type*. It selects
by text now, which is what it always meant.

Three new tests, each pinning something that actually drifted:

- the rail's four destinations and the queue's three group headings, so the next
  time the app moves and the demo doesn't, something fails;
- exactly one `is-spot` per tab, and four distinct lens sentences — a second
  spotlight would point the reader at two things at once, which is the same as
  pointing at nothing;
- the `#spec` section carries provenance in both halves and lists the unsettled
  disagreement rather than picking a side.

## 9. Note on tooling

`npx prettier --write` was run on these files and **reverted**. The repo has no
prettier dependency and no config; `.editorconfig` declares `indent_size = 4`
while the frontend is authored at 2, so prettier reindented ~3,400 lines of
`styles.css` and buried the real diff. The stylesheet was reindented back to the
repo's own convention and the two TSX files restored from HEAD and re-edited.
**Don't run prettier in this repo** until someone decides to adopt it, config
and all, as its own change.
