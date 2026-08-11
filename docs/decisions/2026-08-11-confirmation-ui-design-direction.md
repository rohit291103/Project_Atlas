# Decision Log — Confirmation UI Design Direction

**Date:** 2026-08-11
**Area:** UX / Phase 1 slice 1B (confirmation UI)

## Context

Phase 1 slice 1B is the confirmation UI — the screen a non-engineer PM uses to review Atlas's extracted claims and confirm/edit/reject them. The `docs/ux/` specs existed as v1 drafts; this session pinned down the *visual and interaction* direction against real benchmarks and an interactive mockup, and — importantly — realigned the design to Atlas's cross-source thesis after the first cut read as GitHub-only.

## Decisions

1. **Base design system: Vercel/Geist + Linear review density.** Chosen after benchmarking Linear, Vercel/Geist and Mercury. Geist gives the foundation (dark as the *canonical* surface, "ink is the brand" restraint, accent used like punctuation, fine 1px borders, open-source **Geist Sans + Geist Mono**); Linear gives the review-loop patterns (dense scannable rows, keyboard-first, subtle fast motion). Geist Sans/Mono settles the typeface question — no longer a placeholder. Mercury was the runner-up (warmer/more approachable) and stays a reference if the dev-tool minimalism proves too austere for the PM persona.

2. **Review metaphor: document-view home + keyboard review, refined to a focus model.** Confirmed the earlier 2026-08-03 call (document over card-queue). The mockup refined *how*: distinct bordered cards; **only the focused card expands** to show its source excerpt + Confirm/Edit/Reject actions while the rest stay compact; **reviewed items recede** into quiet dim one-line rows; a **"Review next" / auto-advance** flow walks the PM item to item. This directly answered the first-look complaint that a flat, all-expanded list read as "a wall of data."

3. **Cross-source model: feature-first, source-annotated, cross-source-conflict-forward.** The screen is organized by **feature** and node type, **never split by source** (per-source panes rebuild the silos Atlas exists to remove). Source is provenance metadata on each claim (a small badge; a node may carry multiple `SourceRef`s for the same fact corroborated across tools). The **cross-source `conflicts_with`** — e.g. a PRD requirement vs. a Slack decision — is the headline element, naming both sides' sources, because it is the thing no single tool could surface. **No node-link graph canvas** (over-scope, reintroduces overwhelm, explicit non-goal).

4. **Neutral system now, brand later.** Build the neutral Geist-caliber system now; defer the Atlas logo/wordmark/brand accent to a dedicated `brandkit` pass. Following Geist's accent-as-punctuation restraint, the single accent swaps in one place when brand lands.

5. **Dark committed for the mockup; light is a token swap** in the real system (design-system doc §2.6).

## Consequences

- `docs/ux/design-system-baseline-v1.md` and `docs/ux/confirmation-flow-spec-v1.md` updated in place with the Geist+Linear base, the focus/recede/auto-advance interaction refinements, the source-badge + "Assembled from" components, and the cross-source model.
- An **interactive mockup** was produced (published artifact, session scratchpad `atlas-review-mockup.html`) demonstrating all of the above on the ripgrep `--pre` feature, including a cross-source conflict (PRD vs. Slack) and a corroborated multi-source Goal. It is a design reference, not committed code.
- **Roadmap discipline preserved:** the mockup *shows* Slack/Google Docs/email to prove the design is source-agnostic, but those connectors are **not** built ahead — GitHub is live, Jira is Phase 1, the rest are Phase 2–4. The value of the work is that the review UI needs no redesign when they arrive.
- Does **not** bypass the `codebase-design` gate on the `api/` + frontend boundary (`Phase1_Architecture.md` §5) — these specs are inputs to that pass, which is the next step before scaffolding.

## Still open (unchanged by this decision)

- App-level auth for the PM (`Phase1_Architecture.md` §10 Q2) — the one remaining pre-build blocker.
- Atlas brand identity (logo/wordmark/accent) — deferred `brandkit` pass.
