# Decision Log — Extraction Agent (`extraction/`)

**Date:** 2026-07-23
**Area:** extraction

## Context

The extraction agent is the last core Phase 0 module — the piece that turns a raw GitHub PR into schema-validated `Node`/`Edge` drafts (module boundary: "where AI reasoning lives — it never writes to storage without passing schema validation first"). Phase0_Architecture.md §2 specifies an **agentic** approach: the Claude Agent SDK with tools bound to the GitHub API (`fetch_linked_issue`, `fetch_commit`, `search_repo`), a forced final `emit_extraction(nodes, edges)` tool call, Pydantic validation, retry-once-then-error, and a ~8 tool-call cap. Built with no API key available yet — the user asked to "write the logic," so the design makes the LLM call injectable and everything else testable offline.

## Decisions

### 1. Claude Agent SDK, not the Anthropic Messages API

Phase0_Architecture.md §2/§3 chose the **Claude Agent SDK** (`claude-agent-sdk`, installed), which supplies the agent loop + in-process MCP tools. This is a different product from the Anthropic API Tool Runner (the `claude-api` skill covers the latter and explicitly does *not* cover the Agent SDK). We honour the architecture doc: tools are defined with the SDK's `@tool` decorator, served via `create_sdk_mcp_server`, and run through `query()` with `ClaudeAgentOptions`. The SDK API was verified by introspecting the installed package, not recalled.

### 2. The validation gate (`build_result`) is the centre of gravity, and it's pure

CLAUDE.md's one rule with zero exceptions: nothing reaches storage without passing Pydantic validation. So the gate is a **pure function** — raw agent payload → domain `Node`/`Edge` or raise — with no SDK or network dependency, and it carries the heaviest test coverage. It validates a dedicated **raw output contract** (`RawExtraction`/`RawNode`/`RawEdge`/`RawSourceRef`, `extra="forbid"`), then constructs domain models (which re-enforce provenance ≥1 SourceRef, confidence bounds, no self-edges). Failure modes it rejects: missing/blank provenance, unknown enum, hallucinated field, duplicate node ref, edge referencing a ref the agent never emitted, self-referential edge.

Why a separate raw contract instead of emitting domain models directly: the agent has no UUIDs (it wires edges through local `ref` ids like `"n1"`), assesses confidence as low/medium/high (TRD §5.1), and must not supply system-stamped fields (ids, workspace/feature scope, timestamps). `build_result` assigns the UUIDs, maps confidence via `confidence_to_score` (a deterministic 0.3/0.6/0.9 map, TDD'd), and stamps scope at call sites (per the [workspace_id decision](2026-07-21-phase0-default-workspace-id.md)).

### 3. The LLM call is an injectable seam (`AgentCall`), so orchestration is testable without keys

`run_extraction(seed_prompt, ..., agent_call)` takes `AgentCall = Callable[[str], Awaitable[dict | None]]`. Tests inject a fake agent to exercise the full validate → retry-once → error flow offline; the real implementation (`_make_agent_call`) drives `query()` and parses the transcript. Transcript parsing is factored into a pure `emitted_payload(messages)` helper (also tested). This keeps the SDK-glue surface tiny and everything decision-bearing under test — 22 extraction tests, LLM never called.

### 4. Retry-once, then surface an error — never guess

Per TRD §5.1/§10: a payload that fails validation is retried a single time with the error fed back into the prompt; a second failure raises `ExtractionError` (an ingestion error), never a silently dropped or guessed result.

### 5. `search_repo` needed a connector primitive → added `GitHubClient.search_issues`

The earlier [connector decision](2026-07-22-github-ingestion-connector.md) deferred search until the tool that needed it existed. It exists now, so `search_issues` (read-only `GET /search/issues`, reusing the issue parser) was added to the connector, and `search_repo` scopes every query to the repo (`repo:owner/name …`).

## Security cross-check (touches credentials — CLAUDE.md security workflow)

- **Read-only + least-privilege + cost cap, all via one `can_use_tool` gate.** A single permission callback is the authority for every tool call: it allows only the four `mcp__atlas__*` tools, always permits `emit_extraction`, and **counts** each fetch/search so the run can't exceed `max_tool_calls` GitHub calls (Phase0 §2's ~8-call cost cap — which `max_turns` alone can't guarantee, since one turn may issue several parallel calls). We deliberately do **not** pass `allowed_tools` (pre-approval could bypass the gate and defeat the cap) or `permission_mode="bypassPermissions"` (that would re-open the built-ins). `disallowed_tools` still hard-denies every write/exec/network SDK built-in (`Bash`/`Write`/`Edit`/`Read`/`Glob`/`Grep`/`WebFetch`/`WebSearch`/`NotebookEdit`/`TodoWrite`) before the gate is consulted, and `setting_sources=[]` blocks inheriting local/project tools or MCP servers. The gate's counting/allow/deny logic is unit-tested; the SDK *wiring* of the gate is still unverified until a live run (see revisit trigger). This makes "extraction is read-only" (Philosophy §1) enforced by configuration, not just prompt wording.
- Transport errors (httpx timeouts/resets) during a tool call are surfaced to the agent as an error result, not raised — a network blip can't crash the run; and the connector's blocking sync HTTP is offloaded via `asyncio.to_thread` so it doesn't stall the SDK's event loop. (These, and the cap-vs-`max_turns` gap and the CLI's error handling / edge legibility, came out of a `/code-review` pass over the working diff and were fixed the same session.)
- **No secret handling regressions.** GitHub access stays behind the read-only connector (token in the auth header only, never logged); the agent's `ANTHROPIC_API_KEY` is read by the SDK from the environment (never in code). Raw fetched content is transient (TRD §4.2) — only validated Nodes + SourceRefs are meant to be persisted.
- **Not yet verified against a live agent** (no API key). The tool-restriction config above is set conservatively but must be confirmed when keys land — see revisit trigger.

## Scope / not covered

- **Not yet run end-to-end.** No API key, and no CLI wiring yet (`cli.py` still stubs `ingest`/`review`). `extract_from_pull_request` is the intended entrypoint the CLI will call.
- **Evals not yet run.** This is a new LLM-call code path, so CLAUDE.md requires `writing-evals` + `extraction-quality-review` — but those need the chosen validation OSS repo (still undecided) and a key. Gated on both.
- **`emit_extraction`'s hint schema is hand-written** in `tools.py` (mirrors `RawExtraction`); the authoritative check is `build_result`, so drift is caught, not shipped. If the Agent SDK CLI rejects any part of it, adjust when running live.

## Revisit trigger

When the ANTHROPIC key + validation OSS repo are in place: run the agent end-to-end on the Phase 0 validation PRs, **confirm the tool-restriction config actually blocks built-ins** in a live run, then run `writing-evals` + `extraction-quality-review` against the Phase 0 exit criteria. Phase 1: `Node.confidence_score` becomes optional for manually-created nodes (already noted in the tracker).
