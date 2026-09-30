# Q&A and Google Docs extraction: first evals

**Date:** 2026-09-30
**Why:** both are new LLM call paths (Phase 3), and `writing-evals` requires a golden set before either counts as working. Both evals run offline over recorded model output: the model runs once per recording, and grading costs nothing and is repeated on every test run.

## Q&A (`tests/evals/qa_golden/`)

- **Set:** 11 questions over 4 real recorded fixtures, one of them the GitHub-vs-Jira `--maxdepth` conflict (`pr-111` + `cross-SCRUM-8`). Each fixture's claims are treated as confirmed in memory, so this grades *answering*, not curation.
- **Expectations were written before any answer was recorded:**
  - 7 answerable: the answer must cite a claim containing a named keyword.
  - 3 unanswerable: the answer must cite nothing, and the evidence label must be "none".
  - 1 conflict: the evidence label must be "conflicting".
- **Path:** production `atlas.qa.ask` with `claude-opus-5`, gate included. A gate refusal would have been recorded as a failure, not retried.
- **Result: 11/11 floors met.** Reading the answers, not just the pass count:
  - It refuses to invent. q3 ("largest value --maxdepth accepts") and q7 ("fish completions?") say the claims don't cover it, and cite nothing.
  - It presents both sides of a real dispute rather than picking one (q2). It also surfaced a conflict inside `#706`'s own extraction when asked about precedence (q10).
  - It labels a single-source answer as thin (q6).
- **Limits:** N = 11 is a smoke test with named failures, not a rate. The floors check citation and calibration, not how well an answer is written. There is no judgment-tier grading yet.

## Google Docs extraction (`tests/evals/golden_set/gdoc-*`)

- **Documents:** two real public design docs, Rust RFC 1869 (`eprintln!`) and RFC 2360 (`bench_black_box`), both MIT/Apache-2.0. **Not text written for the test.** Each was recorded through the production `extract_from_gdoc`, using a stub client that returns the doc text. The connector's HTTP, JWT and flattening are covered separately by unit tests.
- **Checks:**
  - Every excerpt appears verbatim in the doc (whitespace-tolerant).
  - Every citation says `gdoc` with the doc's own id. This matters because the agent writes each `source_ref` itself.
  - Rubric floors, written before recording.
- **Result: 5 of 6 checks pass.**
  - Provenance: **every excerpt is verbatim, in both docs.**
  - Citations: **every one is correct.**
  - RFC 1869: floor met. It produced 14 claims, including 5 rejected alternatives that match the RFC's Alternatives section.
  - **RFC 2360: no `goal`.** The summary ("This RFC adds `core::hint::bench_black_box`") was typed as a `decision`, and the motivation came out as two `problem`s. That's defensible under rule 5, but it means a doc whose outcome is only implied yields an empty "Goals" section in the spec. **The floor was not loosened.** The miss is recorded in the rubric as a known gap and reported on every run as an expected failure (xfail), until the doc prompt is revisited under `extraction-quality-review`.
- **Not covered: interview notes.** The roadmap names customer interview notes as the reason the doc source matters, and asks for a transcript golden set. None exists, because no real transcripts are available. Writing some would produce a team-authored fixture, which is what `writing-evals` warns inflates scores. **This remains owed:** it needs a design partner's real notes, used with their permission.

## What would change these conclusions

- A second recording of the same fixtures. Model output varies, and one recording is one sample.
- Judgment-tier grading of answer quality, and of whether the claims extracted from the RFCs are the *right* ones rather than just provenanced ones.
