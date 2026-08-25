# Atlas — brand and logo brief (v1)

**Status:** written 2026-08-22. The **mark is drawn, built and in the product**
(§3); the wordmark is specified and set in type (§7). What remains of the
deferred `brandkit` pass that `docs/tracker.md` has carried under *Next up*
since 2026-08-16 is `--brand-1` / `--brand-2` (§6).
**Name decision:** **Atlas is kept.** The collision was raised and weighed — see
§5 — and the call was to keep it.

§2 is the context block for any further generation. §3 is the mark as built,
with what was rejected on the way. §4 is the standing reject list. §7 specifies
the wordmark, which is set in type rather than generated.

**On generating this:** two rounds of image generation produced the same two
defects both times — a filled arrowhead at the convergence point, which turns
the mark into a play button, and a smudge at 16px. The mark that shipped was
drawn by hand as three SVG paths and iterated against a size ladder in a real
browser. Image tools were useful for finding the *idea*; they could not close
it, because every remaining problem was numeric.

---

## 1. What the product is (one paragraph, for the brief)

Atlas is a context-to-spec engine. It reads what a team has already written in
GitHub pull requests and Jira tickets, extracts typed claims — goals, problems,
requirements, decisions, constraints, open questions — each carrying the literal
sentence it came from and a link back to it, and has a named human confirm,
edit or reject every one. Confirmed claims assemble into a page about the
product and into a Markdown spec a coding agent can be handed. It never writes
back to any source tool. It never paraphrases evidence. When two sources
contradict each other it shows both and picks neither.

**The single sentence the mark has to serve:** *every line is checkable.*

## 2. The context block — paste this first

