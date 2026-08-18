# Product Requirements Document (PRD)

## Product: Context-to-Spec Engine (Working Name — Project Atlas, MVP Scope)

**Document owner:** Product
**Status:** Draft v1
**Audience:** Engineering, Design, GTM, Leadership

---

## 1. Problem Statement

AI coding agents (Claude Code, Cursor, Codex, and similar tools) can implement software far faster than teams can supply them with correct, complete context. Today, the context a coding agent needs — *why* a feature exists, *what* was decided, *what* was rejected, *what constraints apply* — is scattered across PRDs, Jira tickets, Slack threads, meeting notes, and pull requests. No canonical, machine-readable representation of this intent exists.

As a result:
- Coding agents infer missing context, producing plausible-but-wrong implementations.
- Engineers spend significant time manually assembling context before delegating work to an agent.
- When requirements change, nothing propagates automatically to the docs, code, or specs that depend on them.
- Institutional knowledge about *why* decisions were made evaporates as people and tools change.

We are **not** attempting to solve all of this in v1. This PRD scopes the **first sellable unit of value**: a system that ingests existing artifacts for a single feature or workstream, and generates a structured, provenance-linked specification that a coding agent (or a human) can execute against with confidence.

This is the wedge. The long-term Product Graph vision is the destination this wedge is designed to grow into — not something we build upfront.

---

## 2. Goals

### 2.1 Primary Goal (MVP)
Enable a product/engineering team to generate a trustworthy, structured spec for a feature or task — automatically assembled from existing artifacts (tickets, docs, threads, PRs) — with every claim in the spec traceable back to its source, in under 10 minutes, with less manual assembly than today.

### 2.2 Secondary Goals
- Establish the underlying data model (event log + typed nodes/edges) that will later support the full Product Graph, without forcing users to adopt new workflows to get value today.
- Prove, with real usage data, that AI-generated code quality improves measurably when built against a generated spec vs. an unassisted prompt.
- Build the trust mechanism (confidence scores + human confirmation) that will be required for every later feature (propagation, org-wide graph, etc.).

### 2.3 Non-Goals (explicitly out of scope for MVP)
- Full bi-directional sync / becoming system-of-record for any connected tool.
- Cross-team or cross-org graph views.
- Automated change propagation across dependent artifacts.
- Replacing Jira, Notion, Linear, or any PM tool.
- Real-time collaborative editing of the graph.
- Executive/leadership reporting dashboards.

---

## 3. Target Users (MVP)

| User | Role in MVP |
|---|---|
| **Product Manager** | Initiates a "spec run" for a feature; reviews and confirms extracted context |
| **Staff Engineer / Tech Lead** | Reviews technical portions of the generated spec; adds architecture constraints |
| **AI Engineering / Platform Team** | Consumes the generated spec as input to coding agents; provides feedback on spec quality |

We are explicitly **not** targeting executives, compliance, or customer success in the MVP — that expansion comes later, once trust is established with the core builder audience.

---

## 4. User Stories

1. As a PM, I want to select a feature/epic and have the system pull in all linked tickets, docs, and relevant Slack threads, so I don't have to manually reconstruct context before writing a spec.
2. As a PM, I want to see exactly which source (ticket, doc, message) supports each claim in the generated spec, so I can trust and verify it before it's used.
3. As a tech lead, I want to confirm, edit, or reject any extracted requirement or constraint, so incorrect inferences never silently reach the coding agent.
4. As an AI engineering lead, I want to export the confirmed spec in a structured format (Markdown/JSON) that can be dropped directly into a coding agent's context, so agents produce more accurate implementations.
5. As a PM, I want to ask "why does this feature exist / why was this decided" and get an answer with citations, without having to search five tools manually.
6. As an admin, I want to control exactly which sources and channels the system can read from, and who can see the generated specs, so sensitive strategic information stays protected.

---

## 5. Product Requirements

### 5.1 Ingestion
- **R1.** System must connect (read-only) to: GitHub (PRs, commits, issues), Jira (or Linear), and one document source (Notion or Google Docs) at MVP launch.
- **R2.** System must allow a user to scope ingestion to a specific feature/epic/label rather than ingesting an entire workspace at once.
- **R3.** Ingestion must support incremental sync (only new/changed content re-processed), not full re-ingestion on every run.
- **R4.** System must respect source-level permissions — a user cannot see content they don't already have access to in the source tool.

