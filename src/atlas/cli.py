"""Typer entrypoint -- Phase 0's stand-in for the confirmation UI (CLAUDE.md).

Two commands wire the four modules into the end-to-end loop:

  atlas ingest --repo owner/name --pr N
      GitHub (read-only) -> extraction agent -> validated Node/Edge -> append_event
      Prints a fresh feature_scope_id to review against.

  atlas review --feature-scope <id>
      load_projection replays the event log -> Rich console report of the draft
      Nodes (grouped by type, with confidence + status + literal source excerpt).

Everything the agent produces has already passed the `build_result` schema gate
before it reaches `record_extraction`, so nothing unvalidated is ever written
(CLAUDE.md's one rule with zero exceptions). The reusable pieces --
`_parse_repo`, `record_extraction`, `render_projection` -- are factored out of
the command bodies so they're testable without a live API key or database.
"""

from __future__ import annotations

import asyncio
import os
import uuid

import typer
from dotenv import load_dotenv
from rich.console import Console, Group, RenderableType
from rich.table import Table
from sqlalchemy.orm import Session

from atlas.config import DEFAULT_WORKSPACE_ID, Settings
from atlas.extraction.agent import ExtractionError, ExtractionResult, extract_from_pull_request
from atlas.ingestion.github import GitHubClient, GitHubError
from atlas.models.schema import EventType
from atlas.storage.db import get_engine, get_sessionmaker, session_scope
from atlas.storage.projections import Projection, load_projection
from atlas.storage.tables import append_event

app = typer.Typer(help="Project Atlas -- Phase 0 extraction CLI.")
console = Console()


def _parse_repo(repo: str) -> tuple[str, str]:
    """Split an `owner/name` argument, or fail with a clear CLI error."""
    owner, sep, name = repo.partition("/")
    if not sep or not owner or not name:
        raise typer.BadParameter("--repo must be in 'owner/name' form, e.g. acme/gateway")
    return owner, name


def _require_db_url() -> str:
    url = os.environ.get("SUPABASE_DB_URL")
    if not url:
        console.print("[red]SUPABASE_DB_URL is not set (add it to .env).[/red]")
        raise typer.Exit(1)
    return url


def record_extraction(
    session: Session, result: ExtractionResult, *, workspace_id: uuid.UUID
) -> None:
    """Write an extraction result to the event log as append-only events.

    Nodes and edges are already validated `Node`/`Edge` models; storing their
    `model_dump(mode="json")` is the exact shape `load_projection` replays back.
    `append_event` is the sole write path -- no table is ever mutated directly.
    """
    for node in result.nodes:
        append_event(
            session,
            event_type=EventType.NODE_CREATED,
            payload=node.model_dump(mode="json"),
            actor="system",
            workspace_id=workspace_id,
        )
    for edge in result.edges:
        append_event(
            session,
            event_type=EventType.EDGE_CREATED,
            payload=edge.model_dump(mode="json"),
            actor="system",
            workspace_id=workspace_id,
        )


def _short_id(node_id: uuid.UUID) -> str:
    """A short, human-scannable node handle. The Nodes table shows it in an `ID`
    column and the Edges table references the same handle, so a reviewer can map
    an edge's endpoints back to the nodes it connects (full UUIDs are unreadable
    and appear nowhere else)."""
    return str(node_id)[:8]


def render_projection(projection: Projection) -> RenderableType:
    """Build the Rich console report for a feature scope's projected state."""
    nodes = Table(title="Extracted Nodes (unconfirmed drafts)", show_lines=True, expand=True)
    nodes.add_column("ID", style="dim", no_wrap=True)
    nodes.add_column("Type", style="cyan", no_wrap=True)
    nodes.add_column("Content")
    nodes.add_column("Conf.", justify="right", no_wrap=True)
    nodes.add_column("Status", no_wrap=True)
    nodes.add_column("Source")

    if not projection.nodes:
        nodes.add_row("", "—", "No nodes for this feature scope.", "", "", "")
    for node in sorted(projection.nodes.values(), key=lambda n: n.type.value):
        provenance = "\n".join(f"{ref.url}\n“{ref.excerpt}”" for ref in node.source_refs)
        nodes.add_row(
            _short_id(node.id),
            node.type.value,
            node.content,
            f"{node.confidence_score:.2f}",
            node.status.value,
            provenance,
        )

    if not projection.edges:
        return nodes

    edges = Table(title="Edges", show_lines=True, expand=True)
    edges.add_column("From", style="dim", no_wrap=True)
    edges.add_column("Relation", style="magenta", no_wrap=True)
    edges.add_column("To", style="dim", no_wrap=True)
    edges.add_column("Conf.", justify="right", no_wrap=True)
    for edge in projection.edges.values():
        edges.add_row(
            _short_id(edge.from_node_id),
            edge.relation_type.value,
            _short_id(edge.to_node_id),
            f"{edge.confidence_score:.2f}",
        )
    return Group(nodes, edges)


@app.command()
def ingest(repo: str, pr: int) -> None:
    """Ingest one GitHub PR, extract knowledge, and store it as events."""
    load_dotenv()
    try:
        settings = Settings.from_env()
    except KeyError as missing:
        console.print(f"[red]Missing required env var {missing} (add it to .env).[/red]")
        raise typer.Exit(1) from missing

    owner, name = _parse_repo(repo)
    feature_scope_id = uuid.uuid4()

    client = GitHubClient(settings.github_token)
    try:
        result = asyncio.run(
            extract_from_pull_request(
                client=client,
                owner=owner,
                repo=name,
                number=pr,
                workspace_id=DEFAULT_WORKSPACE_ID,
                feature_scope_id=feature_scope_id,
            )
        )
    except (GitHubError, ExtractionError) as exc:
        console.print(f"[red]Extraction failed: {exc}[/red]")
        raise typer.Exit(1) from exc
    finally:
        client.close()

    session_factory = get_sessionmaker(get_engine(settings.supabase_db_url))
    with session_scope(session_factory) as session:
        record_extraction(session, result, workspace_id=DEFAULT_WORKSPACE_ID)

    console.print(
        f"[green]Extracted {len(result.nodes)} node(s) and {len(result.edges)} edge(s).[/green]"
    )
    console.print(f"Review with: [bold]atlas review --feature-scope {feature_scope_id}[/bold]")


@app.command()
def review(feature_scope: str) -> None:
    """Replay the event log and print the draft nodes for a feature scope."""
    load_dotenv()
    try:
        scope_id = uuid.UUID(feature_scope)
    except ValueError as bad:
        raise typer.BadParameter("--feature-scope must be a UUID") from bad

    session_factory = get_sessionmaker(get_engine(_require_db_url()))
    with session_scope(session_factory) as session:
        projection = load_projection(
            session, workspace_id=DEFAULT_WORKSPACE_ID, feature_scope_id=scope_id
        )
    console.print(render_projection(projection))


if __name__ == "__main__":
    app()
