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

The status-transition events (`node_confirmed`/`node_edited`/`node_rejected`,
TRD Sec6) supersede a node in place: the reducer rebuilds it through
`Node.model_validate` with the new status/content, so the same gate that guards
a create also guards an edit. A transition naming a node the log never created
raises rather than being skipped -- that combination means a corrupt log or an
upstream bug, and swallowing it would make a confirm silently vanish.

There is no separate "manual add" event: TRD Sec3.1's `event_type` enum has no
such member, so a hand-written node is a plain `node_created` with
`created_by = user` and no confidence score. `spec_exported` is audit-only, with
no projected effect by definition, and is skipped.

`ingestion_run` projects a third thing alongside nodes and edges: the identity of
a **feature scope** (Phase1_Architecture Sec4.4). It has no Node/Edge effect, but
it is what makes a scope UUID mean "ripgrep #111 -- add a --pre flag" instead of
nothing at all. Scope identity is a projection like everything else -- not a
registry table, and not a name map living outside the log.

Replay order is load-bearing (an edit after a confirm must win), so
`load_projection` orders by `event_log.sequence` -- the database-assigned append
order -- not by wall-clock `timestamp`, which two events in one transaction can
share and a clock adjustment can invert.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from atlas.models.schema import (
    Edge,
    EventType,
    IngestionRunPayload,
    Node,
    NodeEditPayload,
    NodeStatus,
    NodeStatusChangePayload,
)
from atlas.storage.tables import EventLog

__all__ = ["FeatureScope", "Projection", "load_projection", "replay"]

# Audit-only events: real entries in the log, but they carry no Node/Edge state,
# so replaying them is a no-op for a Node/Edge projection.
_NO_OP_EVENTS = frozenset({EventType.SPEC_EXPORTED})

# The confirm/reject pair: a human ruling that changes status and nothing else.
_STATUS_ONLY_TRANSITIONS = {
    EventType.NODE_CONFIRMED: NodeStatus.CONFIRMED,
    EventType.NODE_REJECTED: NodeStatus.REJECTED,
}


class _ReplayableEvent(Protocol):
    """Structural type shared by the ORM row (`EventLog`) and the domain model
    (`Event`): both carry the event type, its JSON payload, and the actor and
    timestamp a status transition stamps onto the node it supersedes."""

    @property
    def event_type(self) -> EventType: ...

    @property
    def payload(self) -> dict[str, Any]: ...

    @property
    def actor(self) -> str: ...

    @property
    def timestamp(self) -> datetime: ...


@dataclass(frozen=True)
class FeatureScope:
    """The projected identity of one feature scope: what its UUID *means*.

    `runs` is every `ingestion_run` that fed this scope, in append order -- a
    feature is assembled from many sources, which is what the UI's "assembled
    from" strip reads.

    **`title` is the *first* run's** -- the one that opened the scope. This is a
    deliberate exception to the last-write-wins rule the rest of the projection
    follows, and slice 1C is what forced it: once a second *source* can join an
    existing scope, last-wins means adding a Jira ticket silently renames a
    feature a GitHub PR named, changing what a reviewer is looking at mid-review.
    A feature scope is named by the artifact it was opened from; later runs add
    evidence to it, they do not re-christen it. The cost is that re-ingesting a
    retitled PR keeps the original name, which is the lesser wrong -- and a
    rename, if ever wanted, should be a deliberate act with its own event rather
    than a side effect of ingestion.
    """

    id: uuid.UUID
    title: str
    runs: tuple[IngestionRunPayload, ...]


