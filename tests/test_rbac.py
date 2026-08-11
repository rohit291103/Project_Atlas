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
from atlas.storage.rbac import WORKSPACE_SETTING, find_membership, scope_to_workspace
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
