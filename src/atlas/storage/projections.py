"""Replay the append-only event_log into materialized Node/Edge state.

Per TRD Sec3.1/Sec3.2, `event_log` is the source of truth and all Node/Edge
state is a *projection* derived by replaying events -- never a table written to
directly. This module is that replay: a pure `replay()` fold over a stream of
events plus a thin `load_projection()` that reads the log from the DB and folds
it. Projections are always rebuildable from the log; nothing here mutates the
log.

The write-side validation gate is re-applied on read: a `node_created` /
`edge_created` payload is fed back through `Node.model_validate` /
`Edge.model_validate`, so a Node that somehow lacked provenance could not
materialize out of the log any more than it could be written into it
(CLAUDE.md: a Node without a SourceRef is structurally impossible).

Phase 0 emits only `node_created` and `edge_created` (see
Phase0_Architecture.md Sec4). The status-transition events
(`node_confirmed/edited/rejected`) belong to Phase 1's confirmation UI; replay
raises `NotImplementedError` on them rather than silently ignoring them, so the
unbuilt behavior can't be depended on by accident. `ingestion_run` and
`spec_exported` are audit-only events with no Node/Edge effect by definition and
are skipped.

Forward note (Phase 1): once status-transition events exist, replay order
becomes semantically load-bearing (a confirm must apply after its create).
`load_projection` orders by `(timestamp, id)`, which is deterministic but not a
true insertion sequence; a monotonic sequence column is the robust fix and
should be added with the schema change that introduces those events, not now.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from atlas.models.schema import Edge, EventType, Node
from atlas.storage.tables import EventLog

__all__ = ["Projection", "load_projection", "replay"]

# Audit-only events: real entries in the log, but they carry no Node/Edge state,
# so replaying them is a no-op for a Node/Edge projection.
_NO_OP_EVENTS = frozenset({EventType.INGESTION_RUN, EventType.SPEC_EXPORTED})

# Emitted by Phase 1's confirmation UI; deliberately unbuilt in Phase 0.
_PHASE_1_EVENTS = frozenset(
    {EventType.NODE_CONFIRMED, EventType.NODE_EDITED, EventType.NODE_REJECTED}
)


class _ReplayableEvent(Protocol):
    """Structural type shared by the ORM row (`EventLog`) and the domain model
    (`Event`): both carry the event type and its JSON payload, which is all the
    reducer needs."""

    @property
    def event_type(self) -> EventType: ...

    @property
    def payload(self) -> dict[str, Any]: ...


@dataclass(frozen=True)
class Projection:
    """Materialized Node/Edge state at a point in the event log.

    Keyed by id so a future update event can supersede an entity in place by
    re-assigning the same key. Rebuilt from the log on demand -- never stored.
    """

    nodes: dict[uuid.UUID, Node] = field(default_factory=dict)
    edges: dict[uuid.UUID, Edge] = field(default_factory=dict)

    def for_feature_scope(self, feature_scope_id: uuid.UUID) -> Projection:
        """Narrow to one feature scope -- what `atlas review --feature-scope`
        shows. Edges are Node-scoped transitively: an edge is kept only when
        both endpoints survive the filter, so a relationship reaching a node
        outside the scope doesn't dangle in the scoped view."""
        nodes = {
            node_id: node
            for node_id, node in self.nodes.items()
            if node.feature_scope_id == feature_scope_id
        }
        edges = {
            edge_id: edge
            for edge_id, edge in self.edges.items()
            if edge.from_node_id in nodes and edge.to_node_id in nodes
        }
        return Projection(nodes=nodes, edges=edges)


def replay(events: Iterable[_ReplayableEvent]) -> Projection:
    """Fold an ordered event stream into a `Projection`.

    Caller passes events in chronological order. In Phase 0 the final state is
    order-independent (every event creates a distinct entity, no updates), but
    that stops being true once status-transition events land -- see the module
    docstring's forward note.
    """
    nodes: dict[uuid.UUID, Node] = {}
    edges: dict[uuid.UUID, Edge] = {}

    for event in events:
        event_type = event.event_type
        if event_type == EventType.NODE_CREATED:
            node = Node.model_validate(event.payload)
            nodes[node.id] = node
        elif event_type == EventType.EDGE_CREATED:
            edge = Edge.model_validate(event.payload)
            edges[edge.id] = edge
        elif event_type in _NO_OP_EVENTS:
            continue
        elif event_type in _PHASE_1_EVENTS:
            raise NotImplementedError(
                f"{event_type.value!r} is a Phase 1 confirmation event; "
                "projection replay does not handle it yet"
            )
        else:  # pragma: no cover - guards against a new EventType with no handler
            raise ValueError(f"no projection handler for event type {event_type!r}")

    return Projection(nodes=nodes, edges=edges)


def load_projection(
    session: Session,
    *,
    workspace_id: uuid.UUID,
    feature_scope_id: uuid.UUID | None = None,
) -> Projection:
    """Read the event_log for one workspace and replay it into a `Projection`.

    Filtering by workspace happens in SQL; the optional feature-scope narrowing
    happens on the replayed result (feature scope lives inside the Node payload,
    not on the event row).
    """
    stmt = (
        select(EventLog)
        .where(EventLog.workspace_id == workspace_id)
        .order_by(EventLog.timestamp, EventLog.id)
    )
    projection = replay(session.execute(stmt).scalars())
    if feature_scope_id is not None:
        projection = projection.for_feature_scope(feature_scope_id)
    return projection
