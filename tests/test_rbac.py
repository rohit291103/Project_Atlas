"""Workspace membership and the RLS scope (slice 1D, TRD Sec9).

`find_membership` is ordinary SQL and is tested against SQLite like the rest of
storage. `scope_to_workspace` is not: it issues a Postgres `set_config`, and
SQLite has neither that function nor row-level security. So what is asserted
here is that it *issues the statement on Postgres and stays silent elsewhere* --
which is the seam. **The policies themselves are not exercised by this suite**;
they are DDL in migration `b7c2f1a45d90` and are only live once that migration
has been applied to a real Postgres database.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from atlas.models.schema import Role
from atlas.storage.db import Base, get_engine, get_sessionmaker, session_scope
from atlas.storage.rbac import (
    WORKSPACE_SETTING,
    MembershipError,
    create_workspace,
    find_membership,
    scope_to_workspace,
    seat_member,
    workspace_session,
)
from atlas.storage.tables import Workspace, WorkspaceMember

WORKSPACE_A = uuid.UUID(int=0)
WORKSPACE_B = uuid.uuid4()


@pytest.fixture
def session_factory() -> sessionmaker[Session]:
    engine: Engine = get_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return get_sessionmaker(engine)


def _seed(session: Session) -> None:
    session.add(Workspace(id=WORKSPACE_A, name="Acme"))
    session.add(Workspace(id=WORKSPACE_B, name="Globex"))
    session.add(WorkspaceMember(workspace_id=WORKSPACE_A, actor="Priya", role=Role.EDITOR))
    session.add(WorkspaceMember(workspace_id=WORKSPACE_A, actor="Sam", role=Role.VIEWER))
    session.add(WorkspaceMember(workspace_id=WORKSPACE_B, actor="Dan", role=Role.ADMIN))
    session.flush()


def test_membership_resolves_workspace_and_role(session_factory: sessionmaker[Session]) -> None:
    with session_scope(session_factory) as session:
        _seed(session)

        membership = find_membership(session, "Priya")

    assert membership is not None
    assert membership.workspace_id == WORKSPACE_A
    assert membership.role is Role.EDITOR


def test_a_stranger_has_no_membership(session_factory: sessionmaker[Session]) -> None:
    with session_scope(session_factory) as session:
        _seed(session)

        assert find_membership(session, "Outsider") is None


def test_membership_does_not_leak_across_workspaces(
    session_factory: sessionmaker[Session],
) -> None:
    """The tenant boundary: Dan's workspace is not Priya's, and nothing about
    being a member somewhere grants membership everywhere."""
    with session_scope(session_factory) as session:
        _seed(session)

        dan = find_membership(session, "Dan")

    assert dan is not None
    assert dan.workspace_id == WORKSPACE_B


def test_membership_is_case_and_whitespace_exact(
    session_factory: sessionmaker[Session],
) -> None:
    """`actor` is the same string that lands on every Event, so a near-miss must
    not silently resolve to someone else's membership."""
    with session_scope(session_factory) as session:
        _seed(session)

        assert find_membership(session, "priya") is None
        assert find_membership(session, " Priya") is None


def test_membership_in_two_workspaces_resolves_deterministically(
    session_factory: sessionmaker[Session],
) -> None:
    """Phase 1 has no workspace switcher, but the answer must not change between
    two identical requests."""
    with session_scope(session_factory) as session:
        _seed(session)
        session.add(WorkspaceMember(workspace_id=WORKSPACE_B, actor="Priya", role=Role.VIEWER))
        session.flush()

        first = find_membership(session, "Priya")
        second = find_membership(session, "Priya")

    assert first == second


# --- the RLS scope --------------------------------------------------------------


class _FakeSession:
    """Records what would be sent to the database, for the two dialect cases."""

    def __init__(self, dialect: str) -> None:
        self.dialect = dialect
        self.statements: list[tuple[str, Any]] = []

    def get_bind(self) -> Any:
        session = self

        class _Bind:
            dialect = type("D", (), {"name": session.dialect})()

        return _Bind()

    def execute(self, statement: Any, params: Any = None) -> None:
        self.statements.append((str(statement), params))


