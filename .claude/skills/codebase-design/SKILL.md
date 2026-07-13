---
name: codebase-design
description: Vocabulary and checklist for designing deep, maintainable Python modules per CLAUDE.md's Module Boundary (no premature microservices/abstractions, four-module decomposition). Use proactively when scaffolding a new module or significant abstraction under src/atlas/.
---

# codebase-design

Root `CLAUDE.md`'s Explicit Non-Goals are specific about what to avoid: a dedicated graph database, a task queue, RBAC, or a confirmation UI ahead of the phase that needs them; premature microservices; unnecessary abstractions. This skill is the checklist to run before adding structure, not after — overengineering is far cheaper to prevent than to unwind, and a one-person Phase 0 project has essentially zero budget for it.

Before scaffolding anything, read `docs/tracker.md` (via the `tracker-sync` skill) to confirm what already exists — don't design a module boundary for a module that's already further along (or less far along) than assumed.

## The four modules are the current boundary

Root `CLAUDE.md` already defines the decomposition — don't invent a different one without discussing it first:

1. `ingestion/` — read-only source connectors (GitHub in Phase 0; Jira/Linear + a doc tool join in Phase 1–2)
2. `extraction/` — the Claude Agent SDK agent, its tools, and its prompts
3. `storage/` — event log + projections
4. `cli/` — Typer entrypoint (Phase 0's stand-in for the confirmation UI)

A new piece of logic should slot into one of these four, not spawn a fifth without a clear reason it doesn't fit. If it genuinely doesn't fit, say so explicitly and explain why before creating a new module. (Phase 1+ will add a confirmation-UI layer and a spec-assembly layer — that's an expected future boundary, not license to build it early.)

## "Deep module" checklist before adding an abstraction

A deep module (simple interface, does meaningful work behind it) beats a shallow one (interface as complicated as the implementation). Before adding a new class/interface/service boundary, check:

- Does this hide real complexity, or just rename a single function call? (If the latter, skip it.)
- Could this be a plain function in the existing module instead of a new class/service?
- Is there a second concrete caller today, or is this "for later"? Avoid building for hypothetical future requirements — one caller doesn't justify an abstraction layer.
- Does it cross a boundary that needs to be a boundary (e.g. `extraction/` output feeding `storage/` input, gated by schema validation), or is it splitting something that's naturally one piece?

## Anti-patterns flagged by this skill

- A new microservice/separate deployable for what could be a module in the existing CLI app — Phase 0 explicitly excludes scaling infrastructure.
- A generic plugin/strategy-pattern system built before there are ≥2 concrete variants needing it (e.g. don't build a generic "connector interface" before Jira ingestion actually exists in Phase 1 — GitHub-only is fine as a single concrete implementation for now).
- A task queue, dedicated graph database, or vector store introduced before the phase that needs it (per CLAUDE.md's Explicit Non-Goals) — Postgres/Supabase + projections, and synchronous CLI invocations, are sufficient at current scale.
- Direct Node/Edge table mutation instead of an event write — this isn't a style preference, it's the Engineering Philosophy's event-sourcing guarantee; any "convenience" direct-write path is a bug, not a shortcut.

## When this skill is satisfied

The result should be boring: a small number of clearly-bounded modules matching the four-module boundary, plain functions/classes within them, and zero new infrastructure (queues, services, frameworks) that wasn't already in `docs/Phase0_Architecture.md`'s tech stack.
