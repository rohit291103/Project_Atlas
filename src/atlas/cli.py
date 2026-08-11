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
from rich.text import Text
from sqlalchemy.orm import Session

from atlas.config import DEFAULT_WORKSPACE_ID, JiraSettings, Settings
from atlas.extraction.agent import (
    ExtractionError,
    ExtractionResult,
    extract_from_jira_issue,
    extract_from_pull_request,
)
from atlas.ingestion.github import GitHubClient, GitHubError
from atlas.ingestion.jira import JiraClient, JiraError
from atlas.models.schema import EventType, IngestionRunPayload
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


def _parse_scope(feature_scope: str) -> uuid.UUID:
    try:
        return uuid.UUID(feature_scope)
    except ValueError as bad:
        raise typer.BadParameter("--feature-scope must be a UUID") from bad


def _require_db_url() -> str:
    url = os.environ.get("SUPABASE_DB_URL")
    if not url:
        console.print("[red]SUPABASE_DB_URL is not set (add it to .env).[/red]")
        raise typer.Exit(1)
    return url


def record_extraction(
    session: Session,
    result: ExtractionResult,
    *,
    workspace_id: uuid.UUID,
    ingestion_run: IngestionRunPayload,
) -> None:
    """Write an extraction result to the event log as append-only events.

    Nodes and edges are already validated `Node`/`Edge` models; storing their
    `model_dump(mode="json")` is the exact shape `load_projection` replays back.
    `append_event` is the sole write path -- no table is ever mutated directly.

    The `ingestion_run` event goes first, so replaying the log in order names the
    feature scope before the nodes that belong to it appear. It is required, not
    optional: a run that wrote nodes under a scope nobody can name is the gap
    slice 1A' exists to close.
    """
    append_event(
        session,
        event_type=EventType.INGESTION_RUN,
        payload=ingestion_run.model_dump(mode="json"),
        actor="system",
        workspace_id=workspace_id,
    )
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


