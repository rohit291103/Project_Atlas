# Competitive Read: Linear — and the Atlas UI Design Direction

**Date:** 2026-07-28
**Why this exists:** At Phase 1 entry the user flagged that Linear "does something kind of similar, not exactly," and set the direction that the Atlas confirmation UI should feel like a modern tool (Linear as the reference). This doc records (a) where Linear actually overlaps Atlas and where it doesn't — the strategic wedge — and (b) the concrete UI design language to carry into `docs/ux/` when slice 1B is built. This feeds design, it doesn't settle it.

---

## Part 1 — Linear vs. Atlas: overlap and wedge

### Where Linear overlaps Atlas (the "kind of similar" is real)
Linear (2026) has pushed well past issue tracking into AI/"Product Intelligence":
- **Semantic search that *synthesizes*** across issues, customer requests, and code changes — not just keyword lookup, but "genuinely useful answers." This is the closest thing to Atlas's extraction + Phase 3 Q&A.
- **Triage/Product Intelligence:** auto-linking duplicate issues, suggesting assignees from past fixes, labels, project assignment.
- **Code Intelligence + a Linear Coding Agent** (beta, gated to Business+): tying issues to code changes.
- **Tight dev integrations** (GitHub, GitLab, Slack, Figma, Sentry) that auto-link PRs and update issue status.

So the user is right: Linear is *synthesizing context across issues and code*. That neighbors Atlas.

### Where Atlas is different (why it's not the same product)
The differences are structural, not cosmetic — and they map directly to Atlas's Engineering Philosophy and Non-Goals:

1. **Linear is a system-of-record you must live in; Atlas is read-only over tools you already use.** Linear's synthesis only sees what's *in Linear*. Atlas ingests **across heterogeneous sources** (GitHub + Jira + Notion) read-only and asks no one to migrate their work. A team on GitHub + Jira + Notion is exactly who Linear's in-graph intelligence can't fully serve.
2. **Atlas's output is a confirmed, provenance-linked spec — an artifact — not an in-context suggestion.** Linear's AI assists inside Linear's surfaces. Atlas produces a structured spec (Phase 2) meant to be fed to a *coding agent*, where every claim carries a literal source excerpt + deep-link, and nothing is "fact" until a human confirms it (draft-never-fact). That trust/provenance model *is* the product.
3. **Human-in-the-loop confirmation is the core loop, not a nicety.** Linear surfaces AI output as suggestions. Atlas's whole Phase 1 exists to make a *non-engineer confirm/edit/reject* extracted knowledge — the confirmation UI is the point.
4. **Cross-tool, per-scope, least-privilege by design.** Atlas mirrors source permissions and only ever sees what the connecting credential already can (Philosophy §6).

**The one-line wedge:** *Linear makes the work inside Linear smarter. Atlas turns the context already scattered across a team's real tools into a trustworthy, provenance-linked spec a coding agent can execute against — without asking the team to change tools.*

**Watch-item / non-goal guard:** don't drift Atlas toward "a better issue tracker" or "chat with your workspace." Cross-org/workspace querying and being a system-of-record are explicit Non-Goals (CLAUDE.md, PRD §2.3). If a feature idea starts to look like rebuilding Linear, that's the signal to stop.

---

## Part 2 — UI design direction ("feel like Linear")

Distilled from Linear's own design writing + analysis. These are concrete tokens/rules for the `docs/ux/` baseline, **not** a mandate to clone Linear's brand — Atlas needs its own identity; this is the *quality bar and language*.

### Principles
- **Linearity / low cognitive load:** one scan direction, one subject per view, an orderly sequence of sections. Minimal "ways forward" per screen. This is what makes it *feel* fast — perceived speed comes from reduced choice, not just performance.
- **Keyboard-first:** command palette (Cmd/Ctrl-K), fast navigation, shortcuts for the core actions. For Atlas that means confirm/edit/reject/next should be keyboard-drivable — a reviewer clearing a queue of extracted nodes shouldn't need the mouse.
- **Modular components over a rigid grid:** a large set of small, purposeful components, each presenting one content format well.

### Concrete tokens
- **Color:** monochrome-first (black/white/greys), dark-mode-native, a *single* restrained accent. 2024–25 Linear trend is *less* saturation, fewer bold colors. Build a brand color as 1–10% lightness steps for a harmonious palette.
- **Spacing:** strict **8px scale** (8 / 16 / 32 / 64…). This alone buys most of the "consistent, calm" feel.
- **Radii & borders:** modest border radii; crisp, sharp borders; high contrast for readability.
- **Depth:** soft shadows; optional subtle gradients/glass for *faux depth without clutter* — use sparingly.
- **Motion:** subtle, fast transitions; nothing bouncy. Motion confirms an action, it doesn't perform.
- **Typography:** bold, declarative hierarchy; avoid the default-sans-serif flatness — a deliberate typeface is part of the identity.

### What this means specifically for the Atlas confirmation UI (slice 1B)
- A **feature-scope view** = a calm, top-to-bottom reading surface: nodes grouped by type (Goal / Requirement / Decision / Constraint / Open Question…), unconfirmed vs. confirmed clearly separated.
- Each node card shows content, type, confidence, and — non-negotiable — the **literal source excerpt + deep-link** (provenance is the product; the UI must make it one click to the source).
- **Conflict flags** (`conflicts_with`) surfaced prominently, not buried — this is a differentiator, show it off.
- **Confirm / edit / reject** as fast, keyboard-drivable actions; a reviewer should be able to clear a scope's draft nodes quickly (the 20-minute exit criterion is a *UX* bar).

---

## Part 3 — Connector model (the user's "later stages" vision, reconciled with the phases)

The user's product vision: users add connectors (GitHub, Jira, Notion, …) and grant access to **only specific repos/pages** — least-privilege. This is already the architecture's intent (TRD §4.2 scoped ingestion, §9 admin allow-list + "permissions mirror source," Philosophy §6). Phasing:

- **Phase 1:** the exit criterion literally requires "connect **two** sources" — so a *minimal* connector-management surface (connect GitHub + Jira, scope to a repo / project-epic-label) is in-phase. Basic, not a marketplace.
- **Phase 2:** Notion / a doc tool is the **third** source — the "specific pages" granularity lands with it.
- **Phase 4:** feature-level RBAC + full admin allow-list controls + disconnect-purges-raw-content.

So the vision is correct and already load-bearing in the design — it just arrives in layers, not all at slice 1. The "add a connector, pick exactly what it can see" UX is a first-class product surface to design well (it's a trust moment for the user), but the *granular* version is Phase 2+.

---

## Part 4 — Product framing note

The user's steer: **build like it's a product for real users** (incl. a future demo video), not an internal script. This reinforces the existing PRD direction (pilots, design partners) and raises the bar on the confirmation UI specifically — it's the first surface a non-engineer ever touches, and the thing a demo video would show. Design it as the product's front door.

---

## Sources
- [Linear AI features (2026) — eesel](https://www.eesel.ai/blog/linear-ai)
- [Linear Review 2026 — utilo](https://utilo.io/blog/linear-review-2026-project-management)
- [Linear design — LogRocket](https://blog.logrocket.com/ux-design/linear-design/)
- [Which UI libraries support the Linear aesthetic — LogRocket](https://blog.logrocket.com/ux-design/linear-design-ui-libraries-design-kits-layout-grid/)
- [How we redesigned the Linear UI (part II) — Linear](https://linear.app/now/how-we-redesigned-the-linear-ui)
