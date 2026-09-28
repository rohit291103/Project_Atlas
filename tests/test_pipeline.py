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
    ActorKind,
    CreatedBy,
    Edge,
    IngestionRunPayload,
    Node,
    NodeStatus,
    NodeType,
    RelationType,
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
    artifact_external_id,
    parse_target,
    reconcile,
    run_ingestion,
)
from atlas.storage.confirmations import reject_node
from atlas.storage.db import Base, get_engine, get_sessionmaker
from atlas.storage.projections import Projection, load_projection
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


# --- re-running the same artifact: idempotent (Phase 3) ------------------------
#
# Engineering Philosophy §5: "Re-running ingestion must never duplicate or
# corrupt existing data." Until 2026-09-28 these tests documented the opposite --
# every re-run duplicated every claim, and the API refused the second run as a
# stopgap. Identity is now decided once, in `pipeline.reconcile`: an extracted
# node is the claim already in the scope when it has the same type and quotes the
# same excerpt of the same artifact. Excerpts are literal source text, so this
# survives the LLM rewording the claim between runs.


def _node(excerpt: str = "rate-limit by client IP", **overrides: Any) -> Node:
    fields: dict[str, Any] = {
        "type": NodeType.GOAL,
        "content": "Let a user rate-limit by client IP.",
        "confidence_score": 0.9,
        "created_by": CreatedBy.SYSTEM,
        "source_refs": [
            SourceRef(
                source_type=SourceType.GITHUB_PR,
                external_id="acme/web#42",
                url="https://github.com/acme/web/pull/42",
                excerpt=excerpt,
                workspace_id=WORKSPACE,
            )
        ],
        "workspace_id": WORKSPACE,
        "feature_scope_id": SCOPE,
    }
    fields.update(overrides)
    return Node(**fields)


def _nodes(session_factory: sessionmaker[Session]) -> list[Node]:
    with session_factory() as session:
        return list(load_projection(session, workspace_id=WORKSPACE).nodes.values())


