"""Every endpoint the confirmation UI needs, and nothing else.

Read the route bodies as the specification of the thinness rule
(`docs/decisions/2026-08-11-api-frontend-module-boundary.md` §2): each write is
*authenticate -> load projection -> call one `storage/confirmations.py` function
-> return the resulting node*. There is no branch on domain state anywhere in
this file; if one appears, the logic belongs in `storage/`.

The request/response models declared here are envelopes and input bodies only.
`Node`, `Edge` and `FeatureScope` are returned **as themselves** -- FastAPI
serializes the domain models directly, so there is no wire-level mirror that can
drift from the validation gate. That is the same reason there is no
`api/schemas.py`: the models that matter already exist and are already validated.

Slice 2B added the two endpoints slice 1B deliberately refused -- connecting a
source and starting a run -- and the reasoning that refused them is not being
waved away, it is being solved. A run returns **202 immediately** and does its
work in-process via `BackgroundTasks`: no broker, no worker, no new deployable,
none of the task-queue pressure that was the objection (an explicit CLAUDE.md
Non-Goal). The cost -- a process that dies mid-run -- is made visible by the
projection rather than hidden (`storage/projections.py::INTERRUPTED_AFTER`).

The thinness rule holds for both: the ingest endpoint's one function is
`pipeline.start_run`, and the connect endpoint's is
`storage/connections.py::create_connection`. **No secret appears in any response
model in this file**, and `ConnectionView` has no field one could occupy.

Still absent: grouping and ordering endpoints -- node ordering and the four
queue sections are presentation decisions already fixed in
`docs/ux/confirmation-flow-spec-v1.md` §3.2-3.3, and putting them here would move
a UX decision into the backend.

**Counting is no longer in that list, deliberately.** `FeatureScopeRow` carries
`counts`, and the line this crosses is narrower than it looks: *how many claims
are still unreviewed* is a fact about stored state, the same kind of fact as a
node's status, whereas *how to group and order them* is a choice about a screen.
What forced it is that three surfaces need the identical number -- the feature
list, the Conflicts entry, the product dashboard -- and the alternative was
shipping every claim and excerpt of every feature to the browser so it could
count them, with the definition of "unreviewed" copied into three components.
The rule that still holds: the API returns the number, and never decides how it
is grouped, sorted or drawn.
"""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import UTC, datetime

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from atlas.api.deps import (
    SESSION_COOKIE,
    SESSION_MAX_AGE_SECONDS,
    Principal,
    PrincipalDep,
    SessionDep,
    SessionFactoryDep,
    SettingsDep,
    WriterDep,
    issue_session,
    verify_passphrase,
)
from atlas.models.schema import (
    AtlasModel,
    DescriptionStr,
    Edge,
    IngestionRunPayload,
    Node,
    NodeType,
    NonBlankStr,
    Role,
    RunState,
    RunTargetKind,
    SourceType,
)
from atlas.pipeline import (
    DEFAULT_LIMIT,
    MAX_LIMIT,
    Credential,
    GitHubCredential,
    JiraCredential,
    RunRequest,
    TargetError,
    artifact_external_id,
    check_access,
    execute_run,
    start_run,
)
from atlas.storage import confirmations, connections, products
from atlas.storage.connections import ConnectionView, SecretError
from atlas.storage.projections import FeatureScope, Product, Run, ScopeCounts, load_projection
from atlas.storage.rbac import find_membership, workspace_session

router = APIRouter()


# --- request/response envelopes ------------------------------------------------


class SignInRequest(AtlasModel):
    """`name` becomes the `actor` on every Event this person goes on to write --
    it is the audit record, not a display preference."""

    passphrase: NonBlankStr
    name: NonBlankStr


class SignInResponse(AtlasModel):
    actor: str
    #: What the UI hides write affordances on -- a viewer should not be shown
    #: confirm buttons that will only fail.
    role: Role


class EditNodeRequest(AtlasModel):
    #: `NonBlankStr` is the domain's own rule, reused rather than restated -- so a
    #: whitespace-only claim is a 422 at the wire instead of a 500 from the gate
    #: behind it.
    content: NonBlankStr


