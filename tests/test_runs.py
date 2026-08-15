"""Run status is derived by replay, never stored — including the interrupted case.

The `tdd` skill names run-status derivation *including the interrupted case* as
mandatory test-first, and that case is the one carrying a real design claim: a
run started in the API process dies with the process, leaving a start event and
no terminal event, which looks exactly like a slow run. These tests pin the rule
that a stale start is reported as `interrupted` rather than as `running` forever.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from atlas.models.schema import (
    Event,
    EventType,
    IngestionRunPayload,
    RunFailedPayload,
    RunFinishedPayload,
    RunStartedPayload,
    RunState,
    RunTargetKind,
    SourceType,
)
from atlas.storage.projections import INTERRUPTED_AFTER, replay

WORKSPACE = uuid.UUID(int=1)
SCOPE = uuid.UUID(int=2)
PRODUCT = uuid.UUID(int=3)
T0 = datetime(2026, 8, 15, 12, 0, tzinfo=UTC)


def _event(event_type: EventType, payload: object, *, at: datetime = T0) -> Event:
    return Event(
        event_type=event_type,
        payload=payload.model_dump(mode="json"),  # type: ignore[attr-defined]
        actor="Priya",
        timestamp=at,
        workspace_id=WORKSPACE,
    )


def _started(run_id: uuid.UUID, *, at: datetime = T0) -> Event:
    return _event(
        EventType.INGESTION_RUN_STARTED,
        RunStartedPayload(
            run_id=run_id,
            feature_scope_id=SCOPE,
            product_id=PRODUCT,
            target_kind=RunTargetKind.GITHUB_PR,
            target="acme/web#42",
        ),
        at=at,
    )


def _ingested(run_id: uuid.UUID | None, *, at: datetime = T0) -> Event:
    return _event(
        EventType.INGESTION_RUN,
        IngestionRunPayload(
            feature_scope_id=SCOPE,
            title="Add a --pre flag",
            source_type=SourceType.GITHUB_PR,
            external_id="acme/web#42",
            url="https://github.com/acme/web/pull/42",
            product_id=PRODUCT,
            run_id=run_id,
        ),
        at=at,
    )


def _finished(run_id: uuid.UUID, *, at: datetime = T0) -> Event:
    return _event(
        EventType.INGESTION_RUN_FINISHED,
        RunFinishedPayload(run_id=run_id, nodes=8, edges=5),
        at=at,
    )


def _failed(run_id: uuid.UUID, *, at: datetime = T0) -> Event:
    return _event(
        EventType.INGESTION_RUN_FAILED,
        RunFailedPayload(run_id=run_id, error="GitHub said 404"),
        at=at,
    )


# --- the states ----------------------------------------------------------------


def test_a_start_with_no_terminal_event_is_running() -> None:
    run_id = uuid.uuid4()
    run = replay([_started(run_id)]).runs[run_id]
    assert run.state(now=T0 + timedelta(seconds=30)) is RunState.RUNNING


def test_a_finished_run_succeeded() -> None:
    run_id = uuid.uuid4()
    run = replay([_started(run_id), _ingested(run_id), _finished(run_id)]).runs[run_id]
    assert run.state(now=T0) is RunState.SUCCEEDED
    assert (run.artifacts, run.nodes, run.edges) == (1, 8, 5)


def test_a_failed_run_carries_its_reason() -> None:
    run_id = uuid.uuid4()
    run = replay([_started(run_id), _failed(run_id)]).runs[run_id]
    assert run.state(now=T0) is RunState.FAILED
    assert run.error == "GitHub said 404"


def test_a_stale_start_is_interrupted_not_running() -> None:
    """The honest cost of running in-process: the projection says so out loud."""
    run_id = uuid.uuid4()
    run = replay([_started(run_id)]).runs[run_id]
    assert run.state(now=T0 + INTERRUPTED_AFTER + timedelta(seconds=1)) is RunState.INTERRUPTED


def test_a_finished_run_never_becomes_interrupted_with_age() -> None:
    run_id = uuid.uuid4()
    run = replay([_started(run_id), _finished(run_id)]).runs[run_id]
    assert run.state(now=T0 + timedelta(days=400)) is RunState.SUCCEEDED


def test_one_ingestion_run_does_not_end_a_multi_artifact_run() -> None:
    """The reason `ingestion_run_finished` exists at all. A run over an epic emits
    one `ingestion_run` per child; treating the first as terminal would report a
    run finished while it was still pulling."""
    run_id = uuid.uuid4()
    run = replay([_started(run_id), _ingested(run_id), _ingested(run_id)]).runs[run_id]
    assert run.state(now=T0) is RunState.RUNNING


def test_a_run_lists_the_feature_scopes_it_produced() -> None:
    run_id = uuid.uuid4()
    run = replay([_started(run_id), _ingested(run_id), _finished(run_id)]).runs[run_id]
    assert run.feature_scope_ids == (SCOPE,)


# --- replaying over history that predates all of this --------------------------


def test_an_ingestion_run_with_no_run_id_projects_no_run() -> None:
    """Every `ingestion_run` in the live log predates slice 2B. Those must replay
    as they always did — a named feature scope and no run — rather than
    materializing a phantom run with no beginning."""
    projection = replay([_ingested(None)])
    assert projection.runs == {}
    assert projection.feature_scopes[SCOPE].title == "Add a --pre flag"


def test_a_terminal_event_for_an_unknown_run_is_refused() -> None:
    """Same rule the node transitions follow: a terminal naming a run the log
    never started means a corrupt log, and swallowing it hides that."""
    with pytest.raises(ValueError, match="unknown run"):
        replay([_finished(uuid.uuid4())])


def test_runs_are_ordered_by_when_they_started() -> None:
    first, second = uuid.uuid4(), uuid.uuid4()
    projection = replay([_started(first, at=T0), _started(second, at=T0 + timedelta(minutes=5))])
    assert list(projection.runs) == [first, second]
