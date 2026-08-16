# Landing page: a scoped brand identity, and the loop as a diagram

**Date:** 2026-08-16
**Touches:** `frontend/src/pages/LandingPage.tsx`, `frontend/src/components/landing/loop.tsx` (new), `frontend/src/styles.css`, `frontend/tests/ui-smoke.spec.ts`
**Prompted by:** the user, pointing at arize.com as the visual reference — its hero gradient and use of space, its demo section, its continual-learning-loop diagram, and its Observe/Evaluate/Improve rows.

## 1. The problem the restyle actually fixes

The landing page's *substance* was already right after the 2026-08-16 rebuild: live product DOM instead of prose, one real worked example, no invented customers. What it was wearing was the app's own chrome — hairline borders, 13–15px type, ink-only restraint, `--accent` as the single spot of colour. That is exactly correct for a review screen a PM sits inside for twenty minutes, and it is the wrong instrument for a page a stranger gives eight seconds.

Marketing surfaces and work surfaces want opposite things from one design system. The review screen spends its entire colour budget on **status and conflict** (design-system-baseline-v1 §2.3–2.4) and can afford nothing else. The page in front of it is allowed one confident gesture, because that gesture *is* the job.

## 2. What was decided

**A landing-scoped brand identity**, declared on `.landing` and unreachable from any screen behind the sign-in wall:

```
--brand-1: #ff4d9d   magenta
--brand-2: #a855f7   violet
--brand-3: var(--accent)   ← the product's real interaction blue
```

The ramp runs magenta → violet → **`--accent`**. That third stop is not a fourth brand colour; it is the exact blue the primary button in the app already is. The marketing gesture therefore *resolves into* the product's palette rather than promising a differently-coloured application — which is the specific way a gradient landing page usually lies about the software behind it.

This is a partial, deliberate early landing of what `design-system-baseline-v1.md` §9 defers to a `brandkit` pass ("the placeholder `--accent` and typeface get replaced at the brand pass"). **`--accent` itself was not touched**, no in-product screen changed, and the whole swap when brandkit lands is two hex values in one block. The baseline's rule — accent as punctuation, status and conflict own the colour budget — still holds everywhere it was written to hold.

Enforced, not merely asserted: the four new primitives (`.action--brand`, `.action--lg`, `.pill`, `.display`) are declared as `.landing .x`, so using them elsewhere does not silently pick up undefined tokens.

**A loop diagram** (`loop.tsx`) — the one section on the page that is a picture rather than a screen. Ring geometry is `r=30` in a 0–100 viewBox with the four node cards positioned at the same radius in percentages of a square container, so ring and cards stay locked together at any width with no measurement. Under 900px it linearises into a vertical rail, because a circle of four cards on a phone is four cards and an invisible circle.

**Three acts became three questions.** "Point it at one feature" → "What exactly is Atlas allowed to read?"; "Claims, each with its receipt" → "Where did this claim actually come from?"; "One claim at a time, and your name on it" → "Who decided this was true?". Answering the question a PM arrives with is a stronger claim than naming a feature.

## 3. The honesty constraint, and where it bit

Two places where the reference layout wanted something Atlas cannot back:

**The logo wall.** Arize's hero is followed by "Powering the world's leading AI teams" and eleven customer logos. Atlas has no customers. That slot now holds **sources** rather than companies — and labels four of the six (`Linear`, `Notion`, `Slack`, `Confluence`) as *not built yet*, in the markup, visibly. The same slot, the same visual weight, zero implied claims. The metrics band ("1 Trillion spans processed") has no honest analogue at all and was dropped rather than invented.

**The fourth node of the loop.** A four-step cycle wants to close with "Atlas assembles your spec" — which is Phase 2 (root `CLAUDE.md`), and would have been a lie told in the most memorable element on the page. The fourth node is **Hand off**, which describes what the confirmed set already *is* and what a person does with it, and the return arc credits the closing of the loop to the team's own work landing as new pull requests and tickets. That is a real cycle and it claims nothing unbuilt.

## 4. Verification

- Typecheck + build clean; no console errors; no horizontal overflow at 1440px or 430px.
- Rendered and inspected in a real browser at 1440×1000 in **both** dark and light, and at 430px — the light theme deepens `--brand-1/2` and cuts the glow opacities, because a violet bloom that reads as "lit" on `#0c0d11` reads as a smudge on `#fafafb`.
- Three landing smoke tests pass. Two needed updating for markup that genuinely changed: the refusals copy (`It never writes back.` → `Never writes back.`) and the hero's primary-button class (`.action--primary` → `.action--brand`). Both assertions keep their original intent.

## 5. Not done

- The `brandkit` pass proper — logo/wordmark are untouched; `.rail__glyph` is still the placeholder mark.
- No `frontend-reviewer` pass has been run over this yet.
- The before/after section's two columns still have unequal heights, leaving dead space under the shorter one. Pre-existing, unrelated to this change.