class AddNodeRequest(AtlasModel):
    type: NodeType
    content: NonBlankStr


class CreateProductRequest(AtlasModel):
    name: NonBlankStr


class DescribeRequest(AtlasModel):
    """What a product or a feature is, in the PM's own words (slice 3).

    `DescriptionStr` rather than `NonBlankStr`, and that is the whole difference:
    an empty description is not a malformed one, it is how a wrong description is
    removed. The length bound is the domain's own, reused rather than restated at
    the wire.
    """

    description: DescriptionStr


class ConnectSourceRequest(AtlasModel):
    """Connect one source to one product.

    `secret` is the *only* field in this file that ever holds a credential, it
    only ever travels inbound, and nothing echoes it back -- the response is a
    `ConnectionView`, which has no field it could occupy.

    `email` is required for Jira and meaningless for GitHub: Jira Cloud
    authenticates email + API token, GitHub authenticates the token alone. The
    endpoint validates that pairing rather than accepting a half-filled
    connection that would fail on its first run.
    """

    source_type: SourceType
    host: NonBlankStr
    scope: NonBlankStr
    secret: NonBlankStr
    email: str | None = None


class ConnectionCreated(AtlasModel):
    """The stored connection, plus what its credential turned out to reach.

    The access summary is the trust moment: a PM sees "Private repository · 12
    open issues" *before* Atlas is trusted with anything. It is shown and
    discarded -- never stored, because it is a fact about right now, not
    provenance.
    """

    connection: ConnectionView
    access_label: str
    access_detail: str


class StartRunRequest(AtlasModel):
    """Pull one target into a feature -- a new one, or one that already exists.

    Naming an existing `feature_scope_id` is what makes a feature cross-source:
    the run is handed the claims the other source already produced, so a
    contradiction between them becomes a `conflicts_with` edge instead of two
    unaware halves.
    """

    connection_id: uuid.UUID
    target_kind: RunTargetKind
    target: NonBlankStr
    feature_scope_id: uuid.UUID | None = None
    limit: int = DEFAULT_LIMIT


class RunView(AtlasModel):
    """One run, as the Sources screen reads it.

    `state` is resolved here, at read time, because one of its four values is a
    function of *now* -- a start with no terminal event older than
    `INTERRUPTED_AFTER` is interrupted, not running.
    """

    id: uuid.UUID
    feature_scope_id: uuid.UUID
    product_id: uuid.UUID | None
    connection_id: uuid.UUID | None
    target_kind: RunTargetKind
    target: str
    state: RunState
    started_at: datetime
    started_by: str
    finished_at: datetime | None = None
    error: str | None = None
    artifacts: int = 0
    nodes: int = 0
    edges: int = 0

    @classmethod
    def of(cls, run: Run) -> RunView:
        return cls(
            id=run.id,
            feature_scope_id=run.feature_scope_id,
            product_id=run.product_id,
            connection_id=run.connection_id,
            target_kind=run.target_kind,
            target=run.target,
            state=run.state(now=datetime.now(UTC)),
            started_at=run.started_at,
            started_by=run.started_by,
            finished_at=run.finished_at,
            error=run.error,
            artifacts=run.artifacts,
            nodes=run.nodes,
            edges=run.edges,
        )


class FeatureScopeRow(AtlasModel):
    """One row of a feature list: the scope's identity plus how much of it is
    still work.

    A separate envelope from the `FeatureScope` projection dataclass because the
    two answer different questions -- that one is identity, this one is identity
    *and* state as of now. Composed rather than flattened so the counts stay
    recognisably derived, and so adding a fourth number later touches one place.
    """

    id: uuid.UUID
    title: str
    runs: list[IngestionRunPayload]
    product_id: uuid.UUID | None
    counts: ScopeCounts
    #: What the feature is for, or `None` until someone says. Carried on the row
    #: so a product's feature list can show it without fetching every feature's
    #: full detail to read one sentence.
    description: str | None


class FeatureScopeDetail(AtlasModel):
    """One feature scope's projected state, as the review page reads it.

    `feature_scope` is nullable because a scope ingested before slice 1A' has
    nodes but no `ingestion_run` event, and so no title. The UI renders that as
    an unnamed scope rather than being handed a fabricated one.
    """

    feature_scope: FeatureScope | None
    nodes: list[Node]
    edges: list[Edge]


