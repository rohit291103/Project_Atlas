"""One ingestion run, start to finish -- the sequence both the CLI and the API drive.

**Why this is its own module and not part of `cli/`, `ingestion/`, `extraction/`
or `storage/`.** It spans all three of the latter: parse a target, build a
read-only client, run the agent, write validated output through `append_event`.
Until slice 2B there was exactly one caller (`cli.py`) and so no reason to
extract it. There are now two -- the API's ingest endpoint runs the identical
sequence -- which is the `codebase-design` skill's own bar for pulling an
abstraction out. Duplicating it would let the two drift, and the thing that would
drift is the path along which "extraction never reaches storage unvalidated"
holds. That makes it a correctness concern rather than a tidiness one.

**The run lifecycle, and the honest cost of having no queue.** A run started from
the browser returns before it finishes, so its state has to be answerable from
the log:

    ingestion_run_started      written before any network call
      ingestion_run            one per artifact actually pulled (unchanged meaning)
      ...
    ingestion_run_finished     exactly one terminal success
    ingestion_run_failed       or exactly one terminal failure

The work happens in the API process (FastAPI `BackgroundTasks`) -- no broker, no
worker, no new deployable, all of which are explicit CLAUDE.md Non-Goals. The
cost is that a process dying mid-run leaves a start with no terminal event, which
is indistinguishable from a slow run; `storage/projections.py::INTERRUPTED_AFTER`
is where that is made visible rather than hidden.

**Credentials are arguments, never environment.** `run_ingestion` takes a
`Credential`; who read it out of `.env` (the CLI) or decrypted it from the
`connection` table (the API) is the composition root's business. Nothing in this
module or in `ingestion/` knows which.
"""

from __future__ import annotations

import asyncio
import re
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.orm import Session, sessionmaker

from atlas.extraction.agent import (
    ExtractionError,
    ExtractionResult,
    extract_from_jira_issue,
    extract_from_pull_request,
)
from atlas.ingestion.github import GitHubClient, GitHubError
from atlas.ingestion.jira import JiraClient, JiraError
from atlas.models.schema import (
    ActorKind,
    EventType,
    IngestionRunPayload,
    Node,
    RunFailedPayload,
    RunFinishedPayload,
    RunStartedPayload,
    RunState,
    RunTargetKind,
)
from atlas.storage.projections import load_projection
from atlas.storage.rbac import workspace_session
from atlas.storage.tables import append_event

__all__ = [
    "AccessSummary",
    "Credential",
    "check_access",
    "GitHubCredential",
    "JiraCredential",
    "RunOutcome",
    "RunRequest",
    "TargetError",
    "UnsupportedHostError",
    "execute_run",
    "record_extraction",
    "resolve_jira_keys",
    "run_ingestion",
    "start_run",
]

#: Hard ceiling on artifacts a single run may pull (TRD Sec4.2). Scoped ingestion
#: is deliberate: one PR, one issue, one epic's children, one label -- never a
#: crawl. A mistyped label cannot start an unbounded run.
DEFAULT_LIMIT = 10
MAX_LIMIT = 50

#: `owner/repo#123`. Fully qualified because a feature scope is workspace-global
#: and a bare PR number is unique only inside one repository.
_GITHUB_TARGET = re.compile(r"^(?P<owner>[\w.-]+)/(?P<repo>[\w.-]+)#(?P<number>\d+)$")
#: `PROJ-42`, Jira's own key shape.
_JIRA_KEY = re.compile(r"^[A-Za-z][A-Za-z0-9_]*-\d+$")
#: A label is freer, but still not a wildcard.
_JIRA_LABEL = re.compile(r"^[\w.-]{1,64}$")

#: Failure messages are read by a PM, not by a debugger. Long enough to be
#: actionable, short enough not to paste a stack trace into a UI.
_MAX_ERROR = 400


class TargetError(ValueError):
    """The requested target is not a shape this system will pull.

    Raised before any network call and before the run is even started, so a
    malformed target never produces a run record to explain.
    """


