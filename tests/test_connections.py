"""Connections: encryption at the boundary, and a secret that cannot get out.

Written test-first per the `tdd` skill, which names the encryption round-trip
explicitly. Two of these tests encode *rules* rather than behaviour, and are the
ones worth keeping if the rest were ever thinned:

* `test_connection_view_has_no_field_that_could_hold_a_secret` — the structural
  version of "no endpoint returns a secret", in the spirit of `source_refs`
  having `min_length=1`. Forgetting to exclude a field cannot leak one, because
  the read model has nowhere to put it.
* `test_tampered_ciphertext_is_refused` — Fernet is authenticated, so a row
  edited in the database fails to decrypt rather than yielding a different
  credential. That is the property that makes "database compromise alone yields
  ciphertext" true in both directions.
"""

from __future__ import annotations

import uuid

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from atlas.models.schema import ActorKind, SourceType
from atlas.storage.connections import (
    Connection,
    ConnectionView,
    SecretError,
    create_connection,
    generate_secret_key,
    get_connection,
    list_connections,
    revoke_connection,
    seal,
    unseal,
)
from atlas.storage.db import Base
from atlas.storage.projections import load_projection

WORKSPACE = uuid.UUID(int=1)
OTHER_WORKSPACE = uuid.UUID(int=2)
PRODUCT = uuid.UUID(int=7)
KEY = Fernet.generate_key().decode()


@pytest.fixture
def session() -> Session:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def _create(session: Session, **overrides: object) -> Connection:
    kwargs: dict[str, object] = {
        "workspace_id": WORKSPACE,
        "product_id": PRODUCT,
        "source_type": SourceType.GITHUB_PR,
        "account": "atlas-bot",
        "host": "github.com",
        "scope": "acme/web",
        "secret": "ghp_supersecrettoken1234",
        "actor": "Priya",
        "actor_kind": ActorKind.HUMAN,
        "key": KEY,
    }
    kwargs.update(overrides)
    return create_connection(session, **kwargs)  # type: ignore[arg-type]


# --- encryption ----------------------------------------------------------------


def test_seal_unseal_round_trips() -> None:
    assert unseal(seal("ghp_token", KEY), KEY) == "ghp_token"


def test_ciphertext_does_not_contain_the_plaintext() -> None:
    """The point of the exercise: a database dump yields no credential."""
    assert b"ghp_token" not in seal("ghp_token", KEY)


def test_seal_is_not_deterministic() -> None:
    """Fernet carries a random IV, so two connections holding the same token do
    not produce matching rows — otherwise the table leaks *which* credentials are
    reused across products without decrypting anything."""
    assert seal("ghp_token", KEY) != seal("ghp_token", KEY)


def test_tampered_ciphertext_is_refused() -> None:
    ciphertext = bytearray(seal("ghp_token", KEY))
    ciphertext[-1] ^= 0x01
    with pytest.raises(SecretError):
        unseal(bytes(ciphertext), KEY)


def test_wrong_key_is_refused() -> None:
    with pytest.raises(SecretError):
        unseal(seal("ghp_token", KEY), generate_secret_key())


def test_malformed_key_fails_with_a_message_that_names_the_env_var() -> None:
    with pytest.raises(SecretError, match="ATLAS_SECRET_KEY"):
        seal("ghp_token", "not-a-fernet-key")


def test_secret_error_never_repeats_the_secret() -> None:
    """An exception is the most likely thing to be logged, so it is the most
    likely thing to leak. Same discipline as the `ALTER ROLE` redaction fix."""
    try:
        unseal(seal("ghp_token", KEY), generate_secret_key())
    except SecretError as caught:
        assert "ghp_token" not in str(caught)
        assert caught.__cause__ is None  # `from None` — a chained cause prints too


# --- the read model ------------------------------------------------------------


def test_connection_view_has_no_field_that_could_hold_a_secret() -> None:
    forbidden = {"secret", "secret_ciphertext", "token", "api_token", "password", "credential"}
    assert not forbidden & set(ConnectionView.model_fields)


def test_view_shows_a_fingerprint_and_not_the_credential(session: Session) -> None:
    connection = _create(session)
    view = ConnectionView.of(connection)
    assert view.secret_hint == "1234"
    assert "supersecret" not in view.model_dump_json()


# --- CRUD ----------------------------------------------------------------------


def test_create_then_read_back_the_secret(session: Session) -> None:
    connection = _create(session)
    assert unseal(connection.secret_ciphertext, KEY) == "ghp_supersecrettoken1234"


def test_create_appends_an_audit_event_carrying_no_secret(session: Session) -> None:
    _create(session)
    session.commit()
    events = load_projection(session, workspace_id=WORKSPACE)
    assert events.nodes == {}  # a connection is not domain truth
    payloads = _event_payloads(session)
    assert payloads and "supersecret" not in str(payloads)


def test_list_is_scoped_to_one_product(session: Session) -> None:
    _create(session)
    _create(session, product_id=uuid.UUID(int=8), scope="acme/api")
    session.commit()
    found = list_connections(session, workspace_id=WORKSPACE, product_id=PRODUCT)
    assert [connection.scope for connection in found] == ["acme/web"]


def test_a_connection_in_another_workspace_is_invisible(session: Session) -> None:
    """Application-level scoping, belt to the RLS policy's braces. SQLite cannot
    exercise the policy at all, which is why `scripts/verify_rls.py` exists."""
    created = _create(session, workspace_id=OTHER_WORKSPACE)
    session.commit()
    assert get_connection(session, workspace_id=WORKSPACE, connection_id=created.id) is None


def test_revoke_removes_the_row_rather_than_flagging_it(session: Session) -> None:
    """A credential must actually be *gone*: a soft delete leaves usable
    ciphertext behind, which is the thing revocation exists to prevent."""
    created = _create(session)
    session.commit()
    assert revoke_connection(
        session,
        workspace_id=WORKSPACE,
        connection_id=created.id,
        actor="P",
        actor_kind=ActorKind.HUMAN,
    )
    session.commit()
    assert get_connection(session, workspace_id=WORKSPACE, connection_id=created.id) is None


def test_revoking_something_that_is_gone_reports_it(session: Session) -> None:
    assert not revoke_connection(
        session,
        workspace_id=WORKSPACE,
        connection_id=uuid.uuid4(),
        actor="P",
        actor_kind=ActorKind.HUMAN,
    )


def test_revoke_appends_an_audit_event(session: Session) -> None:
    created = _create(session)
    session.commit()
    before = len(_event_payloads(session))
    revoke_connection(
        session,
        workspace_id=WORKSPACE,
        connection_id=created.id,
        actor="Priya",
        actor_kind=ActorKind.HUMAN,
    )
    session.commit()
    assert len(_event_payloads(session)) == before + 1


def test_blank_secret_is_refused(session: Session) -> None:
    with pytest.raises(ValueError, match="secret"):
        _create(session, secret="   ")


def _event_payloads(session: Session) -> list[dict[str, object]]:
    from sqlalchemy import select

    from atlas.storage.tables import EventLog

    return [row.payload for row in session.execute(select(EventLog)).scalars()]