# --- helpers -------------------------------------------------------------------


def _require_node(session: Session, principal: Principal, node_id: uuid.UUID) -> Node:
    """Load the node from the caller's own workspace, or 404.

    The projection is loaded for `principal.workspace_id`, so a node belonging to
    another workspace is not "forbidden" -- it is invisible, which is the
    property worth having.
    """
    projection = load_projection(session, workspace_id=principal.workspace_id)
    node = projection.nodes.get(node_id)
    if node is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no node {node_id}")
    return node


def _require_feature_scope(session: Session, principal: Principal, scope_id: uuid.UUID) -> None:
    """404 unless the caller's workspace actually has this scope.

    Existence, not domain logic: without it a typo'd id would silently create an
    orphan scope holding one hand-typed node and nothing else. A scope counts as
    real if it has an identity *or* nodes -- one ingested before slice 1A' has
    only the latter.
    """
    projection = load_projection(
        session, workspace_id=principal.workspace_id, feature_scope_id=scope_id
    )
    if not projection.feature_scopes and not projection.nodes:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no feature scope {scope_id}")


def _require_product(session: Session, principal: Principal, product_id: uuid.UUID) -> Product:
    """The product from the caller's own workspace, or 404.

    Existence, not domain logic -- the same shape as `_require_feature_scope`.
    A product is a projection, so there is no row to constrain against, which
    makes this check the thing standing between a typo'd id and a connection
    filed under a product that does not exist.
    """
    projection = load_projection(session, workspace_id=principal.workspace_id)
    product = projection.products.get(product_id)
    if product is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no product {product_id}")
    return product


def _require_named_feature_scope(
    session: Session, principal: Principal, scope_id: uuid.UUID
) -> FeatureScope:
    """The scope's projected *identity*, or 404 -- stricter than
    `_require_feature_scope`, deliberately.

    A scope with nodes but no `ingestion_run` (the pre-1A' case) has no identity
    to hang a description on, and the replay drops a description naming one
    rather than fabricating a feature for it (`storage/projections.py`). Refusing
    at the wire is what keeps the log free of events that could never be read
    back.
    """
    projection = load_projection(session, workspace_id=principal.workspace_id)
    scope = projection.feature_scopes.get(scope_id)
    if scope is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no feature scope {scope_id}")
    return scope


# --- session ------------------------------------------------------------------


@router.post("/session", response_model=SignInResponse)
def sign_in(
    body: SignInRequest,
    request: Request,
    response: Response,
    session: SessionDep,
    settings: SettingsDep,
) -> SignInResponse:
    """Exchange the shared passphrase plus a name for a signed session cookie.

    Membership is checked here as well as on every later request: failing at the
    door with "you are not a member" beats issuing a session that 403s on
    everything the person then tries to do.
    """
    if not verify_passphrase(body.passphrase, settings):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "incorrect passphrase")
    membership = find_membership(session, body.name)
    if membership is None:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, f"{body.name} is not a member of any workspace"
        )
    response.set_cookie(
        SESSION_COOKIE,
        issue_session(body.name, settings),
        max_age=SESSION_MAX_AGE_SECONDS,
        httponly=True,
        samesite="lax",
        # True whenever the app is actually served over TLS, so local http dev
        # works without a config flag and production never ships a cookie the
        # network can read.
        secure=request.url.scheme == "https",
    )
    return SignInResponse(actor=body.name, role=membership.role)


@router.delete("/session", status_code=status.HTTP_204_NO_CONTENT)
def sign_out(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, httponly=True, samesite="lax")


@router.get("/session", response_model=SignInResponse)
def current_session(principal: PrincipalDep) -> SignInResponse:
    """Who the browser is currently signed in as -- what the SPA asks on load so
    a returning PM isn't sent back through a login form they already passed."""
    return SignInResponse(actor=principal.actor, role=principal.role)


# --- read ---------------------------------------------------------------------


