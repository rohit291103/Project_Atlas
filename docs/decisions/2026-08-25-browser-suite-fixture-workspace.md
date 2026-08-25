# The browser suite stops mutating the workspace it measures

**Date:** 2026-08-25
**Slice:** 6 of `docs/decisions/2026-08-19-product-orientation-rerun-safety-and-demo-data.md` — the last item before the Phase 1 exit measurement
**Touches:** new `scripts/seed_test_workspace.py`, new `scripts/__init__.py`, new `tests/test_seed_test_workspace.py`, new `frontend/tests/fixture.ts`, new `frontend/tests/global-setup.ts`, `frontend/playwright.config.ts`, `frontend/tests/ui-smoke.spec.ts`, `frontend/README.md`

## 1. What was actually wrong

On 2026-08-16 the browser suite confirmed six real claims under the user's name,
and nothing in the log could tell them apart from rulings he had made.
`X-Atlas-Automated` (2026-08-18) fixed the half of that which was about
**attribution**: every request the suite makes now declares itself a machine, so
its writes log as `actor_kind = automated` and stay out of roadmap-v2's guard
metric.

It fixed nothing about **mutation**. A confirmation the suite makes is still a
real event in an append-only log, in the workspace the demo is given from, and it
cannot be taken back. The whole defence was a line in the tracker saying *exclude
the two mutating tests* — a rule a person has to remember, at 11pm, about a suite
that had grown to 42 tests and runs against the same log the demo does.

There was a second, quieter version of the same problem. The suite read its
actors from `ATLAS_TEST_EDITOR` / `ATLAS_TEST_VIEWER` and, unset, **guessed** at
the local seed's names. A guess about *who you are signing in as* is a guess
about *which workspace you land in*, because membership is what resolves a
session to a workspace (`api/deps.py::get_principal`). That guess once looked
like twenty page defects.

## 2. The fix is a workspace, not a rule

`scripts/seed_test_workspace.py` provisions one workspace — a constant `uuid5`,
never an argument — seats two actors in it who are members of nothing else, and
**rebuilds its contents from scratch before every suite run**
(`globalSetup` in `playwright.config.ts`). The suite can confirm whatever it
likes: the next run starts from the same claims regardless.

That is why the two mutating tests are no longer excluded, and why the viewer
test no longer skips itself for want of a viewer. **42 of 42 tests now pass, on
two consecutive runs**, where the standing instruction was 35 read-only tests and
one skip.

## 3. The fixture is recorded output, not invented data

Every claim in it is real extraction output from `tests/evals/golden_set/` —
excerpts, URLs and confidence scores carried over untouched. Only identifiers are
re-stamped.

This is the decision worth defending. Hand-writing 28 plausible claims would have
been faster and would have produced **28 fabricated `SourceRef`s sitting in the
database of a product whose entire argument is that provenance is real**
(Engineering Philosophy §4). A fixture that lies about where its claims came from
is a fixture that cannot be used to demonstrate anything, and the day someone
screenshots it, the lie is public.

Three consequences fell out of choosing real data:

- **The cross-source conflict is real.** `cross-SCRUM-8`'s recorded edges reach
  back into `pr-111`'s nodes — a Jira ticket contradicting a GitHub PR, found by
  the extractor, not staged. Seeding both cases into one feature reproduces it
  exactly, and a test fails if the plan ever drops one rather than the conflict
  quietly disappearing.
- **A plan that cites an artifact its recording never quotes is refused.** The
  run event states where a feature's claims came from; if that URL is typed from
  memory and the case was re-recorded against something else, the feature carries
  a run pointing at an artifact none of its claims mention. That is a
  mislabelled source, which is worse than a missing one.
- **Ids are `uuid5` off one namespace.** A rebuild reproduces the same workspace,
  feature, claim and edge ids, so a failing test can be re-run against a fixture
  that is *identical* rather than merely similar — and nothing minted from
  `uuid4` can ever collide with it. **Product ids are the exception**, and
  deliberately: `create_product` mints its own, because a caller choosing its own
  product id is the hole that function exists to close, and wanting a tidy
  fixture is not a reason to reach around it.

Every node and edge is re-validated through `Node`/`Edge` and written through
`record_extraction`, `storage/products.py` and `storage/confirmations.py` — the
same paths ingestion and the API use. "Nothing unvalidated reaches storage" has
no exemption for a seed script, and a fixture holding a shape the product could
not have produced would test the fixture rather than the product.

## 4. Deleting from an append-only log, and the one guard on it

The rebuild deletes every event in the fixture workspace. That is not history
being rewritten — it is a fixture being rebuilt. The log is the source of truth
about *what people decided*, and nobody decided anything in this workspace: every
event in it was written by the seed or by a suite declaring itself automated.

Two things keep that true rather than merely believed:

