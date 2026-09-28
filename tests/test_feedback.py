"""Tests for `feedback.py`: the feedback loop over human rulings (Phase 3).

Roadmap v2's metric table is the spec here. The guard metric (share of rulings
made by a human) is read first; spec acceptance rate is counted only over a
node's *first* ruling, only when a human made it, and only over extracted nodes
-- a PM's own manual claim is not the extractor's output to grade.

Pure functions over in-memory `Event`s: no DB, no network.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from atlas.feedback import feedback_report
from atlas.models.schema import (
    ActorKind,
    CreatedBy,
    Event,
    EventType,
    Node,
    NodeEditPayload,
    NodeStatusChangePayload,
    NodeType,
    SourceRef,
    SourceType,
)

WORKSPACE = uuid.UUID(int=0)
SCOPE = uuid.UUID(int=1)
MONDAY = datetime(2026, 9, 14, 9, 0, tzinfo=UTC)


def _node(
    node_type: NodeType = NodeType.REQUIREMENT,
    *,
    source: SourceType = SourceType.GITHUB_PR,
    created_by: CreatedBy = CreatedBy.SYSTEM,
    content: str = "Plot visitors",
) -> Node:
    return Node(
        type=node_type,
        content=content,
        confidence_score=0.9 if created_by is CreatedBy.SYSTEM else None,
        created_by=created_by,
        source_refs=[
            SourceRef(
                source_type=source,
                external_id="acme/web#1",
                url="https://github.com/acme/web/pull/1",
                excerpt="plot visitors",
                workspace_id=WORKSPACE,
            )
        ],
        workspace_id=WORKSPACE,
        feature_scope_id=SCOPE,
    )


def _created(node: Node, at: datetime = MONDAY) -> Event:
    return Event(
        event_type=EventType.NODE_CREATED,
        payload=node.model_dump(mode="json"),
        actor="system",
        actor_kind=ActorKind.AUTOMATED,
        workspace_id=WORKSPACE,
        timestamp=at,
    )


def _ruled(
    event_type: EventType,
    node: Node,
    *,
    kind: ActorKind = ActorKind.HUMAN,
    at: datetime = MONDAY,
    content: str | None = None,
) -> Event:
    payload = (
        NodeEditPayload(node_id=node.id, content=content or "x", previous_content=node.content)
        if event_type is EventType.NODE_EDITED
        else NodeStatusChangePayload(node_id=node.id)
    )
    return Event(
        event_type=event_type,
        payload=payload.model_dump(mode="json"),
        actor="Priya" if kind is ActorKind.HUMAN else "browser-suite",
        actor_kind=kind,
        workspace_id=WORKSPACE,
        timestamp=at,
    )


def test_acceptance_rate_is_first_human_rulings_kept_unedited() -> None:
    kept, edited, rejected = _node(), _node(), _node()

    report = feedback_report(
        [
            *map(_created, (kept, edited, rejected)),
            _ruled(EventType.NODE_CONFIRMED, kept),
            _ruled(EventType.NODE_EDITED, edited, content="Plot unique visitors"),
            _ruled(EventType.NODE_REJECTED, rejected),
        ]
    )

    assert (report.overall.kept, report.overall.edited, report.overall.rejected) == (1, 1, 1)
    assert report.overall.acceptance_rate == 1 / 3


def test_only_the_first_ruling_counts() -> None:
    """A claim confirmed, then edited on a second read, was accepted at first read."""
    node = _node()

    report = feedback_report(
        [
            _created(node),
            _ruled(EventType.NODE_CONFIRMED, node),
            _ruled(EventType.NODE_EDITED, node, at=MONDAY + timedelta(hours=1)),
        ]
    )

    assert (report.overall.kept, report.overall.edited) == (1, 0)


def test_an_automated_first_ruling_is_excluded_and_trips_the_guard() -> None:
    """The guard metric: below 100% human, no other number may be cited."""
    by_bot, by_person = _node(), _node()

    report = feedback_report(
        [
            _created(by_bot),
            _created(by_person),
            _ruled(EventType.NODE_CONFIRMED, by_bot, kind=ActorKind.AUTOMATED),
            _ruled(EventType.NODE_CONFIRMED, by_person),
        ]
    )

    assert report.overall.ruled == 1
    assert report.human_share == 0.5
    assert not report.guard_passes


def test_a_manual_node_is_not_graded_as_extraction_output() -> None:
    manual = _node(created_by=CreatedBy.USER, source=SourceType.HUMAN_ASSERTION)

    report = feedback_report([_created(manual), _ruled(EventType.NODE_REJECTED, manual)])

    assert report.overall.ruled == 0


def test_breakdowns_by_type_and_source_say_where_extraction_is_weakest() -> None:
    goal = _node(NodeType.GOAL)
    ticket = _node(NodeType.CONSTRAINT, source=SourceType.JIRA_TICKET)

    report = feedback_report(
        [
            _created(goal),
            _created(ticket),
            _ruled(EventType.NODE_CONFIRMED, goal),
            _ruled(EventType.NODE_REJECTED, ticket),
        ]
    )

    assert report.by_type["goal"].acceptance_rate == 1.0
    assert report.by_type["constraint"].acceptance_rate == 0.0
    assert report.by_source["jira_ticket"].rejected == 1


def test_weekly_trend_is_bucketed_by_iso_week_of_the_first_ruling() -> None:
    """The Phase 3 exit criterion reads this: acceptance trending up across two
    consecutive weeks."""
    first, second, third = _node(), _node(), _node()
    next_week = MONDAY + timedelta(days=7)

    report = feedback_report(
        [
            *map(_created, (first, second, third)),
            _ruled(EventType.NODE_REJECTED, first),
            _ruled(EventType.NODE_CONFIRMED, second, at=next_week),
            _ruled(EventType.NODE_CONFIRMED, third, at=next_week),
        ]
    )

    assert [(week.week, week.acceptance_rate) for week in report.weekly] == [
        ("2026-W38", 0.0),
        ("2026-W39", 1.0),
    ]


def test_edits_and_rejections_are_kept_as_prompt_signal() -> None:
    edited = _node(content="Plot visitors")
    rejected = _node(NodeType.DECISION, content="Use Redis")

    report = feedback_report(
        [
            _created(edited),
            _created(rejected),
            _ruled(EventType.NODE_EDITED, edited, content="Plot unique visitors"),
            _ruled(EventType.NODE_REJECTED, rejected),
        ]
    )

    (edit,) = report.edits
    assert (edit.extracted, edit.corrected) == ("Plot visitors", "Plot unique visitors")
    (rejection,) = report.rejections
    assert (rejection.type, rejection.content, rejection.excerpt) == (
        NodeType.DECISION,
        "Use Redis",
        "plot visitors",
    )


def test_the_report_can_be_narrowed_to_some_nodes() -> None:
    mine, theirs = _node(), _node()

    report = feedback_report(
        [
            _created(mine),
            _created(theirs),
            _ruled(EventType.NODE_CONFIRMED, mine),
            _ruled(EventType.NODE_REJECTED, theirs),
        ],
        node_ids={mine.id},
    )

    assert (report.overall.kept, report.overall.rejected) == (1, 0)


def test_no_rulings_is_an_empty_report_not_a_division_by_zero() -> None:
    report = feedback_report([_created(_node())])

    assert report.overall.acceptance_rate is None
    assert report.human_share is None
    assert report.weekly == ()