### 5.2 Extraction & Structuring
- **R5.** System must extract candidate structured elements from ingested content: goals, requirements, constraints, decisions, rejected alternatives, and open questions.
- **R6.** Every extracted element must carry: source reference (deep link), confidence score, and extraction timestamp.
- **R7.** Extraction must be re-runnable on demand when new source content is added, without discarding previously confirmed edits.
- **R8.** System must flag conflicting information across sources (e.g., two tickets stating different acceptance criteria) rather than silently picking one.

### 5.3 Human Review & Confirmation
- **R9.** All extracted elements start in an "unconfirmed" state and must be explicitly confirmed, edited, or rejected by a user before being included in an exported spec.
- **R10.** Users must be able to manually add elements not captured by extraction (e.g., a constraint mentioned verbally in a meeting).
- **R11.** System must show a clear visual distinction between confirmed and unconfirmed content at all times.

### 5.4 Spec Generation & Export
- **R12.** System must generate a structured spec document combining all confirmed elements, organized by: Context/Why, Requirements, Constraints, Architecture Notes, Open Questions.
- **R13.** Export formats: Markdown (for direct use in coding agent context files) and JSON (for programmatic consumption).
- **R14.** Every exported spec must retain inline provenance links back to source artifacts.
- **R15.** System must version each spec export, allowing comparison between versions as source content changes.

### 5.5 Contextual Q&A
- **R16.** Users must be able to ask natural-language questions ("why does this feature exist?") scoped to ingested content for a feature, and receive an answer with citations to specific sources.
- **R17.** Answers must clearly indicate when supporting evidence is thin or conflicting, rather than presenting low-confidence answers as fact.

### 5.6 Access Control & Security
- **R18.** Role-based access control at the workspace and feature level.
- **R19.** Full audit log of who viewed, confirmed, edited, or exported any element.
- **R20.** Data encrypted at rest and in transit; no source content persisted beyond what's needed for extraction and display.
- **R21.** Admin controls to restrict which channels/repos/spaces can be ingested at all.

---

## 6. Success Metrics

> **Superseded 2026-08-18.** The metric set below was replaced in `docs/prd/roadmap-v2.md` — one guard
> metric, one primary, three supporting. In particular *"% of extracted elements confirmed without edit"*
> was retired as confounded (a rubber-stamping reviewer and a perfect extractor produce the same number).
> This section is retained unchanged as record.

| Metric | Target (90 days post-launch) |
|---|---|
| Time-to-first-spec for a new team | < 15 minutes from connecting sources to first export |
| % of extracted elements confirmed without edit | Track as a proxy for extraction quality (target improvement trend, not absolute number initially) |
| Coding agent output quality with spec vs. without (measured via internal eval or customer-reported rework rate) | Statistically meaningful improvement in at least one pilot team |
| Weekly active spec-runs per team | Indicates habitual usage vs. one-time trial |
| Manual context-assembly time saved (self-reported) | Directional signal, validated via user interviews |

We explicitly avoid vanity metrics like "nodes in graph" or "documents ingested" as primary success indicators — they don't correlate with value delivered.

---

## 7. Risks & Mitigations

| Risk | Mitigation |
|---|---|
| Extraction produces confidently wrong context | Confidence scoring + mandatory human confirmation before export |
| Low adoption due to setup friction | Scope ingestion to single feature/team, not full workspace, to minimize activation energy |
| Security concerns block enterprise pilots | RBAC, audit logs, and read-only architecture from day one |
| Competitive overlap with Glean/Notion AI/Atlassian Rovo | Position narrowly as "coding agent context," not general knowledge search |
| Users don't trust AI-generated specs | Transparency-first UX: every claim shows its source; nothing ships unconfirmed |

---

## 8. Open Questions

1. Which document source should be prioritized first for MVP — Notion or Google Docs — based on target pilot customers?
2. Should Slack ingestion be included in MVP or deferred to v1.1 given the added extraction complexity of conversational data?
3. What's the right pricing wedge — per-seat, per-workspace, or usage-based (per spec-run)?
4. Do we build our own extraction pipeline on top of a foundation model, or lean on retrieval + prompting initially and defer fine-tuning?

---

## 9. Appendix: Relationship to Long-Term Vision

This MVP is the first slice of the eventual Product Graph. The underlying data model (event log of typed nodes/edges with provenance) is designed to extend into:
- Multi-feature, cross-team graph views (Phase 2)
- Automated change propagation across dependent artifacts (Phase 3)
- Organization-wide operational memory (Phase 4)

No MVP decision should foreclose this future, but no MVP feature should be built *for* that future at the expense of shipping a fast, trustworthy wedge today.
