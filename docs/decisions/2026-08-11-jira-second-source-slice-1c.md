# Decision Log — Jira as the Second Source, and Cross-Source Conflicts (Slice 1C)

**Date:** 2026-08-11
**Area:** ingestion, extraction, storage, cli, frontend
**Implements:** `Phase1_Architecture.md` §6. **Resolves §10 Q4** (Jira OAuth vs. API token) and the title question slice 1A′ deferred to this slice.

## What was built

`ingestion/jira.py` (read-only Jira Cloud connector), Jira extraction tools + a Jira system/seed prompt, `extract_from_jira_issue`, `atlas ingest-jira`, cross-source `conflicts_with`, and the UI naming the other side's source. 271 tests green.

## 1. Auth: email + API token, not OAuth 3LO — §10 Q4 resolved

A Jira Cloud API token carries **exactly the permissions of the person who minted it**. That *is* least privilege (Philosophy §6) with no scope negotiation: Atlas cannot read a project its holder could not already open. OAuth 3LO would add an app registration, a callback URL and refresh-token storage — config surface on the very demo whose success criterion is "a PM, unassisted" — to buy a token model that is not actually more restricted. Enterprise auth (SSO/SAML, per-connector OAuth) stays Phase 4, and nothing here forecloses it.

## 2. ADF flattening is a provenance problem, not a formatting one

Jira Cloud returns rich text as Atlassian Document Format — a JSON tree — and a `SourceRef.excerpt` must be literal text a human can find on the page. `adf_to_text` concatenates text nodes in document order and **descends into node types it doesn't recognise** rather than skipping them, because ADF gains node types over time and dropping one would silently truncate an excerpt. No markdown is reconstructed: an excerpt is evidence, and decorating it would stop it being verbatim. This is the one part of the connector with no GitHub counterpart, and it has the heaviest test coverage for that reason — a quietly-wrong excerpt is fabricated provenance, which CLAUDE.md rates Critical.

Provenance URLs are `/browse/<KEY>`, never the REST `self` link, which serves JSON to a reviewer who clicks it.

## 3. The GitHub prompt is frozen, and a test says so

The rules in the system prompt are properties of the product, not of GitHub, so `_build_system_prompt` templates only two spans: what the agent is reading, and which tools it has. The GitHub prompt **renders byte-identically** to the version the Phase 0 eval runs validated, and `tests/test_jira_extraction.py` asserts that against a golden copy.

Without that test, adding a source silently re-words the prompt the extraction-quality evidence was gathered against, and the evidence stops describing the system. With it, any future edit to the shared template fails loudly and forces an `extraction-quality-review` re-run — which is the correct trigger, not a memory.

## 4. Cross-source conflict: an edge may point at a node from an earlier run

This is the substantive change, and the problem it solves is easy to miss: **each extraction run only ever sees its own artifact.** A GitHub PR saying "must stream" and a Jira ticket saying "we agreed to buffer" cannot conflict as far as either run is concerned, because neither run knows the other exists. TRD §5.2 requires the conflict to be surfaced anyway.

So when a source is ingested into a scope that already has claims, the run is handed them (`prompts.build_known_nodes_block`: id, type, content, source), and `build_result` accepts an edge whose `to_ref` is one of those ids.

**The gate got stricter, not looser.** An id that is not in the set offered to that run is rejected. A fabricated relationship is shaped exactly like a real one — nothing downstream could tell them apart — which puts it in the same class as a fabricated excerpt, so it fails at the gate rather than being stored.

Rejected alternatives: a separate LLM pass comparing nodes after the fact (a second LLM code path, its own evals, more code for the same result), and textual-similarity heuristics (fragile, and it would silently *decide* what disagrees rather than let the agent argue it from the text).

## 5. A feature scope keeps the title of the run that opened it

Slice 1A′ made the title last-write-wins to match the rest of the projection, and flagged this as the question 1C would force. It forces it: with last-wins, adding a Jira ticket **renames the feature a GitHub PR named**, changing what a reviewer is looking at mid-review.

Decided: **first run wins.** A feature scope is named by the artifact it was opened from; later runs add evidence, they do not re-christen it. The cost is that re-ingesting a retitled PR keeps the original name — the lesser wrong, and a rename, if ever wanted, should be a deliberate act with its own event rather than a side effect of ingestion. This is the one deliberate exception to last-write-wins in the projection, and it is documented as such at the definition.

## 6. The agent supplies text, never JQL

`search_project` takes free text and builds `project = "X" AND text ~ "..."` itself. The project clause is ours, not the agent's — a tool that can be talked into querying another project is not scoped. The read-tool allow-list in the permission gate is likewise central rather than per-connector, and adding `search_project` to it is what makes the Jira search usable at all; a connector tool missing from that list is silently denied, and the agent quietly extracts less. That is now covered by a test.

## Not done

- **The extraction eval suite has not been run against Jira.** This is a new LLM code path (new prompt, new tools, new cross-source instruction), and CLAUDE.md's workflow requires `writing-evals` + `extraction-quality-review` before it is considered done. The GitHub path is protected by the frozen-prompt test; the Jira path has no quality evidence yet, only structural tests. **It has also never run against a real Jira site** — every test replays recorded fixtures.
- No third source. No incremental sync (`last_synced_at` stays Phase 4).
