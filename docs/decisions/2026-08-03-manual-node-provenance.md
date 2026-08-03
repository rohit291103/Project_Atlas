# Decision Log — Provenance for Manually-Added Nodes (`human_assertion`)

**Date:** 2026-08-03
**Area:** models, storage
**Amends:** TRD §3.1 (`SourceType`), `Phase1_Architecture.md` §8

## Context

Slice 1A (`2026-08-03-confirmation-loop-backend.md`) built `add_node` and surfaced a direct contradiction between three documents:

- **CLAUDE.md** — "A Node without a `SourceRef` is a bug, not an edge case — schema validation should make it structurally impossible." Stated as the one rule with zero exceptions.
- **PRD R10** — "Users must be able to manually add elements not captured by extraction (e.g., a constraint mentioned verbally in a meeting)."
- **`Phase1_Architecture.md` §8** — proposed resolving this by making manual nodes "the one node type without provenance."

A constraint mentioned verbally has no artifact by definition. So R10 and the `SourceRef` rule are jointly unsatisfiable as written, and §8's proposal resolves it by breaking the invariant.

## Decision

**Add `SourceType.human_assertion`.** Manual nodes get a `SourceRef` whose evidence is the person: `external_id` = the actor, `excerpt` = the claim as typed, `url` = `atlas:node/<uuid>`. `source_refs` keeps `min_length=1`, unchanged, with no exception clause.

`add_node` also changed shape — from taking a caller-built `Node` to taking `node_type` / `content` / `actor` / `workspace_id` / `feature_scope_id` and constructing the Node itself.

## Why not the two obvious options

**Relax `source_refs` to allow empty when `created_by = user`.** Makes "a Node with no provenance" expressible in the schema, which is exactly what CLAUDE.md says must be structurally impossible. Every consumer — the UI, Phase 2's export, Phase 3's retrieval — then handles an empty-provenance case forever, and the invariant degrades from "guaranteed" to "usually."

**Keep the rule strict and require the PM to cite something.** This is the option that looks safest and is actually the most dangerous. A required field a user cannot honestly satisfy gets satisfied dishonestly: the PM pastes the nearest PR URL and an unrelated sentence to get past the form. The result is a Node whose excerpt does not support its claim and which is **indistinguishable from a real extraction** — fabricated provenance, which CLAUDE.md rates Critical, caused by the enforcement meant to prevent it.

The rule "every Node has a `SourceRef`" is a proxy for the rule that actually matters: **every Node's origin is honestly recorded and machine-distinguishable.** For extracted nodes that means a literal excerpt. For human nodes the honest origin is the human, and `human_assertion` is what lets the schema say so.

## What this buys beyond keeping the invariant

- **Phase 2's export can distinguish "the PR says X" from "Priya says X."** A downstream coding agent can weight them differently. Neither alternative preserves that distinction — one erases it, the other disguises it.
- **The excerpt is a snapshot.** A later `edit_node` changes `content` and leaves the excerpt alone, so what was *originally asserted* survives revision — exactly how an extracted node's excerpt behaves. Without a `SourceRef` there is nothing to hold that.
- **No migration.** `SourceType` lives inside the JSONB payload; only `EventType` is a Postgres enum.

## On the asymmetry with `node_added`

Slice 1A **refused** to add a `node_added` event type and **accepts** a new `SourceType` member. The test applied in both cases: does the existing vocabulary already describe the thing completely? `node_created` + `created_by = user` fully describes a manual node, so a new event type bought nothing and cost a migration. Nothing in `SourceType` describes a human assertion, so without it the invariant can only survive by lying.

## `add_node` takes fields, not a Node

Secondary decision, same commit, and it closes the seam flagged in the slice-1A forward note. Building the Node inside `add_node` means:

- Extraction output **cannot** be routed through the manual path to be laundered into a confirmed fact — there is no `node` parameter to pass one in.
- An API endpoint **cannot** let a request body choose its own `workspace_id` — the caller passes it explicitly, and it must come from the authenticated session.
- The `human_assertion` ref is built correctly by construction rather than by convention.

Both risks become structurally unreachable instead of guarded against. Full enforcement of the session-derived `workspace_id`/`actor` rule still arrives with workspace RBAC + RLS in slice 1D.

## Open question deferred to slice 1B

`url = atlas:node/<uuid>` is a URN because the app has no base URL yet — inventing a host would be a lie the UI would then have to render. When the frontend exists it may be worth writing a real deep link instead. Events written before that keep their URN, which stays honest; no backfill.
