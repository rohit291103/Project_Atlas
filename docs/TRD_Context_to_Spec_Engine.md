# Technical Requirements Document (TRD)

## Product: Context-to-Spec Engine (MVP)

**Document owner:** Engineering
**Status:** Draft v1
**Companion documents:** PRD_Product_Knowledge_Layer_MVP.md, MVP_Roadmap.md

---

## 1. System Overview

The system ingests content from external sources (GitHub, Jira, Notion/Google Docs), extracts structured, typed elements representing product intent (goals, requirements, decisions, constraints, evidence, open questions), stores them in an append-only event log with provenance and confidence metadata, and allows humans to confirm/edit/reject extracted elements before assembling them into an exportable spec.

High-level flow:

```
[External Sources] 
      → [Ingestion Layer] 
      → [Extraction Pipeline (LLM-based)] 
      → [Event Log / Graph Store] 
      → [Confirmation UI] 
      → [Spec Assembly & Export]
      → [Q&A Retrieval Layer] (queries the same store)
```

---

## 2. Architecture Principles

1. **Read-only by default.** No write-back to source systems in MVP. This reduces integration risk, security surface, and trust burden.
2. **Extraction is a draft, never a fact.** Every extracted element is unconfirmed until a human acts on it. No unconfirmed element reaches an export.
3. **Event-sourced, not fixed-schema.** Store an append-only log of typed events; derive graph views/projections at query time. Avoid hard-coding a rigid stage pipeline (Goal→Problem→Evidence→...) as a storage constraint — model it as a flexible typed-edge system instead, so real-world messiness (revisited decisions, split requirements) doesn't break the schema.
4. **Provenance is non-negotiable.** Every stored element must carry a pointer back to its literal source (URL + excerpt reference), not just a paraphrase.
5. **Idempotent, incremental ingestion.** Re-running ingestion must not duplicate or corrupt existing confirmed data; only new/changed source content triggers new extraction.
6. **Least-privilege data access.** The system should only ever be able to see what the connecting user/service account already has permission to see in the source tool.

---

## 3. Data Model

### 3.1 Core Entities

**Source Reference**
```
SourceRef {
  id: UUID
  source_type: enum [github_pr, github_issue, github_commit, jira_ticket, notion_page, gdoc]
  external_id: string
  url: string
  excerpt: text          // the specific text span that supports the extraction
  fetched_at: timestamp
  workspace_id: UUID
}
```

**Node (typed knowledge element)**
```
Node {
  id: UUID
  type: enum [goal, problem, evidence, decision, requirement, constraint, 
              architecture_note, open_question, rejected_alternative]
  content: text
  confidence_score: float (0.0–1.0)
  status: enum [unconfirmed, confirmed, edited, rejected]
  source_refs: [SourceRef]         // one node can be supported by multiple sources
  created_by: enum [system, user]
  created_at: timestamp
  updated_at: timestamp
  updated_by: user_id | null
  workspace_id: UUID
  feature_scope_id: UUID           // scopes node to a specific feature/epic run
}
```

**Edge (relationship between nodes)**
```
Edge {
  id: UUID
  from_node_id: UUID
  to_node_id: UUID
  relation_type: enum [supports, derives_from, conflicts_with, 
                        implements, rejects, depends_on]
  confidence_score: float
  created_at: timestamp
}
```

**Event (append-only log entry — source of truth)**
```
Event {
  id: UUID
  event_type: enum [node_created, node_confirmed, node_edited, node_rejected, 
                     edge_created, spec_exported, ingestion_run]
  payload: JSON
  actor: user_id | "system"
  timestamp: timestamp
  workspace_id: UUID
}
```

All Node/Edge state is a materialized projection derived by replaying Events. This gives us versioning, audit history, and undo "for free," and avoids destructive updates to the graph.

### 3.2 Why event-sourced over fixed relational schema

