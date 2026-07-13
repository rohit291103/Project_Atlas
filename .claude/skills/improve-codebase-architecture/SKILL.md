---
name: improve-codebase-architecture
description: Scan src/atlas/ for deepening opportunities — refactors that turn shallow modules into deep ones — present them as a visual HTML report, then grill through whichever one the user picks. Use when asked to review or improve backend architecture, not for routine feature work or Phase 0 scaffolding.
---

# improve-codebase-architecture

Surface architectural friction in `src/atlas/` and propose **deepening opportunities** — refactors that turn shallow modules into deep ones. The aim is testability and clarity within Project Atlas's four-module boundary (see the `codebase-design` skill).

This is a refactor-review skill, not a design-from-scratch skill. Per CLAUDE.md's Current Development Phase, Atlas is in Phase 0 (proving the extraction loop on one source) — this skill earns its keep once `src/atlas/` has real, working code to deepen, not while modules are still being scaffolded. If invoked against a near-empty or nonexistent `src/atlas/`, say so and suggest `codebase-design` instead.

Use the `codebase-design` skill's vocabulary in every finding: **module, interface, implementation, depth, deep, shallow, seam, adapter, leverage, locality**. Don't drift into "component," "service," "API," or "boundary." The four modules (`ingestion`, `extraction`, `storage`, `cli`) are the module boundary — findings should map onto them, not propose a different decomposition.

`docs/decisions/` is this project's record of past calls — don't re-litigate a decision already filed there without flagging that you're doing so.

## Process

### 1. Explore

Read `docs/tracker.md` (via `tracker-sync`) and any relevant `docs/architecture/` and `docs/decisions/` files for the area first.

Then use the Agent tool with `subagent_type=Explore` to walk `src/atlas/`. Don't follow rigid heuristics — explore organically and note where you experience friction:

- Where does understanding one concept require bouncing between many small modules?
- Where are modules **shallow** — interface nearly as complex as the implementation?
- Where have pure functions been extracted just for testability, but the real bugs hide in how they're called (no **locality**)?
- Where do tightly-coupled modules leak across their seams (e.g. `extraction/` reaching directly into `storage/` internals instead of going through the event-write interface)?
- Which parts of the codebase are untested, or hard to test through their current interface?
- Any code path where extraction output reaches `storage/` without passing schema validation, or where a Node/Edge table is mutated directly instead of via an event — that's architectural friction *and* a Critical-severity correctness issue per `backend-reviewer`, not just a style nit.

Apply the **deletion test** to anything you suspect is shallow: would deleting it concentrate complexity, or just move it? A "yes, concentrates" is the signal you want.

### 2. Present candidates as an HTML report

Write a self-contained HTML file to the OS temp directory so nothing lands in the repo. Resolve the temp dir from `$TMPDIR`, falling back to `/tmp`, and write to `<tmpdir>/architecture-review-<timestamp>.html` so each run gets a fresh file. Open it for the user with `open <path>` (macOS) and tell them the absolute path.

The report uses **Tailwind via CDN** for layout and styling, and **Mermaid via CDN** for diagrams where a graph/flow/sequence reliably communicates the structure. Mix Mermaid with hand-crafted CSS/SVG visuals. Each candidate gets a **before/after visualisation**. Be visual, not prose-heavy.

For each candidate, render a card with:

- **Files** — which files/modules are involved (monospace)
- **Module** — which of the four modules this sits in
- **Problem** — why the current architecture is causing friction (one sentence)
- **Solution** — plain English description of what would change (one sentence)
- **Wins** — bullets, ≤6 words each, in glossary terms (e.g. "locality: bugs concentrate in one module")
- **Before / After diagram** — side-by-side, illustrating the shallowness and the deepening
- **Recommendation strength** — `Strong` (emerald), `Worth exploring` (amber), or `Speculative` (slate), as a badge

End the report with a **Top recommendation** section: which candidate to tackle first and why, with an anchor link to its card.

**Decision conflicts**: if a candidate contradicts an existing `docs/decisions/` entry, only surface it when the friction is real enough to warrant revisiting that decision. Mark it clearly (e.g. an amber callout: _"contradicts docs/decisions/2026-XX-XX-foo.md — but worth reopening because…"_). Don't list every theoretical refactor a past decision forbids.

Do NOT propose interfaces yet in the report. After the file is written, ask the user: "Which of these would you like to explore?"

### 3. Grilling loop

Once the user picks a candidate, run the `grilling` skill to walk the design with them — constraints, dependencies, the shape of the deepened module, what sits behind the seam, what tests survive.

Side effects happen inline as decisions crystallize:

- **Sharpening a fuzzy term during the conversation?** Run `domain-modeling` to update the canonical definition.
- **User rejects the candidate with a load-bearing reason?** Offer to file it via `docs-sync`: _"Want me to log this as a decision so future architecture reviews don't re-suggest it?"_ Only offer when the reason would actually be needed by a future reviewer — skip ephemeral or self-evident reasons.
- **Decision reached on how to deepen a module?** File it via `docs-sync` once implementation is agreed — per CLAUDE.md's Documentation Rules, this is not optional.

Implementation itself should go through `tdd` for any schema/storage/event-sourcing logic, and a `backend-reviewer` pass after.
