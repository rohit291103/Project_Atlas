"""Typer entrypoint -- the engineer-facing read/debug path (CLAUDE.md).

  atlas ingest --repo owner/name --pr N       GitHub -> agent -> event log
  atlas ingest-jira --issue/--epic/--label    Jira, into a new or existing scope
  atlas product-create / product-assign       the product a feature is filed under
  atlas review --feature-scope <id>           replay the log, print the draft

**This module holds no orchestration.** As of slice 2B the sequence "parse a
target -> build a read-only client -> run the agent -> write validated events"
lives in `atlas/pipeline.py`, because the API's ingest endpoint runs the
identical sequence and two copies of it would drift. The commands here read
credentials out of the environment, hand `pipeline` a `RunRequest`, and render
the result -- that is all. `tests/test_cli.py` has a test that fails if
orchestration comes back to this file.

Everything the agent produces has already passed the `build_result` schema gate
before it reaches the event log (CLAUDE.md's one rule with zero exceptions).
"""

from __future__ import annotations

import os
import uuid

import typer
from dotenv import load_dotenv
from rich.console import Console, Group, RenderableType
from rich.table import Table
from rich.text import Text

from atlas.config import DEFAULT_WORKSPACE_ID, JiraSettings, Settings
from atlas.models.schema import RunState, RunTargetKind
from atlas.pipeline import (
    GitHubCredential,
    JiraCredential,
    RunOutcome,
    RunRequest,
    TargetError,
    run_ingestion,
)
from atlas.storage.db import get_engine, get_sessionmaker
from atlas.storage.products import assign_feature_scope, create_product
from atlas.storage.projections import Projection, load_projection
from atlas.storage.rbac import workspace_session

app = typer.Typer(help="Project Atlas -- extraction CLI and debug read path.")
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


def _report(request: RunRequest, outcome: RunOutcome) -> None:
    """Print a run's result. The CLI's whole job after `pipeline` returns."""
    if outcome.state is not RunState.SUCCEEDED:
        console.print(f"[red]Ingestion failed: {outcome.error}[/red]")
        raise typer.Exit(1)
    console.print(
        f"[green]Pulled {outcome.artifacts} artifact(s): "
        f"{outcome.nodes} node(s), {outcome.edges} edge(s).[/green]"
    )
    console.print(
        f"Review with: [bold]atlas review --feature-scope {request.feature_scope_id}[/bold]"
    )


@app.command()
def ingest(
    repo: str,
    pr: int,
    feature_scope: str = typer.Option(
        None, help="Add to an existing feature scope instead of opening a new one."
    ),
) -> None:
    """Ingest one GitHub PR, extract knowledge, and store it as events."""
    load_dotenv()
    try:
        settings = Settings.from_env()
    except KeyError as missing:
        console.print(f"[red]Missing required env var {missing} (add it to .env).[/red]")
        raise typer.Exit(1) from missing

    owner, name = _parse_repo(repo)
    request = RunRequest(
        workspace_id=DEFAULT_WORKSPACE_ID,
        actor="cli",
        target_kind=RunTargetKind.GITHUB_PR,
        target=f"{owner}/{name}#{pr}",
        feature_scope_id=_parse_scope(feature_scope) if feature_scope else uuid.uuid4(),
    )
    session_factory = get_sessionmaker(get_engine(settings.supabase_db_url))
    _report(
        request,
        run_ingestion(
            session_factory, request=request, credential=GitHubCredential(settings.github_token)
        ),
    )


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
    handed the claims the other source already produced, so the agent can flag a
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
    kind, target = (
        (RunTargetKind.JIRA_ISSUE, issue)
        if issue
        else (RunTargetKind.JIRA_EPIC, epic)
        if epic
        else (RunTargetKind.JIRA_LABEL, label)
    )

    request = RunRequest(
        workspace_id=DEFAULT_WORKSPACE_ID,
        actor="cli",
        target_kind=kind,
        target=target,
        feature_scope_id=_parse_scope(feature_scope) if feature_scope else uuid.uuid4(),
        limit=limit,
    )
    session_factory = get_sessionmaker(get_engine(database_url))
    try:
        outcome = run_ingestion(
            session_factory,
            request=request,
            credential=JiraCredential(
                base_url=jira.base_url, email=jira.email, api_token=jira.api_token
            ),
        )
    except TargetError as bad:
        raise typer.BadParameter(str(bad)) from bad
    _report(request, outcome)


@app.command("product-create")
def product_create(name: str) -> None:
    """Open a product -- the container a PM's features and connections live in."""
    load_dotenv()
    session_factory = get_sessionmaker(get_engine(_require_db_url()))
    with workspace_session(session_factory, DEFAULT_WORKSPACE_ID) as session:
        product_id, _ = create_product(
            session, workspace_id=DEFAULT_WORKSPACE_ID, name=name, actor="cli"
        )
    console.print(f"[green]Created product[/green] [bold]{name}[/bold] · {product_id}")


@app.command("product-assign")
def product_assign(feature_scope: str, product: str) -> None:
    """File an existing feature scope under a product.

    This is the path for the scopes ingested before products existed: it appends
    one event, and never rewrites the `ingestion_run` that opened the scope.
    """
    load_dotenv()
    scope_id = _parse_scope(feature_scope)
    try:
        product_id = uuid.UUID(product)
    except ValueError as exc:
        raise typer.BadParameter(f"{product!r} is not a UUID") from exc

    session_factory = get_sessionmaker(get_engine(_require_db_url()))
    with workspace_session(session_factory, DEFAULT_WORKSPACE_ID) as session:
        projection = load_projection(session, workspace_id=DEFAULT_WORKSPACE_ID)
        if product_id not in projection.products:
            console.print(f"[red]No product {product_id} in this workspace.[/red]")
            raise typer.Exit(1)
        if scope_id not in projection.feature_scopes:
            console.print(f"[red]No feature scope {scope_id} in this workspace.[/red]")
            raise typer.Exit(1)
        assign_feature_scope(
            session,
            workspace_id=DEFAULT_WORKSPACE_ID,
            feature_scope_id=scope_id,
            product_id=product_id,
            actor="cli",
        )
    console.print(
        f"[green]Filed[/green] {projection.feature_scopes[scope_id].title} "
        f"under [bold]{projection.products[product_id].name}[/bold]"
    )


@app.command()
def review(feature_scope: str) -> None:
    """Replay the event log and print the draft nodes for a feature scope."""
    load_dotenv()
    scope_id = _parse_scope(feature_scope)

    session_factory = get_sessionmaker(get_engine(_require_db_url()))
    with workspace_session(session_factory, DEFAULT_WORKSPACE_ID) as session:
        projection = load_projection(
            session, workspace_id=DEFAULT_WORKSPACE_ID, feature_scope_id=scope_id
        )
    console.print(render_projection(projection))


if __name__ == "__main__":
    app()
