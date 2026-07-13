# Phase 0 Architecture: Foundation & Single-Source Proof

**Document owner:** Engineering
**Status:** Draft v1
**Companion documents:** PRD_Product_Knowledge_Layer_MVP.md, TRD_Context_to_Spec_Engine.md, MVP_Roadmap.md
**Scope:** Implementation architecture for Roadmap Phase 0 only (Weeks 1-4) — proving the extraction loop on GitHub, single team, internal tool.

---

## 1. Goal

Prove the core extraction loop end-to-end on one source (GitHub) before building anything else. This document scopes *how* Phase 0 is built, as a Python-first, AI-native implementation of the TRD's architecture principles — not a redesign of them.

---

## 2. Key Architectural Decision: Agentic Extraction

The TRD (§5.1) describes extraction as single-shot structured prompting: pre-fetch all linked content, one Claude call per document, output schema-validated JSON.

For Phase 0, we're instead building the extraction step as an **agent using the Claude Agent SDK**, with tools bound to the GitHub API:

- `fetch_linked_issue(number)`
- `fetch_commit(sha)`
- `search_repo(query)`

Rather than pre-fetching every cross-reference in ingestion code, the agent follows references it discovers in the text (e.g. a PR description mentioning "see ISSUE-123") by calling the relevant tool itself. This is more AI-native and better suited to the messiness of real historical PRs, at the cost of more complexity, latency, and per-run token cost than single-shot prompting.

**Guardrails:**
- Every tool call is logged (provenance + audit trail, and cost visibility).
- Max ~8 tool calls per extraction run, to bound cost and prevent runaway exploration on a single PR.
- The agent's final output is a **forced tool call** — `emit_extraction(nodes, edges)` — validated against the Pydantic schema below. Malformed output is retried once, then surfaced as an ingestion error (matches TRD §10 target: <2% schema-validation failure rate).
- All tools are read-only. No write scope to GitHub.

---

## 3. Tech Stack

| Layer | Choice | Rationale |
|---|---|---|
| Language | Python 3.12, `uv` for dependency management | Fast, modern tooling; project is Python-first per direction |
| Extraction | Claude Agent SDK | Agentic tool-using extraction (see §2) |
| GitHub access | `httpx`-based client, exposed as agent tools | Thin and read-only; no heavyweight SDK dependency |
| Schema | Pydantic v2 — `Node`, `Edge`, `SourceRef`, `Event` (mirrors TRD §3.1 exactly) | Structural validation gate before anything is persisted |
| Storage | **Supabase** (hosted Postgres), append-only `event_log` table (JSONB payload) | Event-sourced from day one (TRD §3.2) — Phase 1's confirm/edit/reject events slot in later with no migration. Hosted means no local Docker setup; pgvector ships enabled, so Phase 3's Q&A embeddings need zero new infra when that phase arrives |
| ORM / migrations | SQLAlchemy 2.0 + Alembic | Standard, unopinionated, adequate at this scale |
| Interface | Typer CLI (`atlas ingest`, `atlas review`) | Phase 0 is explicitly internal-tool-only, no UI polish (Roadmap Phase 0 scope) |
| Review output | Rich-formatted console report | Stands in for the confirmation UI, which is Phase 1 scope |
| Tests | pytest + recorded GitHub API fixtures (VCR-style) | Replayable extraction runs without live API calls / token cost on every test run |
| Evals | `tests/evals/` — golden-set fixtures + Tier 1 deterministic pytest checks (schema validity, provenance verification, rubric); Tier 2 judgment grading via the `extraction-quality-review` skill | LLM output isn't exact-match-testable, but provenance and schema validity are — see `.claude/skills/writing-evals/SKILL.md` |

---

## 4. Data Flow

```
atlas ingest --repo <owner/name> --pr <number>
      │
      ▼
ingestion/github.py — fetch seed PR (title, description, comments)
      │
      ▼
extraction/agent.py — Claude Agent SDK agent, tools:
   fetch_linked_issue(number)
   fetch_commit(sha)
   search_repo(query)
      │  (agent follows references it finds in the text;
      │   each tool call logged for provenance/audit)
      ▼
emit_extraction(nodes, edges)  ← forced tool call, Pydantic-validated
      │  (invalid output → retry once → else surfaced as ingestion error)
      ▼
Supabase event_log: node_created / edge_created events (append-only)
      │
      ▼
atlas review --feature-scope <id>
   replays events → Node/Edge projection → Rich console report,
   grouped by type, showing confidence + source excerpt + URL
   → this is the manual review step against 3-5 real historical PRs
```

---

## 5. Repo Layout