@router.get("/products", response_model=list[Product])
def list_products(
    session: SessionDep,
    principal: PrincipalDep,
) -> list[Product]:
    """Every product in the caller's workspace, in creation order.

    Feature scopes carry their own `product_id`, so grouping the rail happens on
    the client -- consistent with node ordering and the progress meter, which are
    presentation decisions the API deliberately does not make.
    """
    projection = load_projection(session, workspace_id=principal.workspace_id)
    return list(projection.products.values())


@router.post("/products", response_model=Product, status_code=status.HTTP_201_CREATED)
def create_product(
    body: CreateProductRequest,
    session: SessionDep,
    principal: WriterDep,
) -> Product:
    """Open a new product. The id is minted in `storage/`, never taken from the
    request -- same reason `add_node` builds its Node from fields."""
    product_id, _ = products.create_product(
        session,
        workspace_id=principal.workspace_id,
        name=body.name,
        actor=principal.actor,
        actor_kind=principal.actor_kind,
    )
    return Product(id=product_id, name=body.name)


@router.put("/products/{product_id}/description", response_model=Product)
def describe_product(
    product_id: uuid.UUID,
    body: DescribeRequest,
    session: SessionDep,
    principal: WriterDep,
) -> Product:
    """Say what this product is. `PUT` because the body states the field's whole
    value -- sending it twice leaves the same product, even though each send
    appends its own audit event.

    Authored orientation, not an extracted claim: no provenance, no confirmation
    loop, and nothing here can reach a spec export
    (`docs/decisions/2026-08-19-product-orientation-rerun-safety-and-demo-data.md`
    decision 4).
    """
    product = _require_product(session, principal, product_id)
    products.describe_product(
        session,
        workspace_id=principal.workspace_id,
        product_id=product_id,
        description=body.description,
        actor=principal.actor,
        actor_kind=principal.actor_kind,
    )
    return replace(product, description=body.description or None)


@router.get("/feature-scopes", response_model=list[FeatureScopeRow])
def list_feature_scopes(
    session: SessionDep,
    principal: PrincipalDep,
) -> list[FeatureScopeRow]:
    """The left rail. Ordered by ingestion, oldest first -- the log's own order.

    Each row carries its own work-left counts. The alternative -- letting the
    client fetch every scope's full detail and count nodes itself -- means
    shipping every claim and excerpt of every feature to the browser to render
    a number in a sidebar, and it puts the definition of "unreviewed" in the
    frontend where three screens would each get their own copy of it.
    """
    projection = load_projection(session, workspace_id=principal.workspace_id)
    return [
        FeatureScopeRow(
            id=scope.id,
            title=scope.title,
            runs=list(scope.runs),
            product_id=scope.product_id,
            counts=projection.counts_for(scope.id),
            description=scope.description,
        )
        for scope in projection.feature_scopes.values()
    ]


@router.get("/feature-scopes/{feature_scope_id}", response_model=FeatureScopeDetail)
def get_feature_scope(
    feature_scope_id: uuid.UUID,
    session: SessionDep,
    principal: PrincipalDep,
) -> FeatureScopeDetail:
    """The review page: every node and edge for one feature, flat and ungrouped."""
    projection = load_projection(
        session, workspace_id=principal.workspace_id, feature_scope_id=feature_scope_id
    )
    if not projection.feature_scopes and not projection.nodes:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no feature scope {feature_scope_id}")
    return FeatureScopeDetail(
        feature_scope=projection.feature_scopes.get(feature_scope_id),
        nodes=list(projection.nodes.values()),
        edges=list(projection.edges.values()),
    )


@router.put("/feature-scopes/{feature_scope_id}/description", response_model=FeatureScope)
def describe_feature_scope(
    feature_scope_id: uuid.UUID,
    body: DescribeRequest,
    session: SessionDep,
    principal: WriterDep,
) -> FeatureScope:
    """Say what this feature is *for*.

    Not a rename. The title stays the one the artifact that opened the scope
    gave it -- first-run-wins, per `storage/projections.py` -- so a reviewer
    keeps the name they recognise and gains the sentence saying why it exists.
    """
    scope = _require_named_feature_scope(session, principal, feature_scope_id)
    products.describe_feature_scope(
        session,
        workspace_id=principal.workspace_id,
        feature_scope_id=feature_scope_id,
        description=body.description,
        actor=principal.actor,
        actor_kind=principal.actor_kind,
    )
    return replace(scope, description=body.description or None)


