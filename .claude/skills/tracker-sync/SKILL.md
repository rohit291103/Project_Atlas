---
name: tracker-sync
description: Read and refresh docs/tracker.md, the living snapshot of what's done, in progress, and next across docs and engineering. Use proactively at the START of any new chat/task to load current project state before doing work, and again at the END of any session that touched src/atlas/ or docs/, to refresh the tracker. Unlike docs-sync's decision log (permanent, never rewritten), the tracker is disposable and gets overwritten in place every time.
---

# tracker-sync

Root `CLAUDE.md` says "Chats are temporary. Documentation is permanent." The decision log (`docs/decisions/`, maintained by `docs-sync`) is the permanent record of *why* things happened. `docs/tracker.md` is the other half: a fast, disposable answer to "what's the current state of this project, right now" — so a new chat doesn't have to re-derive it by reading every decision doc and grepping the codebase.

The defining rule: **the tracker reflects current state, not history.** It is overwritten, not appended to. If you find yourself adding a fourth bullet under "Last session notes" or letting "Done" grow without bound, you're doing it wrong — prune and consolidate instead.

## Mode A — Read at the start of a session

Before starting any non-trivial engineering or docs work, read `docs/tracker.md`. It tells you:
- What's already built (don't re-derive this from scratch by reading the whole codebase — and as of Phase 0, don't assume anything is built; the repo may not even be scaffolded yet).
- What's explicitly mid-flight (don't silently abandon it or duplicate it).
- What the last session intentionally left undone, and why.

If the tracker's "Done" claims something exists, verify it still does before relying on it (files get renamed/removed) — same rule as recalling any other persisted state.

## Mode B — Refresh at the end of a session

Run this after any session that materially changed `src/atlas/`, `docs/`, or `.claude/`. Edit `docs/tracker.md` in place:

1. **Docs / Engineering sections** — for each area touched this session:
   - Move finished "In progress" items into "Done."
   - **Consolidate, don't append.** If a new "Done" bullet supersedes an old one (e.g. "GitHub connector fetches PR + linked issues + commits" replaces "GitHub connector fetches PR title/description only"), delete the old bullet — the tracker shows current capability, not the history of how it got there. History belongs in `docs/decisions/` or git, not here.
   - Update "In progress" to reflect only what's genuinely still active. Empty is fine — write "Nothing active."
   - Update "Next up" with the real next steps, removing ones that got done or are no longer relevant. As the project grows past Phase 0, add new sections here (e.g. split "Engineering" into per-module sections once `ingestion/`, `extraction/`, `storage/` each have enough independent activity to warrant it) rather than cramming unrelated work into one bucket.
2. **Last updated** — set to today's date (convert any relative date the user gave you, e.g. "today," to an absolute `YYYY-MM-DD`) plus a short label for the session.
3. **Last session notes** — **replace entirely**, don't append. This section is always exactly one session's worth of summary — the most recent delta, in plain language, for someone walking in cold.
4. **Snapshot** — only touch this 2-3 sentence paragraph if the overall project phase or state materially shifted; otherwise leave it.

## Relationship to other docs work

- If this session's change is non-trivial enough to need a *reason* recorded (not just a status update), also file a decision log entry via `docs-sync` Mode B. The tracker's "Next up" can note "log decision for X" as a reminder if you're deferring that to a later session — that's the one case where the tracker is allowed to point at unfinished documentation work rather than do it.
- Don't duplicate decision-log content into the tracker. The tracker gets one consolidated bullet ("X shipped"); the decision log gets the why.
- `docs/tracker.md` intentionally lives outside the `/docs` subfolders (`prd`, `architecture`, `research`, `ux`, `decisions`, `prompts`) listed in root `CLAUDE.md` — it's a status board, not a category of permanent content. A `docs-sync` audit should treat it as expected, not stray.