1. **The script refuses to delete anything a human actor wrote**, naming them,
   unless `--force`. A log only moves forward; a deleted confirmation is not
   recoverable from it, and "it was only the test workspace" is not a thing you
   can check afterwards.
2. **The delete needs the owner credential.** `atlas_app` holds `SELECT, INSERT`
   on `event_log` and nothing else (`c3d8e1f60b21`), so the application role
   *structurally cannot* do this. `SUPABASE_DB_ADMIN_URL` clears the log and
   seats membership; `SUPABASE_DB_URL` writes the contents, under RLS, exactly as
   the API would. Membership is provisioned out of band for the same reason it
   always was: a compromised application process must not be able to grant itself
   a tenant.

## 5. What the fixture holds, and why each piece is there

Two products, because a switcher over one product switches nothing and "All
products" would be a view of a single thing. Three features, each named and
described, because orientation renders at both layers.

The **first** feature is the cross-source, conflict-bearing one, deliberately:
half a dozen tests open `.rail__item` first and would otherwise skip themselves.
It carries 14 claims — some confirmed, one edited, one rejected, five left
unruled — because a fixture with nothing ruled cannot exercise About or the spec
export, and one with everything ruled cannot exercise the review queue.

The ruling recipe rules only on claims no disagreement touches, and takes exactly
one side of each conflict. **A rejection settles a conflict**
(`assembly._live_conflicts`), so a recipe that rejected an endpoint would empty
About's disagreement section and the test asserting it would skip rather than
fail. That property is pinned by a test rather than a comment.

The second product has nothing ruled at all — the state every product starts in,
and the one that renders About's honest empty state.

## 6. Tested in pytest, not only in a browser

`tests/test_seed_test_workspace.py` seeds the fixture into an in-memory database,
replays it, and asserts it holds what the suite looks for: two products, a claim
left to stage, a live disagreement, a confirmed body for About and the export,
and no unruled claim anywhere in the assembled document. **It fails on the same
commit that would break the browser suite, without a browser** — 16 tests, ~0.5s,
against a suite that takes 2.7 minutes and needs a database and a running API.

`scripts/` gained an `__init__.py` so the fixture builder can be imported under
the same module name mypy checks it under. Nothing in `src/atlas/` imports from
it, and that stays true.

## 7. Verified

- **Three full runs of 42/42** (~2.8 min each) against the live Supabase
  database — including the two mutating tests and the viewer test that had never
  actually run. A fourth run, between them, failed one test and is written up
  below: it was a flake the fixture did not cause and did expose.
- **The demo workspace was untouched.** After both runs its newest event still
  dated from 2026-08-20; the fixture workspace held 73 events (71 seeded, 2 from
  the mutating tests), which the next run cleared and rewrote.
- 537 Python tests pass; `ruff` and `mypy src scripts tests` clean.

### The one failure, and what it was

`the product you left is the product you come back to` timed out once, waiting
for a sign-in form that never rendered. The page snapshot showed the app **still
signed in**.

`signOut` awaits `DELETE /session` before it navigates, and the test called
`page.goto("/signin")` immediately after the click — aborting that request in
flight. The cookie survived, `/signin` redirected a still-valid session back into
the app, and the test waited 30 seconds for a form it was never going to get. The
test now waits for the marketing page before signing back in, which is what its
own comment already claimed it did.

**It leaves a finding worth keeping**, not for this slice: a sign-out whose
request is lost clears the client's state and leaves the *session valid*, so the
next page load is signed in again. A person clicking "Sign out" and walking away
would not notice. Nothing here fixes that — it is one screen in the UI the user
is about to review, and a change to the auth path deserves its own look.

**One pre-existing formatting failure is not ours:** `ruff format --check .`
wants to reformat `migrations/versions/f9b41d7e3a52_event_actor_kind.py`, a
committed file this change does not touch.

## 8. Not built, and why

- **The browser suite still does not run in CI.** The slice plan listed "CI env"
  among what it touches; CI has never run this suite, and putting it there means
  putting a Supabase owner credential in GitHub Actions secrets. That is a
  security decision with a blast radius (the owner role can drop tables), not a
  wiring change, and it belongs with the Phase 4 hardening that will also want
  key rotation. The seed script makes it *possible*; nothing here makes it
  automatic.
- **The suite still runs in one worker.** The workspace is its own now, but it is
  still one mutable log shared by every test in the file.
- **`VITE_API_BASE=""` is now documented rather than fixed.** The built SPA bakes
  in `http://localhost:8000` at build time, so serving the build from any other
  port makes every request cross-origin, and the only symptom is "Couldn't sign
  in. Is the API running?" on a form whose credentials are correct. It cost
  fifteen minutes and a full 42-test run of 30-second timeouts to diagnose here.
  `frontend/README.md` now says so where the command lives.