@dataclass(frozen=True)
class GitHubCredential:
    token: str


#: Jira Cloud sites, and nothing else.
#:
#: **This is a server-side request forgery control, not a convenience.** Before
#: slice 2B the Jira site came from `JIRA_BASE_URL` in the environment, which is
#: trusted. It now comes from a form field, and `JiraClient` turns it into the
#: base URL of an outbound request carrying a `Basic` auth header -- so without
#: this, any workspace editor could aim the API process at `169.254.169.254`, at
#: an internal service, or at a host they control, and read part of the answer
#: back through the connect endpoint's access summary.
#:
#: An allowlist rather than a denylist of private ranges, because `ingestion/`
#: only ever supported Jira **Cloud** (`JiraSettings`, `JiraClient`) and a
#: Cloud site is always `<name>.atlassian.net`. Enumerating what to block is a
#: game you lose to DNS rebinding, redirects and IPv6 forms; enumerating what is
#: allowed is not. If Jira Server/Data Center is ever supported, this is the line
#: that has to change, and it should change with its own decision entry.
_JIRA_HOST = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.atlassian\.net$", re.IGNORECASE)


class UnsupportedHostError(TargetError):
    """The host is not one this system is willing to send a credential to."""


@dataclass(frozen=True)
class JiraCredential:
    """Jira Cloud credentials, with the site checked on the way in.

    Validated in `__post_init__` rather than at the API boundary so *both*
    callers are covered by one rule: the connect endpoint, which takes the host
    from a form, and the ingest endpoint, which takes it from a stored row. A
    check in only the first would be bypassed by any row written before it
    existed.
    """

    base_url: str
    email: str
    api_token: str

    def __post_init__(self) -> None:
        host = self.base_url.removeprefix("https://").removeprefix("http://").rstrip("/")
        if not _JIRA_HOST.match(host):
            raise UnsupportedHostError(
                f"{host or self.base_url!r} is not a Jira Cloud site "
                "— expected something like acme.atlassian.net"
            )
        if not self.base_url.startswith("https://"):
            # Plaintext would put the API token on the wire in the clear.
            raise UnsupportedHostError("a Jira site must be reached over https")


Credential = GitHubCredential | JiraCredential


@dataclass(frozen=True)
class RunRequest:
    """What to pull, into what, and on whose behalf.

    `feature_scope_id` is supplied rather than minted here: a run into an
    *existing* scope is what makes a feature cross-source, and the caller is the
    one who knows whether the PM picked "a new feature" or "add to this one".
    """

    workspace_id: uuid.UUID
    actor: str
    target_kind: RunTargetKind
    target: str
    feature_scope_id: uuid.UUID
    product_id: uuid.UUID | None = None
    connection_id: uuid.UUID | None = None
    limit: int = DEFAULT_LIMIT


@dataclass(frozen=True)
class AccessSummary:
    """What a credential can see, in words a PM reads before saving it.

    The trust moment the flow spec asks for: least privilege is a claim the
    product would otherwise only assert. `detail` is deliberately human ("Private
    repository · 12 open issues") rather than a payload — it is shown, never
    stored and never acted on.
    """

    label: str
    detail: str


def check_access(credential: Credential, *, scope: str) -> AccessSummary:
    """Probe what `credential` reaches at `scope`, read-only. Raises on failure.

    One metadata call, no crawl. A credential that cannot see its own scope is
    rejected at the connect step rather than at the first run, which is the
    difference between "that token is wrong" and "ingestion mysteriously failed
    an hour later".
    """
    if isinstance(credential, GitHubCredential):
        owner, _, repo = scope.partition("/")
        if not owner or not repo:
            raise TargetError(f"{scope!r} is not a repository — expected owner/repo")
        client = GitHubClient(credential.token)
        try:
            access = client.describe_repository(owner, repo)
        finally:
            client.close()
        visibility = "Private repository" if access.private else "Public repository"
        return AccessSummary(
            label=access.full_name,
            detail=f"{visibility} · {access.open_issues} open issue(s)",
        )
    client_jira = JiraClient(
        base_url=credential.base_url, email=credential.email, api_token=credential.api_token
    )
    try:
        project = client_jira.describe_project(scope)
    finally:
        client_jira.close()
    kind = project.project_type or "project"
    return AccessSummary(label=f"{project.name} ({project.key})", detail=f"Jira {kind}")