- Supports full history/versioning without extra bookkeeping tables.
- Avoids brittle foreign-key constraints that break when real-world product decisions get revisited or split.
- Enables spec versioning (R15 in PRD) trivially — a spec export is just a snapshot of confirmed nodes at a point in the event log.
- Lets us evolve the node/edge taxonomy over time without migrating historical data.

---

## 4. Ingestion Layer

### 4.1 Connectors (MVP)
- **GitHub:** REST/GraphQL API — PRs (title, description, comments), linked issues, commit messages. OAuth app install, scoped to selected repos.
- **Jira/Linear:** REST API — tickets scoped by project/epic/label. OAuth or API token, scoped to selected projects.
- **Notion/Google Docs:** API-based read access to specific pages/docs the user explicitly connects (not full workspace crawl in MVP).

### 4.2 Ingestion Requirements
- Ingestion is **pull-based and scoped**: a user selects a feature/epic, and the system pulls only linked/relevant content (via labels, linked issues, referenced PRs) — not a full-workspace crawl.
- Incremental sync: store a `last_synced_at` per source connection; only fetch deltas on subsequent runs.
- Rate-limit aware: backoff and batch requests per source API limits.
- All ingested raw content is transient — stored only long enough to run extraction, then discarded; only extracted Nodes + SourceRefs (with excerpt, not full document) are persisted. This limits data retention exposure.

---

## 5. Extraction Pipeline

### 5.1 Approach (MVP)
- LLM-based extraction using a foundation model (Claude) via structured prompting — **not** a custom-trained model for MVP. Fine-tuning is explicitly deferred (see PRD Open Questions).
- Extraction runs per source document/thread, prompted to output structured JSON matching the Node/Edge schema, with:
  - Required source excerpt for every claim (no claim without a literal quote/reference from source).
  - Required confidence self-assessment (low/medium/high, mapped to a numeric score).
  - Required conflict flagging when contradictory information is detected across sources in the same run.
- Output is **strictly schema-validated** before being written as `node_created` events — malformed or unparseable model output is retried once, then surfaced as an ingestion error rather than silently dropped or guessed.

### 5.2 Conflict Detection
- When two sources produce nodes of the same type referencing the same feature scope with materially different content, create a `conflicts_with` edge and surface both to the user rather than auto-resolving.

### 5.3 Quality Feedback Loop (Phase 3+)
- Track edit/rejection rate per extraction run, source type, and node type.
- Use this signal to tune prompts (and, later, evaluate whether fine-tuning is warranted) — this is instrumentation-first, not a fine-tuning commitment for MVP.

---

## 6. Confirmation & Review Layer

- UI reads projected Node/Edge state for a feature scope, grouped by type and status.
- Actions (confirm/edit/reject/add manually) each write a corresponding Event; no direct mutation of Node table without an Event record.
- Manually-added nodes (`created_by: user`) skip confidence scoring and default to `confirmed`.
- Edited nodes retain a link to the original system-extracted version for audit/comparison.

---

## 7. Spec Assembly & Export

