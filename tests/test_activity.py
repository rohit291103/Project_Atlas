"""Tests for `activity.py` -- the admin's view of how Atlas is being used (Phase 4).

Counted from the event log and nothing else: no tracking is added to produce
it. Rulings are attributed to the person who made them, and automated rulings
are counted apart, never folded in -- the same line the guard metric draws.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from atlas.activity import activity_report
from atlas.models.schema import (
    ActorKind,
    CommentPayload,
    Event,
    EventType,
    NodeStatusChangePayload,
    RunFailedPayload,
    RunFinishedPayload,
    RunStartedPayload,
    RunTargetKind,
)

WORKSPACE = uuid.UUID(int=0)
MONDAY = datetime(2026, 9, 14, 9, 0, tzinfo=UTC)
NEXT_WEEK = MONDAY + timedelta(days=7)


def _event(
    event_type: EventType,
    payload: dict[str, object],
    *,
    actor: str = "Priya",
    kind: ActorKind = ActorKind.HUMAN,
    at: datetime = MONDAY,
) -> Event:
    return Event(
        event_type=event_type,
        payload=payload,
        actor=actor,
        actor_kind=kind,
        workspace_id=WORKSPACE,
        timestamp=at,
    )


def _ruling(actor: str, kind: ActorKind = ActorKind.HUMAN, at: datetime = MONDAY) -> Event:
    return _event(
        EventType.NODE_CONFIRMED,
        NodeStatusChangePayload(node_id=uuid.uuid4()).model_dump(mode="json"),
        actor=actor,
        kind=kind,
        at=at,
    )


def _run(outcome: EventType | None, at: datetime = MONDAY) -> list[Event]:
    run_id = uuid.uuid4()
    events = [
        _event(
            EventType.INGESTION_RUN_STARTED,
            RunStartedPayload(
                run_id=run_id,
                feature_scope_id=uuid.uuid4(),
                target_kind=RunTargetKind.GITHUB_PR,
                target="acme/web#1",
            ).model_dump(mode="json"),
            kind=ActorKind.AUTOMATED,
            at=at,
        )
    ]
    if outcome is EventType.INGESTION_RUN_FINISHED:
        payload = RunFinishedPayload(run_id=run_id, nodes=3, edges=1)
        events.append(_event(outcome, payload.model_dump(mode="json"), at=at))
    elif outcome is EventType.INGESTION_RUN_FAILED:
        failed = RunFailedPayload(run_id=run_id, error="401")
        events.append(_event(outcome, failed.model_dump(mode="json"), at=at))
    return events


def test_rulings_are_counted_per_person_and_automation_apart() -> None:
    report = activity_report(
        [
            _ruling("Priya"),
            _ruling("Priya"),
            _ruling("Sam"),
            _ruling("browser-suite", ActorKind.AUTOMATED),
        ]
    )

    (week,) = report.weeks
    assert week.rulings_by_person == {"Priya": 2, "Sam": 1}
    assert week.automated_rulings == 1


def test_runs_are_counted_by_outcome() -> None:
    report = activity_report(
        [
            *_run(EventType.INGESTION_RUN_FINISHED),
            *_run(EventType.INGESTION_RUN_FAILED),
            *_run(None),  # still running, or interrupted
        ]
    )

    (week,) = report.weeks
    assert (week.runs_started, week.runs_succeeded, week.runs_failed) == (3, 1, 1)


def test_comments_are_counted() -> None:
    comment = CommentPayload(node_id=uuid.uuid4(), body="Is this still true?")

    report = activity_report([_event(EventType.COMMENT_ADDED, comment.model_dump(mode="json"))])

    assert report.weeks[0].comments == 1


def test_weeks_are_chronological_and_people_are_listed_once() -> None:
    report = activity_report([_ruling("Sam", at=NEXT_WEEK), _ruling("Priya"), _ruling("Sam")])

    assert [week.week for week in report.weeks] == ["2026-W38", "2026-W39"]
    assert report.people == ("Priya", "Sam")


def test_an_empty_log_is_an_empty_report() -> None:
    report = activity_report([])

    assert report.weeks == ()
    assert report.people == ()
