# 2026-07-28 — Extraction tool-call audit logging: gap acknowledged, deferred as a tracked follow-up

## Context

The first live extraction run (all 4 golden PRs, on the Claude Pro subscription) was followed by three reviews: `extraction-quality-review` Tier-2, `security-review`, and the `backend-reviewer` agent. Two of the three were clean. The backend review surfaced one Important finding (confidence 85), recorded here so it isn't silently dropped.

## The finding

`docs/architecture/Phase0_Architecture.md` §2 lists, as an explicit guardrail alongside the ~8-tool-call cap:

> Every tool call is logged (provenance + audit trail, and cost visibility).

This is **not implemented.** There is no `logging` or audit call anywhere in `src/atlas/extraction/agent.py`, `tools.py`, or `cli.py`. `_make_permission_gate` tracks a per-run budget counter, but that state is discarded when the gate closure exits — so after an `atlas ingest` run there is no record of which `fetch_linked_issue` / `fetch_commit` / `search_repo` calls were made, with what arguments.

Why it matters (not a style nit): the extraction agent's read-only, least-privilege guarantee is *supposed* to be independently checkable against an audit trail. Without one, "the agent only made read-only, in-budget calls" is enforced (by the gate) but not **observable after the fact**. That observability is the documented guardrail.

## Decision

**Defer implementation to its own dedicated task; do not bolt it on now.** Rationale:

- Phase 0's exit criterion ("usable, mostly-correct structured output on 3–5 real PRs, validated manually") is **met** on the Tier-1 + Tier-2 + security + (this one gap aside) backend axes. Logging is not required to establish that extraction works.
- Audit logging is a real feature, not a one-liner: it needs a deliberate sink decision (structured log vs. an `ingestion_run` event carrying the tool-call manifest — the latter fits the event-sourced model and the §2 "provenance + audit trail" framing better), argument redaction review, and its own test coverage per the `tdd` skill. Rushing it onto the end of a review pass would produce exactly the kind of untested, unconsidered addition the philosophy warns against.
- Doing it as a focused task lets it be designed against the event-log model rather than as ad-hoc `logging` calls.

This is a **conscious deferral, tracked** (see `docs/tracker.md` → Extraction → Next up), not an omission.

## Trigger to implement

Before the extraction module is considered "closed" for Phase 0 — i.e. before building on top of it in Phase 1 — or sooner if a validation run ever produces a surprising/ suspect tool-call pattern that we'd want the trail to diagnose. Preferred shape: record the per-run tool-call manifest (tool name + arguments + count) as part of the `ingestion_run` audit event, so it lives in the event log and is replayable, consistent with the read-only + provenance guarantees it exists to make checkable.

## Also from this review (no action / already handled)

- **Streaming-fix seam regression test** — the backend review flagged that the streaming fix (`_make_agent_call` → `query(prompt=_as_stream(...))`) had no test asserting `query` receives a stream, not a string. **Fixed the same day**: `tests/test_extraction.py::test_make_agent_call_streams_prompt_and_shares_gate_across_calls` monkeypatches `atlas.extraction.agent.query` and asserts (a) the prompt is a streaming `AsyncIterator`, not a `str` (a string bypasses the `can_use_tool` gate), and (b) the same options/gate instance is shared across the initial + retry attempts. A clarifying comment was added at the retry site in `agent.py` documenting that the shared per-run budget is deliberate.
- **Shared retry budget** — confirmed correct by design (per-run cap, not per-attempt), matching Phase0 §2. No change.
- **`anthropic_api_key` is dead data** — intentional: it's a documented optional escape hatch to pay-as-you-go API billing; auth normally flows through the Claude Agent SDK's Claude Code CLI login (the Pro subscription). No change.
