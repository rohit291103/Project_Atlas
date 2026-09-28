"""The feedback loop: what human rulings say about extraction (Phase 3).

Roadmap v2's metrics, computed from the event log and nothing else:

- **Guard** -- the share of rulings made by a human. Below 100%, no other
  number here may be cited (roadmap v2, "check this before reading any other
  number"). The browser suite once confirmed six real claims as a person; this
  is what catches that.
- **Spec acceptance rate** -- of extracted claims, the share a human kept
  *unedited at first read*. Only the first ruling counts, because later passes
  are confounded by fatigue and rubber-stamping; only human first rulings count,
  for the guard's reason; only system-extracted nodes count, because a PM's own
  manual claim is not the extractor's output to grade.
- **Where it is weakest** -- the same rate broken down by claim type and by
  source, plus the literal edits (extracted -> corrected) and rejections. That
  is the signal for improving `extraction/prompts.py`, and it is kept verbatim.

Why its own module rather than part of `storage/projections.py`: a projection
replays the log into *current state*, and current state has already forgotten
which ruling came first. This reads the log itself, in order, like `replay`,
and interprets it -- the same relationship `assembly.py` has to `Projection`.

Nothing here is stored. Conflict yield (roadmap v2) is not computed: it needs a
reviewer to say whether a conflict was *already known*, and nothing records that
yet.
"""

from __future__ import annotations

import uuid
from collections.abc import Collection, Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from atlas.models.schema import (
    ActorKind,
    CreatedBy,
    EventType,
    Node,
    NodeEditPayload,
    NodeStatusChangePayload,
    NodeType,
)


class LoggedEvent(Protocol):
    """What this module reads off an event -- satisfied by both the ORM row
    (`EventLog`) and the domain `Event`, as `projections._ReplayableEvent` is."""

    @property
    def event_type(self) -> EventType: ...

    @property
    def payload(self) -> dict[str, Any]: ...

    @property
    def actor_kind(self) -> ActorKind: ...

    @property
    def timestamp(self) -> datetime: ...


_RULINGS = frozenset({EventType.NODE_CONFIRMED, EventType.NODE_EDITED, EventType.NODE_REJECTED})

#: Which of kept/edited/rejected a first ruling counts toward.
_SLOT = {EventType.NODE_CONFIRMED: 0, EventType.NODE_EDITED: 1, EventType.NODE_REJECTED: 2}

#: How many edits/rejections to carry verbatim. Enough to read for a pattern;
#: bounded so a large workspace does not ship its whole log to a browser.
SAMPLE_LIMIT = 50


@dataclass(frozen=True)
class Tally:
    """First human rulings over some set of extracted claims.

    Derived values are plain fields rather than properties so they serialize:
    the API returns this dataclass as-is, and a property would silently never
    reach the browser.
    """

    kept: int
    edited: int
    rejected: int
    ruled: int
    #: Kept unedited / ruled. `None` when nothing was ruled -- zero rulings is an
    #: absence of evidence, not a 0% rate.
    acceptance_rate: float | None


def _tally(kept: int = 0, edited: int = 0, rejected: int = 0) -> Tally:
    ruled = kept + edited + rejected
    return Tally(
        kept=kept,
        edited=edited,
        rejected=rejected,
        ruled=ruled,
        acceptance_rate=kept / ruled if ruled else None,
    )


@dataclass(frozen=True)
class WeeklyTally:
    #: ISO week of the first ruling, `YYYY-Www`.
    week: str
    kept: int
    ruled: int
    acceptance_rate: float | None


@dataclass(frozen=True)
class Correction:
    """An extracted claim a human rewrote at first read -- prompt signal."""

    node_id: uuid.UUID
    type: NodeType
    extracted: str
    corrected: str


@dataclass(frozen=True)
class Rejection:
    """An extracted claim a human ruled out at first read, with its excerpt, so
    a reader can see whether the model misread the source or overreached it."""

    node_id: uuid.UUID
    type: NodeType
    content: str
    excerpt: str