> **Product:** Atlas, a "context-to-spec engine" for product managers and
> engineers. It reads a team's existing pull requests and tickets, pulls out the
> decisions and requirements buried in them, quotes the exact sentence each one
> came from, and has a person confirm it. The output is a specification whose
> every line can be checked against its source.
>
> **Personality:** restrained, precise, evidentiary, quiet. Closer to a
> reference book or a law report than to a chat app. It is a tool for someone
> doing forty careful judgements in a sitting. It should feel like something
> that would not lie to you.
>
> **Visual system it must live inside:** dark canvas is canonical, light is a
> first-class second theme. Typography is Geist (variable sans) and Geist Mono.
> Colour is spent deliberately and sparingly: a single interaction blue
> (#6b7bff on dark, #4453e0 on light), a confirmation green (#3fb07a), a
> conflict amber (#e0a33c). A marketing-only gradient runs magenta #ff4d9d →
> violet #a855f7 → that same interaction blue, and always ends on the blue, so
> the brand gesture resolves into the product's real palette. One warm surface
> (#1d1a15 on dark, a warm cream on light) is reserved exclusively for quoted
> source material — in this product, **evidence has a different temperature
> from interface**, and that is its most distinctive idea.
>
> **The idea the mark must carry:** several scattered sources of knowledge —
> pull requests, tickets, review threads — converging into one specification.
> Not a map, not a globe, not a world. The subject is **convergence and
> synthesis**, drawn as flow rather than as a network.
>
> **What it must not become:** a node-and-edge network graph. That is both the
> default logo of every AI product since 2023 and, more importantly, a promise
> this product deliberately breaks — a node-link graph view is an explicit
> non-goal in three of its own design documents, on the grounds that it
> reintroduces the overwhelm the review screen exists to remove. The mark must
> not advertise a screen that will never exist.

**The previous globe/meridian glyph is retired.** `.rail__glyph` currently draws
a circle with an inner meridian — the literal reading of the name, and it says
nothing about what the product does. Replacing it is one CSS rule plus its two
uses (the rail brand and the landing demo's rail).

## 3. The mark, as drawn — settled 2026-08-22

Three lines enter from the left — a trunk and two tributaries — and one line
leaves to the right. Several sources of context converging into one spec.

    <path d="M1 8h14"/>
    <path d="M1 3h3l5 5"/>
    <path d="M1 13h3l5-5"/>

On a 16×16 grid at stroke 1.5, round caps and joins — the same grid and weight
as `icons.tsx`, so the brand and the rail's navigation glyphs are demonstrably
one family. `currentColor`, so it themes itself and needs no light/dark variant.
Asset: `docs/ux/brand/atlas-mark.svg`. Component: `frontend/src/components/Logo.tsx`.

### 3.1 What was drawn and rejected first

Four geometries were rendered at 16/18/20/24/32/64px in both themes before this
one was chosen. The rejections are the useful part:

- **Curved tributaries** bow outward and read as a *wheat sprig*. Organic, where
  this product is precise. This is also what the first AI-generated attempt
  produced, twice.
- **Four or five tributaries** close into a smudge below ~20px. The rail renders
  the mark at 16px, so anything that dies there is disqualified regardless of
  how it looks on a slide.
- **A single convergence point fills in.** Five stroked paths meeting at one
  coordinate paint a solid triangle, and the mark becomes a **play button** —
  *execute*, rather than *these came together*. The two tributaries here meet
  the trunk at the same x but never terminate on each other, so the junction
  stays open.
- **Staggered joins** (tributaries meeting the trunk at different x) read as a
  drawing error at small sizes rather than as intent.

Straight 45° diagonals survived all four tests, and read as *engineered* rather
than grown — the register the rest of the product is in.

### 3.2 Three inbound lines is not arbitrary

It is GitHub, Jira, and the third source Phase 3 adds. It stops being literal
the day there is a fourth, and by then "several" is all it has to say.

### 3.3 The "unequal source lengths" idea was dropped

The brief originally asked for incoming strokes of unequal length, on the
grounds that sources are not uniform. At 16px that variation is invisible; at
32px it reads as misalignment rather than as intent. A uniform left edge is more
confident and survives every size. Dropped deliberately, not forgotten.

## 4. Reject on sight

- **Globes, maps, compasses, meridians, a titan carrying the world.** The name
  is not the idea. Drawing the name is what produces a mark that could belong to
  a travel company.
- **Node-and-edge network graphs, constellations, molecule diagrams.** The
  cliché of the category, *and* a promise this product breaks on purpose: a
  node-link graph view is an explicit non-goal in three of its own documents.
- **Gradient-filled marks.** The gradient is a marketing surface only and must
  never enter the product's own chrome; a gradient logomark drags it in
  permanently. The mark is one colour.
- **Anything that stops working at 16px.** The rail renders it at 16px. That is
  the size that matters, not the size on the pitch deck.
- **Anything needing a light-mode and dark-mode variant that differ in form.**
  The mark is drawn in `currentColor` and inherits the theme; only the colour
  may change.
- **Letterforms, monograms, an "A".** An initial says nothing and collides with
  everything.
- **Magnifying glasses, brains, lightbulbs, robots, sparkles, chat bubbles.**
  Every AI-product logo made in the last three years.
- **Chunky filled arrows and thick tapering funnels.** That is the visual
  language of an ETL/data-pipeline vendor. This is a reading and judgement tool;
  the weight should be a hairline throughout.

## 5. On the name, recorded rather than reopened

The collision is real and was weighed before the decision to keep the name:
Atlassian ships a product called **Atlas**, and the *Atlas for Jira Cloud* app
is installed by default in every Jira Cloud plan — while Jira is this product's
second source and the demo's integration story. **MongoDB Atlas** additionally
owns developer search results for the word.

**The call was to keep Atlas**, and this brief proceeds on that basis. Recorded
here so the trade-off is legible later rather than rediscovered. If it is ever
revisited, the user-facing rename is roughly 25 strings across `LandingPage.tsx`,
`App.tsx`, `SignInPage.tsx`, `index.html` and the demo wordmark — about half a
day, fully covered by the browser suite — while the code-level rename
(`src/atlas/`, the `ATLAS_*` environment variables, the CLI binary, the
Dockerfile) touches eleven more files and changes the deployment contract. The
first is cheap at any time; the second should never happen close to a demo.

## 6. What still needs deciding after the mark exists

Per `docs/tracker.md`'s *Next up*, the brand pass owns three things and only one
of them is the logo:

1. **The mark** — this document.
2. **`--brand-1` and `--brand-2`.** The magenta/violet ramp is a placeholder,
   and the stylesheet says so at the token: *"When the deferred brandkit pass
   lands, `--brand-1` and `--brand-2` are the whole swap."* Nothing else in the
   product depends on them.
3. **The wordmark** — how "Atlas" is set beside the mark. Specified in §7.

`--accent` is **not** in scope. It means "interactive" on every surface in the
app, and changing it for brand reasons would move a functional signal.

---

## 7. The wordmark — how "Atlas" is set

**Set it in Geist. Do not draw it, and do not generate it.** The product already
ships Geist Variable, so the wordmark costs nothing, renders as live text
wherever that is wanted (selectable, theme-aware, sharp at every size), and
matches the UI by construction rather than by anyone remembering to. An AI image
model will return letterforms that *look* like a typeface and are not one — they
cannot be re-set at another size, in another string, or as text.

### 7.1 The defect this spec fixed

The two lockups disagreed, and both sized the mark wrong. **Corrected
2026-08-22**; recorded because the fix is a rule, not a value:

| | `.rail__brand` | `.landing__brand` |
|---|---|---|
| size | inherited body (15px) | 20px |
| tracking | −0.01em | −0.02em |
| mark | hardcoded 16px | hardcoded 16px |

A 16px mark beside 15px Geist is **taller than the cap height of the word it
sits with** (Geist caps ≈ 0.72em ≈ 10.8px), so in the rail the mark overpowered
the wordmark; at 20px on the landing page it was undersized. Mark height is a
function of cap height, never of a pixel constant.

The mark now sets `height: 1em`, and the arithmetic is why: its ink fills 11.5
of its 16-unit box, so 1em × 11.5/16 ≈ 0.72em — Geist's cap height. Change the
font-size and the mark follows on its own. Both lockups now carry −0.02em
tracking and a `0.34em` gap (half a cap height).

### 7.2 The specification

- **Typeface:** Geist Variable. Never Geist Mono — mono uppercase at 0.1em
  tracking is this system's *label* language (every section header wears it), so
  a mono wordmark would read as a UI label rather than as a brand.
- **Weight:** 600. 500 goes weak beside the mark at rail sizes.
- **Case:** sentence case, `Atlas`. **Decided 2026-08-22** after rendering it
  against lowercase at 15/20/34/64px in both themes. It is a proper noun, the
  personality is precise and evidentiary rather than casual, and lowercase is the
  default gesture across developer tools — the least distinctive way to spend the
  one wordmark decision that is still visible at rail size.
- **Tracking:** −0.02em at every size. One value, both lockups.
- **Mark height:** 0.72em of the wordmark's font-size — i.e. its cap height.
- **Gap between mark and word:** 0.5 × cap height.
- **Clear space:** 1 × cap height on all four sides, minimum.
- **Minimum size:** the wordmark never goes below 14px. The type floor is 12px
  and the brand should not sit on the floor. Below 14px, the mark appears alone.
- **Colour:** `currentColor`. The wordmark is ink, never the accent and never
  the brand gradient. The mark may take the accent; the word does not.

### 7.3 The `t`–`l` ligature was designed, then dropped

The brief proposed extending the crossbar of the `t` rightward to join the `l`,
so that one continuous line ran through mark and word. It was drawn, and then
abandoned for two reasons — the first fatal, the second disqualifying on its
own.

**It cannot align.** The idea was only worth anything if the mark's exit stroke
and the ligature sat on the *same* horizontal line. The mark is centred on the
cap band, so its trunk falls at half of cap height — about 0.36em above the
baseline. A lowercase `t`'s crossbar sits at the x-height line, about 0.52em.
Those are different heights, and the only ways to close the gap are to shift the
mark up until it is visibly lopsided against the capital `A`, or to drop the
crossbar until it is no longer a crossbar. The shared line was a good idea that
the letterforms do not permit.

**It reads as strikethrough.** A horizontal rule through the middle of a word
means *deleted* — and in this product specifically, strikethrough is how a
**rejected** claim renders (`.ld-settled__row.is-rejected`). A wordmark that
reads as "struck out" in a tool whose core verb is *confirm or reject* is an
accidental meaning worth more than a distinctive letterform.

So the wordmark is plain Geist 600 at −0.02em, and **the mark carries the
identity alone.** That is the ordinary arrangement for a young product — a
distinctive mark beside cleanly set type — and it has a real benefit: the
wordmark stays live text everywhere, so it is selectable, themable, and needs no
outlined-path asset that goes stale the day the type changes.

### 7.3a The flattened `A` apex, tested and not adopted

One custom move survives every rule in §7.6, and it is a genuinely good
observation: **a capital `A` in a geometric grotesque is two 45° diagonals
converging on a point** — the mark's own gesture, rotated. The mark's rule is
that the junction stays open and never fills, so flattening the apex would make
the letterform obey the mark's own law. One letter, no stroke crossing the word,
no strikethrough reading.

It does not survive the render sizes. This wordmark lives at **15px in the rail
and 20px in the landing nav**; a flattened apex at those sizes is sub-pixel. It
is barely visible at 64px in a mockup and invisible everywhere the product
actually draws it. Adopting it would mean maintaining a second outlined asset to
express a detail the application itself can never show.

**The conclusion is a size finding, not a matter of taste:** below roughly 24px,
no letterform detail reads at all. The mark carries the identity because at
these sizes the mark is the only thing that *can*. That is also why §7.2's floor
matters — under 14px the word stops earning its place and the mark stands alone.

### 7.4 What ships

Two artifacts, and they are not the same thing:

1. **The lockup SVG** — mark plus wordmark, with the `t`–`l` ligature, paths
   outlined so it needs no font. This is the asset for the landing page brand,
   the nav, a favicon set and anything marketing.
2. **Live-text rules** — the §7.2 values as CSS, for every place the brand
   appears inside the app. The ligature does **not** exist here; in-app the
   wordmark is plain Geist 600 at −0.02em. That is fine and deliberate: the
   ligature is a signature, and a signature belongs on the front door, not on
   every screen of the building.

### 7.5 Prompt content — for exploration only

Use this to *look at options*, then redraw the chosen one as vector. Do not ship
what comes back.

> Typographic wordmark exploration for a developer tool called Atlas. The word
> "Atlas" set in a modern geometric grotesque sans (Geist, Inter or similar),
> semibold, sentence case, tight negative letterspacing. Show six variations of
> one idea: the crossbar of the lowercase "t" extended to the right until it
> joins the ascender of the "l", forming a single continuous horizontal stroke
> through the middle of the word. Vary the weight, length and vertical position
> of that connecting stroke across the six. Flat black on white, no effects, no
> logomark, no background, no gradient, no shadow, no outline, no 3D. Precise
> and restrained, like a reference book or a legal document, not playful.

And for the lockup, once a mark is chosen:

> Logo lockup sheet. A minimal monoline geometric logomark on the left, and to
> its right the word "Atlas" set in a geometric grotesque sans at semibold with
> tight negative letterspacing. The mark's height equals the cap height of the
> word exactly. The gap between them is half the cap height. Show the horizontal
> lockup, the mark alone, and a clear-space diagram with margins of one cap
> height on all sides. Flat, single colour, no gradients, no shadows, no
> background texture.

### 7.6 Reject

- The word set in mono, or in all caps, or letterspaced wide — that is this
  product's section-label style and it will read as a heading, not a brand.
- Gradient fill on the letters. The gradient is a marketing-surface gesture and
  never enters the chrome; a gradient wordmark drags it in permanently.
- Any custom move on more than one letter. Two is a redesign of a typeface you
  did not commission.
- Outline, emboss, shadow, stretched or condensed letterforms, a dot over a
  letter that is not an "i".
