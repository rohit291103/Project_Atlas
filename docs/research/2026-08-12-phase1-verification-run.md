# Phase 1 Verification Run — extraction re-run, real-browser pass, migration blocked

**Date:** 2026-08-12
**Covers:** the three verification items the tracker listed after slices 1C/1D were built. Not a decision doc — this is the record of what was actually run and what it showed.

## 1. Extraction re-run (GitHub golden set) — PASS, 4/4

Slice 1C refactored how the agent call is constructed (`_agent_call` shared between sources) and slice 1D added manifest recording to the permission gate. Both sit on the live path, and neither is exercised by a unit test that talks to the real SDK — so the four `BurntSushi/ripgrep` validation PRs were re-extracted live and graded by the golden set's own deterministic checkers.

| PR | Schema | Provenance | Rubric floor | Nodes/edges (re-run vs. Phase 0 baseline) | Tool calls |
|---|---|---|---|---|---|
| 111 | pass | pass | pass | 8/5 vs 10/6 | 2 |
| 723 | pass | pass | pass | 14/7 vs 11/6 | 1 |
| 706 | pass | pass | pass | 11/8 vs 9/6 | 1 |
| 3472 | pass | pass | pass | 5/3 vs 5/4 | 0 |

**Every excerpt in every re-run verified verbatim against the recorded source corpus.** Volume moves in both directions run to run (two up, one down, one flat), which is expected of a non-deterministic extractor and shows no systematic drift.

Two things worth keeping:

- **The refactor is sound on the live path.** Tools are wired, the right system prompt reaches the SDK, and the manifest fills. That was the actual question.
- **The audit manifest earned itself immediately.** On PR #111 the agent called `fetch_linked_issue{number: 109}` **twice** — identical arguments, two of its eight-call budget on the same fetch. Harmless here, invisible before slice 1D, and exactly the class of thing the guardrail exists to make observable. Worth a look if the budget ever binds; no action taken now.

**Baselines were not overwritten.** The recorded `extraction.json` fixtures are the evidence Phase 0's exit was judged on; the re-run outputs were graded and discarded rather than promoted, so the eval history stays honest.

**Still unverified: the Jira extraction path.** It has no eval evidence and has never run against a real Jira site — every Jira test replays recorded fixtures. That needs a real site to change.

## 2. Real-browser pass — 3 defects found and fixed

Playwright (Chromium) added as a frontend dev dependency, and the app driven for the first time in an actual browser. `tsc --noEmit` and `vite build` had both been clean throughout — and were clean while all three of these were live:

1. **A viewer was taught shortcuts that do nothing.** The keyboard-hint footer advertised `c confirm`, `e edit`, `x reject`, `a add`, `u undo` to read-only users whose keypresses were correctly ignored and whose buttons were correctly hidden. Now the footer lists only the keys the role can use.
2. **Expanding a source excerpt printed it twice** — once clipped on the toggle line, once in full in the well below. The signature provenance component, doubling its own text. The toggle now steps aside (`▾ hide excerpt`) when expanded.
3. **A reviewed card kept a full-loud conflict banner**, which made *done* work the noisiest thing on the page and directly contradicted the focus model's "reviewed items recede". Conflicts must not disappear on confirm — confirming one side does not resolve it (TRD §5.2) — so the banner now shrinks to a marker on a receded card and keeps the signal.

None of these are type errors. All three are the kind of thing only visible when something renders the page.

**Kept as a suite, not a one-off:** `frontend/tests/ui-smoke.spec.ts` (7 tests, `npm run test:ui`), covering the cross-source "assembled from" strip, a conflict naming the other tool, provenance expansion, confirm→recede, the viewer's read-only surface, and the add composer never asking for a citation.

Two harness lessons are baked into the config and worth not relearning: the tests run **single-worker and in order**, because they drive a shared mutable event log and parallel workers raced each other's confirmations; and cards are focused by clicking `.card__head`, because clicking a card's centre lands on whatever control is there — the first version of the suite confirmed nodes by accident and then failed on the state it had silently created.

**Also confirmed visually:** the dark canonical surface renders as designed, the cross-source conflict banners read as the loudest element, monospace excerpts + source badges work, and the light-theme token remap holds.

## 3. RBAC/RLS migration — BLOCKED, not applied

`alembic upgrade head` could not run: **`db.<ref>.supabase.co` does not resolve** while `api.github.com` and `supabase.com` both do, so this is not a network problem at this end. That hostname failing to resolve is the standard symptom of a **paused or deleted Supabase project**.

Consequence: migration `b7c2f1a45d90` remains written and unapplied, RLS is inert, and workspace isolation still rests on the application-level `workspace_id` filter alone (where it already rested — no regression, but not yet the second lock it is meant to be).

### A blocker found *before* trying to apply it

`scope_to_workspace` was called only from `api/deps.py`. **Every CLI command opened an unscoped transaction.** Because the policy is `FORCE`d — which is what makes it bind the application's own role rather than being decorative — applying the migration would have made `atlas ingest`, `atlas ingest-jira` and `atlas review` read **zero rows** and fail every insert's `WITH CHECK`, with no error explaining why.

Fixed before the attempt: `storage/rbac.py::workspace_session` pairs `session_scope` with `scope_to_workspace`, every CLI command uses it, and a test fails if `cli.py` ever reaches for a bare `session_scope` again — a failure mode that would look perfectly healthy against SQLite in CI and be silently broken in production.

## What this leaves

- Unpause or replace the Supabase project, then `alembic upgrade head` and verify isolation with two workspaces. **Note for whoever does it:** after `FORCE` RLS lands, anything reading `event_log` without setting `atlas.workspace_id` — psql, the Supabase table editor — will also see nothing. That is the policy working.
- Jira extraction quality remains unevidenced until there is a real Jira site to run against.
- The Phase 1 exit criterion is still a measurement nobody has taken: a PM outside the build team, unassisted, under 20 minutes.
