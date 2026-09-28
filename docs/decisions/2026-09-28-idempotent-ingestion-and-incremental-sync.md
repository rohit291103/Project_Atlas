# Idempotent ingestion and incremental sync (Phase 3)

**Date:** 2026-09-28
**Status:** built
**Supersedes:** the re-run hard block, decision 5 of `2026-08-19-product-orientation-rerun-safety-and-demo-data.md`, which was planned from the start to be "removed, not loosened, when Phase 3 makes ingestion idempotent".

## Context

Engineering Philosophy §5 says re-running ingestion must never duplicate or corrupt existing data. Until now nothing enforced that. Node ids were minted per run, so every re-run duplicated every claim. The API refused a second run of a single PR or issue as a stopgap. Epics and labels were never covered by that block.

The user also asked on 2026-09-28 to build Phases 2–3 without waiting for the Phase 1 PM measurement. That lifts the CLAUDE.md gate for construction only. The evidence gates still stand.

## Decisions

1. **What makes two claims the same.** Two nodes are the same claim when they have the same `NodeType` and quote the same `(source_type, external_id, excerpt)` in the same feature scope. Content is not part of the identity, because the LLM rewords a claim between runs. The excerpt is literal source text that the eval harness pins verbatim, so it is the stable part. One shared excerpt is enough to match.
2. **Matching ignores status.** A re-extracted claim that matches a rejected node is not created again. Rulings survive a re-run, which is the failure the old block existed to prevent.
3. **A re-run never deletes.** Claims that a later run does not re-extract are left alone. A claim a human ruled on does not disappear because the model missed it the second time.
4. **Edges.** Edges are remapped onto the ids that survive. An edge is dropped when it already exists (`conflicts_with` counts in either direction), or when both of its ends collapse into one node.
5. **Where the check runs.** `pipeline.reconcile` is a pure function. It runs inside the transaction that writes, so the pipeline and the CLI share it. Concurrent runs into one scope can still race past it. That is acceptable with a single API worker, and a lock belongs with the queue when one arrives.
6. **Incremental sync.** `IngestionRunPayload.content_hash` is the sha256 of the seed prompt, taken before the known-nodes block is appended. The next run over the same artifact passes the hash back. If it matches, the agent never runs: no tokens are spent, no `ingestion_run` event is written, and `RunFinishedPayload.unchanged` counts the skip. **Known gap:** a change only in content the agent reaches through tool calls (a linked issue, a commit) does not trigger re-extraction.
7. **The API re-syncs instead of refusing.** A re-run of a single artifact that names no feature goes into the scope that already holds it. Naming a different feature returns 409, because filing the same artifact under two scopes is the one path that could still duplicate. An epic or label re-run without a chosen feature still opens a new feature.

## Not done

- Semantic duplicates, where the same claim is supported by a *different* excerpt, are not matched. That needs a judgment-based pass, not a key.
- Spec versioning (Phase 3) builds on this and is next.
