---
name: to-issues
description: Breaks a PRD or decision doc into independently-buildable, vertical-slice work items. Use when the user asks to "break this down," "make a task list," or "turn this into issues" after a PRD or decision has been written.
---

# to-issues

A PRD describes what to build; this skill decides the order and slicing of how to build it without losing the "narrow and deep" MVP philosophy — each item should be a complete, demoable vertical slice (touches schema → extraction/ingestion → storage as needed for that one capability), not a horizontal layer (e.g. not "build all Pydantic schemas" as one item).

## Before slicing

Read the source PRD/decision doc in full. If it references the data model, also read `docs/TRD_Context_to_Spec_Engine.md` §3 so slices don't get ordered ahead of their dependencies (e.g. don't slice "surface conflicting Nodes in the review report" before "conflict-detection edge creation" exists). Also read `docs/tracker.md` (via the `tracker-sync` skill) — order slices relative to what's actually "Done" today, not what the source doc assumed at the time it was written.

## What makes a good slice

- Independently buildable and testable — a reviewer can see it work end-to-end without the next slice existing.
- Sized to one sitting of focused work, not a multi-day epic.
- Named as an outcome, not a layer: "Agent follows linked-issue references during extraction" not "Add fetch_linked_issue tool."
- Ordered by dependency, not by perceived importance — schema/storage slices that others depend on come first.

## Output

There's no issue tracker or GitHub remote wired up yet (project root isn't a git repo as of this writing) — so output is a checklist appended to the source doc or saved alongside it, not a `gh issue create` call. If a GitHub remote exists by the time this runs, confirm with the user before creating real issues; default to the checklist doc.

```markdown
## Implementation slices — <source PRD/decision name>

1. [ ] <Outcome-named slice> — depends on: <none | slice N>
   - Touches: <files/schema/module>
2. [ ] ...
```

Save under the same `/docs` subfolder as the source doc (e.g. a PRD's slice list lives next to it in `docs/prd/`), not in a new location.
