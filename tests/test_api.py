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

import json
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from atlas.api.app import create_app
from atlas.api.deps import (
    AUTOMATED_ACTOR_HEADER,
    SESSION_COOKIE,
    get_api_settings,
    get_session,
    get_session_factory,
)
from atlas.config import ApiSettings
from atlas.extraction.agent import build_result
from atlas.models.schema import (
    ActorKind,
    CreatedBy,
    EventType,
    IngestionRunPayload,
    NodeStatus,
    Role,
    SourceType,
)
from atlas.storage.connections import Connection, generate_secret_key, seal
from atlas.storage.db import Base, get_sessionmaker, session_scope
from atlas.storage.products import assign_feature_scope
from atlas.storage.tables import EventLog, Workspace, WorkspaceMember

WORKSPACE_ID = uuid.UUID(int=0)  # DEFAULT_WORKSPACE_ID -- what `Principal` stamps
FEATURE_SCOPE_ID = uuid.uuid4()
PASSPHRASE = "open-sesame"
#: The Fernet key connections are encrypted with. Generated per test run, so no
#: key is ever committed and a leaked fixture value cannot decrypt anything real.
SECRET_KEY = generate_secret_key()
#: Seated as admin: since Phase 4 only an admin may connect or revoke a source,
#: and an admin can do everything an editor can, so every editor-path test holds.
ACTOR = "Priya (PM)"
VIEWER = "Sam (observer)"
#: A plain editor -- may rule on claims and pull from connected sources, but may
#: not grant Atlas access to anything new.
EDITOR_ONLY = "Eli (engineer)"


#: A stand-in Google service account. Never used to sign anything in these
#: tests -- `check_access` and `execute_run` are stubbed -- so the key is inert.
GOOGLE_ACCOUNT = {
    "client_email": "atlas-reader@atlas-demo.iam.gserviceaccount.com",
    "private_key": "-----BEGIN PRIVATE KEY-----\nINERT\n-----END PRIVATE KEY-----\n",
}


