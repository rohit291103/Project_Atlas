# Decision Log — Event-Log Projection Replay (`storage/projections.py`)

**Date:** 2026-07-22
**Area:** storage

## Context

TRD §3.1/§3.2 make `event_log` the source of truth and say "all Node/Edge state is a materialized projection derived by replaying Events" — never a table written to directly. With the schema (`models/schema.py`) and the append-only `event_log` (`storage/tables.py`) both landed, and the `workspace_id` sentinel decided ([2026-07-21](2026-07-21-phase0-default-workspace-id.md)), the read side was the next unblocked module: turn the log back into Node/Edge state so `atlas review --feature-scope <id>` (Phase0_Architecture.md §4) can show extracted drafts. Built test-first per the `tdd` skill (projection replay is one of its mandatory-discipline areas).

## Decisions

### 1. Pure `replay()` reducer + thin DB-backed `load_projection()`

`replay(events) -> Projection` is a pure fold over any iterable of events (a `Protocol` structurally satisfied by both the `EventLog` ORM row and the `Event` domain model), with no DB or network. `load_projection(session, *, workspace_id, feature_scope_id=None)` is the thin adapter that queries `event_log` for one workspace, orders it, and folds it. This keeps the replay logic exhaustively unit-testable with in-memory events and isolates the one impure concern (the query) in a wrapper. `Projection` is a frozen dataclass of `nodes`/`edges` dicts keyed by id (so a future update event can supersede an entity in place).

### 2. The write-side validation gate is re-applied on read

A `node_created`/`edge_created` payload is fed back through `Node.model_validate`/`Edge.model_validate` during replay. A Node that somehow lacked provenance in the log could not materialize out of it — the provenance gate holds on the read path, not just the write path (CLAUDE.md: a Node without a `SourceRef` is structurally impossible, no exceptions).

### 3. Fail loud on Phase 1 status-transition events, skip audit-only events

Phase 0 emits only `node_created`/`edge_created`. `ingestion_run`/`spec_exported` are audit-only events with no Node/Edge effect *by definition* → skipped. The status-transition events (`node_confirmed`/`edited`/`rejected`) belong to Phase 1's confirmation UI and are **not** built — replay raises `NotImplementedError` on them rather than silently ignoring them. Silent-ignore was rejected: once those events exist, ignoring a `node_rejected` would let a rejected node still read as `unconfirmed`, a latent correctness bug. Failing loud makes the Phase 0 boundary impossible to depend on by accident, and Phase 1's job becomes "add a handler." An exhaustive `else` guards against a new `EventType` member being added with no handler.

### 4. `for_feature_scope()` filters edges transitively

Narrowing a projection to one feature scope keeps only nodes with that `feature_scope_id`, then keeps an edge only when *both* endpoints survive — so a relationship reaching a node outside the scope doesn't dangle in the scoped view. Feature-scope filtering happens on the replayed result (scope lives inside the Node payload, not on the event row); workspace filtering happens in SQL.

## Storage fix surfaced by this work: dialect-portable UUID columns

The DB-backed tests exposed a real SQLite-only defect in `storage/tables.py`: `PG_UUID(as_uuid=True)` compiles to an unrecognized `UUID` type name on SQLite, which gets NUMERIC affinity, so the **nil `DEFAULT_WORKSPACE_ID`** (`"000…0"`, all digits) is coerced to the integer `0` on write and then crashes on read (`uuid.UUID(0)`). Because the nil UUID is the actual Phase 0 default, *every* workspace-scoped SQLite test would hit this.

Fixed by making the `id`/`workspace_id` columns dialect-portable — `PG_UUID(as_uuid=True).with_variant(Uuid(as_uuid=True), "sqlite")` — mirroring the existing `JSON().with_variant(JSONB(), "postgresql")` pattern in the same file. **Postgres DDL is byte-identical** (`id UUID`, `workspace_id UUID` — verified offline by compiling `CreateTable` against the postgres dialect), so the applied `create_event_log` migration stays correct and there is zero schema drift; only SQLite's emission changes to `CHAR(32)` (TEXT affinity → the value round-trips intact). This is a test-harness fidelity fix, not a production-Postgres bug.

## Alternatives rejected

- **Store projections in their own tables.** Directly contradicts TRD §3.2 — projections are always rebuildable from the log, never independently persisted. No dedicated Node/Edge tables in any current phase.
- **Dodge the nil-UUID SQLite quirk by using `uuid4()` workspaces in the projection tests.** Would hide the defect and stop the tests from exercising the real production default. Fixing the column typing is correct.
- **Handle `node_confirmed/edited/rejected` now.** Building ahead of Phase 1 (CLAUDE.md Non-Goals). The reducer is structured so adding them is a one-branch change.

## Forward note (Phase 1)

Once status-transition events exist, replay order becomes semantically load-bearing (a confirm must apply after its create). `load_projection` orders by `(timestamp, id)` — deterministic but not a true insertion sequence. A monotonic sequence column is the robust fix and should be added with the schema change that introduces those events, not now.
