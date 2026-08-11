# Atlas Design System — Baseline (v1)

**Status:** Proposal / first draft. Nothing here is settled truth until validated in a real build (root `CLAUDE.md`). This is the reusable visual foundation for the Phase 1 confirmation UI (`Phase1_Architecture.md` §5–6, slice 1B); the screens that consume it live in `confirmation-flow-spec-v1.md`.

**Decisions this doc is built on** (settled with the user 2026-08-03 → 2026-08-11):
- **Base design system: Vercel/Geist + Linear review density** (settled 2026-08-11 after a benchmark of Linear / Vercel / Mercury). Geist supplies the foundation — **dark as the canonical surface**, "**ink is the brand**" restraint (greys do the work, accent used *like punctuation*), fine 1px borders + soft minimal shadows, a mix of sharp small radii and pill controls, and the **open-source Geist Sans + Geist Mono** typefaces. Linear supplies the **review-loop patterns** on top — dense scannable rows, keyboard-first navigation, subtle fast motion. The two are complementary (both dark, monochrome, restrained). Reference: `docs/research/2026-07-28-competitive-linear-and-ui-direction-v1.md` + the 2026-08-11 benchmark.
- **Neutral system now, brand identity later.** Typeface is now settled (Geist Sans/Mono, open source — no longer a placeholder). What stays deferred to a dedicated `brandkit` pass is the Atlas **logo/wordmark and brand accent**: the single `--accent` value below is still a **placeholder** to swap when brand lands. Following Geist, accent is used sparingly, so that swap touches very little.

Where Atlas legitimately diverges from a pure Geist/Linear system: the confirmation UI must encode **status, confidence, provenance, and conflict** simultaneously without noise. Geist's near-zero-color restraint makes that *harder*, not easier — so those four semantic encodings are designed deliberately below (color **paired with shape**, so they survive Geist's monochrome discipline), not borrowed.

---

## 1. Principles

1. **Low cognitive load.** One scan direction, one subject per view, minimal choices per screen. Perceived speed comes from reduced choice, not just performance.
2. **Provenance is a first-class visual citizen.** The literal source excerpt + deep-link is Atlas's signature component, not a footnote. It gets deliberate typographic treatment (§4, §6).
3. **Status is the core state machine, shown honestly.** `unconfirmed` is the default and must read as "awaiting you," never as an error. Confirmed/edited/rejected are visually distinct at a glance, and never encoded by color alone (colorblind-safe: color + icon/shape).
4. **Keyboard-first.** Every core action (confirm/edit/reject/add/open-source/navigate) has a shortcut; the mouse is optional. A command surface (⌘K) is a v1.x target, not v1.0-blocking.
5. **Theme-aware, dark-native.** Designed dark-first; light theme is a first-class token swap, not an afterthought.

---

## 2. Color

Defined as tokens. Dark is the primary design target; light is a full remap of the same roles. **Do not hard-code any raw hex in components — reference the role token.**

### 2.1 Neutrals (dark theme, primary)
| Role | Token | Value (placeholder) | Use |
|---|---|---|---|
| Background | `--bg` | `#0B0C0E` | App canvas |
| Surface | `--surface` | `#141619` | Cards, panels |
| Surface (elevated) | `--surface-2` | `#1C1F24` | Hover, popovers, active card |
| Border | `--border` | `#2A2E35` | Crisp 1px hairlines |
| Border (strong) | `--border-strong` | `#3A404A` | Focus rings, dividers that matter |
| Text (primary) | `--text` | `#ECEEF1` | Claim text, headings |
| Text (secondary) | `--text-2` | `#A6ADB8` | Metadata, labels |
| Text (muted) | `--text-3` | `#6B7280` | Timestamps, disabled |

### 2.2 Accent (single, placeholder — brand swaps this)
| Token | Value | Use |
|---|---|---|
| `--accent` | `#5B8DEF` | Primary action, selection, focus, links |
| `--accent-weak` | `rgba(91,141,239,0.14)` | Selected-row tint, accent backgrounds |

One accent only, and — following **Geist's "accent as punctuation"** — used *sparingly*: greys and the ink text do almost all the work. The accent appears on the primary action, the selection/focus rule, and links, and essentially nowhere else. This restraint is also why swapping it at the brand pass is nearly free.

### 2.3 Semantic — status (the state machine)
Color is always paired with an icon/shape so it survives colorblindness and greyscale.
| Status | Token | Value | Icon/shape | Reads as |
|---|---|---|---|---|
| `unconfirmed` | `--status-unconfirmed` | `--text-2` (neutral) | hollow dot `○` | "Awaiting you" — the calm default, **not** alarming |
| `confirmed` | `--status-confirmed` | `#3FB950` (green) | check `✓` | Human-affirmed |
| `edited` | `--status-edited` | `#5B8DEF` (info) | pencil `✎` | Human-modified (links to `previous_content`) |
| `rejected` | `--status-rejected` | `--text-3` + strike | `✕` | De-emphasized, kept in log, filtered from future spec |

