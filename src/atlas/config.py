import json
import os
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# The single logical workspace every piece of Phase 0 data belongs to.
#
# Phase 0 is explicitly one team / one internal tool with no workspace-creation
# flow and no multi-tenancy (real workspaces + RBAC are Phase 4 — see CLAUDE.md
# Non-Goals). But `workspace_id` is *required* on every Node/SourceRef/Event and
# on the event_log table, by design: the data model is event-sourced from day one
# (TRD §3.2) so multi-tenancy slots in later with no schema migration.
#
# Until real workspaces exist, application code stamps everything with this
# well-known nil sentinel. The nil UUID is deliberate — it reads unmistakably as
# "the default workspace, not a provisioned one," making the Phase 4 migration a
# trivial, greppable "reassign every nil-workspace event to the real workspace."
#
# Note this is a plain constant, NOT a default on the schema fields: the fields
# stay required so the single-workspace assumption lives visibly at the call
# sites. When real workspaces arrive, schema.py is untouched — only the call
# sites change to pass a real id.
DEFAULT_WORKSPACE_ID: uuid.UUID = uuid.UUID(int=0)


@dataclass(frozen=True)
class Settings:
    # Optional, and unused by our code directly. Extraction runs through the
    # Claude Agent SDK, which authenticates via the Claude Code CLI login -- so a
    # Claude Pro/Max subscription covers it with NO API key. Setting this env var
    # instead routes the SDK through pay-as-you-go Anthropic API billing (a
    # separate wallet from the subscription). Left as an optional escape hatch;
    # `from_env` never requires it.
    anthropic_api_key: str | None
    github_token: str
    supabase_db_url: str

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY"),
            github_token=os.environ["GITHUB_TOKEN"],
            supabase_db_url=os.environ["SUPABASE_DB_URL"],
        )


@dataclass(frozen=True)
class JiraSettings:
    """Credentials for the second source (slice 1C).

    Email + API token, not OAuth 3LO -- resolving `Phase1_Architecture.md` §10 Q4.
    A Jira Cloud API token carries exactly the permissions of the person who
    minted it, so least privilege (Philosophy §6) holds with no scope negotiation:
    Atlas cannot read a project its holder could not already open. Separate from
    `Settings` because a GitHub-only ingest must not require Jira credentials to
    exist, and vice versa.
    """

    base_url: str
    email: str
    api_token: str

    @classmethod
    def from_env(cls) -> "JiraSettings":
        return cls(
            base_url=os.environ["JIRA_BASE_URL"],
            email=os.environ["JIRA_EMAIL"],
            api_token=os.environ["JIRA_API_TOKEN"],
        )


@dataclass(frozen=True)
class ApiSettings:
    """What the API process needs -- deliberately *not* a superset of `Settings`.

    **It still holds no source credential of its own.** Slice 2B gave the API an
    ingest endpoint, so it does now reach GitHub and Jira -- but with a
    per-product credential the PM connected, decrypted from the `connection`
    table for the duration of one run. `GITHUB_TOKEN` and `JIRA_API_TOKEN` remain
    absent from this class on purpose: the web-facing process must not carry an
    ambient credential that every request could use
    (Engineering Philosophy §6, least privilege applied to our own processes).

    `secret_key` is the Fernet key those connections are encrypted with. It lives
    in the environment, never in the database, which is what makes "a database
    compromise alone yields ciphertext" true
    (`docs/decisions/2026-08-15-connections-and-ui-ingestion.md`).

    `app_passphrase` is Phase 1's whole authentication story -- one workspace,
    one shared passphrase plus a name that becomes the audit `actor`.
    """

    supabase_db_url: str
    app_passphrase: str
    session_secret: str
    secret_key: str
    #: Google service accounts, **one per workspace** -- the one deliberate
    #: exception to "no ambient source credential" above (2026-09-28, "share
    #: with Atlas"; `docs/decisions/2026-09-28-google-docs-source.md`). Accepted
    #: because an account's reach is exactly the docs people shared with it,
    #: read-only. Per workspace (2026-09-30) so a doc shared with one
    #: workspace's address is unreadable from another -- a single shared account
    #: made any doc URL ingestible by every tenant. Empty: Google Docs is simply
    #: unavailable. `repr=False` keeps private keys out of any log line.
    google_service_accounts: dict[uuid.UUID, dict[str, Any]] = field(
        default_factory=dict, repr=False
    )

    def google_account(self, workspace_id: uuid.UUID) -> dict[str, Any] | None:
        return self.google_service_accounts.get(workspace_id)

    @classmethod
    def from_env(cls) -> "ApiSettings":
        return cls(
            supabase_db_url=os.environ["SUPABASE_DB_URL"],
            app_passphrase=os.environ["ATLAS_APP_PASSPHRASE"],
            session_secret=os.environ["ATLAS_SESSION_SECRET"],
            secret_key=os.environ["ATLAS_SECRET_KEY"],
            google_service_accounts=google_service_accounts(
                os.environ.get("ATLAS_GOOGLE_SERVICE_ACCOUNTS")
            ),
        )


def google_service_accounts(value: str | None) -> dict[uuid.UUID, dict[str, Any]]:
    """`ATLAS_GOOGLE_SERVICE_ACCOUNTS`: a JSON object mapping workspace id to
    that workspace's key -- the key JSON itself, or a path to it.

    Fails loudly rather than starting with Google Docs half-configured, and
    refuses two workspaces sharing one account: that configuration would
    quietly reopen the cross-tenant gap this mapping exists to close. Error
    messages name the workspace, never the key.
    """
    if not value or not value.strip():
        return {}
    mapping = json.loads(value)
    if not isinstance(mapping, dict):
        raise ValueError("ATLAS_GOOGLE_SERVICE_ACCOUNTS must map workspace id to a key")
    accounts: dict[uuid.UUID, dict[str, Any]] = {}
    owners: dict[str, uuid.UUID] = {}
    for raw_id, raw_key in mapping.items():
        try:
            workspace_id = uuid.UUID(raw_id)
        except ValueError:
            raise ValueError(
                f"ATLAS_GOOGLE_SERVICE_ACCOUNTS: {raw_id!r} is not a workspace id"
            ) from None
        info = json.loads(Path(raw_key).read_text()) if isinstance(raw_key, str) else raw_key
        if not isinstance(info, dict) or not {"client_email", "private_key"} <= info.keys():
            raise ValueError(
                f"ATLAS_GOOGLE_SERVICE_ACCOUNTS: the key for workspace {workspace_id} "
                "is not a service account key (expected client_email and private_key)"
            )
        email = str(info["client_email"])
        if email in owners:
            raise ValueError(
                f"ATLAS_GOOGLE_SERVICE_ACCOUNTS: {email} is given to two workspaces "
                f"({owners[email]} and {workspace_id}); each needs its own account"
            )
        owners[email] = workspace_id
        accounts[workspace_id] = info
    return accounts
