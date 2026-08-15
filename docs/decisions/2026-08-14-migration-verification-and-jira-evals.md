# Verifying what SQLite can't, and grading Jira extraction

**Date:** 2026-08-14
**Context:** closing the two findings from the 2026-08-13 `backend-reviewer` and `security-review` passes, then building the Jira half of the eval harness.

## 1. The `ALTER ROLE ... PASSWORD` error path is redacted

`c3d8e1f60b21` inlines the app password into a statement, because `ALTER ROLE ... PASSWORD` takes no bind parameter. The literal is quoted by the server via `quote_literal` rather than by string formatting, which was the right call for injection — but it left the *statement text* a secret, and a driver exception carries the statement that failed. A failure (role renamed, connection dropped mid-statement) would have printed the cleartext password to stderr and into whatever captured it.

Both statements now re-raise a redacted `RuntimeError`. `from None`, not bare `raise ... from exc`: a chained cause prints too, which would have defeated the whole exercise.

Credit where due — this is the reviewer's sharper version of a concern I had raised and then downplayed as theoretical.

## 2. A verification script, not a Docker-backed test

**The gap:** `tests/` runs on SQLite. SQLite has no roles, no GRANTs, no row-level security. Nothing in 308 passing tests would fail if the tenant boundary were deleted tomorrow. Every guarantee in `b7c2f1a45d90`, `c3d8e1f60b21` and `d4a91c72e5f8` is invisible to pytest. That is structural, not a forgotten test.

**Considered:** a Docker-backed Postgres integration test. **Rejected for now** — that is real infrastructure, and there is no CI pipeline for it to live in, so it would sit unrun. Root `CLAUDE.md` is explicit about not adding infrastructure ahead of the phase that needs it.

**Chosen:** `scripts/verify_rls.py` — 11 checks against the real database, sub-second, exits non-zero. Plus `docs/architecture/rls-verification-checklist-v1.md` for the part a script cannot know about (a table added by the migration being written right now), and a header in `migrations/script.py.mako` so the next migration author sees the grant rules before writing DDL rather than after.

Three things that made it worth writing as code rather than a list of psql commands:

- **The manual version passed while being wrong.** psycopg's `connection.transaction()` nests as a SAVEPOINT, so an `is_local => true` scope from an earlier block was still in force during the supposedly *unscoped* read. It returned rows and looked like a correct answer to a different question. Every check now opens its own connection.
- **It has a negative control.** `SUPABASE_DB_URL="$SUPABASE_DB_ADMIN_URL"` reproduces the original broken state on demand: 9 of 11 fail. A script that has never been made to fail is not evidence.
- **It distinguishes *why* something was denied.** `permission denied for table` and `new row violates row-level security policy` share SQLSTATE 42501 and are not interchangeable — one is the grant, the other is the policy. A check accepting either would still pass after one mechanism was removed.

Writing it also surfaced a trap worth recording: computing `max(sequence) + 1` as `atlas_app` reads only rows **inside the current scope**, so it produces a value the rest of the table already used. Under RLS an aggregate is an aggregate over what you can see.

**Result:** 11/11 pass; negative control 9/11 fail as expected.

## 3. Jira evals: what got graded, and what a green run does not mean

Five fixtures under `tests/evals/golden_set/jira-*`, re-recordable via `scripts/record_jira_golden.py` (which touches the API, never the database). Full results: `docs/research/2026-08-14-jira-extraction-quality-run.md`.

Three decisions worth recording:

**Provenance is checked per source issue, not against a merged corpus.** Jira extraction routinely quotes an issue other than the one being ingested — both SCRUM-9 and SCRUM-10 pull background from the epic, correctly attributed to it. Against a merged corpus, an excerpt lifted from the epic but stamped with the child's id and URL would pass, because the text *is* in the sources somewhere. That is precisely the failure this product exists to prevent. A ref naming an unrecorded issue is reported rather than skipped: an excerpt nobody can check is not the same as a correct one.

**Rubrics gained ceilings (`max_nodes`, `max_confidence`), not just floors.** Floors ask "did extraction find what is there". The restraint fixture asks the opposite — "did it invent claims where there are none". Deliberately not `max_nodes: 0`: demanding silence would grade a judgment call ("is an onboarding tip a requirement?") as if it were a fact.

**The confidence split was promoted from observation to test.** Extraction emits 0.9 for claims stated outright and 0.6 for inferences and for everything on content with no feature claims — with no prompt instructing it. `max_confidence: 0.6` on the restraint fixture means a prompt change that flattens confidence into uniform 0.9 now fails a test instead of silently making every card look equally trustworthy.

**The honest caveat, which belongs in this record and not only in the research doc:** four of the five Jira fixtures were written by the build team. `writing-evals` is explicit that synthetic examples inflate scores. A green run means "no regression against tickets we authored". SCRUM-1 — untouched Atlassian template content — is the only Jira fixture nobody wrote with extraction in mind, and it produced the run's most useful finding: extraction has no notion of "this ticket contains no feature claims" and will always emit something.

## Open, deliberately not fixed here

- **Goal/requirement duplication** — in three of four feature tickets the agent emitted a `goal` restating a `requirement`/`decision` it had already emitted, in one case off the identical excerpt. This is the highest-leverage next fix, and it is a prompt change, so it needs a re-record and a read of the resulting diff.
- **Cross-source conflict detection has no Tier-1 coverage.** The five conflicts from 2026-08-13 were judged by eye and never recorded as a graded fixture — the most valuable behaviour in the product and the least tested.
- **Graded fixtures from a real Jira project.** The single biggest weakness in this eval set, and not something more code can fix.