@dataclass(frozen=True)
class RunOutcome:
    run_id: uuid.UUID
    state: RunState
    artifacts: int = 0
    nodes: int = 0
    edges: int = 0
    error: str | None = None


# --- targets -------------------------------------------------------------------


def parse_target(kind: RunTargetKind, target: str) -> tuple[str, ...]:
    """Validate a target against its kind and split it into its parts.

    Deliberately strict. This is the one place a UI-supplied string becomes
    something the connectors act on, and a permissive parse here is how "ingest
    one PR" quietly becomes "ingest whatever this expands to".
    """
    cleaned = target.strip()
    if kind is RunTargetKind.GITHUB_PR:
        match = _GITHUB_TARGET.match(cleaned)
        if not match:
            raise TargetError(f"{target!r} is not a pull request — expected owner/repo#123")
        return match.group("owner"), match.group("repo"), match.group("number")
    if kind in (RunTargetKind.JIRA_ISSUE, RunTargetKind.JIRA_EPIC):
        if not _JIRA_KEY.match(cleaned):
            raise TargetError(
                f"{target!r} is not a Jira issue key — expected something like PROJ-42"
            )
        return (cleaned.upper(),)
    if not _JIRA_LABEL.match(cleaned):
        raise TargetError(f"{target!r} is not a usable Jira label")
    return (cleaned,)


def resolve_jira_keys(
    client: JiraClient, *, kind: RunTargetKind, target: str, limit: int
) -> list[str]:
    """Turn a Jira target into the issue keys to ingest.

    Scoped ingestion (TRD Sec4.2): one issue, one epic's children, or one label
    -- never a crawl of a Jira site. `limit` is a hard ceiling, so a mistyped
    label cannot start an unbounded run. GitHub needs no equivalent because a
    GitHub target names exactly one PR.
    """
    (value,) = parse_target(kind, target)
    if kind is RunTargetKind.JIRA_ISSUE:
        return [value]
    if kind is RunTargetKind.JIRA_EPIC:
        jql = f'parent = "{value}" ORDER BY created ASC'
    elif kind is RunTargetKind.JIRA_LABEL:
        jql = f'labels = "{value}" ORDER BY created ASC'
    else:  # pragma: no cover - a GitHub kind never reaches the Jira resolver
        raise TargetError(f"{kind.value} is not a Jira target")
    return [found.key for found in client.search_issues(jql, limit=limit)]


# --- writing -------------------------------------------------------------------


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
        actor_kind=ActorKind.AUTOMATED,
        workspace_id=workspace_id,
    )
    for node in result.nodes:
        append_event(
            session,
            event_type=EventType.NODE_CREATED,
            payload=node.model_dump(mode="json"),
            actor="system",
            actor_kind=ActorKind.AUTOMATED,
            workspace_id=workspace_id,
        )
    for edge in result.edges:
        append_event(
            session,
            event_type=EventType.EDGE_CREATED,
            payload=edge.model_dump(mode="json"),
            actor="system",
            actor_kind=ActorKind.AUTOMATED,
            workspace_id=workspace_id,
        )


