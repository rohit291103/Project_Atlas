"""The run lifecycle: what `pipeline` writes, in what order, and on failure.

The extraction agent itself is stubbed out — this is about the events that
bracket it. Two properties are the reason the module exists at all: a run always
writes exactly one terminal event (so "is it still going?" is answerable from the
log), and a credential never reaches one of them.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from atlas.extraction.agent import ExtractionError, ExtractionResult
from atlas.models.schema import (
    CreatedBy,
    IngestionRunPayload,
    Node,
    NodeType,
    RunState,
    RunTargetKind,
    SourceRef,
    SourceType,
)
from atlas.pipeline import (
    GitHubCredential,
    JiraCredential,
    RunRequest,
    TargetError,
    UnsupportedHostError,
    parse_target,
    run_ingestion,
)
from atlas.storage.db import Base, get_engine, get_sessionmaker
from atlas.storage.projections import load_projection
from atlas.storage.tables import EventLog

WORKSPACE = uuid.UUID(int=0)
SCOPE = uuid.UUID(int=5)
PRODUCT = uuid.UUID(int=6)
TOKEN = "ghp_a_very_secret_token"


@pytest.fixture
def session_factory() -> sessionmaker[Session]:
    engine = get_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return get_sessionmaker(engine)


def _request(**overrides: Any) -> RunRequest:
    fields: dict[str, Any] = {
        "workspace_id": WORKSPACE,
        "actor": "Priya",
        "target_kind": RunTargetKind.GITHUB_PR,
        "target": "acme/web#42",
        "feature_scope_id": SCOPE,
        "product_id": PRODUCT,
    }
    fields.update(overrides)
    return RunRequest(**fields)


def _result() -> ExtractionResult:
    node = Node(
        type=NodeType.GOAL,
        content="Let a user rate-limit by client IP.",
        confidence_score=0.9,
        created_by=CreatedBy.SYSTEM,
        source_refs=[
            SourceRef(
                source_type=SourceType.GITHUB_PR,
                external_id="acme/web#42",
                url="https://github.com/acme/web/pull/42",
                excerpt="rate-limit by client IP",
                workspace_id=WORKSPACE,
            )
        ],
        workspace_id=WORKSPACE,
        feature_scope_id=SCOPE,
    )
    return ExtractionResult(nodes=[node], edges=[])


def _payload() -> IngestionRunPayload:
    return IngestionRunPayload(
        feature_scope_id=SCOPE,
        title="Rate limiting",
        source_type=SourceType.GITHUB_PR,
        external_id="acme/web#42",
        url="https://github.com/acme/web/pull/42",
    )


def _types(session_factory: sessionmaker[Session]) -> list[str]:
    with session_factory() as session:
        rows = session.execute(select(EventLog).order_by(EventLog.sequence)).scalars()
        return [row.event_type.value for row in rows]


def _stub_github(monkeypatch: pytest.MonkeyPatch, behaviour: Any) -> None:
    async def fake(**kwargs: Any) -> tuple[IngestionRunPayload, ExtractionResult]:
        result: tuple[IngestionRunPayload, ExtractionResult] = behaviour(**kwargs)
        return result

    monkeypatch.setattr("atlas.pipeline.extract_from_pull_request", fake)
    monkeypatch.setattr("atlas.pipeline.GitHubClient", lambda token: _FakeClient())


class _FakeClient:
    def close(self) -> None:
        return None


# --- targets -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("kind", "target"),
    [
        (RunTargetKind.GITHUB_PR, "acme/web"),
        (RunTargetKind.GITHUB_PR, "acme/web#"),
        (RunTargetKind.GITHUB_PR, "https://github.com/acme/web/pull/42"),
        (RunTargetKind.JIRA_ISSUE, "SCRUM"),
        (RunTargetKind.JIRA_EPIC, "not a key"),
        (RunTargetKind.JIRA_LABEL, "a label with spaces"),
    ],
)
def test_a_malformed_target_is_refused_before_anything_happens(
    kind: RunTargetKind, target: str
) -> None:
    with pytest.raises(TargetError):
        parse_target(kind, target)


def test_a_jira_key_is_normalized_but_a_github_target_is_split() -> None:
    assert parse_target(RunTargetKind.JIRA_ISSUE, " scrum-6 ") == ("SCRUM-6",)
    assert parse_target(RunTargetKind.GITHUB_PR, "acme/web#42") == ("acme", "web", "42")


# --- the happy path ------------------------------------------------------------


def test_a_successful_run_brackets_its_artifacts(
    session_factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_github(monkeypatch, lambda **kwargs: (_payload(), _result()))

    outcome = run_ingestion(session_factory, request=_request(), credential=GitHubCredential(TOKEN))

    assert outcome.state is RunState.SUCCEEDED
    assert _types(session_factory) == [
        "ingestion_run_started",
        "ingestion_run",
        "node_created",
        "ingestion_run_finished",
    ]


def test_the_run_stamps_its_id_and_product_onto_the_artifact(
    session_factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Which product a feature belongs to and which job pulled it are facts about
    the request, not about the artifact — so `extraction/` never sets them."""
    _stub_github(monkeypatch, lambda **kwargs: (_payload(), _result()))

    outcome = run_ingestion(session_factory, request=_request(), credential=GitHubCredential(TOKEN))

    with session_factory() as session:
        projection = load_projection(session, workspace_id=WORKSPACE)
    run = projection.runs[outcome.run_id]
    assert run.state() is RunState.SUCCEEDED
    assert run.artifacts == 1
    assert projection.feature_scopes[SCOPE].product_id == PRODUCT
    assert projection.feature_scopes[SCOPE].runs[0].run_id == outcome.run_id


