# Google Docs as the third source

**Date:** 2026-09-28
**Status:** built. Not yet run live (needs a Google service account) and not yet evaluated (needs a doc golden set).
**Roadmap:** v2 Phase 3, "Third source: one doc tool". The user chose Google Docs over Notion.

## Decisions (the user's two choices, then what followed from them)

1. **Access is "share with Atlas".** Atlas has one Google service account. A PM shares specific docs with its email, exactly as they would with a teammate. The service account requests `documents.readonly`, so its reach is exactly what was shared and it cannot write. No OAuth app, no consent screen, and no Google verification review. `documents.readonly` would need that review under per-user OAuth; for a service account it doesn't.
2. **A doc is filed into a feature when it's pulled**, the same as a PR or a ticket. The open modelling question from the roadmap (where do interview notes that predate any feature attach?) is *deferred, not answered*. If real usage shows unfiled interviews matter, it gets a `domain-modeling` pass then.
3. **The key lives in the environment** (`ATLAS_GOOGLE_SERVICE_ACCOUNT`, as the JSON itself or a path to it). It never goes in the database. A docs `connection` row holds **no secret**: `secret_ciphertext` and `secret_hint` are NULL. Migration `c7e2a9d41f06` makes them nullable, and a check constraint makes that *exact*: NULL for `gdoc`, NOT NULL for every other source. `create_connection` enforces the same rule in code. The migration was applied to the live database on 2026-09-28.

## An amendment, made deliberately

`ApiSettings` (from slice 2B) says the API process holds **no ambient source credential**, so that no request can reach a source except through a credential a PM connected. A single service account *is* an ambient credential. **It is accepted as the one exception** because its reach is structurally narrower than the credentials the rule was written against. A GitHub or Jira token reaches everything its owner can; this account reaches only the docs people have explicitly shared with it, and only to read them. The exception is written into `ApiSettings`'s docstring as well as here.

## The known limit: tenant isolation

One service account serves every workspace. **Any workspace that knows a doc's URL can ingest a doc that someone else shared with Atlas.** Doc ids are long and unguessable, so the URL works like a secret link, but that is not tenant isolation.

- **Acceptable now:** Atlas runs as a single-team pilot.
- **Must close before a second customer:** give each workspace its own service account (for example, a key per workspace in the secrets manager), or move to per-user OAuth. This belongs with Phase 4 security hardening, and it is listed there.

## How the pieces are built

- `ingestion/gdocs.py`: signs a JWT with the service-account key using `cryptography`, which is already a dependency, so there's no new one. It exchanges the JWT for a token and GETs the document. It flattens text runs verbatim, including table cells, so every excerpt can be found in the doc. A doc longer than 120,000 characters is **refused rather than truncated**: truncation would drop claims and leave excerpts pointing at text the agent never read. A 403 or 404 tells the PM which address to share the doc with.
- **Extraction:** docs use the shared system prompt with **rule 3 replaced**. Docs have no tools, so the rule says to read only the given text and to quote a customer's words exactly. The GitHub and Jira prompts are unchanged, and a byte-identity test still passes. The seed prompt spells out `source_type "gdoc"` and the doc id, because the agent writes each `source_ref` itself. Everything still goes through `build_result`.
- **Pipeline:** docs get the same idempotent re-sync and content-hash skip as the other sources. The private key is kept out of `repr`, and redacted from failure messages, including when its formatting changed in transit.
- **API:** `GET /sources/google-docs` returns the address to share docs with. The connect endpoint takes no secret for docs. A run's target kind must now match its connection's source, which closes an older gap: a mismatch used to fail deep inside the run.

## Still owed

- **A doc golden set** (`writing-evals`), with interview notes among the docs. Rule 5 (one claim, one node) and the tool budget were tuned on PR threads, and a 45-minute transcript is mostly not claims. Until that set exists, doc extraction is *built*, not *known to work*.
- **A live run.** Someone has to create the service account, set the env var, share a doc and pull it.
- **The per-workspace service account** described above, before a second customer.

## Amended 2026-09-30: one service account per workspace, and the tenant gap closed

The limit recorded above ("any workspace that knows a doc's URL can ingest a doc someone else shared with Atlas") is **closed**.

- `ATLAS_GOOGLE_SERVICE_ACCOUNT` (a single key) is replaced by **`ATLAS_GOOGLE_SERVICE_ACCOUNTS`**: a JSON object mapping each workspace id to that workspace's key, given as the key JSON or a path to it. The single-key variable had existed for two days and was never set in any environment, so nothing needed migrating.
- Every lookup uses the caller's workspace (`ApiSettings.google_account(workspace_id)`): connecting, the "share with" address, and starting a run. A workspace with no account of its own gets a 409. It never borrows another workspace's account, and a test asserts that.
- **Configuration refuses one account given to two workspaces**, because that would silently reopen the gap. Error messages name the workspace, never the key.
- Result: a doc shared with workspace A's address can't be read through workspace B, because B's account was never given access. The doc URL is no longer a capability.

The exception to "no ambient source credential" (above) still stands, now scoped per workspace.
