# Rotating `ATLAS_SECRET_KEY`

**Date:** 2026-09-30
**Status:** built and tested. It hasn't been run against the live database, because a rotation is an operator action.
**Roadmap:** v2 Phase 4, "key rotation for `ATLAS_SECRET_KEY`".

## What changed

- **`ATLAS_SECRET_KEY` can now be a comma-separated list.** The first key encrypts, and every listed key can decrypt (Fernet's multi-key mode). One key is the normal state. More than one exists only while a rotation is in progress. A malformed entry is reported by its position, and its value is never repeated.
- **`storage.connections.rotate_connection_secrets`** re-encrypts every stored credential under the first key, in every workspace. Google Docs rows hold no secret and are skipped. It refuses to run with only one key, because that almost always means the `new,old` deploy step was skipped. A row encrypted under a key that isn't listed fails loudly rather than being skipped, since a skipped row would fail on its next run with no explanation.
- **`atlas rotate-secrets`** is the CLI entry point. It connects with `SUPABASE_DB_ADMIN_URL` through the new `storage.rbac.owner_session`: a named, deliberate way to cross workspaces, which keeps the CLI's "never an unscoped transaction" guard intact. It prints a count and never a key.

## Procedure

1. Generate a new key: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`.
2. Deploy the API with `ATLAS_SECRET_KEY="<new>,<old>"`. New connections are encrypted under the new key, and existing ones still decrypt.
3. With the same value in `.env`, run `uv run atlas rotate-secrets`. It re-encrypts every stored credential under `<new>`.
4. Deploy with `ATLAS_SECRET_KEY="<new>"` only. The old key can now be destroyed.

If step 3 fails partway through, nothing is committed (it runs in a single transaction). Fix the cause and run it again.

## Not done

- **No audit event for a rotation.** The `connection` table is mutable by design, and a new event type would need an enum migration. For now the operator's shell history is the record. Add an event if the security questionnaire asks for one.
- **Only the credential key rotates.** `ATLAS_SESSION_SECRET` and the Google service account key rotate the ordinary way: replace the value and redeploy. Replacing the session secret signs everyone out.