@dataclass(frozen=True)
class Projection:
    """Materialized Node/Edge/feature-scope state at a point in the event log.

    Keyed by id so a future update event can supersede an entity in place by
    re-assigning the same key. Rebuilt from the log on demand -- never stored.
    """

    nodes: dict[uuid.UUID, Node] = field(default_factory=dict)
    edges: dict[uuid.UUID, Edge] = field(default_factory=dict)
    feature_scopes: dict[uuid.UUID, FeatureScope] = field(default_factory=dict)

    def for_feature_scope(self, feature_scope_id: uuid.UUID) -> Projection:
        """Narrow to one feature scope -- what `atlas review --feature-scope`
        shows. Edges are Node-scoped transitively: an edge is kept only when
        both endpoints survive the filter, so a relationship reaching a node
        outside the scope doesn't dangle in the scoped view.

        A scope ingested before slice 1A' has nodes but no `ingestion_run`, so
        its identity is simply absent -- the caller renders an unnamed scope
        rather than being handed a fabricated title.
        """
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
        scope = self.feature_scopes.get(feature_scope_id)
        return Projection(
            nodes=nodes,
            edges=edges,
            feature_scopes={} if scope is None else {feature_scope_id: scope},
        )


def _supersede(
    nodes: dict[uuid.UUID, Node],
    node_id: uuid.UUID,
    event: _ReplayableEvent,
    **changes: Any,
) -> Node:
    """Rebuild the node `node_id` with `changes` applied, stamped with who acted.

    Deliberately re-validates through `Node.model_validate` rather than mutating
    or `model_copy`-ing: an edit passes the same gate a create does, so no
    transition can produce a node the schema would have refused.
    """
    current = nodes.get(node_id)
    if current is None:
        raise ValueError(
            f"{event.event_type.value!r} names unknown node {node_id}: "
            "the log has no node_created for it"
        )
    return Node.model_validate(
        {
            **current.model_dump(),
            **changes,
            "updated_by": event.actor,
            "updated_at": event.timestamp,
        }
    )


def replay(events: Iterable[_ReplayableEvent]) -> Projection:
    """Fold an ordered event stream into a `Projection`.

    Caller passes events in append order (`load_projection` orders by
    `event_log.sequence`). Order is load-bearing: transitions supersede a node in
    place, so the last event to touch a node wins -- which is also what makes
    undo free, a reject followed by a confirm leaving the node confirmed.
    """
    nodes: dict[uuid.UUID, Node] = {}
    edges: dict[uuid.UUID, Edge] = {}
    feature_scopes: dict[uuid.UUID, FeatureScope] = {}

    for event in events:
        event_type = event.event_type
        if event_type == EventType.NODE_CREATED:
            node = Node.model_validate(event.payload)
            nodes[node.id] = node
        elif event_type == EventType.EDGE_CREATED:
            edge = Edge.model_validate(event.payload)
            edges[edge.id] = edge
        elif event_type in _STATUS_ONLY_TRANSITIONS:
            ruling = NodeStatusChangePayload.model_validate(event.payload)
            nodes[ruling.node_id] = _supersede(
                nodes, ruling.node_id, event, status=_STATUS_ONLY_TRANSITIONS[event_type]
            )
        elif event_type == EventType.NODE_EDITED:
            edit = NodeEditPayload.model_validate(event.payload)
            nodes[edit.node_id] = _supersede(
                nodes, edit.node_id, event, content=edit.content, status=NodeStatus.EDITED
            )
        elif event_type == EventType.INGESTION_RUN:
            run = IngestionRunPayload.model_validate(event.payload)
            existing = feature_scopes.get(run.feature_scope_id)
            feature_scopes[run.feature_scope_id] = FeatureScope(
                id=run.feature_scope_id,
                title=existing.title if existing else run.title,
                runs=(*(existing.runs if existing else ()), run),
            )
        elif event_type in _NO_OP_EVENTS:
            continue
        else:  # pragma: no cover - guards against a new EventType with no handler
            raise ValueError(f"no projection handler for event type {event_type!r}")

    return Projection(nodes=nodes, edges=edges, feature_scopes=feature_scopes)


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
    stmt = select(EventLog).where(EventLog.workspace_id == workspace_id).order_by(EventLog.sequence)
    projection = replay(session.execute(stmt).scalars())
    if feature_scope_id is not None:
        projection = projection.for_feature_scope(feature_scope_id)
    return projection