def test_scope_sets_a_transaction_local_setting_on_postgres() -> None:
    session = _FakeSession("postgresql")

    scope_to_workspace(session, WORKSPACE_B)  # type: ignore[arg-type]

    (statement, params) = session.statements[0]
    assert WORKSPACE_SETTING in statement
    # `true` is the is_local flag: transaction-scoped, so the setting cannot leak
    # to the next request that borrows this pooled connection.
    assert statement.rstrip().endswith("true)")
    assert params == {"workspace_id": str(WORKSPACE_B)}


def test_scope_is_a_no_op_where_there_is_no_row_level_security() -> None:
    session = _FakeSession("sqlite")

    scope_to_workspace(session, WORKSPACE_B)  # type: ignore[arg-type]

    assert session.statements == []


def test_workspace_session_scopes_the_transaction_it_opens(
    session_factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The RLS policy is FORCEd, so it binds the application's own role: a
    transaction that never sets the setting reads zero rows and fails every
    insert. Pairing the two here is what stops a caller opening an unscoped one."""
    scoped: list[uuid.UUID] = []
    monkeypatch.setattr(
        "atlas.storage.rbac.scope_to_workspace",
        lambda session, workspace_id: scoped.append(workspace_id),
    )

    with workspace_session(session_factory, WORKSPACE_A):
        pass

    assert scoped == [WORKSPACE_A]


def test_workspace_session_commits_like_session_scope(
    session_factory: sessionmaker[Session],
) -> None:
    with workspace_session(session_factory, WORKSPACE_A) as session:
        session.add(Workspace(id=WORKSPACE_A, name="Acme"))

    with workspace_session(session_factory, WORKSPACE_A) as session:
        assert session.get(Workspace, WORKSPACE_A) is not None


def test_the_cli_never_opens_an_unscoped_transaction() -> None:
    """A grep with a reason. Every CLI command touches `event_log`, so one that
    slips back to a bare `session_scope` would work perfectly against SQLite in
    tests and silently read nothing in production once RLS is on -- the failure
    mode no unit test would catch."""
    from pathlib import Path

    source = (Path(__file__).parent.parent / "src" / "atlas" / "cli.py").read_text()

    assert "session_scope(" not in source
    assert "workspace_session(" in source


# --- provisioning (operator-only, over the owner connection) --------------------


def test_a_created_workspace_can_seat_a_member_who_then_resolves_to_it(
    session_factory: sessionmaker[Session],
) -> None:
    with session_scope(session_factory) as session:
        workspace_id = create_workspace(session, "PM measurement")
        seat_member(session, workspace_id, "Priya Shah", Role.ADMIN)

        membership = find_membership(session, "Priya Shah")

    assert membership is not None
    assert (membership.workspace_id, membership.role) == (workspace_id, Role.ADMIN)


def test_seating_someone_already_in_another_workspace_is_refused(
    session_factory: sessionmaker[Session],
) -> None:
    """A person in two workspaces resolves to the earliest, so seating them in a
    second one would sign them in somewhere else without a word. Refused."""
    with session_scope(session_factory) as session:
        _seed(session)
        fresh = create_workspace(session, "PM measurement")

        with pytest.raises(MembershipError, match="already a member"):
            seat_member(session, fresh, "Priya", Role.ADMIN)


def test_reseating_in_the_same_workspace_changes_the_role(
    session_factory: sessionmaker[Session],
) -> None:
    with session_scope(session_factory) as session:
        _seed(session)
        seat_member(session, WORKSPACE_A, "Priya", Role.ADMIN)

        membership = find_membership(session, "Priya")

    assert membership is not None and membership.role is Role.ADMIN


@pytest.mark.parametrize("name", ["", "   ", " Priya", "Priya "])
def test_a_name_that_could_never_be_typed_at_sign_in_is_refused(
    session_factory: sessionmaker[Session], name: str
) -> None:
    """Membership matches the sign-in name exactly, so a stray space seats a
    member who can never sign in -- and the measurement session would open on a
    403 in front of the PM."""
    with session_scope(session_factory) as session:
        workspace_id = create_workspace(session, "PM measurement")

        with pytest.raises(MembershipError):
            seat_member(session, workspace_id, name, Role.ADMIN)


def test_seating_into_a_workspace_that_does_not_exist_is_refused(
    session_factory: sessionmaker[Session],
) -> None:
    with (
        session_scope(session_factory) as session,
        pytest.raises(MembershipError, match="no workspace"),
    ):
        seat_member(session, uuid.uuid4(), "Priya Shah", Role.ADMIN)
