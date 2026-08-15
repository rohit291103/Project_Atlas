# CLAUDE.md — Project Atlas (Context-to-Spec Engine)

This file is the entry point for any AI session working in this repo. Read it first. Then read `docs/tracker.md` (every session, via the `tracker-sync` skill) for current state — this file describes what's permanently true; the tracker describes what's true *right now*.

## What this project is

AI coding agents can implement software faster than teams can supply them with correct context. Project Atlas ingests existing artifacts for a feature (GitHub PRs/issues now, Jira/Notion later), extracts structured, provenance-linked claims (goals, requirements, decisions, constraints, open questions), and assembles them into a spec a coding agent or human can execute against with confidence. Full problem statement: `docs/prd/PRD_Product_Knowledge_Layer_MVP.md` §1.

## Companion documents

| Doc | Contains |
|---|---|
| `docs/prd/PRD_Product_Knowledge_Layer_MVP.md` | Product requirements, target users, success metrics, non-goals |
| `docs/architecture/TRD_Context_to_Spec_Engine.md` | Full technical architecture, data model, all phases |
| `docs/prd/MVP_Roadmap.md` | Phased roadmap (Phase 0–4), exit criteria per phase |
| `docs/architecture/Phase0_Architecture.md` | Current phase's concrete implementation plan (stack, repo layout, data flow) |
| `docs/tracker.md` | Living current-state snapshot — read first, every session |

These are the source of truth. Don't re-derive scope, schema, or architecture from memory when it's already written down — read the doc.

## Roadmap — the whole story

This file describes the **entire project across all five phases** — philosophy, module boundary, non-goals — not just whichever phase is currently in progress. It doesn't get rewritten as phases advance; only the "Current Development Phase" section below does. Full detail: `docs/prd/MVP_Roadmap.md`.

| Phase | Weeks | Core Deliverable | Primary Risk Being Retired |
|---|---|---|---|
| **0** ← current | 1–4 | Internal extraction proof (GitHub only) | Does extraction even work? |
| 1 | 5–9 | Confirmation UI + 2nd source | Can a non-engineer use this? |
| 2 | 10–13 | Spec generation & export | Does this improve coding agent output? |
| 3 | 14–18 | Contextual Q&A + feedback loop | Does extraction quality improve with usage? |
| 4 | 19–24 | Security/RBAC hardening | Will enterprises actually pilot this? |

Each phase's *concrete* implementation plan gets its own doc in `docs/architecture/` (`Phase0_Architecture.md` now; `Phase1_Architecture.md` etc. as each phase starts) — read this file for the permanent picture, read the current phase's architecture doc for what's actually being built right now.

## Current Development Phase

**Phase 1** (Roadmap Weeks 5–9): make the loop usable by a non-engineer (a PM) and extend to a second source. Concrete plan: `docs/architecture/Phase1_Architecture.md`. Exit criterion: a PM outside the build team can, *unassisted*, connect two sources, review extracted elements, and confirm/reject them in under 20 minutes. **Primary risk being retired: can a non-engineer actually use this?** — not "does more get built."

