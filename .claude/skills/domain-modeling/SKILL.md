---
name: domain-modeling
description: Sharpens and locks down Project Atlas's data-model vocabulary (Node vs. Event vs. Edge, confirmed vs. edited vs. rejected, confidence vs. status, SourceRef vs. excerpt, feature_scope vs. workspace, etc.) so docs and code use the same words for the same concepts. Use when introducing a new data-model term, when a term is used inconsistently across /docs or code, or before modeling a new node/edge type or extraction concept.
---

# domain-modeling

Project Atlas lives or dies on trust, and trust collapses the moment two docs use the same word for different things, or two different words for the same thing (a `Node` that's "confirmed" in one doc and "verified" in another is exactly the kind of drift that makes a provenance-linked spec untrustworthy). This skill exists to catch that before it reaches code or a new doc.

## When to run this

- A new node/edge type, extraction concept, or storage field is about to be modeled.
- You notice a term used two different ways across `docs/`, `.claude/`, or code.
- Before writing a schema or API contract that will outlive this conversation.

Also check `docs/tracker.md` (via the `tracker-sync` skill) — if the module this term would land in doesn't exist yet, the reconciliation step below should still pick a canonical definition, just note it's being defined ahead of implementation.

## The core distinctions to keep straight in Atlas

These are the terms most likely to get blurred — check new content against this list first (all defined in `docs/architecture/TRD_Context_to_Spec_Engine.md` §3):

| Term | Is | Is NOT |
|---|---|---|
| **Event** | An append-only log entry — the actual source of truth (`node_created`, `node_confirmed`, `edge_created`, etc.) | A `Node` or `Edge` row — those are *projections* derived by replaying events |
| **Node** | A typed knowledge element (goal, requirement, decision, constraint, evidence, open question, etc.) — a *materialized view*, not directly written | An `Event` (see above); not something you `UPDATE` directly — a change is a new event |
| **Edge** | A typed relationship between two Nodes (`supports`, `conflicts_with`, `implements`, etc.) | A `SourceRef` (an edge connects two Nodes; a SourceRef connects a Node to external evidence) |
| **SourceRef** | A pointer to the literal external evidence for one Node — URL + excerpt, not a paraphrase | The Node's `content` field (content is the extracted *claim*; SourceRef is the *evidence* for that claim) |
| **Confidence score** | A 0.0–1.0 numeric estimate of extraction certainty, mapped deterministically from the agent's self-reported low/medium/high | `status` (see below) — a Node can be `high confidence` and still `unconfirmed`; the two are independent axes |
| **Status** | The human-review lifecycle state of a Node: `unconfirmed` → `confirmed` / `edited` / `rejected` | Confidence (see above); status changes only via a human action (or `created_by: user`, which defaults to `confirmed`) |
| **Feature scope** | The unit a Node/ingestion run is bounded to — one feature/epic (`feature_scope_id`) | Workspace (a workspace can contain many feature scopes; ingestion is always scoped to one feature, never a full workspace crawl) |
| **Ingestion run** | The act of pulling raw content from a source (GitHub PR, issue, commit) | An "extraction run" — ingestion fetches raw content; extraction is the separate step that turns it into Nodes/Edges |
| **Conflict** (`conflicts_with` edge) | Two Nodes of the same type, same feature scope, with materially different content, surfaced to the user | Something the system auto-resolves — conflicting Nodes are never silently reconciled (TRD §5.2) |

## Workflow

1. **Inventory** — grep the term (and close synonyms) across `docs/` and any code in `src/atlas/`. List every place it's defined or used.
2. **Reconcile** — if usages conflict, the canonical definition wins from (in order): `docs/architecture/TRD_Context_to_Spec_Engine.md` §3 (if the term is already a schema field) → `docs/prd/PRD_Product_Knowledge_Layer_MVP.md` → root `CLAUDE.md`. If none of these define it yet, propose one definition and say so explicitly — don't silently pick one.
3. **Record** — new or clarified terms belong in `docs/architecture/TRD_Context_to_Spec_Engine.md` (if amending the core schema — flag this as a notable change, don't edit it silently) or a `docs/architecture/` note for a term scoped to one feature. Don't invent a new `/docs` subfolder for a glossary; route per the `docs-sync` skill's Mode C.
4. **Flag, don't silently rewrite** — if you find an existing doc using a term incorrectly per this reconciliation, tell the user before changing historical research/decision docs (same rule `docs-sync` follows).

## Output shape when reporting findings

```
## Domain term check — <term>

**Canonical definition:** <definition + source doc>
**Conflicting usages found:** <file:line — what it implies instead>
**Recommendation:** <align all to canonical, or canonical needs updating because ___>
```
