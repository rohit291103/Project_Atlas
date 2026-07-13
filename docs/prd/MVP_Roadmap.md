# MVP Roadmap: Context-to-Spec Engine

**Scope:** From zero to a pilot-ready MVP, sequenced to de-risk the core bet (extraction quality + trust) before investing in breadth.

**Guiding principle:** Every phase must end with something a real team can use and give feedback on — no phase is "infrastructure only."

---

## Phase 0 — Foundation & Single-Source Proof (Weeks 1–4)

**Goal:** Prove the core extraction loop works end-to-end on one source, for one team, before building anything else.

**Scope:**
- Read-only ingestion from **GitHub only** (PRs, linked issues, commit messages).
- Basic extraction pipeline: goals, requirements, decisions, open questions — no UI polish, internal tool only.
- Manual review by the team building it, against 3–5 real historical features, to sanity-check extraction quality.
- Core data model v0: append-only event log, typed nodes (goal, requirement, decision, evidence), typed edges, confidence score field, provenance field.

**Exit criteria:** Extraction produces usable, mostly-correct structured output for at least 3 real past features, validated manually.

**Deliverable:** Internal proof-of-concept, not customer-facing.

---

## Phase 1 — Confirmation UI & Second Source (Weeks 5–9)

**Goal:** Make the loop usable by a non-engineer (PM) and extend to a second source.

**Scope:**
- Add Jira (or Linear) as second ingestion source.
- Build the confirmation UI: unconfirmed vs. confirmed states, inline edit, source deep-links, conflict flags.
- Scoped ingestion by epic/label rather than full workspace.
- Basic RBAC (workspace-level) and audit logging.

**Exit criteria:** A PM outside the build team can, unassisted, connect two sources, review extracted elements, and confirm/reject them in under 20 minutes.

**Deliverable:** First closed-alpha build, used internally + 1 friendly design-partner team.

---

## Phase 2 — Spec Generation & Export (Weeks 10–13)

**Goal:** Ship the actual sellable unit of value — a structured, exportable spec.

**Scope:**
- Spec assembly from confirmed elements (Context/Why, Requirements, Constraints, Architecture Notes, Open Questions).
- Export to Markdown and JSON.
- Spec versioning (compare v1 vs v2 of a spec as source content changes).
- Add third source: one doc tool (Notion or Google Docs, whichever the design partner uses).

**Exit criteria:** A design-partner team generates a spec, drops it into a coding agent's context, and reports whether output quality improved vs. their normal workflow.

**Deliverable:** MVP v1 — ready for a small paid pilot cohort (3–5 teams).

---

## Phase 3 — Contextual Q&A + Quality Feedback Loop (Weeks 14–18)

**Goal:** Add the second high-value, low-lift feature and start closing the extraction-quality feedback loop.

**Scope:**
- Natural-language Q&A over ingested content ("why does this feature exist?") with citations.
- Confidence-aware answers (flag thin/conflicting evidence rather than asserting).
- Instrumentation: track % of extracted elements confirmed-without-edit over time, to measure whether extraction quality improves as usage grows.
- Begin capturing structured feedback signal (edits, rejections) to inform prompt/extraction improvements.

**Exit criteria:** Pilot teams use Q&A weekly without prompting; extraction-confirmation rate trending upward across two consecutive weeks of usage.

**Deliverable:** MVP v1.1 — pilot cohort expanded to 8–10 teams.

---

## Phase 4 — Hardening for Broader Pilot (Weeks 19–24)

**Goal:** Remove the blockers that stop this from being a real enterprise pilot, not just a friendly-customer trial.

**Scope:**
- Full RBAC (feature-level, not just workspace-level) and admin controls over what can be ingested.
- Data retention and encryption review; security questionnaire readiness (SOC2-track groundwork, not certification yet).
- Incremental sync (only process new/changed content) to reduce cost and latency.
- Basic usage analytics dashboard for admins (spec-runs, confirmation rates, active users) — internal + light customer-facing view.

**Exit criteria:** Passes a basic security review from at least one prospective enterprise pilot's IT/security team.

**Deliverable:** MVP v2 — ready for broader paid pilot / initial GTM push.

---

## What Comes After the MVP (Not Yet Scheduled)

These are intentionally **not** part of this roadmap — they are the next horizon, to be scoped only once MVP usage data validates the core extraction-trust loop:

- Automated change propagation across dependent artifacts (Phase 3 of the original vision).
- Slack/meeting-transcript ingestion (higher extraction complexity, conversational data).
- Cross-team / org-wide graph views.
- Fine-tuned or custom extraction models (vs. current prompting + retrieval approach).

---

## Roadmap Summary Table

| Phase | Weeks | Core Deliverable | Primary Risk Being Retired |
|---|---|---|---|
| 0 | 1–4 | Internal extraction proof (GitHub only) | Does extraction even work? |
| 1 | 5–9 | Confirmation UI + 2nd source | Can a non-engineer use this? |
| 2 | 10–13 | Spec generation & export | Does this improve coding agent output? |
| 3 | 14–18 | Contextual Q&A + feedback loop | Does extraction quality improve with usage? |
| 4 | 19–24 | Security/RBAC hardening | Will enterprises actually pilot this? |