def _render_feature_scope(projection: Projection) -> RenderableType | None:
    """Name the scope being reviewed, or `None` when the projection doesn't
    identify exactly one.

    A scope ingested before slice 1A' has no `ingestion_run` in the log and so no
    title; the report then omits the header rather than inventing one. Listing
    the runs it was assembled from is the CLI's version of what the confirmation
    UI's header shows (`docs/ux/confirmation-flow-spec-v1.md` Sec3.1)."""
    if len(projection.feature_scopes) != 1:
        return None
    scope = next(iter(projection.feature_scopes.values()))
    # dict.fromkeys dedupes while keeping ingest order -- re-ingesting the same
    # PR shouldn't list it twice.
    sources = " · ".join(dict.fromkeys(run.external_id for run in scope.runs))
    header = Text(scope.title, style="bold")
    header.append(f"\nAssembled from {sources}", style="dim")
    return header


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
        # Manually-added nodes carry no confidence score (TRD Sec6) -- an em dash
        # says "not scored," where "0.00" would read as "scored, and worthless."
        score = "—" if node.confidence_score is None else f"{node.confidence_score:.2f}"
        nodes.add_row(
            _short_id(node.id),
            node.type.value,
            node.content,
            score,
            node.status.value,
            provenance,
        )

    header = _render_feature_scope(projection)
    sections: list[RenderableType] = [nodes] if header is None else [header, nodes]

    if not projection.edges:
        return sections[0] if len(sections) == 1 else Group(*sections)

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
    return Group(*sections, edges)


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
        run, result = asyncio.run(
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
        record_extraction(session, result, workspace_id=DEFAULT_WORKSPACE_ID, ingestion_run=run)

    console.print(
        f"[green]Extracted {len(result.nodes)} node(s) and {len(result.edges)} edge(s).[/green]"
    )
    console.print(f"Feature scope: [bold]{run.external_id} · {run.title}[/bold]")
    console.print(f"Review with: [bold]atlas review --feature-scope {feature_scope_id}[/bold]")


def resolve_jira_keys(
    client: JiraClient, *, issue: str | None, epic: str | None, label: str | None, limit: int
) -> list[str]:
    """Turn `--issue` / `--epic` / `--label` into the issue keys to ingest.

    Scoped ingestion (TRD Sec4.2): a scope is pulled *deliberately* -- one issue,
    one epic's children, or one label -- never by crawling a Jira site. The
    `limit` is a hard ceiling, so a mistyped label can't start an unbounded run.
    GitHub needs no equivalent because `atlas ingest` is already per-PR.
    """
    if issue:
        return [issue]
    if epic:
        jql = f'parent = "{epic}" ORDER BY created ASC'
    elif label:
        jql = f'labels = "{label}" ORDER BY created ASC'
    else:
        raise typer.BadParameter("pass exactly one of --issue, --epic or --label")
    return [found.key for found in client.search_issues(jql, limit=limit)]


@app.command("ingest-jira")
def ingest_jira(
    issue: str = typer.Option(None, help="One issue key, e.g. GATE-42."),
    epic: str = typer.Option(None, help="Ingest every child of this epic key."),
    label: str = typer.Option(None, help="Ingest every issue carrying this label."),
    feature_scope: str = typer.Option(
        None, help="Add to an existing feature scope instead of opening a new one."
    ),
    limit: int = typer.Option(10, help="Hard ceiling on issues pulled by --epic/--label."),
) -> None:
    """Ingest Jira issues into a feature scope (new, or one that already exists).

    Passing `--feature-scope` is what makes a feature *cross-source*: the run is
    handed the claims GitHub already produced, so the agent can flag a
    contradiction between them (TRD Sec5.2) instead of the two sources sitting
    side by side, each unaware of the other.
    """
    load_dotenv()
    try:
        jira = JiraSettings.from_env()
        database_url = _require_db_url()
    except KeyError as missing:
        console.print(f"[red]Missing required env var {missing} (add it to .env).[/red]")
        raise typer.Exit(1) from missing

    if sum(bool(option) for option in (issue, epic, label)) != 1:
        raise typer.BadParameter("pass exactly one of --issue, --epic or --label")
    scope_id = _parse_scope(feature_scope) if feature_scope else uuid.uuid4()

    session_factory = get_sessionmaker(get_engine(database_url))
    client = JiraClient(base_url=jira.base_url, email=jira.email, api_token=jira.api_token)
    try:
        keys = resolve_jira_keys(client, issue=issue, epic=epic, label=label, limit=limit)
        if not keys:
            console.print("[yellow]No matching Jira issues.[/yellow]")
            raise typer.Exit(1)
        for key in keys:
            # Re-read per issue: an issue ingested earlier in this same loop is
            # itself context the next one can conflict with.
            with session_scope(session_factory) as session:
                known = list(
                    load_projection(
                        session, workspace_id=DEFAULT_WORKSPACE_ID, feature_scope_id=scope_id
                    ).nodes.values()
                )
            run, result = asyncio.run(
                extract_from_jira_issue(
                    client=client,
                    key=key,
                    workspace_id=DEFAULT_WORKSPACE_ID,
                    feature_scope_id=scope_id,
                    known_nodes=known,
                )
            )
            with session_scope(session_factory) as session:
                record_extraction(
                    session, result, workspace_id=DEFAULT_WORKSPACE_ID, ingestion_run=run
                )
            cross = sum(
                1 for edge in result.edges if edge.to_node_id in {node.id for node in known}
            )
            console.print(
                f"[green]{key}: {len(result.nodes)} node(s), {len(result.edges)} edge(s)"
                f"{f', {cross} cross-source' if cross else ''}.[/green]"
            )
    except (JiraError, ExtractionError) as exc:
        console.print(f"[red]Ingestion failed: {exc}[/red]")
        raise typer.Exit(1) from exc
    finally:
        client.close()

    console.print(f"Review with: [bold]atlas review --feature-scope {scope_id}[/bold]")


@app.command()
def review(feature_scope: str) -> None:
    """Replay the event log and print the draft nodes for a feature scope."""
    load_dotenv()
    scope_id = _parse_scope(feature_scope)

    session_factory = get_sessionmaker(get_engine(_require_db_url()))
    with session_scope(session_factory) as session:
        projection = load_projection(
            session, workspace_id=DEFAULT_WORKSPACE_ID, feature_scope_id=scope_id
        )
    console.print(render_projection(projection))


if __name__ == "__main__":
    app()
