---
name: tdd
description: Red-green-refactor test-first workflow, mandatory for schema validation, event-log writes, and projection replay logic in storage/ and extraction/; lighter-touch for CLI wiring and prompt-only extraction tweaks. Use proactively before implementing any storage, schema-validation, or event-sourcing logic.
---

# tdd

Root `CLAUDE.md` calls schema validation and event-sourcing the project's non-negotiable foundation — extraction output must never reach storage unvalidated, and Node/Edge state must never be mutated directly. "Never" only stays true if it's verifiably true, and tests are how that becomes a fact instead of an assumption.

Check `docs/tracker.md` (via the `tracker-sync` skill) before starting — confirm the module you're testing is the one actually in scope for this session, not one still marked "Next up."

## Where this is mandatory vs. optional

- **Mandatory, test-first:** `models/schema.py` (Pydantic validation — a Node without a `SourceRef` must fail to construct), `storage/tables.py` and `storage/projections.py` (event writes and replay-to-projection logic), the confidence-mapping function (low/medium/high → numeric), and any conflict-detection logic (`conflicts_with` edge creation). These are the "structurally impossible to violate" guarantees CLAUDE.md's Engineering Philosophy demands — they get the strictest discipline.
- **Lighter touch:** `extraction/prompts.py` (prompt wording — test the contract, e.g. "given this PR body, the agent emits a Node of type `requirement`," not exact phrasing) and `cli.py` presentation formatting.

## The loop

1. **Red** — write a failing test that encodes the expected behavior from the spec (TRD §3 for schema shape, TRD §5 for extraction contract, or a stated requirement in the PRD). For schema/storage logic, prefer concrete cases over abstract property checks first ("a Node dict missing `source_refs` raises a `ValidationError`") — concrete cases catch the exact validation-gap bugs that matter most here.
2. **Green** — write the minimum code to pass. Resist adding handling for cases the test suite doesn't yet demand.
3. **Refactor** — clean up only with the safety net of passing tests; don't refactor and add behavior in the same step.

## Test design notes specific to this domain

- **Golden-case tests** for extraction: record a real (or realistic, fixture-based) GitHub PR body and assert the extraction agent emits the expected Node types with excerpts traceable back to the fixture text — not invented expected output. Store fixtures under `tests/fixtures/` per `docs/Phase0_Architecture.md`, so extraction tests replay recorded API/agent responses rather than hitting live APIs (and burning tokens) on every run.
- **Boundary tests** for schema validation — a Node with an empty excerpt, a confidence score outside 0.0–1.0, a `status` transition that shouldn't be reachable (e.g. `rejected` → `confirmed` without going through review) are where these bugs live.
- **No mocking the validation gate itself** — a test can mock the LLM/agent call to control what "extraction" returns, but never mock or bypass Pydantic validation to make a test pass; that defeats the entire point of this skill existing.

## Scope discipline

Per CLAUDE.md's Explicit Non-Goals ("avoid infrastructure ahead of the phase that needs it"), don't introduce a testing framework, fixture system, or CI pipeline beyond what's needed to run the tests that exist today. `pytest` + recorded fixtures (already decided in `docs/Phase0_Architecture.md`) is the whole toolset until something concrete demands more.
