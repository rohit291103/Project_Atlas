# Security and data handling: what Atlas does today, and what a pilot must close

**Status:** written 2026-10-03 from the code at `ccde226`, not from intent. Each claim names where it's enforced. Where something isn't built, this doc says so; it doesn't describe a plan as if it were a control.
**For:** answering a pilot's security questionnaire, and deciding what must change before one starts.
**Scope:** Phase 4's "data retention and encryption review" and "security-questionnaire readiness". SSO is out of scope here: deferred by the user until a pilot asks for it (see §6).

## 1. Pilot blockers

Read this section first. Everything after it supports it.

| # | Gap | Why it matters | Smallest fix |
|---|---|---|---|
| **B1** | **Identity is self-asserted.** Sign-in is one shared passphrase plus a typed name (`api/routes.py::sign_in`). Anyone with the passphrase can sign in as any seated member. | Every ruling in the log is attributed to a name that nothing verified. The audit trail is only as good as the passphrase. | Per-person sign-in: an emailed magic link, or the pilot's SSO. Membership already keys on one string (`WorkspaceMember.actor`), the seam left for exactly this. |
| **B2** | **No deletion path for a workspace's content.** The event log is append-only *by privilege*: the app role can only `SELECT` and `INSERT` it (`c3d8e1f60b21`). `event_log` has no foreign key to `workspace`, so deleting a workspace leaves its events behind. | "Delete our data when the pilot ends" can't be answered with a procedure today. Excerpts can quote people, so this is also an erasure question. | An operator command over the owner connection that deletes one workspace's events, connections and members, and records that it ran. The same pattern as `rotate-secrets`. |
| **B3** | **The model call runs under a developer's local Claude login.** No `ANTHROPIC_API_KEY` is configured. The Agent SDK uses the local CLI's credentials. | A pilot's source text is sent to Anthropic (§3). It should go under an organisation API key and commercial terms the pilot can be pointed at, not a personal login. | Set `ANTHROPIC_API_KEY` from an organisation account in the deployed environment. `config.py` already reads it. |
| **B4** | **Not deployed anywhere.** It runs locally. The database is a free-tier Supabase project, which pauses after 7 idle days (it did on 2026-09-02). | A pilot can't depend on a laptop, and a paused database looks like an outage. | Deploy the one-image build (`docs/architecture/demo-deployment-v1.md`) behind TLS, on a paid database tier. |

B1 and B2 are code. B3 and B4 are account and configuration decisions for the user.

## 2. What is stored

All in one Postgres database (Supabase, region `ap-northeast-2`, Seoul).

| Store | Contents | Notes |
|---|---|---|
| `event_log` | Every claim, ruling, edit, comment, product, run and connection event, as JSONB | **Append-only**: the app role has `SELECT, INSERT` only. Row-level security is on and forced. |
| ↳ claims (`Node`) | The extracted statement, its type, and ≥1 `SourceRef`: **a verbatim excerpt** of the source, its URL, the artifact id and the fetch time | Excerpts are short spans, but they are the source's own words. They can contain names and anything else the source contained. |
| ↳ runs | Artifact title, URL, a sha256 of the content, and the agent's tool-call names and arguments (e.g. which issue it fetched) | **Not the content itself.** The hash detects change; it can't be reversed into the text. |
| ↳ comments | Up to 2,000 characters per comment, author name | Written by members. |
| `connection` | Source type, host, scope, account label, **the credential encrypted** (§4) | The only mutable table holding customer secrets. A Google Docs connection holds no secret, enforced by a check constraint. |
| `workspace`, `workspace_member` | Workspace names; member names and roles | Written only over the owner connection. |

**Raw source content is not persisted.** Pull requests, issues and docs are fetched into memory for one extraction run, sent to the model, and discarded. Only the verbatim excerpts backing each claim are kept. That is the provenance rule (Engineering Philosophy §4), and it is also the data-minimisation answer.

## 3. Where data goes (subprocessors)

| Party | Receives | Direction |
|---|---|---|
| **Supabase** (Postgres host) | Everything in §2 | Storage |
| **Anthropic** (Claude) | Full text of each artifact being extracted. For Q&A: the confirmed claims of one product plus the question. | Sent per run, per question. Not stored by Atlas beyond §2. See B3 for whose terms apply. |
| **GitHub / Atlassian (Jira) / Google (Docs)** | Authenticated read requests | **Atlas only reads.** No write path to any source exists in `atlas.*` (Philosophy §1). |

## 4. Encryption and secrets