@dataclass(frozen=True)
class FeedbackReport:
    #: Human rulings / all rulings, over every ruling event (not just first
    #: ones). `None` when there are no rulings at all.
    human_share: float | None
    overall: Tally
    by_type: dict[str, Tally]
    by_source: dict[str, Tally]
    weekly: tuple[WeeklyTally, ...]
    edits: tuple[Correction, ...]
    rejections: tuple[Rejection, ...]
    #: Roadmap v2's guard: 100% human, or nothing else here is citable. An empty
    #: log passes vacuously -- there is nothing unsound to cite yet.
    guard_passes: bool


def feedback_report(
    events: Iterable[LoggedEvent], *, node_ids: Collection[uuid.UUID] | None = None
) -> FeedbackReport:
    """Fold the log, in order, into the feedback report.

    `node_ids` narrows every number to those nodes (a product's, typically);
    `None` means the whole log given.
    """
    extracted: dict[uuid.UUID, Node] = {}
    first_ruled: set[uuid.UUID] = set()
    human = total = 0
    # [kept, edited, rejected], mutable while folding and frozen at the end.
    overall = [0, 0, 0]
    by_type: dict[str, list[int]] = {}
    by_source: dict[str, list[int]] = {}
    weekly: dict[str, list[int]] = {}
    edits: list[Correction] = []
    rejections: list[Rejection] = []

    for event in events:
        if event.event_type is EventType.NODE_CREATED:
            created = Node.model_validate(event.payload)
            if created.created_by is CreatedBy.SYSTEM and (
                node_ids is None or created.id in node_ids
            ):
                extracted[created.id] = created
            continue
        if event.event_type not in _RULINGS:
            continue

        node_id = _ruled_node_id(event)
        if node_ids is not None and node_id not in node_ids:
            continue
        total += 1
        human += event.actor_kind is ActorKind.HUMAN

        node = extracted.get(node_id)
        if node is None or node_id in first_ruled:
            continue
        # The first ruling is consumed whoever made it: an automated first
        # ruling means this node has no clean first read to count, ever.
        first_ruled.add(node_id)
        if event.actor_kind is not ActorKind.HUMAN:
            continue

        slot = _SLOT[event.event_type]
        overall[slot] += 1
        by_type.setdefault(node.type.value, [0, 0, 0])[slot] += 1
        by_source.setdefault(node.source_refs[0].source_type.value, [0, 0, 0])[slot] += 1
        bucket = weekly.setdefault(_iso_week(event.timestamp), [0, 0])
        bucket[0] += event.event_type is EventType.NODE_CONFIRMED
        bucket[1] += 1

        if event.event_type is EventType.NODE_EDITED and len(edits) < SAMPLE_LIMIT:
            edit = NodeEditPayload.model_validate(event.payload)
            edits.append(
                Correction(
                    node_id=node_id,
                    type=node.type,
                    extracted=edit.previous_content,
                    corrected=edit.content,
                )
            )
        elif event.event_type is EventType.NODE_REJECTED and len(rejections) < SAMPLE_LIMIT:
            rejections.append(
                Rejection(
                    node_id=node_id,
                    type=node.type,
                    content=node.content,
                    excerpt=node.source_refs[0].excerpt,
                )
            )

    human_share = human / total if total else None
    return FeedbackReport(
        human_share=human_share,
        overall=_tally(*overall),
        by_type={key: _tally(*counts) for key, counts in by_type.items()},
        by_source={key: _tally(*counts) for key, counts in by_source.items()},
        weekly=tuple(
            WeeklyTally(week=week, kept=kept, ruled=ruled, acceptance_rate=kept / ruled)
            for week, (kept, ruled) in sorted(weekly.items())
        ),
        edits=tuple(edits),
        rejections=tuple(rejections),
        guard_passes=human_share is None or human_share == 1.0,
    )


def _ruled_node_id(event: LoggedEvent) -> uuid.UUID:
    if event.event_type is EventType.NODE_EDITED:
        return NodeEditPayload.model_validate(event.payload).node_id
    return NodeStatusChangePayload.model_validate(event.payload).node_id


def _iso_week(moment: datetime) -> str:
    year, week, _ = moment.isocalendar()
    return f"{year}-W{week:02d}"
