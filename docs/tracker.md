# Project Atlas — Tracker

**Last updated:** 2026-08-03 — **Phase 1 slice 1A (confirmation-loop backend) built and tested**, including manual-node provenance (`SourceType.human_assertion`). The loop is now writable end-to-end at the storage layer; the UI (slice 1B) is next and is what actually retires Phase 1's primary risk.

## Snapshot

**Phase 1 is in progress** (Roadmap Weeks 5–9): make the loop usable by a non-engineer PM + add a second source. Scope settled with the user (`docs/decisions/2026-07-28-phase0-exit-phase1-entry.md`) — **React SPA + FastAPI** confirmation UI, **Jira** as the 2nd source, sequenced **UI-first on existing GitHub data** to retire the primary risk ("can a non-engineer use this?") before adding Jira. Full plan: `docs/architecture/Phase1_Architecture.md` (still a proposal; the `api/` + frontend module boundary is pending a `codebase-design` pass before scaffolding). Slice 1A is done — confirm/edit/reject/add now write events and replay correctly. No UI, no API, no Jira yet.

Phase 0 is complete (extraction proven end-to-end on the 4 `BurntSushi/ripgrep` golden PRs via the Claude Pro subscription; all three reviews passed). History lives in git + `docs/decisions/`; not re-listed here now that the phase is closed.

## Docs

### Done
- **Manual-node provenance settled** (`docs/decisions/2026-08-03-manual-node-provenance.md`): `SourceType.human_assertion` added, so a hand-typed node's evidence is the named human rather than a fabricated URL — CLAUDE.md's zero-exception `SourceRef` rule keeps holding literally while PRD R10 becomes satisfiable. **Amends TRD §3.1** (`SourceType` list) and `Phase1_Architecture.md` §8, both annotated in place with the reason and a pointer.
- **Slice 1A decision log** (`docs/decisions/2026-08-03-confirmation-loop-backend.md`): the sequence column, the `confidence_score` invariant, transition replay through the validation gate, why there is no `node_added` event type, the `storage/confirmations.py` write path, `previous_content` vs. `original_content`, and the blank-actor gap closed at `append_event`. `Phase1_Architecture.md` §4.1 amended to match (it had proposed a `node_added` handler).
- **Phase 1 entered** (`docs/decisions/2026-07-28-phase0-exit-phase1-entry.md`): Phase 0 exit criterion declared met; Phase 1 scope settled. Build plan: `docs/architecture/Phase1_Architecture.md`. `CLAUDE.md` "Current Development Phase" updated 0→1; `frontend-reviewer` agent + `brandkit`/`design-taste-frontend-v1` skills noted as now-active.
- Competitive/UI-direction research recorded (`docs/research/2026-07-28-competitive-linear-and-ui-direction-v1.md`): Atlas-vs-Linear wedge, Linear-like UI design tokens, connector least-privilege phasing, product-for-users framing.
- Phase 0 docs (PRD, TRD, Roadmap, Phase0 Architecture, validation-repo selection, extraction-quality run, retroactive decision logs) all written and filed.

### In progress
Nothing active.

### Next up
- `docs/ux/` still empty — gets its first content (design-system baseline + confirmation-UI flow spec) as the first task of slice 1B, after a `feature-discussion`/design pass on the confirmation UX (`Phase1_Architecture.md` §10 Q3), drawing on the UI direction in the Linear research doc.

## Engineering

