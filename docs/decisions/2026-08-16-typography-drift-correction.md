# Decision Log — The type scale was never the design's fault; the build drifted from it

**Date:** 2026-08-16
**Area:** ux / frontend
**Amends:** `docs/ux/design-system-baseline-v1.md` §4 — adds one token (`--text-micro`), and records that the implementation had not been following the section it documents.

---

## Context

The app read as faint and unfinished — text too small, too light, in too many places. The instinct was that the design system needed rethinking.

It did not. `docs/ux/design-system-baseline-v1.md` §4 already specified the right thing, and the stylesheet had quietly shipped something else.

| | Documented (§4) | Actually shipped |
|---|---|---|
| `--text-xs` | 12 | **11** |
| `--text-sm` | 13 | **12.5** |
| `--text-base` | 15 | **14** |
| `--text-lg` | 18 | **17** |
| `--text-xl` | 24 | **23** |
| Weight | 400 body, **500 labels/tags**, 600 headers | 22 weight declarations in a 1,700-line sheet; the 500 rule effectively absent |

Every step was ~1px under spec. Below the token layer it was worse: **42 of roughly 90 `font-size` declarations bypassed the scale entirely** to hardcode `10px` or `10.5px`. The densest and most-read screen in the product was therefore rendered almost wholly between 10px and 12.5px.

And the colour those small sizes were painted in failed accessibility outright:

| Token | Contrast before | WCAG AA (4.5:1) |
|---|---|---|
| dark `--text-faint` | 3.64:1 | fail |
| light `--text-faint` | 3.06:1 (2.85 on `--sunken`) | fail |
| light `--paper-dim` | 3.85:1 | fail |

`--text-faint` was the token used *at 10–11px* — the worst available pairing of size and contrast.

---

## Decisions

### 1. The scale returns to what the design system already specified

`12 / 13 / 15 / 18 / 24`, exactly as documented. No redesign, no new proposal — the spec was right and the build is now following it.

### 2. One new token: `--text-micro: 11px`

Uppercase mono labels read visually larger than their nominal size because of the capitals and letter-spacing, so 11px is honest for a section label and dishonest for a sentence. `--text-micro` gives those labels a legitimate home instead of leaving 10px hardcodes as the de-facto answer.

**It is the only thing permitted below 12px, and it is never used for anything read as prose.** 12px is the floor for everything else.

*This token is an addition to `design-system-baseline-v1.md` §4 and should be reflected there.*

### 3. Weight becomes a token, and small text actually gets it

`--weight-normal: 400` / `--weight-medium: 500` / `--weight-semibold: 600`. Every rule rendering at `--text-micro` (42 of them) plus the interactive surfaces — nav, queue rows, buttons, switcher — now take `medium`, restoring §4's documented rule. Geist is a variable font, so 500 costs nothing to load.

"Small, dim and 400" was the actual mechanism behind "too light". Size alone was only half of it.

### 4. The failing colours were solved for, not eyeballed

Each failing token was walked along its own hue until it cleared 4.5:1 against **every** surface it appears on, rather than being nudged by taste:

| Token | Before | After |
|---|---|---|
| dark `--text-faint` | 3.64:1 | **4.53:1** |
| light `--text-faint` | 3.06:1 | **4.56:1** |
| light `--paper-dim` | 3.85:1 | **4.51:1** |

All text tokens now meet WCAG AA.

### 5. A test enforces the floor, because a doc did not

`no text on the review screen renders below the 11px floor` walks every element owning text on the real review screen and asserts its **computed** font size. A new component hardcoding `font-size: 10px` now fails in CI.

This is the substantive lesson: §4 was correct and ignored for weeks with nothing to catch it. A written scale is not a constraint, it is a suggestion, until something fails when the build disagrees with it.

---

## Not done (deferred)

- **`design-system-baseline-v1.md` §4 has not been edited.** `/ux` docs are permanent under root `CLAUDE.md`'s Documentation Rules, so the `--text-micro` addition and a note about the drift are recorded here and should be folded into the doc (or a `v2`) deliberately rather than as a side effect of a CSS pass.
- **Line-heights were not revisited.** §4 specifies 8px-aligned line-heights per step; only sizes and weights were corrected. Worth a pass.
- **Excerpt monospace sizing.** §4 says excerpts run one step below surrounding claim text; not verified against the current build.
- **The review screen's ~600px of dead vertical space.** Layout, not type.
