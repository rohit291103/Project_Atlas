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

Deliberately absent: any ingest or "connect a source" endpoint. Ingestion stays
CLI-triggered in slice 1B, which is what keeps this API synchronous and free of
task-queue pressure (an explicit CLAUDE.md Non-Goal). Also absent: grouping,
counting and progress endpoints -- node ordering and the progress meter are
presentation decisions already fixed in `docs/ux/confirmation-flow-spec-v1.md`
§3.2-3.3, and putting them here would move a UX decision into the backend.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from atlas.api.deps import (
    SESSION_COOKIE,
    SESSION_MAX_AGE_SECONDS,
    Principal,
    PrincipalDep,
    SessionDep,
    SettingsDep,
    WriterDep,
    issue_session,
    verify_passphrase,
)
from atlas.models.schema import AtlasModel, Edge, Node, NodeType, NonBlankStr, Role
from atlas.storage import confirmations
from atlas.storage.projections import FeatureScope, load_projection
from atlas.storage.rbac import find_membership

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


@router.get("/feature-scopes", response_model=list[FeatureScope])
def list_feature_scopes(
    session: SessionDep,
    principal: PrincipalDep,
) -> list[FeatureScope]:
    """The left rail. Ordered by ingestion, oldest first -- the log's own order."""
    projection = load_projection(session, workspace_id=principal.workspace_id)
    return list(projection.feature_scopes.values())


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


# --- the four confirmation actions (TRD §6) ------------------------------------


@router.post("/nodes/{node_id}/confirm", response_model=Node)
def confirm_node(
    node_id: uuid.UUID,
    session: SessionDep,
    principal: WriterDep,
) -> Node:
    node = _require_node(session, principal, node_id)
    confirmations.confirm_node(session, node=node, actor=principal.actor)
    return _require_node(session, principal, node_id)


@router.post("/nodes/{node_id}/reject", response_model=Node)
def reject_node(
    node_id: uuid.UUID,
    session: SessionDep,
    principal: WriterDep,
) -> Node:
    node = _require_node(session, principal, node_id)
    confirmations.reject_node(session, node=node, actor=principal.actor)
    return _require_node(session, principal, node_id)


@router.post("/nodes/{node_id}/edit", response_model=Node)
def edit_node(
    node_id: uuid.UUID,
    body: EditNodeRequest,
    session: SessionDep,
    principal: WriterDep,
) -> Node:
    node = _require_node(session, principal, node_id)
    confirmations.edit_node(session, node=node, content=body.content, actor=principal.actor)
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
        workspace_id=principal.workspace_id,
        feature_scope_id=feature_scope_id,
    )
    return Node.model_validate(event.payload)
