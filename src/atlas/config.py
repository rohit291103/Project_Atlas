import os
import uuid
from dataclasses import dataclass

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

    The API never talks to GitHub and never runs the extraction agent (there is
    no ingest endpoint in slice 1B -- `docs/decisions/2026-08-11-api-frontend-module-boundary.md`
    §5), so it must not require `GITHUB_TOKEN` to boot. Least-privilege applies
    to our own processes too (Engineering Philosophy §6): the web-facing process
    holds the database URL and its own session secrets, and nothing else.

    `app_passphrase` is Phase 1's whole authentication story -- one workspace,
    one PM (§4 of the same doc). Slice 1D's real RBAC replaces it.
    """

    supabase_db_url: str
    app_passphrase: str
    session_secret: str

    @classmethod
    def from_env(cls) -> "ApiSettings":
        return cls(
            supabase_db_url=os.environ["SUPABASE_DB_URL"],
            app_passphrase=os.environ["ATLAS_APP_PASSPHRASE"],
            session_secret=os.environ["ATLAS_SESSION_SECRET"],
        )
