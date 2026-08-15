"""Per-product source credentials: the table, its CRUD, and encryption at the boundary.

This module carries the one deliberate reversal of a stated CLAUDE.md
non-negotiable ("no secret ever lands in the database"), argued in
`docs/architecture/product-model-and-frontend-rebuild-v1.md` §6 and logged in
`docs/decisions/2026-08-15-connections-and-ui-ingestion.md`. The rule held while
there was one GitHub token and one Jira token in `.env`; it cannot hold when a PM
connects five products' worth of separate orgs and sites through a browser, and
the honest response is to change the posture rather than to pretend a browser
can reach `.env`.

The posture that replaces it, and where each half of it lives:

* **Encrypted at rest, key outside the database** — `seal`/`unseal`, Fernet
  (authenticated AES-CBC + HMAC), key from `ATLAS_SECRET_KEY`. A database dump
  alone yields ciphertext. Nothing is hand-rolled here.
* **Write-only through the API** — `ConnectionView` is the only shape any
  endpoint returns, and it *has no field a secret could occupy*. That is why the
  read model exists separately from the ORM row: excluding a field is something
  you can forget, and not having one is not.
* **Never logged** — `SecretError` is raised `from None` and never formats the
  plaintext, because an exception is the single most likely thing to be printed.
* **Revocation is a delete** — a real one. A soft delete leaves usable ciphertext
  in the table, which is exactly what revoking is supposed to prevent.

Connections are ordinary mutable rows rather than events, and that is not a new
exception to event-sourcing: slice 1D already put `workspace`/`workspace_member`
in tables because membership is operational state, not a claim about the world.
A credential is the same kind of thing — and it *must* be deletable, which an
append-only log cannot express. The log still records **that** a source was
connected or revoked and by whom; it never records the secret.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from cryptography.fernet import Fernet, InvalidToken
from pydantic import Field
from sqlalchemy import DateTime, Enum, ForeignKey, Index, LargeBinary, Text, Uuid, delete, select
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, Session, mapped_column
from sqlalchemy.sql import func

from atlas.models.schema import AtlasModel, ConnectionPayload, EventType, NonBlankStr, SourceType
from atlas.storage.db import Base
from atlas.storage.tables import append_event

__all__ = [
    "Connection",
    "ConnectionView",
    "SecretError",
    "create_connection",
    "generate_secret_key",
    "get_connection",
    "list_connections",
    "mark_used",
    "revoke_connection",
    "seal",
    "unseal",
]

# Same dialect-portable UUID as storage/tables.py, and for the same reason: on
# SQLite an unrecognized `UUID` type name gets NUMERIC affinity, which mangles an
# all-digit hex id on the way back out.
_UUID = PG_UUID(as_uuid=True).with_variant(Uuid(as_uuid=True), "sqlite")

#: How many trailing characters of a credential the UI may show. Enough to answer
#: "is this the token I think it is?" and far too little to be one.
_HINT_LENGTH = 4


class SecretError(Exception):
    """Encryption or decryption failed.

    Deliberately carries no plaintext and no chained cause. `cryptography` does
    not put the secret in its exceptions, but the wrapper is where a future
    edit would be tempted to add context like "while decrypting <token>", and
    the type is the place to say that is not allowed.
    """


def generate_secret_key() -> str:
    """A fresh `ATLAS_SECRET_KEY`. Used by tests and by whoever sets up an env."""
    return Fernet.generate_key().decode()


def _cipher(key: str) -> Fernet:
    try:
        return Fernet(key.encode())
    except (ValueError, TypeError):
        raise SecretError(
            "ATLAS_SECRET_KEY is not a valid Fernet key "
            '(generate one with `python -c "from cryptography.fernet import Fernet; '
            'print(Fernet.generate_key().decode())"`)'
        ) from None


def seal(secret: str, key: str) -> bytes:
    """Encrypt a credential for storage."""
    return _cipher(key).encrypt(secret.encode())


def unseal(ciphertext: bytes, key: str) -> str:
    """Decrypt a stored credential, or fail.

    Fernet is *authenticated*, so a row edited in the database fails here rather
    than decrypting to some other credential — which is what makes "a database
    compromise yields ciphertext" true in both directions.
    """
    try:
        return _cipher(key).decrypt(ciphertext).decode()
    except InvalidToken:
        raise SecretError(
            "stored credential could not be decrypted — the row was altered, or "
            "ATLAS_SECRET_KEY has changed since it was written"
        ) from None


class Connection(Base):
    """One credential bound to one source, for one product, with its scope.

    Mutable by design (see the module docstring). The `workspace_id` column is
    the tenant boundary and carries the same RLS policy `event_log` does —
    application-level filtering in every query here is the first lock, the policy
    is the second.
    """

    __tablename__ = "connection"
    __table_args__ = (Index("ix_connection_workspace_product", "workspace_id", "product_id"),)

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        _UUID, ForeignKey("workspace.id", ondelete="CASCADE"), nullable=False
    )
    #: The product this credential belongs to. Not a foreign key: a product is a
    #: *projection* of the event log, so there is no table to point at.
    product_id: Mapped[uuid.UUID] = mapped_column(_UUID, nullable=False)
    source_type: Mapped[SourceType] = mapped_column(
        Enum(
            SourceType,
            name="source_type",
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
    )
    #: Display only, except for Jira where it is also the auth username (Jira
    #: Cloud authenticates email + API token). Never a secret in either case.
    account: Mapped[str] = mapped_column(Text, nullable=False)
    host: Mapped[str] = mapped_column(Text, nullable=False)
    scope: Mapped[str] = mapped_column(Text, nullable=False)
    secret_ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    #: Last few characters of the credential, so a PM can tell two tokens apart
    #: without either being shown. Stored rather than derived, because deriving
    #: it would mean decrypting a secret in order to render a list.
    secret_hint: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_by: Mapped[str] = mapped_column(Text, nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ConnectionView(AtlasModel):
    """What an endpoint may say about a connection. The whole of it.

    There is no `secret` field, no `ciphertext` field, and no `Any`-typed extras
    bag — so a secret cannot reach a response by someone forgetting to exclude
    it. `tests/test_connections.py` asserts that absence directly, and
    `tests/test_api.py` asserts it again over the generated OpenAPI schema, which
    is what the frontend's types are built from.
    """

    id: uuid.UUID
    product_id: uuid.UUID
    source_type: SourceType
    account: NonBlankStr
    host: NonBlankStr
    scope: NonBlankStr
    secret_hint: str = Field(max_length=_HINT_LENGTH)
    created_at: datetime
    created_by: NonBlankStr
    last_used_at: datetime | None = None

    @classmethod
    def of(cls, connection: Connection) -> ConnectionView:
        return cls(
            id=connection.id,
            product_id=connection.product_id,
            source_type=connection.source_type,
            account=connection.account,
            host=connection.host,
            scope=connection.scope,
            secret_hint=connection.secret_hint,
            created_at=connection.created_at,
            created_by=connection.created_by,
            last_used_at=connection.last_used_at,
        )


def create_connection(
    session: Session,
    *,
    workspace_id: uuid.UUID,
    product_id: uuid.UUID,
    source_type: SourceType,
    account: str,
    host: str,
    scope: str,
    secret: str,
    actor: str,
    key: str,
) -> Connection:
    """Store a credential, encrypted, and append the audit event for it.

    The event is written in the same transaction as the row: a connection that
    exists with no record of who made it is an audit hole, and the two must
    therefore succeed or fail together.
    """
    if not secret.strip():
        raise ValueError("secret must not be blank or whitespace-only")
    connection = Connection(
        workspace_id=workspace_id,
        product_id=product_id,
        source_type=source_type,
        account=account,
        host=host,
        scope=scope,
        secret_ciphertext=seal(secret, key),
        secret_hint=secret[-_HINT_LENGTH:],
        created_by=actor,
    )
    session.add(connection)
    session.flush()
    append_event(
        session,
        event_type=EventType.CONNECTION_CREATED,
        payload=ConnectionPayload(
            connection_id=connection.id,
            product_id=product_id,
            source_type=source_type,
            account=account,
            host=host,
            scope=scope,
        ).model_dump(mode="json"),
        actor=actor,
        workspace_id=workspace_id,
    )
    return connection


def list_connections(
    session: Session, *, workspace_id: uuid.UUID, product_id: uuid.UUID | None = None
) -> list[Connection]:
    """Every connection in the workspace, narrowed to one product when asked."""
    stmt = select(Connection).where(Connection.workspace_id == workspace_id)
    if product_id is not None:
        stmt = stmt.where(Connection.product_id == product_id)
    return list(session.execute(stmt.order_by(Connection.created_at)).scalars())


def get_connection(
    session: Session, *, workspace_id: uuid.UUID, connection_id: uuid.UUID
) -> Connection | None:
    """One connection, or None. Scoped to the workspace so a connection in
    another tenant is *invisible* rather than forbidden — the same property
    `api/routes.py::_require_node` relies on."""
    stmt = select(Connection).where(
        Connection.id == connection_id, Connection.workspace_id == workspace_id
    )
    return session.execute(stmt).scalar_one_or_none()


def revoke_connection(
    session: Session, *, workspace_id: uuid.UUID, connection_id: uuid.UUID, actor: str
) -> bool:
    """Delete a credential outright. Returns False when there was nothing to delete.

    A real delete, not a flag: the point of revocation is that the ciphertext
    stops existing. The audit event records that it happened, which is the part
    that *should* be permanent.
    """
    connection = get_connection(session, workspace_id=workspace_id, connection_id=connection_id)
    if connection is None:
        return False
    payload = ConnectionPayload(
        connection_id=connection.id,
        product_id=connection.product_id,
        source_type=connection.source_type,
        account=connection.account,
        host=connection.host,
        scope=connection.scope,
    )
    session.execute(
        delete(Connection).where(
            Connection.id == connection_id, Connection.workspace_id == workspace_id
        )
    )
    append_event(
        session,
        event_type=EventType.CONNECTION_REVOKED,
        payload=payload.model_dump(mode="json"),
        actor=actor,
        workspace_id=workspace_id,
    )
    return True


def mark_used(session: Session, connection: Connection, *, at: datetime) -> None:
    """Record that a run used this credential — the "last used" line the Sources
    screen shows, and the signal that a connection is stale rather than merely
    old."""
    connection.last_used_at = at
    session.add(connection)