def start_run(session: Session, request: RunRequest) -> uuid.UUID:
    """Record that a run was accepted, and return its id.

    Written **before** any network call, and in the caller's own transaction, so
    the id can be handed back in a 202 and the job is already visible in the
    history while it is still working. A run that dies on its first request has
    still left a trace.
    """
    parse_target(request.target_kind, request.target)
    run_id = uuid.uuid4()
    append_event(
        session,
        event_type=EventType.INGESTION_RUN_STARTED,
        payload=RunStartedPayload(
            run_id=run_id,
            feature_scope_id=request.feature_scope_id,
            product_id=request.product_id,
            connection_id=request.connection_id,
            target_kind=request.target_kind,
            target=request.target.strip(),
        ).model_dump(mode="json"),
        actor=request.actor,
        actor_kind=ActorKind.AUTOMATED,
        workspace_id=request.workspace_id,
    )
    return run_id


def _redact(message: str, credential: Credential) -> str:
    """Strip the credential out of a message before it is stored or shown.

    The connectors send credentials in headers, so an error should not contain
    one -- but "should not" is not a guarantee, and a failure message is written
    to the event log and rendered in a browser. Same discipline as the `ALTER
    ROLE` password redaction: assume the string might carry it, and make sure it
    does not.
    """
    secret = credential.token if isinstance(credential, GitHubCredential) else credential.api_token
    cleaned = message.replace(secret, "***") if secret else message
    return cleaned[:_MAX_ERROR] or "ingestion failed"


# --- the run itself ------------------------------------------------------------


def _known_nodes(session_factory: sessionmaker[Session], request: RunRequest) -> Sequence[Node]:
    """The claims other sources have already produced for this feature scope.

    Read fresh before each artifact, because an artifact ingested earlier in the
    same run is itself context the next one can contradict.
    """
    with workspace_session(session_factory, request.workspace_id) as session:
        return list(
            load_projection(
                session,
                workspace_id=request.workspace_id,
                feature_scope_id=request.feature_scope_id,
            ).nodes.values()
        )


async def execute_run(
    session_factory: sessionmaker[Session],
    *,
    run_id: uuid.UUID,
    request: RunRequest,
    credential: Credential,
) -> RunOutcome:
    """Do the work and write exactly one terminal event.

    Never raises for an ingestion failure: the failure *is* the result, recorded
    where the Sources screen can read it. It runs detached from any request, so
    an exception escaping here would be swallowed by the background-task runner
    and the run would look interrupted rather than failed -- which is a worse
    answer than the one this actually knows.
    """
    artifacts = nodes = edges = 0
    try:
        if isinstance(credential, GitHubCredential):
            artifacts, nodes, edges = await _run_github(
                session_factory, run_id=run_id, request=request, credential=credential
            )
        else:
            artifacts, nodes, edges = await _run_jira(
                session_factory, run_id=run_id, request=request, credential=credential
            )
    except (GitHubError, JiraError, ExtractionError, TargetError, ValueError) as expected:
        return _finish_failed(session_factory, run_id, request, _redact(str(expected), credential))
    except Exception as unexpected:  # noqa: BLE001 - a terminal event is the contract
        # Deliberately broad. Anything at all that gets here would otherwise
        # vanish into the background-task runner and leave the run looking
        # interrupted, when in fact its outcome is known.
        return _finish_failed(
            session_factory, run_id, request, _redact(repr(unexpected), credential)
        )

    with workspace_session(session_factory, request.workspace_id) as session:
        append_event(
            session,
            event_type=EventType.INGESTION_RUN_FINISHED,
            payload=RunFinishedPayload(run_id=run_id, nodes=nodes, edges=edges).model_dump(
                mode="json"
            ),
            actor=request.actor,
            actor_kind=ActorKind.AUTOMATED,
            workspace_id=request.workspace_id,
        )
    return RunOutcome(
        run_id=run_id, state=RunState.SUCCEEDED, artifacts=artifacts, nodes=nodes, edges=edges
    )


def _finish_failed(
    session_factory: sessionmaker[Session],
    run_id: uuid.UUID,
    request: RunRequest,
    error: str,
) -> RunOutcome:
    with workspace_session(session_factory, request.workspace_id) as session:
        append_event(
            session,
            event_type=EventType.INGESTION_RUN_FAILED,
            payload=RunFailedPayload(run_id=run_id, error=error).model_dump(mode="json"),
            actor=request.actor,
            actor_kind=ActorKind.AUTOMATED,
            workspace_id=request.workspace_id,
        )
    return RunOutcome(run_id=run_id, state=RunState.FAILED, error=error)