# --- sources (slice 2B) --------------------------------------------------------


def _normalize_host(host: str) -> str:
    """A bare hostname, however it was typed.

    People paste `https://acme.atlassian.net/` because that is what the address
    bar shows. Normalizing **once, here, before the value is stored** is what
    keeps the connect check and the later run agreeing: an earlier cut stripped
    the scheme only when building the credential, so the check passed against
    `acme.atlassian.net` while the row kept `https://acme.atlassian.net` — and
    the next run built `https://https://acme.atlassian.net`. Found live, because
    a stored value and a derived one only disagree once there is a stored one.
    """
    return host.strip().removeprefix("https://").removeprefix("http://").rstrip("/")


def _credential_from(body: ConnectSourceRequest, host: str) -> Credential:
    """Turn a connect request into the credential its connector expects.

    GitHub authenticates a token; Jira authenticates email + token. Refusing the
    mismatched pairing here means a half-filled connection is a 422 at the door
    rather than a run that fails an hour later with an auth error.
    """
    if body.source_type is SourceType.GITHUB_PR:
        return GitHubCredential(token=body.secret)
    if not (body.email or "").strip():
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Jira needs the email address the API token belongs to",
        )
    try:
        return JiraCredential(
            base_url=f"https://{host}",
            email=body.email or "",
            api_token=body.secret,
        )
    except TargetError as unsupported:
        # An SSRF control, surfaced as a form error: the host becomes the base
        # URL of an outbound request carrying this credential.
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(unsupported)) from None


@router.get("/products/{product_id}/connections", response_model=list[ConnectionView])
def list_connections(
    product_id: uuid.UUID,
    session: SessionDep,
    principal: PrincipalDep,
) -> list[ConnectionView]:
    """The Sources screen. Returns `ConnectionView`, which cannot carry a secret."""
    return [
        ConnectionView.of(connection)
        for connection in connections.list_connections(
            session, workspace_id=principal.workspace_id, product_id=product_id
        )
    ]


@router.post(
    "/products/{product_id}/connections",
    response_model=ConnectionCreated,
    status_code=status.HTTP_201_CREATED,
)
def connect_source(
    product_id: uuid.UUID,
    body: ConnectSourceRequest,
    session: SessionDep,
    principal: WriterDep,
    settings: SettingsDep,
) -> ConnectionCreated:
    """Verify a credential against the scope it claims, then store it encrypted.

    The verification is not decoration. A credential that cannot see its own
    scope is rejected *here*, where the PM is still looking at the form and can
    fix it -- rather than at the first run, where the failure reads as "Atlas is
    broken". It also produces the access summary the flow spec asks for, so
    least privilege is demonstrated rather than asserted.

    One round trip, not two: a "preview then save" pair would mean the browser
    holding the token across two requests, which is worse than checking it once
    on the way in.
    """
    _require_product(session, principal, product_id)
    host = _normalize_host(body.host)
    if not host:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "host must not be blank")
    credential = _credential_from(body, host)
    try:
        access = check_access(credential, scope=body.scope)
    except TargetError as bad:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(bad)) from None
    except Exception:
        # Deliberately not `str(exc)`: a connector error can quote the request it
        # made, and that request carried the credential.
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"That credential cannot read {body.scope} on {host}. "
            "Check the token, the scope, and that the account has access.",
        ) from None

    connection = connections.create_connection(
        session,
        workspace_id=principal.workspace_id,
        product_id=product_id,
        source_type=body.source_type,
        account=(body.email or "").strip() or "token",
        host=host,
        scope=body.scope,
        secret=body.secret,
        actor=principal.actor,
        actor_kind=principal.actor_kind,
        key=settings.secret_key,
    )
    return ConnectionCreated(
        connection=ConnectionView.of(connection),
        access_label=access.label,
        access_detail=access.detail,
    )


