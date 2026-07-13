---
name: docs-sync
description: Keep Project Atlas's /docs tree aligned with the Documentation Rules in root CLAUDE.md — file a decision-log entry, route new content to the right /docs subfolder, or audit /docs for missing folders, broken naming, or duplicated/stale content. Use when a non-trivial decision was just made, when the user asks to "document this" or "log this decision," or when starting work that should read existing docs first.
---

# docs-sync

Root `CLAUDE.md` is explicit: **"Chats are temporary. Documentation is permanent."** This skill is the mechanical half of that rule — it doesn't decide what's worth documenting (use judgment, or ask the user), it makes sure that once something is worth documenting, it lands in the right place with the right name.

## Required structure

Per root `CLAUDE.md`'s "Documentation Rules" section, `/docs` contains six subfolders plus `tracker.md`:

```
/docs
  tracker.md    — the one exception, see below
  /prd          — the master PRD + Roadmap, plus any feature-level PRDs beyond them
  /architecture — the master TRD + current-phase architecture doc, plus any feature-level ones
  /research     — external research (repo selection notes, extraction-quality findings, competitive landscape)
  /ux           — design-system baseline, page/flow specs (doesn't exist until Phase 1's confirmation UI)
  /decisions    — decision log (one file per decision or cleanup pass)
  /handoff      — structured handoff notes for another collaborator, using the template below
```

## Exception: `docs/tracker.md`

`docs/tracker.md` lives directly under `/docs`, outside the six subfolders above — that's intentional, not a misfile. It's a disposable, continuously-overwritten status board (current Done/In progress/Next up per area), maintained by the `tracker-sync` skill, distinct from the permanent decision log this skill maintains. Don't flag it in an audit, and don't apply the "don't overwrite history" rule to it — that rule is for `/decisions` and `/research`, not the tracker.

## Before doing any task in this repo

Read the relevant `/docs` content before writing code or making a recommendation — this project's CLAUDE.md explicitly calls out documentation discipline. Don't re-derive scope, the data model, or architecture decisions from memory when they're already written down in `docs/prd/PRD_Product_Knowledge_Layer_MVP.md` or `docs/architecture/TRD_Context_to_Spec_Engine.md`.

## Mode A — Audit

Run this when asked to "check the docs" or before a large new feature push:

1. Confirm all six subfolders exist and `tracker.md` sits directly under `/docs` (empty folders with no placeholder file are fine since Git won't track them — add a one-line `README.md` if a folder needs to exist before its first real doc; `/prd` and `/architecture` will never be empty since the master docs live there).
2. Grep each file for exact-duplicate content (a doc pasted into itself twice is a recurring failure mode — check for it). A quick check: split the file in half and diff the halves; large duplicate blocks will show as near-zero diff.
3. Check naming consistency. Going-forward convention:
   - Decisions and handoff notes: `YYYY-MM-DD-short-slug.md`
   - Everything else: `kebab-case-topic-v1.md` (bump `v2`, `v3`, … on major revisions; don't overwrite history)
   - The master docs (`PRD_Product_Knowledge_Layer_MVP.md`, `TRD_Context_to_Spec_Engine.md`, `MVP_Roadmap.md`, `Phase0_Architecture.md`) are grandfathered under their existing names rather than renamed to the kebab-case convention — moving them into subfolders was already enough churn for one pass. A major revision still gets a new file (e.g. `Phase1_Architecture.md`) rather than overwriting `Phase0_Architecture.md`.
4. Report findings; don't silently rewrite historical docs without flagging it to the user first (decisions and research docs are a record of what was true at the time — fix structure/naming, not content, unless asked).

## Mode B — File a decision

When a decision just got made (in this conversation or by the user), write `docs/decisions/YYYY-MM-DD-short-slug.md` using this shape:

```markdown
# Decision Log — <Title>

**Date:** YYYY-MM-DD
**Area:** <ingestion / extraction / storage / cli / product / architecture>

## Context
<Why this came up — the problem or ambiguity.>

## Decisions
<Numbered list. Each decision states what changed and why, not just what.>

## Not done (deferred)
<Anything explicitly out of scope for this pass, and why.>
```

## Mode C — Route new content

If unsure which subfolder something belongs in:
- Defines what to build / scope boundaries → `/prd`
- Defines how something is built (schema, system design, agent/tool design, API shape) → `/architecture`
- External findings (validation-repo candidates, extraction-quality observations, competitive landscape) → `/research`
- Page/flow/design-system specs (Phase 1+, once there's a UI) → `/ux`
- A choice that was made and why → `/decisions`
- A handoff note for another collaborator (a teammate, another AI tool, a future session) → `/handoff`, via the `handoff` skill

When a piece of content spans two categories (e.g. a decision that also changes scope), file the full writeup in `/decisions` and add a one-line cross-reference in the other folder's relevant doc rather than duplicating content.
