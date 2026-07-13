---
name: to-prd
description: Converts a conversation, decision, or rough feature idea into a properly-shaped PRD saved to docs/prd/, matching the structure of the master PRD (docs/PRD_Product_Knowledge_Layer_MVP.md). Use when the user says "write this up as a PRD," "turn this into a spec," or asks what a feature's scope/requirements should be before building it.
---

# to-prd

A rough idea discussed with Claude shouldn't have to bounce to another tool just to get written down. This skill produces a feature-level PRD draft in the repo's existing shape; the user reviews/validates it before it's treated as settled scope (per the master PRD's Workflow Philosophy: "no AI output becomes production truth without validation").

Feature-level PRDs produced by this skill are distinct from `docs/PRD_Product_Knowledge_Layer_MVP.md`, which is the master product PRD for the whole MVP — this skill is for a specific feature or slice within (or beyond) that master scope.

## Before drafting

Read `docs/PRD_Product_Knowledge_Layer_MVP.md` first — it's the master PRD and the template to match in tone and structure. Also check root `CLAUDE.md`'s Engineering Philosophy, Current Development Phase, and Explicit Non-Goals sections — a new PRD must not silently expand scope past what those allow, or assume a later phase's capability already exists, without flagging it. Also read `docs/tracker.md` (via the `tracker-sync` skill) so the "Dependencies" section names things that actually exist today, not aspirational state.

## PRD shape (match the master PRD's tone)

```markdown
# PRD — <Feature/Capability Name>

## Goal
<One sentence: what user-facing outcome this enables.>

## Scope
<What's in. Be specific — named modules, named node/edge types, named sources, not "support more sources.">

## Out of scope
<What's explicitly excluded for this pass, and why — usually because CLAUDE.md's Explicit Non-Goals already rules it out, or it's a later roadmap phase.>

## Requirements
<Numbered, testable. Each one should be checkable as done/not-done.>

## Dependencies
<What existing module/schema/agent tool this relies on — name the actual file, e.g. docs/TRD_Context_to_Spec_Engine.md §3.>

## Open questions
<Anything that needs a human decision before this is buildable.>
```

## Workflow

1. Extract the goal and scope from the conversation — don't pad with speculative requirements the user didn't ask for.
2. Cross-check scope against CLAUDE.md's Explicit Non-Goals and Current Development Phase. If the idea conflicts (e.g. it implies RBAC, a second source, or write-back before the phase that scopes those), say so in "Out of scope" rather than quietly omitting it.
3. Save as `docs/prd/<kebab-case-feature-name>-v1.md` (bump `v2` on major revision, per `docs-sync` naming convention — never overwrite a shipped PRD's history).
4. Tell the user it's a draft awaiting their review — don't treat it as approved scope in the same turn it was written.