@router.delete("/connections/{connection_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_connection(
    connection_id: uuid.UUID,
    session: SessionDep,
    principal: WriterDep,
) -> None:
    """Revocation is a real delete -- the ciphertext stops existing. The event
    log keeps the record that it happened, which is the part that should."""
    if not connections.revoke_connection(
        session,
        workspace_id=principal.workspace_id,
        connection_id=connection_id,
        actor=principal.actor,
        actor_kind=principal.actor_kind,
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no connection {connection_id}")


# --- runs (slice 2B) -----------------------------------------------------------


@router.get("/products/{product_id}/runs", response_model=list[RunView])
def list_runs(
    product_id: uuid.UUID,
    session: SessionDep,
    principal: PrincipalDep,
) -> list[RunView]:
    """Run history for one product, oldest first -- the log's own order."""
    projection = load_projection(session, workspace_id=principal.workspace_id)
    return [RunView.of(run) for run in projection.for_product(product_id).runs.values()]


@router.get("/runs/{run_id}", response_model=RunView)
def get_run(
    run_id: uuid.UUID,
    session: SessionDep,
    principal: PrincipalDep,
) -> RunView:
    """What the client polls after a 202. State is derived, never stored."""
    projection = load_projection(session, workspace_id=principal.workspace_id)
    run = projection.runs.get(run_id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no run {run_id}")
    return RunView.of(run)


@router.post(
    "/products/{product_id}/runs",
    response_model=RunView,
    status_code=status.HTTP_202_ACCEPTED,
)
def start_ingestion(
    product_id: uuid.UUID,
    body: StartRunRequest,
    background: BackgroundTasks,
    session: SessionDep,
    principal: WriterDep,
    settings: SettingsDep,
    session_factory: SessionFactoryDep,
) -> RunView:
    """Accept an ingestion job and return before it finishes.

    202, not 200: the run is *accepted*, and the id in the response is what the
    client polls. The `ingestion_run_started` event is written inside this
    request, so the job is already in the history the moment the response goes
    out -- and a run that dies on its first network call has still left a trace.

    The credential is decrypted here, at the composition root, and handed to
    `pipeline` as an argument. Nothing in `pipeline/` or `ingestion/` knows where
    it came from, and the API process holds no ambient source credential of its
    own.
    """
    _require_product(session, principal, product_id)
    connection = connections.get_connection(
        session, workspace_id=principal.workspace_id, connection_id=body.connection_id
    )
    if connection is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no connection {body.connection_id}")

    try:
        secret = connections.unseal(connection.secret_ciphertext, settings.secret_key)
    except SecretError as broken:
        raise HTTPException(status.HTTP_409_CONFLICT, str(broken)) from None
    try:
        credential: Credential = (
            GitHubCredential(token=secret)
            if connection.source_type is SourceType.GITHUB_PR
            else JiraCredential(
                base_url=f"https://{connection.host}", email=connection.account, api_token=secret
            )
        )
    except TargetError as unsupported:
        # A row written before the host allowlist existed, or edited underneath
        # us. Refuse rather than send the credential somewhere unvetted.
        raise HTTPException(status.HTTP_409_CONFLICT, str(unsupported)) from None

    # Refuse a re-run of an artifact already in this workspace. Re-ingesting
    # duplicates every claim it produced, and the copies are identical except for
    # their ids, so a reviewer could confirm one and reject the other. A hard
    # block rather than a warning: the legitimate case (a genuinely updated PR) is
    # served by ingesting into a *new* scope, while the illegitimate one silently
    # doubles a reviewer's queue. Removed, not loosened, when Phase 3's
    # incremental sync makes ingestion actually idempotent
    # (`docs/decisions/2026-08-19-product-orientation-rerun-safety-and-demo-data.md`).
    #
    # An epic or a label yields no id here -- it names many artifacts, none of
    # them individually -- so those re-runs are not blocked. Known gap, stated in
    # `artifact_external_id`.
    try:
        already = artifact_external_id(body.target_kind, body.target)
    except TargetError as bad:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(bad)) from None
    if already is not None:
        source = (
            SourceType.GITHUB_PR
            if body.target_kind is RunTargetKind.GITHUB_PR
            else SourceType.JIRA_TICKET
        )
        held = load_projection(session, workspace_id=principal.workspace_id).scope_holding(
            source, already
        )
        if held is not None:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"{already} is already ingested into '{held.title}'. Re-running it would "
                f"duplicate every claim it produced; ingest into a new feature instead.",
            )

    request = RunRequest(
        workspace_id=principal.workspace_id,
        actor=principal.actor,
        target_kind=body.target_kind,
        target=body.target,
        feature_scope_id=body.feature_scope_id or uuid.uuid4(),
        product_id=product_id,
        connection_id=connection.id,
        limit=max(1, min(body.limit, MAX_LIMIT)),
    )
    # Opened here rather than reusing the request's session, and the reason is a
    # defect found only by running this live: FastAPI holds a `yield`
    # dependency's exit stack open until **after** background tasks finish, so
    # the request session's commit landed at the *end* of the run. The start
    # event was therefore invisible for the run's whole duration and
    # `GET /runs/{id}` -- the endpoint the UI polls -- returned 404 until the
    # moment it returned "succeeded". Every test passed: SQLite with a
    # `StaticPool` shares one connection, so uncommitted rows are visible to the
    # next read and the isolation this depends on does not exist there.
    #
    # Its own transaction makes the id durable before the 202 is written, which
    # is the property the whole poll-a-202 design rests on.
    try:
        with workspace_session(session_factory, principal.workspace_id) as own:
            run_id = start_run(own, request)
    except TargetError as bad:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(bad)) from None

    background.add_task(
        execute_run,
        session_factory,
        run_id=run_id,
        request=request,
        credential=credential,
    )
    return RunView(
        id=run_id,
        feature_scope_id=request.feature_scope_id,
        product_id=product_id,
        connection_id=connection.id,
        target_kind=request.target_kind,
        target=request.target,
        state=RunState.RUNNING,
        started_at=datetime.now(UTC),
        started_by=principal.actor,
    )