def _settings() -> ApiSettings:
    return ApiSettings(
        supabase_db_url="sqlite://",
        app_passphrase=PASSPHRASE,
        session_secret="test-secret-not-a-real-one",
        secret_key=SECRET_KEY,
        google_service_accounts={WORKSPACE_ID: GOOGLE_ACCOUNT},
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
    from atlas.pipeline import record_extraction

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
        session.add(WorkspaceMember(workspace_id=WORKSPACE_ID, actor=ACTOR, role=Role.ADMIN))
        session.add(WorkspaceMember(workspace_id=WORKSPACE_ID, actor=EDITOR_ONLY, role=Role.EDITOR))
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
    # A background run opens its own transactions, so it needs the *factory*
    # pinned to the same in-memory database rather than a real URL.
    app.dependency_overrides[get_session_factory] = lambda: seeded
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
        # Slice 2B. The connect and ingest endpoints are the two that hold a
        # credential, so an unauthenticated one would be the worst hole here.
        ("get", f"/products/{uuid.uuid4()}/connections"),
        ("post", f"/products/{uuid.uuid4()}/connections"),
        ("delete", f"/connections/{uuid.uuid4()}"),
        ("get", f"/products/{uuid.uuid4()}/runs"),
        ("post", f"/products/{uuid.uuid4()}/runs"),
        ("get", f"/runs/{uuid.uuid4()}"),
        # Slice 3. Orientation is authored, so these are writes like any other.
        ("put", f"/products/{uuid.uuid4()}/description"),
        ("put", f"/feature-scopes/{FEATURE_SCOPE_ID}/description"),
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
    assert response.json() == {"actor": ACTOR, "role": Role.ADMIN.value}
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


def test_each_listed_feature_says_how_much_of_it_is_still_work(signed_in: TestClient) -> None:
    """The number the rail badge, the Conflicts entry and the dashboard all read.

    It ships with the list rather than being derived client-side: three surfaces
    need the identical figure, and the alternative is sending every claim and
    excerpt of every feature to the browser so it can count them.
    """
    body = signed_in.get("/feature-scopes").json()

    counts = body[0]["counts"]
    assert counts["total"] == 2
    assert counts["unreviewed"] == 2
    assert counts["conflicts"] == 0


def test_confirming_a_claim_lowers_the_unreviewed_count_on_the_next_read(
    signed_in: TestClient,
) -> None:
    """The count is a projection, not a stored tally -- so a ruling moves it
    without anything having to remember to decrement a column."""
    node_id = signed_in.get(f"/feature-scopes/{FEATURE_SCOPE_ID}").json()["nodes"][0]["id"]
    before = signed_in.get("/feature-scopes").json()[0]["counts"]["unreviewed"]

    assert signed_in.post(f"/nodes/{node_id}/confirm").status_code == 200

    after = signed_in.get("/feature-scopes").json()[0]["counts"]["unreviewed"]
    assert after == before - 1


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


# --- products ------------------------------------------------------------------


def test_products_start_empty_and_a_created_one_is_listed(signed_in: TestClient) -> None:
    assert signed_in.get("/products").json() == []

    created = signed_in.post("/products", json={"name": "Acme Web"})

    assert created.status_code == 201
    assert created.json()["name"] == "Acme Web"
    assert signed_in.get("/products").json() == [created.json()]


def test_a_product_id_from_the_request_body_is_refused(signed_in: TestClient) -> None:
    """The id is minted in `storage/`. `extra="forbid"` means a body trying to
    choose its own is a 422, not a silently ignored field -- the same hole
    `add_node` closes by building its Node from fields."""
    response = signed_in.post("/products", json={"name": "Acme Web", "id": str(uuid.uuid4())})

    assert response.status_code == 422


def test_a_blank_product_name_is_refused_at_the_wire(signed_in: TestClient) -> None:
    assert signed_in.post("/products", json={"name": "   "}).status_code == 422


def test_a_viewer_may_list_products_but_not_create_one(client: TestClient) -> None:
    client.post("/session", json={"passphrase": PASSPHRASE, "name": VIEWER})

    assert client.get("/products").status_code == 200
    assert client.post("/products", json={"name": "Sneaky"}).status_code == 403


def test_a_feature_scope_reports_the_product_it_is_filed_under(
    signed_in: TestClient, seeded: sessionmaker[Session]
) -> None:
    """The rail groups on the client, so the scope has to carry its own product."""
    product_id = uuid.UUID(signed_in.post("/products", json={"name": "Acme Web"}).json()["id"])

    assert signed_in.get("/feature-scopes").json()[0]["product_id"] is None

    with session_scope(seeded) as session:
        assign_feature_scope(
            session,
            workspace_id=WORKSPACE_ID,
            feature_scope_id=FEATURE_SCOPE_ID,
            product_id=product_id,
            actor=ACTOR,
            actor_kind=ActorKind.HUMAN,
        )

    assert signed_in.get("/feature-scopes").json()[0]["product_id"] == str(product_id)


def test_products_are_invisible_across_workspaces(signed_in: TestClient) -> None:
    """Nothing new is being trusted here -- products ride the same workspace
    filter the event log already enforces, and RLS enforces underneath it."""
    signed_in.post("/products", json={"name": "Acme Web"})
    listed = signed_in.get("/products").json()

    assert len(listed) == 1


# --- saying what a product and a feature are (slice 3) --------------------------
#
# PM-authored plain text, not a Node -- no provenance, no confirmation loop
# (`docs/decisions/2026-08-19-product-orientation-rerun-safety-and-demo-data.md`
# decision 4). `PUT` rather than `POST` because the request states the field's
# whole value: sending it twice leaves the same description, even though each
# send appends its own audit event.


def test_a_product_says_what_it_is(signed_in: TestClient) -> None:
    product_id = signed_in.post("/products", json={"name": "Acme Web"}).json()["id"]

    response = signed_in.put(
        f"/products/{product_id}/description",
        json={"description": "Where Acme's customers pay their bills."},
    )

    assert response.status_code == 200
    assert response.json()["description"] == "Where Acme's customers pay their bills."
    assert response.json()["name"] == "Acme Web"
    listed = signed_in.get("/products").json()
    assert listed[0]["description"] == "Where Acme's customers pay their bills."


def test_a_product_description_is_cleared_by_an_empty_one(signed_in: TestClient) -> None:
    product_id = signed_in.post("/products", json={"name": "Acme Web"}).json()["id"]
    signed_in.put(f"/products/{product_id}/description", json={"description": "Wrong."})

    assert (
        signed_in.put(f"/products/{product_id}/description", json={"description": ""}).status_code
        == 200
    )
    assert signed_in.get("/products").json()[0]["description"] is None


def test_describing_a_product_that_does_not_exist_is_a_404(signed_in: TestClient) -> None:
    response = signed_in.put(
        f"/products/{uuid.uuid4()}/description", json={"description": "Ghost."}
    )

    assert response.status_code == 404


def test_a_viewer_may_not_describe_a_product(
    client: TestClient, seeded: sessionmaker[Session]
) -> None:
    client.post("/session", json={"passphrase": PASSPHRASE, "name": ACTOR})
    product_id = client.post("/products", json={"name": "Acme Web"}).json()["id"]
    client.delete("/session")
    client.post("/session", json={"passphrase": PASSPHRASE, "name": VIEWER})

    response = client.put(f"/products/{product_id}/description", json={"description": "Sneaky."})

    assert response.status_code == 403


def test_describing_a_product_is_recorded_as_the_signed_in_person(
    signed_in: TestClient, seeded: sessionmaker[Session]
) -> None:
    """Orientation is not a claim, but it is still someone's statement -- so it
    lands in the log with the same actor and the same `actor_kind` a ruling
    does."""
    product_id = signed_in.post("/products", json={"name": "Acme Web"}).json()["id"]

    signed_in.put(f"/products/{product_id}/description", json={"description": "Billing."})

    events = _events(seeded, EventType.PRODUCT_DESCRIBED)
    assert [(event.actor, event.actor_kind) for event in events] == [(ACTOR, ActorKind.HUMAN)]


def test_a_feature_says_what_it_is(signed_in: TestClient) -> None:
    response = signed_in.put(
        f"/feature-scopes/{FEATURE_SCOPE_ID}/description",
        json={"description": "Stop the gateway falling over under bursts."},
    )

    assert response.status_code == 200
    detail = signed_in.get(f"/feature-scopes/{FEATURE_SCOPE_ID}").json()
    assert detail["feature_scope"]["description"] == "Stop the gateway falling over under bursts."
    row = signed_in.get("/feature-scopes").json()[0]
    assert row["description"] == "Stop the gateway falling over under bursts."


def test_describing_a_feature_scope_that_does_not_exist_is_a_404(signed_in: TestClient) -> None:
    """A scope with nodes but no `ingestion_run` has no projected identity to
    attach a description to, so the write is refused at the wire rather than
    written as an event the replay would drop."""
    response = signed_in.put(
        f"/feature-scopes/{uuid.uuid4()}/description", json={"description": "Ghost."}
    )

    assert response.status_code == 404


def test_a_viewer_may_not_describe_a_feature(client: TestClient) -> None:
    client.post("/session", json={"passphrase": PASSPHRASE, "name": VIEWER})

    response = client.put(
        f"/feature-scopes/{FEATURE_SCOPE_ID}/description", json={"description": "Sneaky."}
    )

    assert response.status_code == 403


def test_an_over_long_description_is_refused_at_the_wire(signed_in: TestClient) -> None:
    product_id = signed_in.post("/products", json={"name": "Acme Web"}).json()["id"]

    response = signed_in.put(
        f"/products/{product_id}/description", json={"description": "x" * 5000}
    )

    assert response.status_code == 422


# --- sources and runs (slice 2B) -----------------------------------------------
#
# The credential is the whole point of the care here: it arrives over HTTP, is
# stored encrypted, and must never come back out. Two of these tests assert that
# structurally rather than by inspection.


PRODUCT_ID = uuid.UUID(int=99)


@pytest.fixture
def with_product(seeded: sessionmaker[Session], client: TestClient) -> uuid.UUID:
    """A real product to hang connections off. Created through the API, so the
    id is minted in `storage/` exactly as it is in production."""
    client.post("/session", json={"passphrase": PASSPHRASE, "name": ACTOR})
    created = client.post("/products", json={"name": "Gateway"})
    assert created.status_code == 201
    return uuid.UUID(created.json()["id"])


def _stub_access(monkeypatch: pytest.MonkeyPatch, *, fails: bool = False) -> None:
    from atlas import pipeline

    def check(credential: object, *, scope: str) -> pipeline.AccessSummary:
        if fails:
            raise RuntimeError(f"401 Unauthorized for token {SECRET_TOKEN}")
        return pipeline.AccessSummary(label=scope, detail="Private repository · 3 open issue(s)")

    monkeypatch.setattr("atlas.api.routes.check_access", check)


SECRET_TOKEN = "ghp_this_must_never_come_back"


def test_no_response_model_in_the_openapi_schema_can_carry_a_secret(
    client: TestClient,
) -> None:
    """The structural rule, checked where it actually binds.

    `frontend/src/api-types.ts` is generated from this schema, so a leaking field
    would flow straight into the UI's own types. Checking the schema rather than
    one model catches a leak added anywhere in `api/`.
    """
    schema = client.get("/openapi.json").json()
    leaky = {"secret_ciphertext", "token", "api_token", "password", "credential"}
    for name, model in schema["components"]["schemas"].items():
        if name in {"ConnectSourceRequest"}:
            continue  # the one inbound-only body that carries `secret`
        assert not leaky & set(model.get("properties", {})), f"{name} can serialize a secret"
        assert "secret" not in model.get("properties", {}), f"{name} can serialize a secret"


def test_connecting_a_source_stores_it_and_reports_what_it_can_see(
    client: TestClient,
    with_product: uuid.UUID,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_access(monkeypatch)

    response = client.post(
        f"/products/{with_product}/connections",
        json={
            "source_type": "github_pr",
            "host": "github.com",
            "scope": "acme/gateway",
            "secret": SECRET_TOKEN,
        },
    )

    assert response.status_code == 201
    body = response.json()
    # The trust moment: what the credential reaches, before it is trusted.
    assert body["access_detail"] == "Private repository · 3 open issue(s)"
    assert body["connection"]["secret_hint"] == SECRET_TOKEN[-4:]
    assert SECRET_TOKEN not in response.text


def test_a_stored_credential_is_ciphertext_in_the_row(
    client: TestClient,
    seeded: sessionmaker[Session],
    with_product: uuid.UUID,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_access(monkeypatch)
    client.post(
        f"/products/{with_product}/connections",
        json={
            "source_type": "github_pr",
            "host": "github.com",
            "scope": "acme/gateway",
            "secret": SECRET_TOKEN,
        },
    )

    with session_scope(seeded) as session:
        stored = session.query(Connection).one()
    assert stored.secret_ciphertext is not None
    assert SECRET_TOKEN.encode() not in stored.secret_ciphertext


def test_a_credential_that_cannot_read_its_scope_is_refused_at_the_door(
    client: TestClient,
    with_product: uuid.UUID,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """And the refusal must not echo the connector's own error, which can quote
    the request it made — and that request carried the credential."""
    _stub_access(monkeypatch, fails=True)

    response = client.post(
        f"/products/{with_product}/connections",
        json={
            "source_type": "github_pr",
            "host": "github.com",
            "scope": "acme/gateway",
            "secret": SECRET_TOKEN,
        },
    )

    assert response.status_code == 422
    assert SECRET_TOKEN not in response.text


def test_jira_without_an_email_is_a_422_rather_than_a_run_that_fails_later(
    client: TestClient, with_product: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_access(monkeypatch)

    response = client.post(
        f"/products/{with_product}/connections",
        json={
            "source_type": "jira_ticket",
            "host": "acme.atlassian.net",
            "scope": "GATE",
            "secret": SECRET_TOKEN,
        },
    )

    assert response.status_code == 422


def test_connecting_to_a_product_that_does_not_exist_is_a_404(
    client: TestClient, with_product: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_access(monkeypatch)

    response = client.post(
        f"/products/{uuid.uuid4()}/connections",
        json={
            "source_type": "github_pr",
            "host": "github.com",
            "scope": "acme/gateway",
            "secret": SECRET_TOKEN,
        },
    )

    assert response.status_code == 404


def test_revoking_a_connection_deletes_the_row(
    client: TestClient,
    seeded: sessionmaker[Session],
    with_product: uuid.UUID,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_access(monkeypatch)
    created = client.post(
        f"/products/{with_product}/connections",
        json={
            "source_type": "github_pr",
            "host": "github.com",
            "scope": "acme/gateway",
            "secret": SECRET_TOKEN,
        },
    ).json()

    assert client.delete(f"/connections/{created['connection']['id']}").status_code == 204
    with session_scope(seeded) as session:
        assert session.query(Connection).count() == 0
    assert client.get(f"/products/{with_product}/connections").json() == []


def test_a_viewer_may_see_sources_but_not_connect_one(
    client: TestClient, with_product: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_access(monkeypatch)
    client.post("/session", json={"passphrase": PASSPHRASE, "name": VIEWER})

    assert client.get(f"/products/{with_product}/connections").status_code == 200
    assert (
        client.post(
            f"/products/{with_product}/connections",
            json={
                "source_type": "github_pr",
                "host": "github.com",
                "scope": "acme/gateway",
                "secret": SECRET_TOKEN,
            },
        ).status_code
        == 403
    )


def _connect(client: TestClient, product_id: uuid.UUID, monkeypatch: pytest.MonkeyPatch) -> str:
    _stub_access(monkeypatch)
    return str(
        client.post(
            f"/products/{product_id}/connections",
            json={
                "source_type": "github_pr",
                "host": "github.com",
                "scope": "acme/gateway",
                "secret": SECRET_TOKEN,
            },
        ).json()["connection"]["id"]
    )


def test_starting_a_run_returns_202_with_something_to_poll(
    client: TestClient,
    with_product: uuid.UUID,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """202, not 200: the run is *accepted*. The id in the body is the handle."""
    connection_id = _connect(client, with_product, monkeypatch)
    scheduled: list[dict[str, Any]] = []

    def capture(*args: Any, **kwargs: Any) -> None:
        scheduled.append(kwargs)

    monkeypatch.setattr("atlas.api.routes.execute_run", capture)

    response = client.post(
        f"/products/{with_product}/runs",
        json={
            "connection_id": connection_id,
            "target_kind": "github_pr",
            "target": "acme/gateway#99",
        },
    )

    assert response.status_code == 202
    body = response.json()
    assert body["state"] == "running"
    # The start event is already in the log, so the run is visible while working.
    assert client.get(f"/runs/{body['id']}").json()["state"] == "running"
    assert scheduled and scheduled[0]["credential"].token == SECRET_TOKEN


def test_a_malformed_target_never_starts_a_run(
    client: TestClient,
    seeded: sessionmaker[Session],
    with_product: uuid.UUID,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection_id = _connect(client, with_product, monkeypatch)
    monkeypatch.setattr("atlas.api.routes.execute_run", lambda *a, **k: None)

    response = client.post(
        f"/products/{with_product}/runs",
        json={
            "connection_id": connection_id,
            "target_kind": "github_pr",
            "target": "https://github.com/acme/gateway/pull/42",
        },
    )

    assert response.status_code == 422
    assert _events(seeded, EventType.INGESTION_RUN_STARTED) == []


def test_a_run_against_an_unknown_connection_is_a_404(
    client: TestClient, with_product: uuid.UUID
) -> None:
    response = client.post(
        f"/products/{with_product}/runs",
        json={
            "connection_id": str(uuid.uuid4()),
            "target_kind": "github_pr",
            "target": "acme/gateway#99",
        },
    )

    assert response.status_code == 404


def test_a_viewer_may_not_start_a_run(
    client: TestClient, with_product: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    connection_id = _connect(client, with_product, monkeypatch)
    client.post("/session", json={"passphrase": PASSPHRASE, "name": VIEWER})

    response = client.post(
        f"/products/{with_product}/runs",
        json={
            "connection_id": connection_id,
            "target_kind": "github_pr",
            "target": "acme/gateway#99",
        },
    )

    assert response.status_code == 403


def test_a_connection_written_with_a_different_key_fails_loudly(
    client: TestClient,
    seeded: sessionmaker[Session],
    with_product: uuid.UUID,
) -> None:
    """Key rotation is unbuilt (`product-model-and-frontend-rebuild-v1.md` §11.3).
    Until it exists, a connection Atlas cannot decrypt must say so rather than
    starting a run that fails with an auth error nobody can explain."""
    with session_scope(seeded) as session:
        session.add(
            Connection(
                id=uuid.uuid4(),
                workspace_id=WORKSPACE_ID,
                product_id=with_product,
                source_type=SourceType.GITHUB_PR,
                account="token",
                host="github.com",
                scope="acme/gateway",
                secret_ciphertext=seal("x", generate_secret_key()),
                secret_hint="xxxx",
                created_by=ACTOR,
            )
        )
    with session_scope(seeded) as session:
        stale = session.query(Connection).one().id

    response = client.post(
        f"/products/{with_product}/runs",
        json={
            "connection_id": str(stale),
            "target_kind": "github_pr",
            "target": "acme/gateway#99",
        },
    )

    assert response.status_code == 409


@pytest.mark.parametrize(
    "typed", ["acme.atlassian.net", "https://acme.atlassian.net", "https://acme.atlassian.net/"]
)
def test_a_pasted_host_is_normalized_before_it_is_stored(
    client: TestClient,
    seeded: sessionmaker[Session],
    with_product: uuid.UUID,
    monkeypatch: pytest.MonkeyPatch,
    typed: str,
) -> None:
    """People paste what the address bar shows. Normalizing once, at the door,
    is what keeps the connect check and the later run agreeing — an earlier cut
    stripped the scheme only when building the credential, so the row kept
    `https://…` and the next run built `https://https://…`."""
    _stub_access(monkeypatch)

    body = client.post(
        f"/products/{with_product}/connections",
        json={
            "source_type": "jira_ticket",
            "host": typed,
            "scope": "GATE",
            "secret": SECRET_TOKEN,
            "email": "pm@acme.test",
        },
    ).json()

    assert body["connection"]["host"] == "acme.atlassian.net"


def test_connecting_jira_to_a_host_atlas_will_not_talk_to_is_refused(
    client: TestClient, with_product: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The SSRF control, at the endpoint that first accepts the host. The
    credential must never leave the process aimed at an arbitrary destination."""
    _stub_access(monkeypatch)

    response = client.post(
        f"/products/{with_product}/connections",
        json={
            "source_type": "jira_ticket",
            "host": "169.254.169.254",
            "scope": "GATE",
            "secret": SECRET_TOKEN,
            "email": "pm@acme.test",
        },
    )

    assert response.status_code == 422
    assert "Jira Cloud site" in response.text
    assert SECRET_TOKEN not in response.text


# --- actor kind at the HTTP seam (2026-08-18) ----------------------------------


def test_a_confirmation_from_a_browser_session_is_recorded_as_human(
    signed_in: TestClient, seeded: sessionmaker[Session]
) -> None:
    node = _nodes(signed_in)[0]

    signed_in.post(f"/nodes/{node['id']}/confirm")

    assert [event.actor_kind for event in _events(seeded, EventType.NODE_CONFIRMED)] == [
        ActorKind.HUMAN
    ]


def test_a_client_declaring_itself_automated_is_recorded_as_automated(
    signed_in: TestClient, seeded: sessionmaker[Session]
) -> None:
    """The header the browser suite sets. Without it, a harness holding a real
    session is indistinguishable from the person whose name it signed in under --
    which is how 6 real claims were confirmed as `Rohit` on 2026-08-16."""
    node = _nodes(signed_in)[0]

    signed_in.post(f"/nodes/{node['id']}/confirm", headers={AUTOMATED_ACTOR_HEADER: "1"})

    assert [event.actor_kind for event in _events(seeded, EventType.NODE_CONFIRMED)] == [
        ActorKind.AUTOMATED
    ]


def test_the_header_cannot_be_used_to_claim_humanness(
    signed_in: TestClient, seeded: sessionmaker[Session]
) -> None:
    """Only the downgrade is claimable. `human` in the header still reads as a
    machine declaring itself, because the header's presence is the signal --
    otherwise a bot could ask for the one label the guard metric trusts."""
    node = _nodes(signed_in)[0]

    signed_in.post(f"/nodes/{node['id']}/confirm", headers={AUTOMATED_ACTOR_HEADER: "human"})

    assert [event.actor_kind for event in _events(seeded, EventType.NODE_CONFIRMED)] == [
        ActorKind.AUTOMATED
    ]


def test_re_running_an_already_ingested_artifact_re_syncs_into_its_feature(
    client: TestClient, with_product: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Phase 3 replaced the 2026-08-19 refusal: ingestion is idempotent per
    feature scope, so a re-run is routed into the scope that already holds the
    artifact -- the one place it cannot duplicate."""
    connection_id = _connect(client, with_product, monkeypatch)
    captured: list[Any] = []
    monkeypatch.setattr(
        "atlas.api.routes.execute_run", lambda *a, **k: captured.append(k["request"])
    )

    response = client.post(
        f"/products/{with_product}/runs",
        json={
            "connection_id": connection_id,
            "target_kind": "github_pr",
            "target": "acme/gateway#42",
        },
    )

    assert response.status_code == 202
    (request,) = captured
    assert request.feature_scope_id == FEATURE_SCOPE_ID


def test_re_syncing_an_artifact_held_by_another_product_is_refused(
    client: TestClient,
    with_product: uuid.UUID,
    seeded: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Backend review 2026-09-28: routing an unscoped re-run into the holder
    must not reach across products -- doing so re-filed the holder's feature
    under the caller's product, moving its confirmed claims out of the other
    product's spec."""
    other = uuid.UUID(client.post("/products", json={"name": "Other"}).json()["id"])
    with session_scope(seeded) as session:
        assign_feature_scope(
            session,
            workspace_id=WORKSPACE_ID,
            feature_scope_id=FEATURE_SCOPE_ID,
            product_id=other,
            actor=ACTOR,
            actor_kind=ActorKind.HUMAN,
        )
    connection_id = _connect(client, with_product, monkeypatch)
    ran: list[Any] = []
    monkeypatch.setattr("atlas.api.routes.execute_run", lambda *a, **k: ran.append(k))

    response = client.post(
        f"/products/{with_product}/runs",
        json={
            "connection_id": connection_id,
            "target_kind": "github_pr",
            "target": "acme/gateway#42",
        },
    )

    assert response.status_code == 409
    assert "another product" in response.json()["detail"]
    assert ran == []


def test_filing_an_ingested_artifact_under_a_second_feature_is_refused(
    client: TestClient, with_product: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The one way a re-run could still duplicate. The refusal names where the
    artifact already is, so a PM can go look rather than guess."""
    connection_id = _connect(client, with_product, monkeypatch)

    response = client.post(
        f"/products/{with_product}/runs",
        json={
            "connection_id": connection_id,
            "target_kind": "github_pr",
            "target": "acme/gateway#42",
            "feature_scope_id": str(uuid.uuid4()),
        },
    )

    assert response.status_code == 409
    assert "Rate-limit the gateway per client IP" in response.json()["detail"]


def test_an_epic_is_not_blocked_because_it_names_no_single_artifact(
    client: TestClient, with_product: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An epic expands to many artifacts and the target names none of them, so
    re-sync routing does not apply; re-running it is still safe because
    `pipeline.reconcile` works per artifact. Pulled through a *Jira*
    connection -- a GitHub one is now refused for a Jira target."""
    _stub_access(monkeypatch)
    connection_id = client.post(
        f"/products/{with_product}/connections",
        json={
            "source_type": "jira_ticket",
            "host": "acme.atlassian.net",
            "scope": "SCRUM",
            "secret": SECRET_TOKEN,
            "email": "pm@acme.test",
        },
    ).json()["connection"]["id"]
    monkeypatch.setattr("atlas.api.routes.execute_run", lambda *a, **k: None)

    response = client.post(
        f"/products/{with_product}/runs",
        json={
            "connection_id": connection_id,
            "target_kind": "jira_epic",
            "target": "SCRUM-1",
        },
    )

    assert response.status_code == 202


# --- the product document (`/products/{id}/document`) ---------------------------
#
# The endpoint the About page and spec export both read. Everything interesting
# is asserted in `tests/test_assembly.py` against the pure function; what belongs
# here is only what the wire adds -- auth, 404, and the fact that the confirmed-
# only rule survives serialization (`docs/architecture/
# product-info-and-spec-export-v1.md` §4).


@pytest.fixture
def documented(signed_in: TestClient, seeded: sessionmaker[Session]) -> uuid.UUID:
    """A product with the seeded feature filed under it."""
    product_id = uuid.UUID(signed_in.post("/products", json={"name": "Gateway"}).json()["id"])
    with session_scope(seeded) as session:
        assign_feature_scope(
            session,
            workspace_id=WORKSPACE_ID,
            feature_scope_id=FEATURE_SCOPE_ID,
            product_id=product_id,
            actor=ACTOR,
            actor_kind=ActorKind.HUMAN,
        )
    return product_id


def test_a_document_for_an_unknown_product_is_a_404(signed_in: TestClient) -> None:
    assert signed_in.get(f"/products/{uuid.uuid4()}/document").status_code == 404


def test_a_document_needs_a_session(client: TestClient, documented: uuid.UUID) -> None:
    client.delete("/session")
    assert client.get(f"/products/{documented}/document").status_code == 401


def test_a_document_withholds_claims_nobody_has_ruled_on(
    signed_in: TestClient, documented: uuid.UUID
) -> None:
    """The rule the module exists for, asserted over the wire: the seeded feature
    has two unconfirmed claims, and the document must contain neither."""
    doc = signed_in.get(f"/products/{documented}/document").json()

    (section,) = doc["features"]
    assert section["claims"] == []
    assert section["unreviewed"] == 2
    assert "rate-limit per client IP" not in json.dumps(doc)


def test_confirming_a_claim_puts_it_in_the_document_with_its_excerpt(
    signed_in: TestClient, documented: uuid.UUID
) -> None:
    """The reward the review loop did not previously have: a ruling makes
    something *appear*, rather than only disappearing from a queue."""
    nodes = signed_in.get(f"/feature-scopes/{FEATURE_SCOPE_ID}").json()["nodes"]
    node = next(item for item in nodes if item["type"] == "requirement")
    assert signed_in.post(f"/nodes/{node['id']}/confirm").status_code == 200

    (section,) = signed_in.get(f"/products/{documented}/document").json()["features"]

    (claim,) = section["claims"]
    assert claim["content"] == "The gateway must rate-limit per client IP."
    assert claim["status"] == "confirmed"
    (source,) = claim["sources"]
    assert source["excerpt"] == "adds a per-IP token-bucket limiter"
    assert source["url"] == "https://github.com/acme/gateway/pull/42"


def test_a_document_carries_readiness_and_evidence_density(
    signed_in: TestClient, documented: uuid.UUID
) -> None:
    """Roadmap v2 2A [+2026-09-02]: the score and its gaps travel with the
    document, and the export states the same score at its head."""
    doc = signed_in.get(f"/products/{documented}/document").json()

    readiness = doc["readiness"]
    assert 0 <= readiness["score"] < 100
    kinds = {gap["kind"] for gap in readiness["gaps"]}
    assert "unreviewed" in kinds
    unreviewed = next(gap for gap in readiness["gaps"] if gap["kind"] == "unreviewed")
    assert len(unreviewed["node_ids"]) == 2

    spec = signed_in.get(f"/products/{documented}/spec").text
    assert f"Readiness: {readiness['score']}/100" in spec


def test_a_document_carries_the_authored_descriptions(
    signed_in: TestClient, documented: uuid.UUID
) -> None:
    signed_in.put(f"/products/{documented}/description", json={"description": "The edge gateway."})
    signed_in.put(
        f"/feature-scopes/{FEATURE_SCOPE_ID}/description",
        json={"description": "How we shed load."},
    )

    doc = signed_in.get(f"/products/{documented}/document").json()

    assert doc["description"] == "The edge gateway."
    assert doc["features"][0]["description"] == "How we shed load."


def test_a_viewer_may_read_a_document(client: TestClient, documented: uuid.UUID) -> None:
    """Reading what a product is is not a write, so a viewer gets it."""
    client.post("/session", json={"passphrase": PASSPHRASE, "name": VIEWER})

    assert client.get(f"/products/{documented}/document").status_code == 200


def test_another_products_features_stay_out_of_the_document(
    signed_in: TestClient, documented: uuid.UUID
) -> None:
    other = signed_in.post("/products", json={"name": "Somebody else's"}).json()["id"]

    assert signed_in.get(f"/products/{other}/document").json()["features"] == []


# --- spec export v0 (`/products/{id}/spec`) -------------------------------------
#
# Roadmap v2 Phase 2A, pulled forward because the About page builds the same
# assembly. The property worth testing here is that the two agree: the export is
# the page's document rendered differently, not a second opinion about what
# "confirmed" means.


def test_the_spec_is_markdown_named_after_the_product(
    signed_in: TestClient, documented: uuid.UUID
) -> None:
    response = signed_in.get(f"/products/{documented}/spec")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/markdown")
    assert response.headers["content-disposition"] == 'attachment; filename="gateway-spec.md"'
    assert response.text.startswith("# Gateway")


def test_a_spec_never_contains_an_unruled_claim(
    signed_in: TestClient, documented: uuid.UUID
) -> None:
    """The rule this whole module exists for, at the far end of the pipe."""
    assert "rate-limit per client IP" not in signed_in.get(f"/products/{documented}/spec").text


def test_a_confirmed_claim_reaches_the_spec_with_its_excerpt(
    signed_in: TestClient, documented: uuid.UUID
) -> None:
    nodes = signed_in.get(f"/feature-scopes/{FEATURE_SCOPE_ID}").json()["nodes"]
    node = next(item for item in nodes if item["type"] == "requirement")
    signed_in.post(f"/nodes/{node['id']}/confirm")

    spec = signed_in.get(f"/products/{documented}/spec").text

    assert "The gateway must rate-limit per client IP." in spec
    assert "adds a per-IP token-bucket limiter" in spec
    assert "https://github.com/acme/gateway/pull/42" in spec


def test_the_spec_and_the_page_agree_about_what_is_confirmed(
    signed_in: TestClient, documented: uuid.UUID
) -> None:
    """One assembly, two renderings. If these ever disagree, the filter has been
    reimplemented somewhere it should not have been."""
    nodes = signed_in.get(f"/feature-scopes/{FEATURE_SCOPE_ID}").json()["nodes"]
    signed_in.post(f"/nodes/{nodes[0]['id']}/confirm")

    doc = signed_in.get(f"/products/{documented}/document").json()
    spec = signed_in.get(f"/products/{documented}/spec").text

    for section in doc["features"]:
        for claim in section["claims"]:
            assert claim["content"] in spec


def test_a_spec_for_an_unknown_product_is_a_404(signed_in: TestClient) -> None:
    assert signed_in.get(f"/products/{uuid.uuid4()}/spec").status_code == 404


def test_a_product_name_cannot_inject_a_download_header(signed_in: TestClient) -> None:
    """The name is user-supplied and lands in `Content-Disposition`, where a
    quote or a newline is a header-injection primitive rather than a cosmetic
    problem. The filename is built from a whitelist, so it cannot carry one."""
    hostile = signed_in.post("/products", json={"name": 'evil"; filename="x.sh'}).json()["id"]

    disposition = signed_in.get(f"/products/{hostile}/spec").headers["content-disposition"]

    assert disposition.count('"') == 2
    assert "\n" not in disposition and "\r" not in disposition
    assert ";" not in disposition[disposition.index('"') :]


# --- the database being unreachable is not the API being down -----------------


@pytest.fixture
def unreachable_db(
    seeded: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> Iterator[TestClient]:
    """A client whose every DB session raises the way a paused Supabase does.

    `psycopg` raises `OperationalError`; SQLAlchemy re-raises it wrapped, which
    is the shape the app actually sees.
    """
    # The CORS assertion below only means anything with the middleware installed.
    monkeypatch.setenv("ATLAS_DEV_CORS", "1")
    app = create_app()

    def _dead_session() -> Iterator[Session]:
        raise OperationalError("select 1", {}, Exception("connection failed: FATAL: ENOTFOUND"))
        yield  # pragma: no cover -- generator dependency, never reached

    app.dependency_overrides[get_session] = _dead_session
    app.dependency_overrides[get_api_settings] = _settings
    app.dependency_overrides[get_session_factory] = lambda: seeded
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


def test_an_unreachable_database_is_503_not_500(unreachable_db: TestClient) -> None:
    """A 500 from an unhandled exception skips the CORS middleware, so the
    browser sees a *network* error and the SPA says "is the API running?" -- the
    one thing that is definitely not wrong. 503 says whose fault it is."""
    response = unreachable_db.post("/session", json={"passphrase": PASSPHRASE, "name": ACTOR})

    assert response.status_code == 503
    assert "database" in response.json()["detail"].lower()


def test_the_unreachable_database_message_leaks_no_connection_detail(
    unreachable_db: TestClient,
) -> None:
    """The driver's message names the host, the pooler tenant and the role. None
    of that belongs in a browser -- it goes to the log instead."""
    detail = unreachable_db.post("/session", json={"passphrase": PASSPHRASE, "name": ACTOR}).json()[
        "detail"
    ]

    for leak in ("FATAL", "ENOTFOUND", "connection failed", "select 1"):
        assert leak not in detail


def test_an_unreachable_database_still_answers_a_cross_origin_request(
    unreachable_db: TestClient,
) -> None:
    """The whole point: the error has to reach the SPA. An unhandled exception
    never passes back out through `CORSMiddleware`, so the browser reports a
    network failure and the real message is lost."""
    response = unreachable_db.post(
        "/session",
        json={"passphrase": PASSPHRASE, "name": ACTOR},
        headers={"Origin": "http://localhost:5173"},
    )

    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


# --- spec versioning (`/products/{id}/changes`, `/spec/changes`) ----------------


def test_changes_since_a_moment_report_a_newly_confirmed_claim(
    signed_in: TestClient, documented: uuid.UUID
) -> None:
    """Phase 3: "what changed since v1" is the log replayed twice and compared."""
    since = datetime.now(UTC) - timedelta(seconds=1)
    nodes = signed_in.get(f"/feature-scopes/{FEATURE_SCOPE_ID}").json()["nodes"]
    node = next(item for item in nodes if item["type"] == "requirement")
    signed_in.post(f"/nodes/{node['id']}/confirm")

    changes = signed_in.get(
        f"/products/{documented}/changes", params={"since": since.isoformat()}
    ).json()

    assert [claim["content"] for claim in changes["added"]] == [
        "The gateway must rate-limit per client IP."
    ]

    markdown = signed_in.get(
        f"/products/{documented}/spec/changes", params={"since": since.isoformat()}
    )
    assert markdown.headers["content-type"].startswith("text/markdown")
    assert "### Added" in markdown.text


def test_a_since_without_an_offset_is_read_as_utc(
    signed_in: TestClient, documented: uuid.UUID
) -> None:
    response = signed_in.get(
        f"/products/{documented}/changes", params={"since": "2026-01-01T00:00:00"}
    )
    assert response.status_code == 200


def test_changes_require_a_since(signed_in: TestClient, documented: uuid.UUID) -> None:
    assert signed_in.get(f"/products/{documented}/changes").status_code == 422


def test_changes_for_an_unknown_product_are_404(signed_in: TestClient) -> None:
    response = signed_in.get(
        f"/products/{uuid.uuid4()}/changes", params={"since": "2026-01-01T00:00:00Z"}
    )
    assert response.status_code == 404


# --- the feedback loop (`/products/{id}/feedback`) ------------------------------


def test_feedback_reports_a_first_human_ruling(
    signed_in: TestClient, documented: uuid.UUID
) -> None:
    nodes = signed_in.get(f"/feature-scopes/{FEATURE_SCOPE_ID}").json()["nodes"]
    signed_in.post(f"/nodes/{nodes[0]['id']}/reject")

    report = signed_in.get(f"/products/{documented}/feedback").json()

    assert report["overall"]["rejected"] == 1
    assert report["overall"]["acceptance_rate"] == 0.0
    assert report["guard_passes"] is True
    assert len(report["rejections"]) == 1


def test_feedback_for_an_unknown_product_is_404(signed_in: TestClient) -> None:
    assert signed_in.get(f"/products/{uuid.uuid4()}/feedback").status_code == 404


# --- Q&A (`/products/{id}/ask`) ------------------------------------------------


def test_ask_answers_from_confirmed_claims_with_citations(
    signed_in: TestClient, documented: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    nodes = signed_in.get(f"/feature-scopes/{FEATURE_SCOPE_ID}").json()["nodes"]
    node = next(item for item in nodes if item["type"] == "requirement")
    signed_in.post(f"/nodes/{node['id']}/confirm")

    async def call(prompt: str) -> str:
        assert "rate-limit per client IP" in prompt
        return '{"answer": "Per client IP [C1].", "citations": ["C1"]}'

    monkeypatch.setattr("atlas.api.routes.model_call", lambda: call)

    answer = signed_in.post(
        f"/products/{documented}/ask", json={"question": "How is it limited?"}
    ).json()

    assert answer["citations"][0]["node_id"] == node["id"]
    assert answer["evidence"] == "thin"


def test_an_answer_that_fails_the_gate_is_a_502(
    signed_in: TestClient, documented: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    nodes = signed_in.get(f"/feature-scopes/{FEATURE_SCOPE_ID}").json()["nodes"]
    signed_in.post(f"/nodes/{nodes[0]['id']}/confirm")

    async def call(prompt: str) -> str:
        return '{"answer": "Made up [C9].", "citations": ["C9"]}'

    monkeypatch.setattr("atlas.api.routes.model_call", lambda: call)

    response = signed_in.post(f"/products/{documented}/ask", json={"question": "?"})

    assert response.status_code == 502


def test_a_blank_question_is_a_422(signed_in: TestClient, documented: uuid.UUID) -> None:
    assert signed_in.post(f"/products/{documented}/ask", json={"question": ""}).status_code == 422


# --- Google Docs, the third source (2026-09-28) ---------------------------------

DOC_URL = "https://docs.google.com/document/d/1AbCdEfGhIjKlMnOpQrStUvWxYz0123/edit"


def test_the_account_to_share_docs_with_is_shown_before_connecting(
    client: TestClient, with_product: uuid.UUID
) -> None:
    """The PM needs the address before they can share anything with it."""
    response = client.get("/sources/google-docs")

    assert response.json() == {"account": GOOGLE_ACCOUNT["client_email"]}
    assert "PRIVATE KEY" not in response.text


def test_connecting_docs_stores_no_secret_and_names_the_account(
    client: TestClient, with_product: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_access(monkeypatch)

    response = client.post(
        f"/products/{with_product}/connections",
        json={"source_type": "gdoc", "host": "docs.google.com", "scope": DOC_URL},
    )

    assert response.status_code == 201
    connection = response.json()["connection"]
    assert connection["account"] == GOOGLE_ACCOUNT["client_email"]
    assert connection["host"] == "docs.google.com"
    assert connection["secret_hint"] == ""


def test_docs_cannot_be_connected_when_atlas_has_no_google_account(
    client: TestClient, with_product: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    from dataclasses import replace as dc_replace

    _stub_access(monkeypatch)
    app = client.app
    app.dependency_overrides[get_api_settings] = lambda: dc_replace(  # type: ignore[attr-defined]
        _settings(), google_service_accounts={}
    )

    response = client.post(
        f"/products/{with_product}/connections",
        json={"source_type": "gdoc", "host": "docs.google.com", "scope": DOC_URL},
    )

    assert response.status_code == 409
    assert "Google Docs" in response.json()["detail"]
    assert client.get("/sources/google-docs").json() == {"account": None}


def test_github_still_needs_a_token(client: TestClient, with_product: uuid.UUID) -> None:
    response = client.post(
        f"/products/{with_product}/connections",
        json={"source_type": "github_pr", "host": "github.com", "scope": "acme/gateway"},
    )

    assert response.status_code == 422


def test_a_docs_run_is_handed_atlas_s_own_account(
    client: TestClient, with_product: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    from atlas.pipeline import GoogleDocsCredential

    _stub_access(monkeypatch)
    connection_id = client.post(
        f"/products/{with_product}/connections",
        json={"source_type": "gdoc", "host": "docs.google.com", "scope": DOC_URL},
    ).json()["connection"]["id"]
    captured: list[Any] = []
    monkeypatch.setattr("atlas.api.routes.execute_run", lambda *a, **k: captured.append(k))

    response = client.post(
        f"/products/{with_product}/runs",
        json={"connection_id": connection_id, "target_kind": "gdoc", "target": DOC_URL},
    )

    assert response.status_code == 202
    (kwargs,) = captured
    assert isinstance(kwargs["credential"], GoogleDocsCredential)


def test_a_target_of_another_source_kind_is_refused(
    client: TestClient, with_product: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A doc URL on a GitHub connection used to fail deep inside the run; it is
    a form error."""
    connection_id = _connect(client, with_product, monkeypatch)

    response = client.post(
        f"/products/{with_product}/runs",
        json={"connection_id": connection_id, "target_kind": "gdoc", "target": DOC_URL},
    )

    assert response.status_code == 422


def test_another_workspace_s_google_account_is_never_used(
    client: TestClient, with_product: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Phase 4: one account per workspace. A workspace with no account of its own
    cannot borrow one configured for someone else -- which is what made a doc
    URL ingestible by every tenant when there was a single shared account."""
    from dataclasses import replace as dc_replace

    _stub_access(monkeypatch)
    elsewhere = uuid.uuid4()
    client.app.dependency_overrides[get_api_settings] = lambda: dc_replace(  # type: ignore[attr-defined]
        _settings(), google_service_accounts={elsewhere: GOOGLE_ACCOUNT}
    )

    response = client.post(
        f"/products/{with_product}/connections",
        json={"source_type": "gdoc", "host": "docs.google.com", "scope": DOC_URL},
    )

    assert response.status_code == 409
    assert client.get("/sources/google-docs").json() == {"account": None}


# --- admin gates sources (Phase 4) -----------------------------------------------
#
# Granting Atlas access to a repo, a Jira project or a doc is the sensitive act,
# so it is an admin's. Pulling from a source an admin already connected stays an
# editor's job -- that is reviewing work, not granting access.


def _as(client: TestClient, actor: str) -> None:
    client.post("/session", json={"passphrase": PASSPHRASE, "name": actor})


def test_an_editor_may_not_connect_a_source(
    client: TestClient, with_product: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_access(monkeypatch)
    _as(client, EDITOR_ONLY)

    response = client.post(
        f"/products/{with_product}/connections",
        json={
            "source_type": "github_pr",
            "host": "github.com",
            "scope": "acme/gateway",
            "secret": SECRET_TOKEN,
        },
    )

    assert response.status_code == 403
    assert "admin" in response.json()["detail"]


def test_an_editor_may_not_revoke_a_source(
    client: TestClient, with_product: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    connection_id = _connect(client, with_product, monkeypatch)
    _as(client, EDITOR_ONLY)

    assert client.delete(f"/connections/{connection_id}").status_code == 403


def test_an_editor_may_still_pull_from_a_connected_source(
    client: TestClient, with_product: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    connection_id = _connect(client, with_product, monkeypatch)
    monkeypatch.setattr("atlas.api.routes.execute_run", lambda *a, **k: None)
    _as(client, EDITOR_ONLY)

    response = client.post(
        f"/products/{with_product}/runs",
        json={"connection_id": connection_id, "target_kind": "github_pr", "target": "acme/web#7"},
    )

    assert response.status_code == 202


# --- comment threads (Phase 4) ---------------------------------------------------


def test_any_member_may_comment_on_a_claim_and_everyone_reads_the_thread(
    client: TestClient, seeded: sessionmaker[Session]
) -> None:
    """Viewers included (2026-09-30): discussion is not a ruling."""
    _as(client, VIEWER)
    node = client.get(f"/feature-scopes/{FEATURE_SCOPE_ID}").json()["nodes"][0]

    posted = client.post(f"/nodes/{node['id']}/comments", json={"body": "Is this still true?"})
    _as(client, ACTOR)
    client.post(f"/nodes/{node['id']}/comments", json={"body": "Yes — see the Sept doc."})

    assert posted.status_code == 201
    thread = client.get(f"/nodes/{node['id']}/comments").json()
    assert [(c["author"], c["body"]) for c in thread] == [
        (VIEWER, "Is this still true?"),
        (ACTOR, "Yes — see the Sept doc."),
    ]


def test_commenting_does_not_rule_on_the_claim(
    client: TestClient, seeded: sessionmaker[Session]
) -> None:
    _as(client, VIEWER)
    node = client.get(f"/feature-scopes/{FEATURE_SCOPE_ID}").json()["nodes"][0]

    client.post(f"/nodes/{node['id']}/comments", json={"body": "Looks right to me."})

    after = client.get(f"/feature-scopes/{FEATURE_SCOPE_ID}").json()["nodes"][0]
    assert after["status"] == node["status"]


def test_a_comment_on_an_unknown_claim_is_404(
    client: TestClient, seeded: sessionmaker[Session]
) -> None:
    _as(client, ACTOR)

    response = client.post(f"/nodes/{uuid.uuid4()}/comments", json={"body": "hello"})

    assert response.status_code == 404


def test_a_blank_comment_is_422(client: TestClient, seeded: sessionmaker[Session]) -> None:
    _as(client, ACTOR)
    node = client.get(f"/feature-scopes/{FEATURE_SCOPE_ID}").json()["nodes"][0]

    assert client.post(f"/nodes/{node['id']}/comments", json={"body": "  "}).status_code == 422


def test_a_feature_reports_how_many_comments_each_claim_has(
    client: TestClient, seeded: sessionmaker[Session]
) -> None:
    _as(client, ACTOR)
    node = client.get(f"/feature-scopes/{FEATURE_SCOPE_ID}").json()["nodes"][0]
    client.post(f"/nodes/{node['id']}/comments", json={"body": "one"})
    client.post(f"/nodes/{node['id']}/comments", json={"body": "two"})

    detail = client.get(f"/feature-scopes/{FEATURE_SCOPE_ID}").json()

    assert detail["comment_counts"] == {node["id"]: 2}


# --- workspace activity (Phase 4, admin only) -------------------------------------


def test_an_admin_sees_the_workspace_s_activity(
    client: TestClient, seeded: sessionmaker[Session]
) -> None:
    _as(client, ACTOR)
    node = client.get(f"/feature-scopes/{FEATURE_SCOPE_ID}").json()["nodes"][0]
    client.post(f"/nodes/{node['id']}/confirm")

    report = client.get("/workspace/activity").json()

    assert report["people"] == [ACTOR]
    assert report["weeks"][-1]["rulings_by_person"] == {ACTOR: 1}


def test_activity_is_admin_only(client: TestClient, seeded: sessionmaker[Session]) -> None:
    _as(client, EDITOR_ONLY)

    assert client.get("/workspace/activity").status_code == 403
