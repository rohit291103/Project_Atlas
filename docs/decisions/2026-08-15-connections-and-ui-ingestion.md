# Slice 2B — connections, encrypted credentials, and ingestion from the UI

**Date:** 2026-08-15
**Plan this implements:** `docs/architecture/product-model-and-frontend-rebuild-v1.md` §4.2, §5, §6, §7, §9 (slice 2B)
**Amends:** CLAUDE.md's security rule *"no secret ever lands in the database (env/secrets manager only)"* — see §1. Also completes the reversal of `docs/decisions/2026-08-11-api-frontend-module-boundary.md` §5's "no ingest endpoint".

---

## 1. The security amendment, stated plainly

CLAUDE.md's `security-review` checklist says **no secret ever lands in the database**. That rule was true and cheap while there was one `GITHUB_TOKEN` and one `JIRA_API_TOKEN` in `.env`. It cannot survive the thing Phase 1 exists to prove: a PM, in a browser, connecting their own products' sources. A browser cannot write to `.env`, and the alternative — the build team pasting each PM's credentials into a server environment by hand — is not a product.

So the rule changes, deliberately, and the posture that replaces it is stricter in every dimension except the one that moved:

| Property | How it is held |
|---|---|
| Encrypted at rest | Fernet (authenticated AES-CBC + HMAC), `cryptography` — no primitive is hand-rolled. `storage/connections.py::seal`. |
| Key outside the database | `ATLAS_SECRET_KEY`, environment only. A database dump alone yields ciphertext. |
| Never returned | `ConnectionView` **has no field a secret could occupy**. Not "we remember to exclude it" — there is nothing to exclude. |
| Never logged | `SecretError` raises `from None`, carries no plaintext, and no exception path formats a credential. The connect endpoint refuses to echo a connector's own error message, because that message can quote the request that carried the token. |
| Still least privilege | The credential carries exactly its owner's permissions, and the connect flow *shows the PM what it reaches* before it is trusted. |
| Revocable | A real `DELETE`. The ciphertext stops existing; the audit event that it was revoked does not. |
| Tenant-isolated | RLS policy + grants on `connection` from its first migration, verified live by `scripts/verify_rls.py` (now 17 checks, 17/17). |

**Two structural tests, not conventions.** `tests/test_connections.py` asserts `ConnectionView` has no secret-shaped field; `tests/test_api.py` asserts the same over the **generated OpenAPI schema**, which is what `frontend/src/api-types.ts` is built from — so a leak added anywhere in `api/` fails, not just one added to one model.

**Not solved, and flagged rather than discovered later:** key rotation. Re-encrypting every connection is straightforward and unbuilt (plan §11.3). Until it exists, a connection Atlas cannot decrypt returns **409 with a message saying so**, rather than starting a run that dies with an auth error nobody can explain.

---

## 2. Where the plan changed while building

### 2.1 A run needs three new event types, not two

The plan proposed `ingestion_run_started` / `ingestion_run_failed` bracketing the existing `ingestion_run`, with `ingestion_run` itself as the success terminal.

That is wrong for the case the product actually has. **One UI action can pull an epic's children**, and each child is its own `ingestion_run` — that event means "one artifact was pulled and extracted", and changing it to mean "the job is done" would either report a run finished while it was still working, or overload an event that other code already reads. So there is a third type, `ingestion_run_finished`, and a run is bracketed by *exactly one* terminal event either way.

The counts on that terminal payload are deliberately asymmetric: **node and edge counts are stated** (a Node carries its feature scope, not the job that produced it, so nothing else could recover them), while the **artifact count is derived** by counting the `ingestion_run` events that actually landed. What the Sources screen shows is therefore what happened, not what the writer believed happened.

### 2.2 Cross-source conflicts now work in both directions

`extract_from_pull_request` gained `known_nodes`, mirroring the Jira path exactly. Slice 1C only needed one direction because GitHub was always ingested first from the CLI. Once a PM can connect sources in either order, a PM who connects Jira and *then* GitHub would have received **no cross-source conflicts at all** — silently withholding the product's most valuable output, with no error and no way to tell.

The Phase 0 evidence survives this: `build_known_nodes_block` returns `""` for an empty sequence, so the seed prompt is byte-identical when there is nothing to offer, and the system prompt is untouched by the change.

### 2.3 Connect verifies in one round trip, not two

The plan asked the connect flow to show "what the credential can see" *before* saving. A literal preview-then-save pair means the browser holds the token across two requests, which is worse. `POST /products/{id}/connections` therefore verifies and stores in one call, and returns the access summary with the created connection: `"BurntSushi/ripgrep" · "Public repository · 176 open issue(s)"`. A credential that cannot read its own scope is a **422 while the PM is still looking at the form**, not a run that fails an hour later.

This added one read method per connector — `describe_repository` / `describe_project`. Both are single metadata calls. Neither crawls.

---

## 3. Two defects only a live run could find

Both passed the entire test suite. Both are recorded because the *class* of gap keeps recurring (see also: `FORCE ROW LEVEL SECURITY` being inert, and `EventType` needing a migration).

### 3.1 A run was 404 for its whole duration

`GET /runs/{id}` — the endpoint the UI polls after a 202 — returned **404 for three and a half minutes and then jumped straight to "succeeded"**.

FastAPI holds a `yield` dependency's exit stack open until *after* background tasks finish, so the request session's commit landed at the end of the run. The `ingestion_run_started` event was written but not visible.

**Why no test caught it:** the API tests run on SQLite with a `StaticPool`, which shares one connection — uncommitted rows are visible to the next read, so the isolation this depends on does not exist in the harness. The test asserting "the run is visible right after the 202" passed against a database where it could not fail.

