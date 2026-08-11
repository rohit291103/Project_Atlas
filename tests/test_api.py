"""Tests for the `api/` transport boundary (Phase 1 slice 1B).

The emphasis is the seam, not the plumbing. Over HTTP, `workspace_id` and
`actor` are attacker-controlled unless something translates a session into them
(`docs/decisions/2026-08-11-api-frontend-module-boundary.md` §4), so what is
asserted hardest here is: no endpoint works unauthenticated, no request body can
choose who it is acting as, and every write lands as an Event carrying the
cookie's actor.

Everything runs against in-memory SQLite with the `event_log.sequence` shim from
conftest.py -- no live Supabase, no secrets, no network.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from atlas.api.app import create_app
from atlas.api.deps import SESSION_COOKIE, get_api_settings, get_session
from atlas.config import ApiSettings
from atlas.extraction.agent import build_result
from atlas.models.schema import (
    CreatedBy,
    EventType,
    IngestionRunPayload,
    NodeStatus,
    Role,
    SourceType,
)
from atlas.storage.db import Base, get_sessionmaker, session_scope
from atlas.storage.tables import EventLog, Workspace, WorkspaceMember

WORKSPACE_ID = uuid.UUID(int=0)  # DEFAULT_WORKSPACE_ID -- what `Principal` stamps
FEATURE_SCOPE_ID = uuid.uuid4()
PASSPHRASE = "open-sesame"
ACTOR = "Priya (PM)"
VIEWER = "Sam (observer)"


def _settings() -> ApiSettings:
    return ApiSettings(
        supabase_db_url="sqlite://",
        app_passphrase=PASSPHRASE,
        session_secret="test-secret-not-a-real-one",
    )


@pytest.fixture
def session_factory() -> sessionmaker[Session]:
    """In-memory SQLite shared across threads.

    `TestClient` runs the ASGI app on a worker thread, and the default SQLite
    pooling would hand that thread its own connection -- i.e. its own empty
    database. `StaticPool` pins every session to the one connection holding the
    schema. Production is Postgres, where none of this applies.
    """
    engine: Engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    return get_sessionmaker(engine)


@pytest.fixture
def seeded(session_factory: sessionmaker[Session]) -> sessionmaker[Session]:
    """One ingested feature scope: a titled scope, two nodes, one edge."""
    from atlas.cli import record_extraction

    result = build_result(
        {
            "nodes": [
                {
                    "ref": "n1",
                    "type": "requirement",
                    "content": "The gateway must rate-limit per client IP.",
                    "confidence": "high",
                    "source_refs": [
                        {
                            "source_type": "github_pr",
                            "external_id": "42",
                            "url": "https://github.com/acme/gateway/pull/42",
                            "excerpt": "adds a per-IP token-bucket limiter",
                        }
                    ],
                },
                {
                    "ref": "n2",
                    "type": "problem",
                    "content": "Gateway stalls under burst traffic.",
                    "confidence": "medium",
                    "source_refs": [
                        {
                            "source_type": "github_issue",
                            "external_id": "17",
                            "url": "https://github.com/acme/gateway/issues/17",
                            "excerpt": "the gateway's event loop stalls",
                        }
                    ],
                },
            ],
            "edges": [
                {
                    "from_ref": "n1",
                    "to_ref": "n2",
                    "relation_type": "derives_from",
                    "confidence": "high",
                }
            ],
        },
        workspace_id=WORKSPACE_ID,
        feature_scope_id=FEATURE_SCOPE_ID,
    )
    run = IngestionRunPayload(
        feature_scope_id=FEATURE_SCOPE_ID,
        title="Rate-limit the gateway per client IP",
        source_type=SourceType.GITHUB_PR,
        external_id="acme/gateway#42",
        url="https://github.com/acme/gateway/pull/42",
    )
    with session_scope(session_factory) as session:
        # A provisioned workspace and one member: as of slice 1D the API resolves
        # both from the database, so a seed without them is a seed nobody can read.
        session.add(Workspace(id=WORKSPACE_ID, name="Acme"))
        session.add(WorkspaceMember(workspace_id=WORKSPACE_ID, actor=ACTOR, role=Role.EDITOR))
        session.add(WorkspaceMember(workspace_id=WORKSPACE_ID, actor=VIEWER, role=Role.VIEWER))
        record_extraction(session, result, workspace_id=WORKSPACE_ID, ingestion_run=run)
    return session_factory


@pytest.fixture
def client(seeded: sessionmaker[Session]) -> Iterator[TestClient]:
    """An unauthenticated client wired to the seeded in-memory database."""
    app = create_app()

    def _test_session() -> Iterator[Session]:
        with session_scope(seeded) as session:
            yield session

    app.dependency_overrides[get_session] = _test_session
    app.dependency_overrides[get_api_settings] = _settings
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def signed_in(client: TestClient) -> TestClient:
    response = client.post("/session", json={"passphrase": PASSPHRASE, "name": ACTOR})
    assert response.status_code == 200
    return client


def _nodes(client: TestClient) -> list[dict[str, object]]:
    body = client.get(f"/feature-scopes/{FEATURE_SCOPE_ID}").json()
    return sorted(body["nodes"], key=lambda node: str(node["type"]))


def _events(session_factory: sessionmaker[Session], event_type: EventType) -> list[EventLog]:
    with session_scope(session_factory) as session:
        return [row for row in session.query(EventLog).all() if row.event_type is event_type]


# --- authentication ------------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/session"),
        ("get", "/feature-scopes"),
        ("get", f"/feature-scopes/{FEATURE_SCOPE_ID}"),
        ("post", f"/nodes/{uuid.uuid4()}/confirm"),
        ("post", f"/nodes/{uuid.uuid4()}/reject"),
        ("post", f"/nodes/{uuid.uuid4()}/edit"),
        ("post", f"/feature-scopes/{FEATURE_SCOPE_ID}/nodes"),
    ],
)
def test_every_endpoint_requires_a_session(client: TestClient, method: str, path: str) -> None:
    response = client.request(method.upper(), path, json={"content": "x", "type": "goal"})

    assert response.status_code == 401


def test_sign_in_rejects_the_wrong_passphrase(client: TestClient) -> None:
    response = client.post("/session", json={"passphrase": "guess", "name": ACTOR})

    assert response.status_code == 401
    assert SESSION_COOKIE not in client.cookies


def test_sign_in_issues_a_session_naming_the_actor(client: TestClient) -> None:
    response = client.post("/session", json={"passphrase": PASSPHRASE, "name": ACTOR})

    assert response.status_code == 200
    assert response.json() == {"actor": ACTOR, "role": Role.EDITOR.value}
    assert client.get("/session").json()["actor"] == ACTOR


def test_sign_out_ends_the_session(signed_in: TestClient) -> None:
    assert signed_in.delete("/session").status_code == 204

    assert signed_in.get("/feature-scopes").status_code == 401


def test_a_tampered_cookie_is_not_a_session(client: TestClient) -> None:
    """The cookie is signed precisely so its `actor` cannot be chosen by whoever
    holds it -- an unsigned or edited value must not authenticate."""
    client.cookies.set(SESSION_COOKIE, "eyJhY3RvciI6ICJhdHRhY2tlciJ9.forged")

    assert client.get("/feature-scopes").status_code == 401


# --- read ----------------------------------------------------------------------


def test_feature_scopes_are_listed_with_their_identity(signed_in: TestClient) -> None:
    """The left rail (`docs/ux/confirmation-flow-spec-v1.md` §1)."""
    body = signed_in.get("/feature-scopes").json()

    assert [scope["title"] for scope in body] == ["Rate-limit the gateway per client IP"]
    assert body[0]["runs"][0]["external_id"] == "acme/gateway#42"


def test_feature_scope_detail_returns_nodes_edges_and_the_header(signed_in: TestClient) -> None:
    body = signed_in.get(f"/feature-scopes/{FEATURE_SCOPE_ID}").json()

    assert body["feature_scope"]["title"] == "Rate-limit the gateway per client IP"
    assert len(body["nodes"]) == 2
    assert len(body["edges"]) == 1
    # provenance reaches the client verbatim -- the UI renders the excerpt itself
    excerpts = {ref["excerpt"] for node in body["nodes"] for ref in node["source_refs"]}
    assert "adds a per-IP token-bucket limiter" in excerpts


def test_unknown_feature_scope_is_404(signed_in: TestClient) -> None:
    assert signed_in.get(f"/feature-scopes/{uuid.uuid4()}").status_code == 404


# --- the four confirmation actions ---------------------------------------------


def test_confirm_records_the_ruling_against_the_session_actor(
    signed_in: TestClient, seeded: sessionmaker[Session]
) -> None:
    node = _nodes(signed_in)[0]

    response = signed_in.post(f"/nodes/{node['id']}/confirm")

    assert response.status_code == 200
    assert response.json()["status"] == NodeStatus.CONFIRMED.value
    assert response.json()["updated_by"] == ACTOR
    assert [event.actor for event in _events(seeded, EventType.NODE_CONFIRMED)] == [ACTOR]


def test_reject_keeps_the_node_and_marks_it_rejected(signed_in: TestClient) -> None:
    node = _nodes(signed_in)[0]

    response = signed_in.post(f"/nodes/{node['id']}/reject")

    assert response.json()["status"] == NodeStatus.REJECTED.value
    assert len(_nodes(signed_in)) == 2  # nothing is deleted


def test_edit_rewrites_content_and_records_what_it_replaced(
    signed_in: TestClient, seeded: sessionmaker[Session]
) -> None:
    node = _nodes(signed_in)[0]
    original = node["content"]

    response = signed_in.post(
        f"/nodes/{node['id']}/edit", json={"content": "Rate-limit per API key."}
    )

    assert response.json()["content"] == "Rate-limit per API key."
    assert response.json()["status"] == NodeStatus.EDITED.value
    (event,) = _events(seeded, EventType.NODE_EDITED)
    assert event.payload["previous_content"] == original


def test_edit_rejects_blank_content(signed_in: TestClient) -> None:
    node = _nodes(signed_in)[0]

    assert signed_in.post(f"/nodes/{node['id']}/edit", json={"content": "   "}).status_code == 422


def test_add_node_creates_a_human_asserted_node(signed_in: TestClient) -> None:
    """PRD R10. Its provenance is the person who typed it, not a fabricated URL."""
    response = signed_in.post(
        f"/feature-scopes/{FEATURE_SCOPE_ID}/nodes",
        json={"type": "constraint", "content": "Must ship before the Q4 freeze."},
    )

    assert response.status_code == 201
    created = response.json()
    assert created["created_by"] == CreatedBy.USER.value
    assert created["status"] == NodeStatus.CONFIRMED.value
    assert created["confidence_score"] is None
    (ref,) = created["source_refs"]
    assert ref["source_type"] == SourceType.HUMAN_ASSERTION.value
    assert ref["external_id"] == ACTOR
    assert len(_nodes(signed_in)) == 3


def test_add_node_to_an_unknown_feature_scope_is_404(signed_in: TestClient) -> None:
    response = signed_in.post(
        f"/feature-scopes/{uuid.uuid4()}/nodes",
        json={"type": "constraint", "content": "Orphaned."},
    )

    assert response.status_code == 404


def test_acting_on_an_unknown_node_is_404(signed_in: TestClient) -> None:
    assert signed_in.post(f"/nodes/{uuid.uuid4()}/confirm").status_code == 404


# --- the seam: identity never comes from the request ---------------------------


def test_a_request_body_cannot_choose_its_own_actor_or_workspace(signed_in: TestClient) -> None:
    """The structural half of the slice-1A forward note: `actor` and
    `workspace_id` are not fields any endpoint accepts, so a body naming them is
    rejected outright rather than partially honoured."""
    response = signed_in.post(
        f"/feature-scopes/{FEATURE_SCOPE_ID}/nodes",
        json={
            "type": "constraint",
            "content": "Injected.",
            "actor": "someone-else",
            "workspace_id": str(uuid.uuid4()),
        },
    )

    assert response.status_code == 422


def test_writes_land_in_the_workspace_of_the_session_not_the_request(
    signed_in: TestClient, seeded: sessionmaker[Session]
) -> None:
    signed_in.post(
        f"/feature-scopes/{FEATURE_SCOPE_ID}/nodes",
        json={"type": "goal", "content": "Typed by the PM."},
    )

    manual = [
        event
        for event in _events(seeded, EventType.NODE_CREATED)
        if event.payload["created_by"] == CreatedBy.USER.value
    ]
    assert [event.workspace_id for event in manual] == [WORKSPACE_ID]
    assert [event.actor for event in manual] == [ACTOR]


# --- workspace RBAC (slice 1D, TRD §9) -----------------------------------------


def test_a_non_member_cannot_sign_in(client: TestClient) -> None:
    """Knowing the passphrase is not membership. Failing at the door beats
    issuing a session that 403s on everything the person then tries."""
    response = client.post("/session", json={"passphrase": PASSPHRASE, "name": "Outsider"})

    assert response.status_code == 403
    assert "not a member" in response.json()["detail"]


def test_a_session_for_a_revoked_member_stops_working(
    client: TestClient, seeded: sessionmaker[Session]
) -> None:
    """Membership is re-read per request rather than trusted from the cookie, so
    revoking someone takes effect on their next call -- not when their cookie
    happens to expire."""
    client.post("/session", json={"passphrase": PASSPHRASE, "name": ACTOR})
    assert client.get("/feature-scopes").status_code == 200

    with session_scope(seeded) as session:
        session.query(WorkspaceMember).filter(WorkspaceMember.actor == ACTOR).delete()

    assert client.get("/feature-scopes").status_code == 403


def test_a_viewer_may_read_the_draft(client: TestClient) -> None:
    client.post("/session", json={"passphrase": PASSPHRASE, "name": VIEWER})

    assert client.get(f"/feature-scopes/{FEATURE_SCOPE_ID}").status_code == 200


@pytest.mark.parametrize("action", ["confirm", "reject"])
def test_a_viewer_may_not_rule_on_a_claim(client: TestClient, action: str) -> None:
    """The distinction the roles exist for: "extraction is a draft until a human
    acts on it" means little if any reader can act."""
    client.post("/session", json={"passphrase": PASSPHRASE, "name": ACTOR})
    node = _nodes(client)[0]
    client.delete("/session")
    client.post("/session", json={"passphrase": PASSPHRASE, "name": VIEWER})

    response = client.post(f"/nodes/{node['id']}/{action}")

    assert response.status_code == 403
    assert "may review but not confirm" in response.json()["detail"]


def test_a_viewer_may_not_add_a_claim(client: TestClient) -> None:
    client.post("/session", json={"passphrase": PASSPHRASE, "name": VIEWER})

    response = client.post(
        f"/feature-scopes/{FEATURE_SCOPE_ID}/nodes",
        json={"type": "constraint", "content": "Sneaking this in."},
    )

    assert response.status_code == 403


def test_the_session_reports_the_role_so_the_ui_can_hide_what_is_refused(
    client: TestClient,
) -> None:
    client.post("/session", json={"passphrase": PASSPHRASE, "name": VIEWER})

    assert client.get("/session").json()["role"] == Role.VIEWER.value
