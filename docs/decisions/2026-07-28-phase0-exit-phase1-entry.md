# Decision Log — Phase 0 Exit & Phase 1 Entry

**Date:** 2026-07-28
**Area:** roadmap / project phase

## Context

Phase 0's exit criterion (Roadmap): *"Extraction produces usable, mostly-correct structured output for at least 3 real past features, validated manually."* As of this date, the extraction loop had run live end-to-end on all 4 golden PRs (`BurntSushi/ripgrep` #111/#723/#706/#3472) on the Claude Pro subscription, and all three Phase 0 reviews were complete:

- **Tier-2 extraction quality** (`docs/research/2026-07-28-extraction-quality-run.md`): correctly-typed, fully-provenanced output on all 4 PRs, zero fabricated excerpts, meaningful confidence calibration, and correct modeling of a self-contradicting source (#706) via a `conflicts_with` edge.
- **Security review:** clean against TRD §9.
- **Backend review:** validation gate / event-sourced writes / read-only tool enforcement / provenance all clean; one Important finding (tool-call audit logging unimplemented), consciously deferred and tracked.

## Decision

**Phase 0's extraction exit criterion is declared MET, and the project enters Phase 1.** The user made this call explicitly after reviewing the Phase 0 result. We are not running additional validation PRs first — at N=4 the signal is qualitative and strong, and the real statistical loop is a Phase 3 concern (TRD §5.3), not a Phase 0 gate.

### Phase 1 scope decisions settled at entry

1. **Confirmation UI stack: React SPA + FastAPI** (TRD §11). A CLI can't meet "non-engineer PM, unassisted"; a lighter server-rendered stack would likely be discarded by Phase 2. Introduces the first new modules since Phase 0 (`api/` + a React frontend).
2. **Second ingestion source: Jira** (Roadmap left this "Jira or Linear"). Chosen over Linear for PM-persona and enterprise-pilot alignment, accepting the messier REST/OAuth surface.
3. **Sequencing: UI-first on existing GitHub data.** Build the confirm/edit/reject loop + UI against already-extracted data to retire the primary Phase 1 risk ("can a non-engineer use this?") before adding the Jira connector.

Full build plan: `docs/architecture/Phase1_Architecture.md`.

## Consequences

- **CLAUDE.md** "Current Development Phase" section updated 0→1; confirmation UI / 2nd source / scoped ingestion / workspace-RBAC / audit logging moved out of the "explicitly NOT current priority" list. Spec export, Q&A, feature-level RBAC, incremental sync remain deferred.
- **Dormant tooling activates:** `frontend-reviewer` agent, `brandkit` + `design-taste-frontend-v1` skills, and the `supabase-postgres-best-practices` `security-*` (RLS) rules all become live for the first time. No net-new skills added — resisting premature tooling per the project's own non-goals philosophy.
- **Two already-logged forward notes come due:** projection replay's `NotImplementedError` on `node_confirmed/edited/rejected` gets real handlers + a monotonic sequence column (`docs/decisions/2026-07-22-projections-event-replay.md`); `Node.confidence_score` becomes optional for manual nodes (own decision doc when built).
- **The deferred tool-call audit-logging task** (`docs/decisions/2026-07-28-extraction-tool-call-audit-logging.md`) folds into Phase 1's audit-logging workstream (slice 1D) rather than remaining standalone.
- **`docs/ux/`** gets its first real content this phase (design-system baseline + flow specs).

## Gate before scaffolding

The new `api/` + frontend module boundary (`Phase1_Architecture.md` §5) is a new abstraction and must pass the `codebase-design` skill before any code is scaffolded, per CLAUDE.md's Module Boundary rule. This decision authorizes *entering* Phase 1 and settles its scope; it does not pre-approve the module decomposition.
