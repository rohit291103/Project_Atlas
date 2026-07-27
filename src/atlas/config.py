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