- **In transit:**
  - Database connections use `sslmode=require` (both roles, via the Supabase pooler).
  - Source APIs and Anthropic are reached over HTTPS.
  - The session cookie is marked `Secure` whenever the app is served over HTTPS (`routes.py::sign_in`). Plain HTTP is used only for local development.
- **At rest:**
  - The database relies on the host's disk encryption. Atlas adds nothing on top for ordinary rows.
  - **Source credentials are additionally encrypted by Atlas** before they reach the database (`storage/connections.py`): Fernet, which is AES-128-CBC with HMAC-SHA256. The key is `ATLAS_SECRET_KEY`, held in the environment and never in the database.
  - No endpoint returns a credential, because `ConnectionView` has no field for one.
  - Revoking a connection deletes the row.
- **Key rotation (`atlas rotate-secrets`):**
  - Deploy with `ATLAS_SECRET_KEY="new,old"`, run the command once, then deploy with only the new key. It refuses to run with a single key.
  - Procedure: `docs/decisions/2026-09-30-secret-key-rotation.md`. **Never yet run against the live database.**
- **Google Docs:** one service account per workspace (`ATLAS_GOOGLE_SERVICE_ACCOUNTS`, in the environment), with scope `documents.readonly`. Config refuses one account mapped to two workspaces. A PM shares a doc with that account's email address to make it readable.
- **Other secrets:** the passphrase, session secret, database URLs and model key live only in the environment.
- **Logging:** Atlas writes no application log of request or response bodies. A failed run's error message is stored and shown to the PM, so the connection's credential is stripped from it first, and any message that still contains a private key is blanked (`pipeline._redact`). The web server's access log records method, path and status.

## 5. Access control

- **Sessions:**
  - A signed cookie (`itsdangerous`, server-side secret) that is `httpOnly`, `SameSite=Lax`, and valid for 24 hours.
  - Membership is re-read from the database on **every** request, so removing a member takes effect on their next click rather than when their cookie expires.
  - Identity itself is not verified (B1).
- **Roles:**
  - **Viewer:** reads and comments.
  - **Editor:** additionally rules on claims and pulls sources.
  - **Admin:** additionally connects and revokes sources, and sees the activity page.
  - Enforced in `api/deps.py` (`WriterDep`, `AdminDep`), not in the UI.
- **Tenant isolation, two locks:**
  - Every query filters by workspace.
  - Postgres row-level security, **forced**, so it binds the application's own role. It keys on a transaction-local setting, which cannot leak across pooled connections (`storage/rbac.py`).
  - The app role (`atlas_app`) can't create workspaces or seat members. Provisioning runs only over the owner connection (`atlas workspace-create`, `atlas member-seat`).
- **Human vs automated:** every event records whether a person or a machine wrote it (`actor_kind`). Automated rulings are never counted as human ones in any metric.
- **Source access is the connecting credential's own.** Atlas sees what that token can see and nothing else. Recommend a **fine-grained, read-only** GitHub token and a Jira account limited to the pilot's project. Jira hosts are allowlisted to `*.atlassian.net`, to block server-side request forgery (`pipeline.py`).

## 6. Retention

- **Today: indefinite.** Nothing expires. The log is append-only, so a rejected claim, an edited claim's original wording and every comment are all kept. That is deliberate (the log is the audit trail), and it is also why B2 matters.
- **Proposed pilot policy:** keep everything for the pilot's duration, and delete the workspace within 30 days of the pilot ending or on request. A pilot can quote this once B2 is built.
- **Backups:** whatever the database tier provides. The free tier's backups aren't something to promise a customer (B4).

## 7. Questions a questionnaire will ask that are still open

- **SSO / SAML:** not built, deferred by the user until a pilot names its identity provider. B1 is the minimum before any pilot regardless.
- **MFA:** no; it follows from B1.
- **Audit log export:** the event log *is* the audit trail, and the activity page summarises it. There is no export endpoint.
- **Penetration test / SOC 2:** none.
- **Data residency:** a single region (Seoul). Moving it means a new project and a migration.
- **Incident response, vulnerability disclosure, sub-processor notice:** no written process yet.

## 8. What was verified, and how

The security reviews of 2026-08-15 (connections), 2026-09-28 (Google Docs) and the backend review of 2026-09-28 each found and fixed issues. They are recorded in their decision docs. Row-level security is checked against the live database with `scripts/verify_rls.py` (`docs/architecture/rls-verification-checklist-v1.md`), not just by the test suite, which runs on SQLite and can't exercise the policies.
