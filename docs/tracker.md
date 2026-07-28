# Project Atlas — Tracker

**Last updated:** 2026-07-28 — **Phase 0 extraction exit criterion MET → entered Phase 1** (confirmation UI + Jira). Phase 1 scope settled; build plan written; nothing coded yet.

## Snapshot

**Phase 1 has begun** (Roadmap Weeks 5–9): make the loop usable by a non-engineer PM + add a second source. Scope settled with the user (`docs/decisions/2026-07-28-phase0-exit-phase1-entry.md`) — **React SPA + FastAPI** confirmation UI, **Jira** as the 2nd source, sequenced **UI-first on existing GitHub data** to retire the primary risk ("can a non-engineer use this?") before adding Jira. Full plan: `docs/architecture/Phase1_Architecture.md` (proposal; the new `api/` + frontend module boundary is pending a `codebase-design` pass before scaffolding). No Phase 1 code exists yet.

Phase 0 is complete (extraction proven end-to-end on the 4 `BurntSushi/ripgrep` golden PRs via the Claude Pro subscription; all three reviews passed). The current codebase is the four Phase 0 modules — `ingestion/`, `extraction/`, `storage/`, `cli/` — fully working, fully tested. History lives in git + `docs/decisions/`; not re-listed here now that the phase is closed.

## Docs

### Done
- **Phase 1 entered** (`docs/decisions/2026-07-28-phase0-exit-phase1-entry.md`): Phase 0 exit criterion declared met; Phase 1 scope settled (React+FastAPI UI, Jira, UI-first sequencing). Build plan written: `docs/architecture/Phase1_Architecture.md`. `CLAUDE.md` "Current Development Phase" updated 0→1; `frontend-reviewer` agent + `brandkit`/`design-taste-frontend-v1` skills noted as now-active. No net-new skills added.
- Competitive/UI-direction research recorded (`docs/research/2026-07-28-competitive-linear-and-ui-direction-v1.md`): Atlas-vs-Linear wedge, Linear-like UI design tokens for the confirmation UI, connector least-privilege phasing, product-for-users framing.
- Phase 0 docs (PRD, TRD, Roadmap, Phase0 Architecture, validation-repo selection, extraction-quality run, retroactive decision logs) all written and filed — see `docs/` and git history.

### In progress
Nothing active.

### Next up
- `docs/ux/` still empty — gets its first content (design-system baseline + confirmation-UI flow spec) as the first task of Phase 1 slice 1B, after a `feature-discussion`/design pass on the confirmation UX (Phase1_Architecture.md §10 Q3), drawing on the UI direction in the Linear research doc.

## Engineering

### Done
- **Phase 0 complete** — all four modules (`ingestion/` read-only GitHub connector, `extraction/` Claude Agent SDK agent + validation gate, `storage/` event_log + projection replay, `cli/` `atlas ingest`/`review`) built, tested (~135 tests), and reviewed clean. Extraction ran live end-to-end on the 4 golden PRs, exit criterion MET. Detail in git + `docs/decisions/`.

### In progress
Nothing active.

### Next up — Phase 1 (see `docs/architecture/Phase1_Architecture.md` §3 for the four slices)

**Slice 1A — confirmation loop (backend), the immediate next work:**
- Implement projection-replay handlers for `node_confirmed` / `node_edited` / `node_rejected` / `node_added` (currently raise `NotImplementedError` on purpose — `docs/decisions/2026-07-22-projections-event-replay.md`). Edit events must retain a link to the original system-extracted node (TRD §6). Test-first (`tdd`).
- Add a **monotonic sequence column** to `event_log` (migration) and order replay by it — once edits/confirms exist, replay order is load-bearing and wall-clock `timestamp` is unsafe.
- Make `Node.confidence_score` optional (`float | None`, or required-only-when-`created_by=system`) for manual nodes — own decision doc when built.

**Then:** Slice 1B (React SPA confirmation UI + FastAPI `api/` — **run `codebase-design` first** on the new module boundary; write `docs/ux/` design-system + flow spec) → 1C (Jira connector + cross-source `conflicts_with`) → 1D (scoped ingestion, workspace RBAC + RLS, **tool-call audit logging** — the deferred Phase 0 follow-up folds in here, `docs/decisions/2026-07-28-extraction-tool-call-audit-logging.md`).

**Carried housekeeping (not phase-blocking):** scratchpad has a throwaway extraction recorder (`run_extraction.py`) — not committed; fold into an `atlas` eval-record subcommand if wanted. The `tests/` CI mypy gap (9 pre-existing strict errors in `test_extraction.py`/`test_cli.py`) is still open.

## Last session notes

**Declared Phase 0 done and set up Phase 1.** Walked the user through the Phase 0 result on a single PR (#111) as a concrete example — a near-empty PR + a 12-comment thread + a chased-down linked issue → 10 typed, verbatim-provenanced, confidence-scored nodes wired into a why→what→how graph, zero fabrication — and clarified that subscription-auth extraction draws from the Claude Pro rolling usage window (no separate bill, but shares the rate limit). User then chose to move to Phase 1 and settled its three open scope forks: **React SPA + FastAPI** UI, **Jira** 2nd source, **UI-first on existing GitHub data** sequencing. Also researched Linear (the Atlas-vs-Linear wedge + Linear-like UI direction) and captured it to `docs/research/` + memory. Produced the transition docs: `docs/architecture/Phase1_Architecture.md`, `docs/decisions/2026-07-28-phase0-exit-phase1-entry.md`, updated `CLAUDE.md`, and this tracker. **No code written** — planning/docs session. Deliberately did **not** add new skills (frontend toolkit already existed dormant). **Immediate next work:** Phase 1 slice 1A (confirmation-loop backend), test-first. The new `api/`+frontend module boundary must pass `codebase-design` before scaffolding.