**Deliberate call:** `unconfirmed` is neutral grey, not amber. Everything starts unconfirmed; an amber default would make the whole first screen read as a wall of warnings and destroy the calm.

### 2.4 Semantic — conflict (the one loud thing)
| Token | Value | Use |
|---|---|---|
| `--conflict` | `#E5A03A` (amber) | `conflicts_with` banners + edge markers |
| `--conflict-bg` | `rgba(229,160,58,0.12)` | Conflict banner background |

Conflict is a differentiator — surfaced prominently, never auto-resolved (TRD §5.2). It is the *only* element allowed to visually shout.

### 2.5 Confidence (quiet, monochrome)
Confidence is **not** color-coded — it would clash with status. It's a 3-pip monochrome indicator (`●●●` / `●●○` / `●○○`) mapping the three extraction levels (0.9 / 0.6 / 0.3), plus `—` for manual `created_by=user` nodes (no score, per TRD §6). Rendered in `--text-2`; tooltip gives the exact value.

### 2.6 Light theme
Same roles, remapped: `--bg #FFFFFF`, `--surface #F7F8FA`, `--surface-2 #EEF0F3`, `--border #E2E5EA`, `--text #1A1D21`, `--text-2 #565D67`, `--text-3 #8A929D`. Semantic hues darken ~one step for contrast. Ship dark first; light is a token file, not a redesign.

---

## 3. Spacing, radii, borders, elevation

- **Spacing:** strict 8px scale — `4` (tight inline only) · `8` · `12` · `16` · `24` · `32` · `48` · `64`. Tokens `--space-1..8`. This single rule buys most of the "calm/consistent" feel.
- **Radii:** modest — `--radius-sm 4px` (pills, tags), `--radius-md 8px` (cards, inputs), `--radius-lg 12px` (modals). Nothing pill-round except status/type chips.
- **Borders:** crisp 1px hairlines (`--border`); borders do the separation work, not heavy shadows.
- **Elevation:** soft, sparing. `--shadow-1` (popover/hover), `--shadow-2` (modal). Faux-depth via subtle surface steps, not big drop shadows.

---

## 4. Typography

- **UI + claim text:** **Geist Sans** (open source; the de-facto dev-tool sans, geometric + neutral). Claim text is the **hero** — it's what the PM reads to decide. (Settled, not a placeholder — Geist Sans is the chosen typeface.)
- **Excerpts (provenance):** **Geist Mono** (open source). This is intentional — a verbatim quote from the source is *evidence*, not our prose, and monospacing it makes that categorical difference legible at a glance. It's the visual heart of the trust model, and using Geist's own mono pairs it precisely with the Sans. Fallback stack `ui-monospace, monospace`.
- **Scale (1.25 ratio, 8px-aligned line-heights):**
  | Token | Size / line | Use |
  |---|---|---|
  | `--text-xs` | 12 / 16 | Metadata, timestamps, pip labels |
  | `--text-sm` | 13 / 20 | Secondary UI, type tags, edge refs |
  | `--text-base` | 15 / 24 | **Claim text — the hero** |
  | `--text-lg` | 18 / 28 | Section headers (node-type groups) |
  | `--text-xl` | 24 / 32 | Feature-scope title |
  - Excerpt monospace runs one step down from surrounding claim text (13/20) so evidence reads as subordinate to the claim.
- **Weight:** 400 body, 500 labels/tags, 600 headers. Bold is declarative and rationed.

---

## 5. Motion

Subtle, fast, functional. Transitions `120–160ms`, ease-out. Motion *confirms an action* (a card settling into `confirmed`, a rejected card collapsing) — it never performs. No bounce. `prefers-reduced-motion` respected: cross-fades collapse to instant state changes.

---

## 6. Core components