def test_re_running_the_same_artifact_creates_no_duplicate(
    session_factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_github(monkeypatch, lambda **kwargs: (_payload(), _result()))

    run_ingestion(session_factory, request=_request(), credential=GitHubCredential(TOKEN))
    run_ingestion(session_factory, request=_request(), credential=GitHubCredential(TOKEN))

    assert _types(session_factory).count("node_created") == 1


def test_a_reworded_claim_with_the_same_excerpt_is_the_same_claim(
    session_factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The LLM does not phrase a claim the same way twice; the excerpt is what
    stays put, because it is literal source text."""
    wordings = iter(["Rate-limit per client IP.", "Limit requests by the caller's IP."])
    _stub_github(
        monkeypatch,
        lambda **kwargs: (_payload(), ExtractionResult(nodes=[_node(content=next(wordings))])),
    )

    run_ingestion(session_factory, request=_request(), credential=GitHubCredential(TOKEN))
    run_ingestion(session_factory, request=_request(), credential=GitHubCredential(TOKEN))

    assert len(_nodes(session_factory)) == 1


def test_a_ruling_survives_a_re_run(
    session_factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The failure the old stopgap existed to prevent: a reviewer's ruling
    silently stranded on a copy they can no longer tell apart from the new one."""
    _stub_github(monkeypatch, lambda **kwargs: (_payload(), _result()))
    run_ingestion(session_factory, request=_request(), credential=GitHubCredential(TOKEN))
    (node,) = _nodes(session_factory)
    with session_factory() as session:
        reject_node(session, node=node, actor="Priya", actor_kind=ActorKind.HUMAN)
        session.commit()

    run_ingestion(session_factory, request=_request(), credential=GitHubCredential(TOKEN))

    (after,) = _nodes(session_factory)
    assert after.id == node.id
    assert after.status is NodeStatus.REJECTED


def test_a_new_claim_on_a_re_run_is_added(
    session_factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    runs = iter([[_node()], [_node(), _node(excerpt="also cap bursts at 100/s")]])
    _stub_github(monkeypatch, lambda **kwargs: (_payload(), ExtractionResult(nodes=next(runs))))

    run_ingestion(session_factory, request=_request(), credential=GitHubCredential(TOKEN))
    run_ingestion(session_factory, request=_request(), credential=GitHubCredential(TOKEN))

    excerpts = sorted(node.source_refs[0].excerpt for node in _nodes(session_factory))
    assert excerpts == ["also cap bursts at 100/s", "rate-limit by client IP"]


def test_edges_are_remapped_onto_surviving_nodes_and_not_duplicated(
    session_factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    def extraction(**kwargs: Any) -> tuple[IngestionRunPayload, ExtractionResult]:
        goal = _node()
        constraint = _node(excerpt="no cookies", type=NodeType.CONSTRAINT, content="No cookies")
        edge = Edge(
            from_node_id=constraint.id,
            to_node_id=goal.id,
            relation_type=RelationType.SUPPORTS,
            confidence_score=0.8,
        )
        return _payload(), ExtractionResult(nodes=[goal, constraint], edges=[edge])

    _stub_github(monkeypatch, extraction)

    run_ingestion(session_factory, request=_request(), credential=GitHubCredential(TOKEN))
    run_ingestion(session_factory, request=_request(), credential=GitHubCredential(TOKEN))

    with session_factory() as session:
        projection = load_projection(session, workspace_id=WORKSPACE)
    (edge,) = projection.edges.values()
    assert {edge.from_node_id, edge.to_node_id} <= set(projection.nodes)


def test_reconcile_drops_an_edge_whose_endpoints_collapse_into_one_node() -> None:
    """Two new nodes can both match one existing claim; an edge between them
    would become a self-reference, which `Edge` itself forbids."""
    existing = _node()
    first, second = _node(), _node()
    edge = Edge(
        from_node_id=first.id,
        to_node_id=second.id,
        relation_type=RelationType.SUPPORTS,
        confidence_score=0.8,
    )
    projection = Projection(nodes={existing.id: existing})

    reconciled = reconcile(ExtractionResult(nodes=[first, second], edges=[edge]), projection)

    assert reconciled.nodes == []
    assert reconciled.edges == []


def test_a_node_with_a_source_the_existing_claim_lacks_is_not_dropped() -> None:
    """Backend review 2026-09-28: matching on *any* shared excerpt discarded the
    new node's other source_refs -- silent provenance loss. A node is the
    existing claim only when every one of its sources is already on it; otherwise
    it is written, and a possible duplicate stays visible for review."""
    existing = _node()
    corroborated = _node()
    corroborated = corroborated.model_copy(
        update={
            "source_refs": [
                *corroborated.source_refs,
                SourceRef(
                    source_type=SourceType.JIRA_TICKET,
                    external_id="PA-7",
                    url="https://acme.atlassian.net/browse/PA-7",
                    excerpt="limit per IP",
                    workspace_id=WORKSPACE,
                ),
            ]
        }
    )

    reconciled = reconcile(
        ExtractionResult(nodes=[corroborated]), Projection(nodes={existing.id: existing})
    )

    assert reconciled.nodes == [corroborated]


def test_the_same_excerpt_under_a_different_type_is_a_different_claim() -> None:
    existing = _node()
    other = _node(type=NodeType.REQUIREMENT)

    reconciled = reconcile(
        ExtractionResult(nodes=[other]), Projection(nodes={existing.id: existing})
    )

    assert reconciled.nodes == [other]


# --- incremental sync: an unchanged artifact is not re-extracted ---------------


def test_the_previous_content_hash_is_handed_to_extraction(
    session_factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[str | None] = []

    def extraction(**kwargs: Any) -> tuple[IngestionRunPayload, ExtractionResult]:
        seen.append(kwargs.get("previous_hash"))
        return _payload().model_copy(update={"content_hash": "h1"}), _result()

    _stub_github(monkeypatch, extraction)

    run_ingestion(session_factory, request=_request(), credential=GitHubCredential(TOKEN))
    run_ingestion(session_factory, request=_request(), credential=GitHubCredential(TOKEN))

    assert seen == [None, "h1"]


def test_an_unchanged_artifact_writes_no_run_and_is_counted_as_unchanged(
    session_factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    results = iter(
        [
            (_payload().model_copy(update={"content_hash": "h1"}), _result()),
            (
                _payload().model_copy(update={"content_hash": "h1"}),
                ExtractionResult(unchanged=True),
            ),
        ]
    )
    _stub_github(monkeypatch, lambda **kwargs: next(results))

    run_ingestion(session_factory, request=_request(), credential=GitHubCredential(TOKEN))
    outcome = run_ingestion(session_factory, request=_request(), credential=GitHubCredential(TOKEN))

    assert _types(session_factory).count("ingestion_run") == 1
    assert outcome.state is RunState.SUCCEEDED
    assert outcome.unchanged == 1


def test_a_single_artifact_target_names_the_id_it_would_be_stored_under() -> None:
    """What the re-run block compares against. Must match exactly what extraction
    stamps on the artifact (`agent.py`), or the block silently never fires."""
    assert artifact_external_id(RunTargetKind.GITHUB_PR, "acme/web#42") == "acme/web#42"
    assert artifact_external_id(RunTargetKind.GITHUB_PR, " acme/web#42 ") == "acme/web#42"
    assert artifact_external_id(RunTargetKind.JIRA_ISSUE, " scrum-6 ") == "SCRUM-6"


def test_a_malformed_target_names_no_id_because_it_never_parses() -> None:
    """The block inherits `parse_target`'s strictness rather than softening it --
    a target too malformed to ingest is also too malformed to compare."""
    with pytest.raises(TargetError):
        artifact_external_id(RunTargetKind.GITHUB_PR, "https://github.com/acme/web/pull/42")


def test_a_multi_artifact_target_names_no_single_id() -> None:
    """An epic or a label expands to many artifacts, none of which the target
    names. Re-running one is safe regardless: `reconcile` works per artifact."""
    assert artifact_external_id(RunTargetKind.JIRA_EPIC, "SCRUM-1") is None
    assert artifact_external_id(RunTargetKind.JIRA_LABEL, "checkout") is None
