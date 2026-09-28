# Placing `feedback.py` and `qa.py`, plus the backend review of the 2026-09-28 session

**Date:** 2026-09-28
**Status:** built and reviewed

## Why this is recorded after the fact

CLAUDE.md asks for a `codebase-design` check *before* a new module is scaffolded. Both modules were built first and checked afterwards, and the `backend-reviewer` pass flagged exactly that gap. This entry records the check so the reasoning is on file. It doesn't pretend the order was right.

## `src/atlas/feedback.py`

- **Why it's its own module and not in `storage/projections.py`:** a projection replays the log into *current state*, and current state has already lost track of which ruling came first. The acceptance metric is defined over the *first* human ruling, so it has to fold the log in order. That puts it beside `replay` and outside `Projection`, the same relationship `assembly.py` has to state.
- **Why not in `api/`:** the definitions (first ruling, human only, extracted nodes only, the guard) are domain rules, and `api/` holds none.
- **Interface:** one pure function, `feedback_report(events, node_ids=None)`, reading from `storage.load_log`. No class and no strategy pattern.

## `src/atlas/qa.py`

- **Why not in `extraction/`:** extraction turns sources into Nodes bound for storage. Q&A reads assembled state and writes nothing. Putting them together would blur the one boundary where "extraction never reaches storage unvalidated" is enforced.
- **Why it reads through `assembly`:** "what counts as confirmed" is decided once, for the About page, the export and the answers alike.
- **The gate:** a citation must name a label the model was shown, the evidence label is computed rather than taken from the model, and nothing confirmed means no call. After review, the model session also has a `can_use_tool` gate that denies every tool, with the prompt streamed so the gate is actually consulted. A string prompt silently bypasses `can_use_tool`, the same defect `extraction.agent._as_stream` exists for. `Task` was added to the deny-list as well.
- **Model:** `claude-opus-5`, the current default for a new LLM path. Extraction keeps its own pinned model.
- **Still owed:** a `writing-evals` golden set for Q&A (questions with known answers over the ripgrep claims, judged on citation correctness and calibration of the evidence label). Until that exists, Q&A is *built*, not *known to work*.

## Backend review outcome (same day)

| Finding | Verdict | Outcome |
|---|---|---|
| A re-sync could re-file another product's feature under the caller's product | Confirmed | **Fixed**: 409 across products, with a test |
| The Q&A model session had no `can_use_tool` gate | Confirmed (structural) | **Fixed**: deny-all gate and a streamed prompt, with tests on both |
| `reconcile` matched on any key, dropping extra `source_ref`s | Plausible | **Fixed**: all-keys match, with a test |
| No eval for the Q&A LLM path | Confirmed | **Open**, as above |
| The incremental hash ignores tool-reached content | By design | Already disclosed in the idempotency decision, item 6 |
| No design record for the two new modules | Confirmed | This document |
| A naive `since` could be read in the database's time zone | Polish | **Fixed**: normalized to UTC |
| Re-sync routing sits inline in `api/routes.py` | Polish | Deferred. It extends an existing pattern, and moving it into `pipeline` is a follow-up |