### Done
- **Phase 0 complete** — all four modules (`ingestion/` read-only GitHub connector, `extraction/` Claude Agent SDK agent + validation gate, `storage/` event_log + projection replay, `cli/` `atlas ingest`/`review`) built, tested, reviewed clean. Extraction ran live end-to-end on the 4 golden PRs, exit criterion MET.
- **Phase 1 slice 1A — confirmation loop (backend)** (172 tests green, `src/` clean under ruff + strict mypy; code committed as `caf4075`, provenance follow-up uncommitted):
  - `node_confirmed` / `node_edited` / `node_rejected` replay handlers — supersede a node by rebuilding it through `Node.model_validate`, so a transition passes the same gate a create does; `updated_by`/`updated_at` come from the Event's own `actor`/`timestamp`. Last write wins, so undo is free. A transition naming an unknown node raises rather than being skipped.
  - `event_log.sequence` — Postgres identity column, unique, `(workspace_id, sequence)` index; `load_projection` orders by it instead of wall-clock `timestamp`. Migration `8c41a0b7e2d5` backfills existing rows in the old `(timestamp, id)` order so a pre-existing log replays identically.
  - `Node.confidence_score` is `float | None`, present **exactly** when `created_by = system` (both directions enforced). `atlas review` renders an absent score as `—`.
  - `storage/confirmations.py` — `confirm_node` / `reject_node` / `edit_node` / `add_node` over `append_event`; the shared write path for the future API and the CLI. Confirm/reject/edit take the `Node`, not a bare id, so an action can't name one that doesn't exist.
  - `append_event` now rejects a blank `actor` (every Event is an audit record — `NOT NULL` doesn't catch `""`).
  - Manual add reuses `node_created` with `created_by = user`; **no** `node_added` event type was added (TRD §3.1's enum has none). `add_node` builds the Node from fields rather than accepting one, so extraction output can't be laundered through it and an API body can't choose its own `workspace_id`.
  - `SourceType.human_assertion` — a manual node's provenance is the named human who typed it (`external_id` = actor, `excerpt` = the claim as typed, `url` = `atlas:node/<uuid>`), so `source_refs` keeps `min_length=1` with no exception clause. The excerpt is a snapshot: a later edit changes `content` and leaves it alone.

### In progress
Nothing active.

### Next up — Phase 1 (see `docs/architecture/Phase1_Architecture.md` §3 for the four slices)

**Slice 1B — confirmation UI (React SPA + FastAPI `api/`), the immediate next work.** This is the slice that retires Phase 1's primary risk. Order of operations:
1. Run **`codebase-design`** on the `api/` + frontend module boundary (`Phase1_Architecture.md` §5) — the gate CLAUDE.md requires before scaffolding either.
2. Settle the two open questions blocking it: app-level auth for the PM (`§10 Q2`) and the confirmation UX itself (`§10 Q3`). Manual-node provenance is now settled — the add-node form asks for a claim, not a citation.
3. Write `docs/ux/` design-system baseline + flow spec, then build. The API sits on `storage/confirmations.py` + `load_projection` and must derive `workspace_id` and `actor` from the authenticated session, never from a request body (see the slice-1A decision doc's forward note).

**Then:** 1C (Jira connector + cross-source `conflicts_with`) → 1D (scoped ingestion, workspace RBAC + RLS, **tool-call audit logging** — the deferred Phase 0 follow-up folds in here, `docs/decisions/2026-07-28-extraction-tool-call-audit-logging.md`).

**Carried housekeeping (not phase-blocking):** scratchpad has a throwaway extraction recorder (`run_extraction.py`) — not committed; fold into an `atlas` eval-record subcommand if wanted. The `tests/` CI mypy gap is still open (11 strict errors in `test_extraction.py`/`test_cli.py`, all pre-existing; `src/` is clean).

## Last session notes

**Built Phase 1 slice 1A — the confirmation-loop backend — test-first.** The three forward notes the codebase had been carrying all came due together and are now closed: the `node_confirmed`/`node_edited`/`node_rejected` replay handlers that Phase 0 deliberately left raising `NotImplementedError`, the monotonic `sequence` column (wall-clock `timestamp` stops being a safe ordering key the moment transitions exist — two events in one transaction can share it), and `confidence_score` becoming optional. Added `storage/confirmations.py` as the shared write path both the future API and the CLI will call, so payload shapes live in one place. Two deviations from `Phase1_Architecture.md` worth knowing about: **no `node_added` event type** was added (TRD §3.1's enum has none, and `node_created` + `created_by = user` describes a manual node completely), and the edit payload records `previous_content` rather than the system original, so successive edits chain honestly back through `node_created`. Also closed a real audit gap found on the way: `append_event` accepted a blank `actor`, because the write path never constructs the `Event` model whose validator forbade it. Security review run on the diff — no findings; the one forward risk (the API must derive `workspace_id`/`actor` from the session, not the request body) is recorded in the decision doc. **Then settled manual-node provenance,** the one question slice 1A had left open. `Phase1_Architecture.md` §8 wanted manual nodes to be "the one node type without provenance"; CLAUDE.md says a Node without a `SourceRef` is structurally impossible; PRD R10 requires adding knowledge that has no artifact ("a constraint mentioned verbally in a meeting"). Both obvious resolutions were wrong — relaxing the schema makes an empty-provenance Node expressible forever, and demanding a citation a PM can't honestly give produces *fabricated* provenance, which is worse because it's indistinguishable from a real extraction. Added `SourceType.human_assertion` instead: a manual node's evidence is the named human, so the invariant stays literally true, and Phase 2's export can distinguish "the PR says X" from "Priya says X." `add_node` now builds the Node from fields instead of accepting one, which also closed the security seam slice 1A had flagged for later. TRD §3.1 and `Phase1_Architecture.md` §4.1/§8 amended in place with reasons and pointers. **Deliberately not built:** the `api/` module and any CLI write commands — the `codebase-design` gate comes first, and the CLI is meant to stay a read/debug path.