- Spec assembly is a read-only query: fetch all `confirmed` or `edited` nodes for a feature scope, grouped into sections (Context/Why, Requirements, Constraints, Architecture Notes, Open Questions), ordered by edge relationships (e.g., requirements grouped under the decisions/evidence that justify them).
- Export formats:
  - **Markdown**: human- and coding-agent-readable, with inline footnote-style links to source (`[1]: <github PR URL>`).
  - **JSON**: full structured export including node/edge metadata, confidence scores, and source refs, for programmatic consumption (e.g., piping directly into an agent's system context via API).
- Each export is itself recorded as a `spec_exported` event, capturing the exact node/edge snapshot included — this gives spec versioning "for free" from the event log.

---

## 8. Contextual Q&A Layer

- Retrieval-augmented Q&A scoped to a feature's confirmed + unconfirmed nodes (clearly distinguishing which in the answer).
- Standard RAG pattern: embed node content, retrieve top-k relevant nodes for a query, pass to LLM with instruction to answer only from retrieved context and cite node/source references.
- If retrieved evidence is sparse or conflicting, the model must explicitly say so rather than asserting a confident answer — enforced via prompt instructions and a post-hoc check on retrieved-node confidence scores.

---

## 9. Access Control & Security

- **AuthN:** OAuth via source systems (GitHub, Jira, Notion/Google) for connecting; internal auth (SSO/SAML for enterprise pilots, deferred to Phase 4) for product access.
- **AuthZ:** RBAC at workspace level (MVP), extended to feature-level scoping in Phase 4. Permissions mirror source-system permissions where possible — a user should not see ingested content they couldn't already access at the source.
- **Data at rest:** encrypted; raw source content not persisted beyond extraction (see §4.2); only extracted nodes + excerpts + links persisted.
- **Data in transit:** TLS everywhere; source API tokens stored in a secrets manager (not in application DB).
- **Audit log:** every Event is inherently an audit record (actor, timestamp, action) — no separate audit system needed given the event-sourced design.
- **Admin controls:** explicit allow-list of repos/projects/doc spaces that can be connected per workspace; disconnecting a source purges its associated raw content (extracted nodes remain, flagged as "source disconnected").

---

## 10. Non-Functional Requirements

| Requirement | Target |
|---|---|
| Ingestion + extraction latency (single feature scope, ~20 source items) | < 3 minutes end-to-end |
| Spec export generation | < 5 seconds from confirmed-node query |
| Q&A response latency | < 5 seconds p95 |
| System availability (pilot phase) | 99.5% (best-effort, not yet enterprise SLA) |
| Data retention for raw ingested content | Ephemeral — purged post-extraction (see §4.2) |
| Extraction schema-validation failure rate | < 2% of runs (auto-retried once before surfacing as error) |

---

## 11. Tech Stack (Proposed, MVP)

- **Backend:** Any modern typed backend framework (e.g., Node/TypeScript or Python/FastAPI) — event log as an append-only Postgres table (JSONB payload) is sufficient for MVP scale; no need for a dedicated graph database yet given projected data volumes.
- **Graph projection:** Materialized views (or a lightweight in-process projection layer) built from the event table — defer adopting a dedicated graph DB (e.g., Neo4j) until query complexity or scale actually demands it.
- **LLM provider:** Claude via Anthropic API, using structured/JSON-constrained outputs for extraction and citations for Q&A.
- **Embeddings/retrieval:** Standard vector store (e.g., pgvector alongside the existing Postgres instance) — avoids introducing a separate infra dependency for MVP.
- **Frontend:** Standard SPA framework, React-based, given ecosystem maturity for the kind of confirmation/review UI required.
- **Connectors:** Direct API integration for GitHub/Jira/Notion in MVP; revisit MCP-based connector architecture as a longer-term integration strategy once the connector surface grows beyond 3–4 sources.

---

## 12. Explicit Technical Non-Goals (MVP)

- No dedicated graph database — Postgres + projections is sufficient at this scale.
- No fine-tuned extraction model — prompting + retrieval only.
- No write-back to any source system.
- No real-time collaborative multi-user editing (last-write-wins is acceptable for MVP review UI).
- No cross-workspace or cross-org querying.
- No automated dependency-propagation engine (deferred to post-MVP per roadmap Phase 3+ of original vision).

---

## 13. Key Technical Risks

| Risk | Mitigation |
|---|---|
| LLM extraction hallucinates unsupported claims | Hard requirement: every node must include a literal source excerpt; schema validation rejects nodes without one |
| Event log grows unmanageably large over time | Projections are cached/materialized; raw event table can be partitioned/archived per workspace as needed post-MVP |
| Source API rate limits throttle ingestion at scale | Scoped, incremental ingestion (not full-workspace crawl) keeps volume low in MVP |
| Confidence scores are poorly calibrated by the LLM | Track edit/rejection rate as a real-world calibration signal (§5.3); do not treat model self-reported confidence as ground truth without validation |
| Security review blocks enterprise pilots | Read-only architecture, ephemeral raw-content storage, and full audit-by-design (event log) directly address the most common enterprise objections |