```
src/atlas/
  config.py              # env: ANTHROPIC_API_KEY, GITHUB_TOKEN, SUPABASE_DB_URL
  models/
    schema.py            # Pydantic: Node, Edge, SourceRef, Event
  storage/
    db.py                # SQLAlchemy engine/session
    tables.py            # event_log table (JSONB payload)
    projections.py        # replay events -> materialized Node/Edge views
  ingestion/
    github.py            # read-only PR/issue/commit fetchers
  extraction/
    agent.py             # Claude Agent SDK agent definition
    tools.py             # tool implementations (fetch_linked_issue, fetch_commit, search_repo)
    prompts.py            # extraction system prompt / instructions
  cli.py                 # Typer entrypoint
tests/
  fixtures/              # recorded GitHub API responses
  test_extraction.py
  evals/
    golden_set/          # real historical PRs used as the standing validation set
      pr-<n>/
        raw.json          # recorded fetch of the PR + linked issues/commits
        rubric.yaml        # hand-authored minimum expectations (required node types, excerpt-source pairs)
    test_golden_set.py    # Tier 1 deterministic checks (schema validity, provenance-excerpt verification, rubric) — see the writing-evals and extraction-quality-review skills
pyproject.toml
```

No local database container to run — `SUPABASE_DB_URL` points at a hosted Supabase project's connection string (a free-tier project is sufficient at Phase 0 scale).

`tests/evals/` is deliberately distinct from `tests/fixtures/` + `test_extraction.py`: the latter are ordinary unit tests for extraction *code* (can mock the LLM call); the former are golden-set evals that assert properties of real agent *output* (schema validity, and — critically — that every source excerpt the agent claims actually appears in the raw source text). Judgment-based grading (does the content read as correct, did the agent miss something) isn't pytest-automatable and is run manually via the `extraction-quality-review` skill instead; see `.claude/skills/writing-evals/SKILL.md` for why that split exists.

---

## 6. How This Maps to TRD Principles

| TRD Principle (§2) | Phase 0 Implementation |
|---|---|
| Read-only by default | All GitHub tools are fetch-only; agent has no write scope |
| Extraction is a draft, never a fact | Nodes are written as `unconfirmed`; Phase 0 has no confirmation UI yet, but the state field exists from day one |
| Event-sourced, not fixed-schema | `event_log` (JSONB) is the source of truth from the first commit; Node/Edge tables are projections replayed from events |
| Provenance is non-negotiable | Schema validation rejects any Node without a `SourceRef` (URL + excerpt) — enforced structurally, not by convention |
| Idempotent, incremental ingestion | Out of scope for Phase 0 (single PR at a time, no scheduled re-sync yet) — deferred to Phase 1 scoped ingestion |
| Least-privilege data access | Single fine-grained GitHub PAT scoped to one public repo; real OAuth app deferred to when there's an actual pilot customer |

---

## 7. Explicit Phase 0 Simplifications

These are deliberate simplifications, not oversights — they match the Roadmap's Phase 0 scope ("no UI polish, internal tool only"):

- No confirmation UI — review happens via CLI + console report.
- No RBAC / auth beyond a single local PAT — Phase 0 is one team, internal.
- No incremental sync — Phase 0 processes one PR/feature at a time on demand.
- No vector store / embeddings usage — Q&A (which needs retrieval) is Phase 3, not Phase 0. (Supabase's pgvector extension is available whenever that phase starts; nothing to provision then.)
- No task queue (Celery/etc.) — extraction runs are synchronous CLI invocations; volume at this stage doesn't warrant async infra.

---

## 8. Validation Target

Run `atlas ingest` + `atlas review` against 3-5 real PRs from a well-documented public open-source repository (candidate selection TBD — prefer a mid-size, actively maintained repo with substantive PR descriptions and linked issues, since extraction needs real signal to work with). These same PRs become the `tests/evals/golden_set/` — grade each run against the Roadmap's Phase 0 exit criteria ("usable, mostly-correct structured output") using the two-tier process in the `extraction-quality-review` skill: deterministic checks (schema, provenance) run automatically via pytest; correctness/completeness/calibration are graded manually per the `writing-evals` skill's guidance, since a sample of 3-5 is too small to treat as a statistic rather than a qualitative read.

---

## 9. Open Questions Carried Into Scaffolding

1. Which specific public repo to validate against (pick at scaffolding time, not architecture time).
2. Exact confidence mapping table (low/medium/high → numeric) — deterministic, to be finalized in `extraction/prompts.py`, not a second model call.
3. Tool-call budget (~8 suggested) may need tuning once we see real agent behavior on messy PRs.
