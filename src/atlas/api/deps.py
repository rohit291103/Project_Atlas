"""The auth seam and the database seam -- the two things every route depends on.

`get_principal` is the seam that matters. Over HTTP, `workspace_id` and `actor`
are attacker-controlled unless something translates a *session* into them, and
that translation is the only real complexity this module hides
(`docs/decisions/2026-08-11-api-frontend-module-boundary.md` §4).

**No route ever reads `workspace_id` or `actor` from a request body, query string
or header.** That is structural, not a convention to remember: routes receive a
frozen `Principal` and pass its fields to `storage/confirmations.py`, whose
`add_node` already builds its Node from fields precisely so a request body cannot
choose its own `workspace_id`. `Principal` is the other half of that design.

The seam is fixed; the *implementation* behind it is deliberately minimal and
Phase-1-only -- a signed cookie behind a shared passphrase, because Phase 1 has
one workspace (`DEFAULT_WORKSPACE_ID` until slice 1D) and one PM. Slice 1D's real
workspace RBAC replaces the body of `get_principal` and nothing else.
"""

from __future__ import annotations

import hmac
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from functools import lru_cache
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy.orm import Session, sessionmaker

from atlas.config import ApiSettings
from atlas.models.schema import ActorKind, Role
from atlas.storage.db import get_engine, get_sessionmaker, session_scope
from atlas.storage.rbac import find_membership, scope_to_workspace

__all__ = [
    "Principal",
    "PrincipalDep",
    "WriterDep",
    "require_writer",
    "SessionDep",
    "SessionFactoryDep",
    "SettingsDep",
    "get_session_factory",
    "SESSION_COOKIE",
    "get_api_settings",
    "get_principal",
    "get_session",
    "issue_session",
    "verify_passphrase",
]

SESSION_COOKIE = "atlas_session"
#: A review sitting is one working session, so a day of validity is generous
#: without leaving a signed cookie useful indefinitely.
SESSION_MAX_AGE_SECONDS = 24 * 60 * 60

#: A client sets this to declare itself a machine, so its writes are logged as
#: `ActorKind.AUTOMATED` rather than inheriting the humanness an authenticated
#: session would otherwise imply. Playwright sets it for the whole browser suite
#: via `extraHTTPHeaders`. Only this direction is claimable -- see `Principal`.
AUTOMATED_ACTOR_HEADER = "X-Atlas-Automated"
_SESSION_SALT = "atlas-session-v1"


@dataclass(frozen=True)
class Principal:
    """Who is acting, where, and with what authority. Frozen: a route cannot
    rewrite its own identity.

    `actor` lands verbatim on every Event this request writes, so the audit trail
    names a real person rather than a placeholder (TRD §9 -- every Event *is* the
    audit record). `workspace_id` and `role` come from the `workspace_member`
    row, never from the request or the cookie: membership is a server-side fact,
    so removing someone takes effect on their next request rather than whenever
    their cookie expires.

    `actor_kind` answers a question `actor` never could: was a person behind
    this request? An authenticated session is the *default* evidence of one, but
    it is not proof -- the browser suite signs in through the same form and
    holds the same cookie, which is how it confirmed 6 real claims under a
    person's name on 2026-08-16. A client may therefore *downgrade* itself to
    automated with the `X-Atlas-Automated` header. Only that direction is
    claimable: understating humanness can make the guard metric more
    conservative but never falsely reassuring, whereas letting a caller claim
    HUMAN would hand a bot the one label the metric trusts.
    """

    workspace_id: uuid.UUID
    actor: str
    role: Role
    actor_kind: ActorKind


@lru_cache(maxsize=1)
def get_api_settings() -> ApiSettings:
    """Read the API's env once per process (see `ApiSettings` on why it is not
    `Settings` -- the web-facing process has no business holding a GitHub token)."""
    return ApiSettings.from_env()


@lru_cache(maxsize=1)
def _session_factory(database_url: str) -> sessionmaker[Session]:
    """One engine (and so one connection pool) per process, not per request."""
    return get_sessionmaker(get_engine(database_url))