**Fix:** the ingest endpoint opens its own `workspace_session` for the start event, making the id durable before the 202 is written — which is the property the whole poll-a-202 design rests on.

### 3.2 A stored host and a derived one disagreed

The connect check stripped `https://` when building the credential but stored the host as typed. So a PM pasting `https://acme.atlassian.net` — which is what the address bar shows — got a connection that verified fine and whose next run built `https://https://acme.atlassian.net`.

**Fix:** normalize once, at the door, before the value is stored. Now regression-tested for all three forms a person might paste.

---

## 4. Module boundary: what was added, and what deliberately was not

Checked against the `codebase-design` verdict in plan §5. It held, with one addition it did not anticipate.

**Added — `storage/connections.py`.** The table, its CRUD, and encryption at the boundary. Real complexity behind one interface.

**Added — `src/atlas/pipeline.py`.** The sequence *parse a target → build a read-only client → run the agent → write validated events*. It has **two concrete callers today** (`cli.py` and the ingest endpoint), which is the skill's own bar. Duplicating it would let them drift, and what would drift is the path along which "extraction never reaches storage unvalidated" holds — a correctness risk, not a style preference. `tests/test_cli.py` fails if orchestration returns to `cli.py`, the same shape as the existing guard against a bare `session_scope`.

**Not added, though the plan allowed it:** no `crypto/` module (two functions, one caller), no `storage/products.py` split, no generic connector-credential interface, no service layer in `api/`. Credentials remain *arguments* to `pipeline`; nothing in `ingestion/` knows whether one came from `.env` or from a decrypted row.

**`api/` kept its thinness rule.** The ingest endpoint's one function is `pipeline.start_run`; the connect endpoint's is `connections.create_connection`.

---

## 5. Verified

- **410 Python tests**, `ruff` + `ruff format` + strict `mypy` clean across `src`, `scripts` **and `tests`** (the `tests` gap is closed; CI and pre-commit now check all three).
- **`scripts/verify_rls.py`: 17/17 against live Postgres**, including four new connection-table checks — cross-workspace read, insert, update and delete. The update/delete checks assert *"reached nothing"* rather than *"was refused"*, because `connection` legitimately holds all four grants and the policy filters rather than raising; asserting the wrong mechanism would have passed while testing nothing.
- **Live, end to end, through the API:** a GitHub credential connected and verified against the real repo; a run started (202), visible as `running` throughout, finishing with 12 claims; a Jira credential connected against the real site; a Jira issue ingested **into the GitHub-seeded feature**, giving one feature assembled from two sources (12 GitHub + 4 Jira claims). A run against a nonexistent PR produced a clean terminal `failed` with `GitHub API 404: Not Found` — and no credential in the message.
- **19/19 browser tests** against live Postgres, including six new ones covering the landing page, the signed-out redirect, and the connect form.

---

## 5b. What the `security-review` pass found

One finding, fixed in the same change.

**SSRF via the Jira site (MEDIUM, fixed).** Before this slice the Jira base URL came from `JIRA_BASE_URL` in the environment — a trusted value. It now comes from a form field and becomes the base URL of an outbound request carrying an `Authorization: Basic` header. Any workspace editor could therefore aim the API process at `169.254.169.254`, at an internal service, or at a host they control, and read part of the answer back through the connect endpoint's access summary.

**Fix:** an allowlist — `<name>.atlassian.net`, https only — enforced in `JiraCredential.__post_init__` rather than at the API boundary, so *both* callers are covered by one rule: the connect endpoint (host from a form) and the ingest endpoint (host from a stored row). A check in only the first would be bypassed by any row written before it existed. An allowlist rather than a denylist of private ranges because `ingestion/` only ever supported Jira **Cloud**; enumerating what to block is a game you lose to DNS rebinding and redirects. Verified live: the real site still starts a run (202); `169.254.169.254` is a 422 naming the reason.

**Checked and clear:**

- **JQL injection.** `resolve_jira_keys` interpolates the target into JQL. `parse_target`'s regexes (`^[A-Za-z][A-Za-z0-9_]*-\d+$`, `^[\w.-]{1,64}$`) admit no quote, space or operator. This is stricter than before: the pre-2B CLI passed `--label` through unvalidated, which was acceptable when the input came from an engineer's shell and is not now that it comes from a browser. Regression-tested with four hostile labels.
- **GitHub host is display-only.** `GitHubClient` always uses `api.github.com`; the stored `host` is never a request target, so the same class of issue does not exist there.
- **No secret reaches a response, a log line, or an error.** Asserted structurally over the generated OpenAPI schema, and the connect endpoint refuses to echo a connector's own message.
- **Tenant isolation.** Every connection query filters on `workspace_id`, and the RLS policy is the second lock — 17/17 live.
- **Authorization.** Reads are member-level; connect, revoke and run are `WriterDep`, so a viewer is refused. Tested.

**Noted, not fixed (not a security issue):** `POST /products/{id}/runs` takes `product_id` from the path and `feature_scope_id` from the body, so a member could file a run's claims under product A into a feature belonging to product B **within their own workspace**. It crosses no tenant, privilege or provenance boundary — it is a data-tidiness question inside one team's data, and inventing a cross-product check now would be building Phase 4's surface early.

---

## 6. Open

1. **Key rotation for `ATLAS_SECRET_KEY`** — unbuilt, fails loudly (409) rather than mysteriously.
2. **One API worker only.** An in-process run dies with the process. `INTERRUPTED_AFTER` (30 min) makes that visible rather than hidden. The day there are two workers, or runs that must survive a deploy, is the day this needs a queue — and that is the phase that should build one, not this one.
3. **A run's `limit` ceiling is 50**, and epic/label runs are the only ones it applies to. Nothing here can crawl.