async def _run_github(
    session_factory: sessionmaker[Session],
    *,
    run_id: uuid.UUID,
    request: RunRequest,
    credential: GitHubCredential,
) -> tuple[int, int, int]:
    owner, repo, number = parse_target(request.target_kind, request.target)
    client = GitHubClient(credential.token)
    try:
        run, result = await extract_from_pull_request(
            client=client,
            owner=owner,
            repo=repo,
            number=int(number),
            workspace_id=request.workspace_id,
            feature_scope_id=request.feature_scope_id,
            known_nodes=_known_nodes(session_factory, request),
        )
    finally:
        client.close()
    _write(session_factory, request, run, result, run_id)
    return 1, len(result.nodes), len(result.edges)


async def _run_jira(
    session_factory: sessionmaker[Session],
    *,
    run_id: uuid.UUID,
    request: RunRequest,
    credential: JiraCredential,
) -> tuple[int, int, int]:
    client = JiraClient(
        base_url=credential.base_url, email=credential.email, api_token=credential.api_token
    )
    nodes = edges = 0
    try:
        keys = resolve_jira_keys(
            client,
            kind=request.target_kind,
            target=request.target,
            limit=min(request.limit, MAX_LIMIT),
        )
        if not keys:
            raise TargetError(f"no Jira issues matched {request.target!r}")
        for key in keys:
            run, result = await extract_from_jira_issue(
                client=client,
                key=key,
                workspace_id=request.workspace_id,
                feature_scope_id=request.feature_scope_id,
                known_nodes=_known_nodes(session_factory, request),
            )
            _write(session_factory, request, run, result, run_id)
            nodes += len(result.nodes)
            edges += len(result.edges)
        return len(keys), nodes, edges
    finally:
        client.close()


def _write(
    session_factory: sessionmaker[Session],
    request: RunRequest,
    run: IngestionRunPayload,
    result: ExtractionResult,
    run_id: uuid.UUID,
) -> None:
    """Persist one artifact's extraction, stamped with the run that pulled it.

    `product_id` and `run_id` are attached here rather than inside `extraction/`:
    which product a feature belongs to and which job pulled it are facts about
    the *request*, not about the artifact, and the agent has no business knowing
    either.
    """
    stamped = run.model_copy(update={"product_id": request.product_id, "run_id": run_id})
    with workspace_session(session_factory, request.workspace_id) as session:
        record_extraction(session, result, workspace_id=request.workspace_id, ingestion_run=stamped)
        if request.connection_id is not None:
            _touch_connection(session, request)


def _touch_connection(session: Session, request: RunRequest) -> None:
    """Record that the credential was used. Imported lazily so `pipeline` does not
    drag the connection table into the CLI's import graph, which has no use for
    it."""
    from atlas.storage.connections import get_connection, mark_used

    assert request.connection_id is not None
    connection = get_connection(
        session, workspace_id=request.workspace_id, connection_id=request.connection_id
    )
    if connection is not None:
        mark_used(session, connection, at=datetime.now(UTC))


def run_ingestion(
    session_factory: sessionmaker[Session],
    *,
    request: RunRequest,
    credential: Credential,
) -> RunOutcome:
    """Start and complete a run synchronously -- what the CLI calls.

    The API does not use this: it calls `start_run` inside the request (so a 202
    can carry the id) and schedules `execute_run` behind it. Both paths write the
    same events in the same order, which is the property that makes having one
    module worth it.
    """
    with workspace_session(session_factory, request.workspace_id) as session:
        run_id = start_run(session, request)
    return asyncio.run(
        execute_run(session_factory, run_id=run_id, request=request, credential=credential)
    )