def get_session() -> Iterator[Session]:
    """Yield a request-scoped session that commits on success, rolls back on error.

    `session_scope` is already the transaction seam the CLI uses; the API reuses
    it rather than introducing a unit-of-work pattern over the top.
    """
    with session_scope(_session_factory(get_api_settings().supabase_db_url)) as session:
        yield session


#: The three things a route may depend on. Declared as `Annotated` aliases so a
#: route signature reads as types rather than as call-in-a-default, and so the
#: dependency set stays small enough to enumerate here.
SettingsDep = Annotated[ApiSettings, Depends(get_api_settings)]
SessionDep = Annotated[Session, Depends(get_session)]


def get_session_factory(settings: SettingsDep) -> sessionmaker[Session]:
    """The session *factory*, for work that outlives the request.

    A background ingestion run cannot borrow the request's session -- that one is
    committed and closed the moment the 202 goes out. It opens its own
    workspace-scoped transactions instead, through the same factory, so there is
    still exactly one engine and one pool per process.

    Takes `settings` as a dependency rather than calling `get_api_settings()`
    directly, so a test that overrides settings overrides this too -- otherwise
    the override is silently bypassed and the background path reads the real
    environment.
    """
    return _session_factory(settings.supabase_db_url)


SessionFactoryDep = Annotated["sessionmaker[Session]", Depends(get_session_factory)]


def _serializer(settings: ApiSettings) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(settings.session_secret, salt=_SESSION_SALT)


def verify_passphrase(candidate: str, settings: ApiSettings) -> bool:
    """Compare in constant time -- a byte-by-byte early return leaks the
    passphrase one character at a time to anyone who can measure the response."""
    return hmac.compare_digest(candidate, settings.app_passphrase)


def issue_session(actor: str, settings: ApiSettings) -> str:
    """Sign the cookie value that `get_principal` will read back.

    Only the actor's name is carried. `workspace_id` is deliberately *not* in the
    cookie: it is a server-side fact, and putting it in a client-held token would
    make the tenant boundary something the client contributes to.
    """
    return _serializer(settings).dumps({"actor": actor})


def get_principal(request: Request, settings: SettingsDep, session: SessionDep) -> Principal:
    """Resolve the signed session cookie into a `Principal`.

    401 when there is no valid session; **403 when there is one but the person is
    not a member of any workspace** -- a real distinction worth keeping: the
    first says "prove who you are", the second says "we know who you are, and
    that is not enough".

    The transaction is then pinned to the resolved workspace, so the RLS policies
    have something to enforce for every query the request goes on to make.
    """
    cookie = request.cookies.get(SESSION_COOKIE)
    if not cookie:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "not signed in")
    try:
        payload = _serializer(settings).loads(cookie, max_age=SESSION_MAX_AGE_SECONDS)
    except SignatureExpired as expired:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "session expired") from expired
    except BadSignature as bad:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid session") from bad

    actor = payload.get("actor", "") if isinstance(payload, dict) else ""
    if not isinstance(actor, str) or not actor.strip():
        # A signed-but-empty actor would write a blank audit record; `append_event`
        # would refuse it anyway, but failing here says why.
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid session")

    membership = find_membership(session, actor)
    if membership is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"{actor} is not a member of any workspace")
    scope_to_workspace(session, membership.workspace_id)
    return Principal(
        workspace_id=membership.workspace_id,
        actor=membership.actor,
        role=membership.role,
        actor_kind=(
            ActorKind.AUTOMATED if request.headers.get(AUTOMATED_ACTOR_HEADER) else ActorKind.HUMAN
        ),
    )


PrincipalDep = Annotated[Principal, Depends(get_principal)]


def require_writer(principal: PrincipalDep) -> Principal:
    """The authorization half of RBAC: a viewer may read the draft but not rule
    on it (TRD §9). Confirming is the product's unit of truth -- "a draft until a
    human acts on it" is hollow if every reader can act."""
    if not principal.role.can_write:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"role {principal.role.value!r} may review but not confirm, edit or add",
        )
    return principal


WriterDep = Annotated[Principal, Depends(require_writer)]