In scope now (Phase 0's extraction exit criterion was met 2026-07-28 — `docs/decisions/2026-07-28-phase0-exit-phase1-entry.md`): the **confirmation UI** (React SPA + FastAPI `api/`), a **second source (Jira)**, **scoped ingestion** by epic/label, **workspace-level RBAC + audit logging**, and cross-source **conflict detection**. Sequencing is **UI-first on existing GitHub data** (retire the primary risk before adding Jira) — see the four vertical slices in `Phase1_Architecture.md` §3.

Explicitly **not** current priority (these are Phase 2–4, don't build ahead of them): spec generation/export, contextual Q&A / retrieval, feature-level RBAC, incremental delta-sync, a third (doc) source, SSO/SAML. If a task implies one of these, flag it rather than quietly building it. The new `api/` + frontend module boundary must pass a `codebase-design` pass before it is scaffolded.

## Engineering Philosophy (non-negotiable — TRD §2)

1. **Read-only by default.** No write-back to any source system, ever, in any phase currently scoped.
2. **Extraction is a draft, never a fact.** Every extracted element is unconfirmed until a human acts on it. Nothing unconfirmed reaches an export (once exports exist) or gets treated as settled in the meantime.
3. **Event-sourced, not fixed-schema.** `event_log` is the source of truth; `Node`/`Edge` state is a projection replayed from events. Never mutate a Node/Edge table directly — write an event.
4. **Provenance is non-negotiable.** Every stored Node must carry a literal source excerpt + URL, not a paraphrase. A Node without a `SourceRef` is a bug, not an edge case — schema validation should make it structurally impossible.
5. **Idempotent, incremental ingestion.** Re-running ingestion must never duplicate or corrupt existing data (binding from Phase 1's scoped/incremental sync onward).
6. **Least-privilege data access.** The system only ever sees what the connecting credential already has access to in the source tool.

**One amendment, made deliberately (2026-08-15, slice 2B).** The `security-review` checklist below used to read "no secret ever lands in the database (env/secrets manager only)". That held while there was one GitHub token and one Jira token in `.env`; it cannot hold once a PM connects their own products' sources *from a browser*, which is what Phase 1 exists to prove. Per-product source credentials now live in the `connection` table **encrypted at rest with a key held outside the database** (`ATLAS_SECRET_KEY`), are never returned by any endpoint (`ConnectionView` has no field one could occupy), are never logged, and are deletable — because revocation must actually remove a credential. Full argument and the posture that replaces the rule: `docs/decisions/2026-08-15-connections-and-ui-ingestion.md` §1. **Nothing else changed:** no other secret goes in the database, and application/session secrets stay in env.

## System Architecture / Module Boundary

This is the module decomposition — don't invent a different one without running it through the `codebase-design` skill first:

1. **`ingestion/`** — read-only source connectors. GitHub only in Phase 0; Jira/Linear and a doc tool join in Phase 1–2.
2. **`extraction/`** — the Claude Agent SDK agent + its tools + prompts. Turns raw ingested content into schema-validated `Node`/`Edge` output. This is where "AI reasoning" lives — it never writes directly to storage without passing through schema validation first.
3. **`storage/`** — `event_log` (Supabase/Postgres, append-only JSONB) plus projections (materialized Node/Edge views replayed from events).
4. **`cli/`** — Typer entrypoint. The engineer-facing read/debug path. **It holds no orchestration** as of slice 2B (below) — the commands read credentials from the environment, hand `pipeline` a request, and render the result.
5. **`api/`** — a thin FastAPI read/write layer over `storage/` projections + the event log. Owns HTTP, auth and serialization and **no domain logic**: every write endpoint is authenticate → load → call one `storage/` function → return.
6. **`pipeline.py`** — one ingestion run, start to finish: parse a target → build a read-only client → run the agent → write validated events. Its own module because it spans `ingestion/`, `extraction/` and `storage/` and has two real callers (the CLI and the ingest endpoint); duplicating it would let the path along which "extraction never reaches storage unvalidated" holds drift between them. `tests/test_cli.py` fails if orchestration returns to `cli.py`.

Modules 5 and 6 arrived during Phase 1 and each passed the `codebase-design` gate before it was scaffolded: `api/` in `docs/decisions/2026-08-11-api-frontend-module-boundary.md`, `pipeline.py` in `docs/architecture/product-model-and-frontend-rebuild-v1.md` §5. Alongside them sits the **React frontend** (repo-root `frontend/`) — the confirmation UI, the public landing/sign-in surface, and the Sources screen — talking only to `api/`. The CLI stays as the engineer-facing/debug read path, not replaced. Still later per the Roadmap: spec assembly/export (Phase 2), Q&A retrieval layer (Phase 3).

## Tech Stack (Phase 0 — see `docs/architecture/Phase0_Architecture.md` for full rationale)

Python 3.12 + `uv` · Claude Agent SDK (agentic extraction) · `httpx` (GitHub) · Pydantic v2 (schema) · Supabase (hosted Postgres, event log; pgvector available for Phase 3) · SQLAlchemy 2.0 + Alembic · Typer (CLI) · Rich (console review output) · pytest + recorded API fixtures · `tests/evals/` golden-set harness for grading LLM output itself (see `writing-evals` skill).

## Explicit Non-Goals (PRD §2.3, TRD §12 — don't build these ahead of schedule)

No dedicated graph database (Postgres + projections is sufficient). No fine-tuned extraction model (prompting + retrieval only). No write-back to any source system. No real-time collaborative editing. No cross-workspace/cross-org querying. No automated dependency-propagation engine. No task queue, vector store usage, or RBAC until the phase that actually needs them — UI-triggered ingestion runs **in-process** via FastAPI `BackgroundTasks` precisely so no broker is introduced; the day there is more than one API worker, or a run that must survive a deploy, is the day a queue is warranted, and that is the phase that should build it.

## Documentation Rules

**Chats are temporary. Documentation is permanent.** `docs/` has six subfolders, plus `docs/tracker.md` as the one file that lives outside all of them (disposable, overwritten in place — everything else here is permanent and never silently rewritten):

| Folder | Contains | Naming |
|---|---|---|
| `docs/prd/` | The master PRD + Roadmap, plus any feature-level PRDs beyond them (`to-prd` skill / `prd-writer` agent) | Master docs keep their existing names; new PRDs are `kebab-case-topic-v1.md` (bump `v2`, `v3`, … on major revision) |
| `docs/architecture/` | The master TRD + the current phase's architecture doc, plus any feature-level architecture docs | Same convention — `PhaseN_Architecture.md` for phase docs, `kebab-case-topic-v1.md` for feature-level ones |
| `docs/decisions/` | Decision log, one file per decision or cleanup pass (`docs-sync` skill) | `YYYY-MM-DD-short-slug.md`, never overwritten |
| `docs/handoff/` | Structured handoff notes for another collaborator (`handoff` skill) | `YYYY-MM-DD-short-slug.md` |
| `docs/research/` | External research findings (validation-repo notes, extraction-quality run logs, competitive landscape) | `kebab-case-topic-v1.md` |
| `docs/ux/` | Design-system baseline, page/flow specs — doesn't exist until Phase 1's confirmation UI | `kebab-case-topic-v1.md` |

A version bump (`v2`, a new `PhaseN_Architecture.md`) always creates a new file — a major revision is never a silent overwrite of the previous one; that history is part of the record.

## Workflow: the path for each kind of task

### New feature
1. **Start:** `tracker-sync` skill, Mode A — read `docs/tracker.md` for current state.
2. **Idea not shaped yet?** → `feature-discussion` agent (Socratic partner, pressure-tests scope against this file's Non-Goals and Current Phase before anything is drafted).
3. **Idea shaped, ready to spec?** → `to-prd` skill or `prd-writer` agent → saved to `docs/prd/`.
4. **Introduces a new or ambiguous domain term** (Node/Edge/Event vocabulary, confidence vs. status, etc.)? → `domain-modeling` skill.
5. **New module or abstraction?** → `codebase-design` skill before scaffolding it.
6. **While coding:** `tdd` skill — mandatory test-first for extraction schema validation, event-log/projection logic, and any deterministic calculation; lighter touch for CLI wiring or prompt-only tweaks.
7. **Changed the extraction agent's prompt or tools, or adding any new LLM-call code path?** → `writing-evals` skill for methodology (deterministic vs. judgment checks, golden-set discipline), then `extraction-quality-review` skill to actually run it against the Phase 0 validation PRs before considering it done.
8. **After coding:** the global `code-review` skill (correctness/simplification), the `backend-reviewer` agent (Atlas Engineering Philosophy adherence), the global `verify` skill (actually run it end-to-end), and the global `security-review` skill if the change touches ingestion, credentials, or stored data.
9. **End:** `tracker-sync` Mode B to refresh `docs/tracker.md`; `docs-sync` Mode B if a non-trivial decision was made this session.

### Bug fix
1. `diagnosing-bugs` skill — reproduce, minimize, hypothesize, instrument, fix, test. A hallucinated Node/Edge or one missing/wrong provenance is **Critical** severity — same tier as a security bug, because it's exactly the failure mode this whole product exists to prevent.
2. Any Critical-tier fix needs a regression test (`tdd` skill) before it's done.
3. `tracker-sync` Mode B if the fix changes what's "Done."

### Security review
1. Global `security-review` skill on the pending diff.
2. Cross-check TRD §9: read-only architecture preserved, credential scoped to least privilege, no raw source content persisted beyond the extraction run, and **source credentials only ever reach the database through `storage/connections.py`** — encrypted, key in env, never in a response model, never in a log line, deletable (see the amendment in Engineering Philosophy above). Every other secret is env/secrets-manager only.
3. Touching Supabase schema or access patterns? Check the `security-*` prefixed rules in the `supabase-postgres-best-practices` skill (RLS basics apply once there's more than one credential/tenant — not yet in Phase 0, but design with it in mind).

### Refactor / architecture change
1. `codebase-design` skill before adding structure — most new abstractions in a project this young are premature; the skill's checklist is there to catch that.
2. `improve-codebase-architecture` skill once there's real, working code to deepen — not yet meaningful while `src/atlas/` is still being scaffolded.

### Merge conflicts
`resolving-merge-conflicts` skill — unchanged, fully generic.

### Handing off to another tool or collaborator
`handoff` skill → saved to `docs/handoff/`.

## Agents available

| Agent | Use for |
|---|---|
| `feature-discussion` | Shaping a raw idea before it's a PRD |
| `prd-writer` | Drafting and saving a PRD to `docs/prd/` |
| `backend-reviewer` | Reviewing ingestion/extraction/storage code for Engineering Philosophy adherence (read-only, provenance, event-sourcing, agent tool-call safety) |
| `frontend-reviewer` | Active as of Phase 1 — reviews the confirmation UI (React SPA) for design-system adherence and real-browser defects once it exists. Pair with the `brandkit` + `design-taste-frontend-v1` skills when building it. |

## What NOT to do

- Don't let extraction output reach storage without passing Pydantic schema validation — this is the one rule with zero exceptions, equivalent in severity to "never let an LLM directly calculate a value that matters."
- Don't add infrastructure (task queue, dedicated graph DB, vector store usage) ahead of the phase that actually needs it.
- Don't build the confirmation UI, RBAC, a second source, or spec export before Phase 0's exit criteria are actually met and the user has agreed to move on.
- Don't treat your own extraction output, PRD draft, or architecture proposal as settled — per the PRD's Workflow Philosophy, nothing AI-generated is production truth until the user validates it.