Each is a small, single-purpose component (Linear's "many small components over a rigid grid"). Full interaction detail is in `confirmation-flow-spec-v1.md`; this is the visual contract.

### 6.1 Node card — the primary object
Anatomy, top to bottom:
```
┌────────────────────────────────────────────────┐
│ [TYPE tag]              [●●○ confidence]  [○ status] │   ← header row
│ Claim text — the hero, --text-base, 2–3 lines max   │
│ ⚠ conflicts with "…" (if any) — --conflict banner   │   ← only when present
│ ▸ "literal source excerpt…"  ↗ source   (collapsed) │   ← provenance block
│ ↳ implements R2 · depends_on D1     (edge refs)     │   ← only when present
└────────────────────────────────────────────────┘
        ↑ hover/focus reveals: [✓ confirm] [✎ edit] [✕ reject]
```
- Selected card: `--accent-weak` tint + `--border-strong` left rule.
- Rejected card: collapsed to a single struck line, `--text-3`, expandable.

### 6.2 Type tag
Small `--radius-sm` chip, `--text-sm` 500, neutral surface. One per node vocabulary type (Goal, Problem, Requirement, Decision, Constraint, Open Question, Architecture note, Evidence). Type is neutral-colored — status/conflict own the color budget.

### 6.3 Status indicator
Icon + label per §2.3. Icon alone in dense rows; icon+label on the card header.

### 6.4 Confidence pips
`●●●`/`●●○`/`●○○` or `—`, `--text-2`, per §2.5.

### 6.5 Provenance block (signature component)
Collapsed by default to one monospace line with a `▸` expander and an always-present `↗ source` deep-link (opens the exact PR/issue/comment anchor in a new tab). Expanded: full excerpt, still monospace, in a subtly inset well (`--surface-2`, left accent hairline). For manual nodes, this block instead reads "Asserted by <actor>" with the typed claim (the `human_assertion` SourceRef — `docs/decisions/2026-08-03-manual-node-provenance.md`).

### 6.6 Conflict banner
`--conflict-bg` fill, `⚠` + "Conflicts with <type> — <short excerpt>", links to the other node. The one deliberately prominent element. When the conflicting node comes from a **different source**, the banner names that source (e.g. "Conflicts with a Decision **in Slack**") — cross-source conflict is Atlas's headline capability and is shown off, not softened.

### 6.6a Source badge + "Assembled from" strip (multi-source)
A small monochrome-with-muted-tint mono badge marks where a claim came from: `gh` (GitHub), `jr` (Jira), `sl` (Slack), `gd` (Google Docs), `@` (email), `you` (a `human_assertion` manual node). Tints are low-saturation brand cues — recognizable but calm, and *below* status/conflict in the color budget. It appears on the node header and inside each provenance line. A node with several `SourceRef`s shows **multiple badges + "N sources"** (corroboration across tools). The feature-scope header carries an **"Assembled from" strip** of source chips (which repo/channel/doc/inbox feeds this feature), making the scope legible as a cross-source *assembly*, not a single artifact. Live vs. roadmap sources are tagged honestly. Rationale + the feature-first (never source-first) rule: `docs/decisions/2026-08-11-confirmation-ui-design-direction.md` and the flow spec's "cross-source model".

### 6.7 Action affordances
Confirm / Edit / Reject as icon-buttons revealed on hover/focus, mirrored to keyboard (`c` / `e` / `x`). Confirm is accent-filled; reject is quiet (destructive-but-reversible — last-write-wins means undo is free, so reject needn't be scary).

### 6.8 Section header
Node-type group header (`--text-lg` 600) with a count and an unconfirmed-remaining badge, e.g. "Requirements · 4 · 2 to review".

### 6.9 Global chrome
Left rail: workspace → feature scopes list. Top bar: feature-scope title + a **progress meter** ("6 of 10 reviewed") — the 20-minute exit criterion made visible. Keyboard-hint footer.

---

## 7. Accessibility floor (non-negotiable in v1)
- Never status-by-color-alone (§2.3 pairs every status with a shape).
- WCAG AA contrast on text (`--text` on `--surface` verified; light theme too).
- Full keyboard operability; visible `--border-strong` focus ring on every interactive element.
- `prefers-reduced-motion` and `prefers-color-scheme` both honored.

---

## 8. What this deliberately does NOT include (Phase 1 scope discipline)
- **No graph visualization.** Edges render as inline text refs (§6.1); a node-graph canvas is Phase 2+ over-scope.
- **No brand identity** — logo, wordmark, brand accent deferred to a `brandkit` pass (§intro).
- **No spec-export / Q&A surfaces** (Phase 2–3).
- **No connector-marketplace UI** — the minimal connect-two-sources surface is speced in the flow doc for slice 1C/1D; the granular per-page version is Phase 2+.
- **⌘K command palette** is a fast-follow (v1.x), not a v1.0 blocker — the core loop must be complete without it.

---

## 9. Open items feeding the build
- The placeholder `--accent` and typeface get replaced at the brand pass — components must reference tokens so that swap is one file.
- App-level auth entry (`Phase1_Architecture.md` §10 Q2) is still unsettled — the login/entry surface is out of this baseline until it is.
- This baseline must be consumed by the `codebase-design` pass on the `api/` + frontend boundary before any component is scaffolded (`Phase1_Architecture.md` §5 gate).
