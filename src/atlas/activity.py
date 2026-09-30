"""How Atlas is being used, per week -- the admin's view (Phase 4).

Roadmap v2 Phase 4: "basic admin usage analytics". Counted from the event log
and nothing else: no tracking is added to produce these numbers, so every one
of them is something the log already had to record for its own reasons.

What is counted, per ISO week:

- **Ingestion runs**, by outcome. A start with no terminal event is counted as
  started only -- it is still running or it was interrupted, and saying which
  is the Sources screen's job (`projections.INTERRUPTED_AFTER`).
- **Rulings per person.** Automated rulings are counted apart and never folded
  in, the same line the feedback guard draws: a busy week of test-suite
  confirmations is not a team using the product.
- **Comments.**

What is deliberately **not** counted: spec exports and Q&A questions (neither
writes an event today, and logging the questions people ask is a retention
decision, not an analytics one), and anything about node volume -- roadmap v2
rejects "nodes in graph" as a vanity metric.

Pure, like `feedback.py`: a fold over events, placed beside it for the same
reason -- it reads the log in order rather than projected state.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from atlas.models.schema import ActorKind, EventType

_RULINGS = frozenset({EventType.NODE_CONFIRMED, EventType.NODE_EDITED, EventType.NODE_REJECTED})


class LoggedEvent(Protocol):
    @property
    def event_type(self) -> EventType: ...

    @property
    def payload(self) -> dict[str, Any]: ...

    @property
    def actor(self) -> str: ...

    @property
    def actor_kind(self) -> ActorKind: ...

    @property
    def timestamp(self) -> datetime: ...


@dataclass
class WeekActivity:
    #: ISO week, `YYYY-Www`.
    week: str
    runs_started: int = 0
    runs_succeeded: int = 0
    runs_failed: int = 0
    rulings_by_person: dict[str, int] = field(default_factory=dict)
    automated_rulings: int = 0
    comments: int = 0


@dataclass(frozen=True)
class ActivityReport:
    weeks: tuple[WeekActivity, ...]
    #: Everyone who ruled on anything, alphabetically -- the columns of a table.
    people: tuple[str, ...]


def activity_report(events: Iterable[LoggedEvent]) -> ActivityReport:
    weeks: dict[str, WeekActivity] = {}
    people: set[str] = set()

    for event in events:
        year, number, _ = event.timestamp.isocalendar()
        key = f"{year}-W{number:02d}"
        week = weeks.get(key)
        if week is None:
            week = weeks[key] = WeekActivity(week=key)

        if event.event_type is EventType.INGESTION_RUN_STARTED:
            week.runs_started += 1
        elif event.event_type is EventType.INGESTION_RUN_FINISHED:
            week.runs_succeeded += 1
        elif event.event_type is EventType.INGESTION_RUN_FAILED:
            week.runs_failed += 1
        elif event.event_type in _RULINGS:
            if event.actor_kind is ActorKind.HUMAN:
                week.rulings_by_person[event.actor] = week.rulings_by_person.get(event.actor, 0) + 1
                people.add(event.actor)
            else:
                week.automated_rulings += 1
        elif event.event_type is EventType.COMMENT_ADDED:
            week.comments += 1

    active = [week for key, week in sorted(weeks.items()) if _has_activity(week)]
    return ActivityReport(weeks=tuple(active), people=tuple(sorted(people)))


def _has_activity(week: WeekActivity) -> bool:
    """A week holding only events this report does not count (a product was
    renamed, say) is not a week of activity, and is left out rather than shown
    as a row of zeros."""
    return bool(
        week.runs_started
        or week.runs_succeeded
        or week.runs_failed
        or week.rulings_by_person
        or week.automated_rulings
        or week.comments
    )