def test_a_run_into_an_existing_scope_is_handed_what_is_already_known(
    session_factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The cross-source path, in the GitHub direction — new in slice 2B. Without
    it a PM who connects Jira first and GitHub second gets no conflicts at all."""
    seen: dict[str, Any] = {}

    def capture(**kwargs: Any) -> tuple[IngestionRunPayload, ExtractionResult]:
        seen.update(kwargs)
        return _payload(), _result()

    _stub_github(monkeypatch, capture)
    run_ingestion(session_factory, request=_request(), credential=GitHubCredential(TOKEN))
    seen.clear()
    run_ingestion(session_factory, request=_request(), credential=GitHubCredential(TOKEN))

    assert [node.content for node in seen["known_nodes"]] == ["Let a user rate-limit by client IP."]


# --- failure -------------------------------------------------------------------


def test_a_failed_run_writes_a_terminal_event_rather_than_raising(
    session_factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(**kwargs: Any) -> tuple[IngestionRunPayload, ExtractionResult]:
        raise ExtractionError("agent did not emit an extraction")

    _stub_github(monkeypatch, boom)

    outcome = run_ingestion(session_factory, request=_request(), credential=GitHubCredential(TOKEN))

    assert outcome.state is RunState.FAILED
    assert _types(session_factory) == ["ingestion_run_started", "ingestion_run_failed"]


def test_an_unexpected_exception_still_ends_the_run(
    session_factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Anything escaping would be swallowed by the background-task runner and the
    run would read as *interrupted* — a worse answer than the one we have."""

    def boom(**kwargs: Any) -> tuple[IngestionRunPayload, ExtractionResult]:
        raise RuntimeError("something nobody predicted")

    _stub_github(monkeypatch, boom)

    outcome = run_ingestion(session_factory, request=_request(), credential=GitHubCredential(TOKEN))

    assert outcome.state is RunState.FAILED
    assert _types(session_factory)[-1] == "ingestion_run_failed"


def test_a_failure_message_never_carries_the_credential(
    session_factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failure message is written to the log and rendered in a browser. The
    connectors send credentials in headers, so one should never appear in an
    error — "should never" is not a guarantee, and this is the guarantee."""

    def boom(**kwargs: Any) -> tuple[IngestionRunPayload, ExtractionResult]:
        raise ExtractionError(f"401 from https://api.github.com with token {TOKEN}")

    _stub_github(monkeypatch, boom)

    outcome = run_ingestion(session_factory, request=_request(), credential=GitHubCredential(TOKEN))

    assert TOKEN not in (outcome.error or "")
    with session_factory() as session:
        rows = session.execute(select(EventLog)).scalars()
        assert TOKEN not in str([row.payload for row in rows])


def test_a_jira_failure_redacts_the_api_token(
    session_factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*args: Any, **kwargs: Any) -> list[str]:
        raise ExtractionError("auth failed for token jira_tok_secret")

    monkeypatch.setattr("atlas.pipeline.resolve_jira_keys", boom)
    monkeypatch.setattr("atlas.pipeline.JiraClient", lambda **kwargs: _FakeClient())

    outcome = run_ingestion(
        session_factory,
        request=_request(target_kind=RunTargetKind.JIRA_EPIC, target="SCRUM-6"),
        credential=JiraCredential(
            base_url="https://acme.atlassian.net", email="p@acme.com", api_token="jira_tok_secret"
        ),
    )

    assert outcome.error is not None
    assert "jira_tok_secret" not in outcome.error
    assert "***" in outcome.error


def test_a_malformed_target_never_starts_a_run(
    session_factory: sessionmaker[Session],
) -> None:
    with pytest.raises(TargetError):
        run_ingestion(
            session_factory,
            request=_request(target="not-a-pr"),
            credential=GitHubCredential(TOKEN),
        )
    assert _types(session_factory) == []


# --- the SSRF control on the Jira site -----------------------------------------


@pytest.mark.parametrize(
    "base_url",
    [
        "https://169.254.169.254",  # cloud instance metadata
        "https://localhost",
        "https://127.0.0.1",
        "https://internal.acme.corp",
        "https://acme.atlassian.net.evil.com",  # suffix smuggling
        "https://evil.com/acme.atlassian.net",  # path, not host
        "http://acme.atlassian.net",  # plaintext puts the token on the wire
    ],
)
def test_a_jira_credential_refuses_a_host_it_should_not_send_a_token_to(base_url: str) -> None:
    """New attack surface in slice 2B: before it, the Jira site came from a
    trusted env var; now it comes from a form field and becomes the base URL of
    a request carrying `Authorization: Basic`."""
    with pytest.raises(UnsupportedHostError):
        JiraCredential(base_url=base_url, email="p@acme.com", api_token="t")


@pytest.mark.parametrize(
    "base_url", ["https://acme.atlassian.net", "https://my-team-2.atlassian.net"]
)
def test_a_real_jira_cloud_site_is_accepted(base_url: str) -> None:
    assert (
        JiraCredential(base_url=base_url, email="p@acme.com", api_token="t").email == "p@acme.com"
    )


def test_the_github_target_regex_cannot_smuggle_jql() -> None:
    """`resolve_jira_keys` interpolates the target into JQL. The regexes are what
    keep a quote or an `ORDER BY` out of it — slice 2B is the first time that
    string arrives from a browser rather than an engineer's shell."""
    for hostile in ['" OR project = "SECRET', 'a" ORDER BY created DESC--', "a b", "a'b"]:
        with pytest.raises(TargetError):
            parse_target(RunTargetKind.JIRA_LABEL, hostile)