# --- the four confirmation actions (TRD §6) ------------------------------------


@router.post("/nodes/{node_id}/confirm", response_model=Node)
def confirm_node(
    node_id: uuid.UUID,
    session: SessionDep,
    principal: WriterDep,
) -> Node:
    node = _require_node(session, principal, node_id)
    confirmations.confirm_node(
        session, node=node, actor=principal.actor, actor_kind=principal.actor_kind
    )
    return _require_node(session, principal, node_id)


@router.post("/nodes/{node_id}/reject", response_model=Node)
def reject_node(
    node_id: uuid.UUID,
    session: SessionDep,
    principal: WriterDep,
) -> Node:
    node = _require_node(session, principal, node_id)
    confirmations.reject_node(
        session, node=node, actor=principal.actor, actor_kind=principal.actor_kind
    )
    return _require_node(session, principal, node_id)


@router.post("/nodes/{node_id}/edit", response_model=Node)
def edit_node(
    node_id: uuid.UUID,
    body: EditNodeRequest,
    session: SessionDep,
    principal: WriterDep,
) -> Node:
    node = _require_node(session, principal, node_id)
    confirmations.edit_node(
        session,
        node=node,
        content=body.content,
        actor=principal.actor,
        actor_kind=principal.actor_kind,
    )
    return _require_node(session, principal, node_id)


@router.post(
    "/feature-scopes/{feature_scope_id}/nodes",
    response_model=Node,
    status_code=status.HTTP_201_CREATED,
)
def add_node(
    feature_scope_id: uuid.UUID,
    body: AddNodeRequest,
    session: SessionDep,
    principal: WriterDep,
) -> Node:
    """A claim the PM types in themselves (PRD R10).

    `workspace_id` and `actor` come from the `Principal`, never the body --
    `add_node` takes fields rather than a Node so that is unreachable rather than
    merely unwritten (`docs/decisions/2026-08-03-manual-node-provenance.md`).
    """
    _require_feature_scope(session, principal, feature_scope_id)
    event = confirmations.add_node(
        session,
        node_type=body.type,
        content=body.content,
        actor=principal.actor,
        actor_kind=principal.actor_kind,
        workspace_id=principal.workspace_id,
        feature_scope_id=feature_scope_id,
    )
    return Node.model_validate(event.payload)
