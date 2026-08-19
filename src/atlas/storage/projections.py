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
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from atlas.models.schema import (
    Edge,
    EventType,
    FeatureScopeAssignedPayload,
    FeatureScopeDescribedPayload,
    IngestionRunPayload,
    Node,
    NodeEditPayload,
    NodeStatus,
    NodeStatusChangePayload,
    ProductDescribedPayload,
    ProductPayload,
    RelationType,
    RunFailedPayload,
    RunFinishedPayload,
    RunStartedPayload,
    RunState,
    RunTargetKind,
    SourceType,
)
from atlas.storage.tables import EventLog

__all__ = [
    "INTERRUPTED_AFTER",
    "FeatureScope",
    "Product",
    "Projection",
    "Run",
    "load_projection",
    "replay",
]

# Audit-only events: real entries in the log, but they carry no Node/Edge state,
# so replaying them is a no-op for a Node/Edge projection. Connection events are
# here because a connection lives in a table (it must be deletable); the log
# records only that one was made or revoked, for audit.
_NO_OP_EVENTS = frozenset(
    {EventType.SPEC_EXPORTED, EventType.CONNECTION_CREATED, EventType.CONNECTION_REVOKED}
)

#: How long a run may sit with a start event and no terminal event before the
#: projection stops calling it "running" and calls it interrupted.
#:
#: Ingestion started from the UI runs in the API process -- no queue, no worker,
#: no new deployable (an explicit CLAUDE.md Non-Goal). The cost of that choice is
#: real and stated here rather than hidden: a process that dies mid-run leaves
#: exactly the same trace as a slow one. Thirty minutes is comfortably longer
#: than any observed run (the slowest live extraction to date is under three) and
#: short enough that a PM is not left watching a spinner for a run that is never
#: coming back.
INTERRUPTED_AFTER = timedelta(minutes=30)

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
    #: The product this feature is filed under, or None for a scope ingested
    #: before products existed. Resolved at the end of `replay` rather than
    #: during the fold, because an assignment and a run can arrive in either
    #: order and the answer must not depend on which.
    product_id: uuid.UUID | None = None
    #: What this feature is *for*, in the PM's own words -- `None` until someone
    #: says. Distinct from `title`, which is inherited from the artifact that
    #: opened the scope and therefore says what the feature was *called*.
    #: Resolved at the end of `replay` for the same order-independence reason
    #: `product_id` is.
    description: str | None = None


@dataclass(frozen=True)
class ScopeCounts:
    """How much of one feature still needs a human.

    Deliberately *not* a field on `FeatureScope`: that dataclass is the scope's
    identity -- what its UUID means -- and identity does not change when someone
    confirms a claim. These are derived aggregates over Nodes and Edges, and
    keeping them apart stops the identity record from looking mutable.

    Computed in `storage/` rather than in the browser because three surfaces
    need the same number (the feature list, the Conflicts nav entry, the product
    dashboard), and because deriving it client-side means shipping every node
    and edge of every feature to the browser in order to count them.
    """

    #: Every claim in the scope, whatever its status.
    total: int
    #: Claims still awaiting a ruling. Confirmed, edited and rejected all count
    #: as ruled -- a human has acted on each -- so this is the work that is left.
    unreviewed: int
    #: Disagreements, counted **once each** rather than once per side.
    conflicts: int


@dataclass(frozen=True)
class Product:
    """One product a PM works on -- its own GitHub org, its own Jira site.

    A product is a projection, not a table, for the same reason feature-scope
    identity is (slice 1A'): the event log is the source of truth and adding a
    table would put state outside it. It is deliberately *not* derived from
    ingested data such as `external_id` -- a product has to exist before the
    first connection is made to it, so it cannot be inferred from the results of
    ingestion that has not happened yet.
    """

    id: uuid.UUID
    name: str
    #: What the product is, in the PM's own words -- `None` until someone says.
    #: Authored text, not an extracted claim (`models/schema.py`
    #: `ProductDescribedPayload`), so it carries no provenance and never enters
    #: the confirmation loop.
    description: str | None = None


@dataclass(frozen=True)
class Run:
    """One ingestion job, as replayed from the log.

    A run is *not* the same thing as an `ingestion_run` event. That event means
    "one artifact was pulled and extracted", and one job can produce several of
    them -- pulling an epic's children is one thing a PM asked for and four
    artifacts fetched. So a job is bracketed by `ingestion_run_started` and
    exactly one `ingestion_run_finished` / `ingestion_run_failed`, and the
    `ingestion_run` events in between name their job through `run_id`.

    `state` is a method rather than a field because one of the four states is a
    function of *now*: see `INTERRUPTED_AFTER`. Storing it would mean writing a
    status column that has to be corrected later, which is the pattern
    event-sourcing exists to avoid.
    """

    id: uuid.UUID
    feature_scope_id: uuid.UUID
    product_id: uuid.UUID | None
    connection_id: uuid.UUID | None
    target_kind: RunTargetKind
    target: str
    started_at: datetime
    started_by: str
    finished_at: datetime | None = None
    #: `None` while running; set by whichever terminal event arrived.
    outcome: RunState | None = None
    error: str | None = None
    artifacts: int = 0
    nodes: int = 0
    edges: int = 0
    #: The feature scopes this run actually fed. Usually one -- an epic's
    #: children all land in the same scope -- but it is a tuple because nothing
    #: in the model forbids a run from opening more than one.
    feature_scope_ids: tuple[uuid.UUID, ...] = ()

    def state(self, *, now: datetime | None = None) -> RunState:
        """The run's state as of `now`, defaulting to the current time."""
        if self.outcome is not None:
            return self.outcome
        moment = now or datetime.now(UTC)
        # Postgres hands back an aware timestamp; SQLite (tests only) hands back a
        # naive one, and subtracting the two raises. The log is written in UTC
        # either way, so reading a naive value as UTC is the truth rather than a
        # guess -- the same class of dialect shim as `_UUID` in storage/tables.py.
        started = self.started_at if self.started_at.tzinfo else self.started_at.replace(tzinfo=UTC)
        return RunState.INTERRUPTED if moment - started > INTERRUPTED_AFTER else RunState.RUNNING


@dataclass(frozen=True)
class Projection:
    """Materialized Node/Edge/feature-scope/product state at a point in the log.

    Keyed by id so a future update event can supersede an entity in place by
    re-assigning the same key. Rebuilt from the log on demand -- never stored.
    """

    nodes: dict[uuid.UUID, Node] = field(default_factory=dict)
    edges: dict[uuid.UUID, Edge] = field(default_factory=dict)
    feature_scopes: dict[uuid.UUID, FeatureScope] = field(default_factory=dict)
    products: dict[uuid.UUID, Product] = field(default_factory=dict)
    #: Ingestion jobs, oldest first (the log's own order).
    runs: dict[uuid.UUID, Run] = field(default_factory=dict)

    def for_product(self, product_id: uuid.UUID) -> Projection:
        """Narrow to the features filed under one product.

        A scope with no product is excluded rather than swept into the first
        product: "not yet filed" and "filed here" are different states, and
        merging them would show a PM someone else's feature.

        `products` is deliberately *not* narrowed -- the product switcher still
        has to list the ones you are not currently looking at.
        """
        scopes = {
            scope_id: scope
            for scope_id, scope in self.feature_scopes.items()
            if scope.product_id == product_id
        }
        nodes = {
            node_id: node for node_id, node in self.nodes.items() if node.feature_scope_id in scopes
        }
        edges = {
            edge_id: edge
            for edge_id, edge in self.edges.items()
            if edge.from_node_id in nodes and edge.to_node_id in nodes
        }
        return Projection(
            nodes=nodes,
            edges=edges,
            feature_scopes=scopes,
            products=dict(self.products),
            # A run is kept when it *targeted* this product, whether or not it
            # got far enough to produce a feature — a failed run is exactly what
            # the Sources screen most needs to show.
            runs={run_id: run for run_id, run in self.runs.items() if run.product_id == product_id},
        )

    def counts_for(self, feature_scope_id: uuid.UUID) -> ScopeCounts:
        """How much of one feature is still work.

        Two rules here are load-bearing and both were chosen to make the number
        on a badge agree with the screen it sends you to:

        1. **A conflict is counted once, not once per side.** The review screen
           deliberately reports both endpoints so either card can raise a
           banner; a count that did the same would render five disagreements as
           ten. Counting edges rather than endpoints gets this for free.
        2. **An edge belongs to the scope only when both endpoints do**, which
           is the rule `for_feature_scope` already applies. A conflict reaching
           a node in another feature is real, but it is not this feature's
           number, and showing it here would send a reviewer to a screen where
           it does not appear.

        Rejected claims drop out of the conflict count: rejecting one side is
        how a person settles a disagreement, and a number no action can clear is
        worse than no number.
        """
        node_ids = {
            node_id
            for node_id, node in self.nodes.items()
            if node.feature_scope_id == feature_scope_id
        }
        live = {
            node_id for node_id in node_ids if self.nodes[node_id].status is not NodeStatus.REJECTED
        }
        return ScopeCounts(
            total=len(node_ids),
            unreviewed=sum(
                1 for node_id in node_ids if self.nodes[node_id].status is NodeStatus.UNCONFIRMED
            ),
            conflicts=sum(
                1
                for edge in self.edges.values()
                if edge.relation_type is RelationType.CONFLICTS_WITH
                and edge.from_node_id in live
                and edge.to_node_id in live
            ),
        )

    def scope_holding(self, source_type: SourceType, external_id: str) -> FeatureScope | None:
        """The feature scope an artifact was already ingested into, if any.

        The pair is the key, not `external_id` alone: an id is only unique
        *within* its source, which is why `IngestionRunPayload` carries both.

        This exists for the API's re-run block. Re-ingesting an artifact
        duplicates every claim it produced -- node ids are minted per run and
        nothing reconciles them -- and the copies are indistinguishable except by
        id, so a reviewer could confirm one and reject the other
        (`tests/test_pipeline.py` records the behaviour). Returning the scope
        rather than a bool lets the refusal say *where* the artifact already is.

        Real idempotency is Phase 3, with incremental sync. This is the guard.
        """
        for scope in self.feature_scopes.values():
            for run in scope.runs:
                if run.source_type is source_type and run.external_id == external_id:
                    return scope
        return None

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
            products=dict(self.products),
            runs={
                run_id: run
                for run_id, run in self.runs.items()
                if run.feature_scope_id == feature_scope_id
            },
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


def _require_run(runs: dict[uuid.UUID, Run], run_id: uuid.UUID, event_type: EventType) -> Run:
    """The run a terminal event names, or raise.

    Same rule the node transitions follow: a terminal event for a run the log
    never started means a corrupt log or an upstream bug, and skipping it would
    make a finished run silently vanish from the history a PM reads.
    """
    run = runs.get(run_id)
    if run is None:
        raise ValueError(
            f"{event_type.value!r} names unknown run {run_id}: "
            "the log has no ingestion_run_started for it"
        )
    return run


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
    products: dict[uuid.UUID, Product] = {}
    runs: dict[uuid.UUID, Run] = {}
    # Two ways a scope can learn its product, kept apart until the fold is over.
    # `assigned` is a deliberate human act; `defaulted` is whatever triggered
    # ingestion supplying a default. Resolving at the end rather than in the fold
    # is what makes the answer independent of the order the two arrive in --
    # otherwise a re-ingestion landing after a filing would silently move the
    # feature out of the product a person put it in.
    assigned: dict[uuid.UUID, uuid.UUID] = {}
    defaulted: dict[uuid.UUID, uuid.UUID] = {}
    # Feature descriptions are resolved at the end for the same reason: a person
    # can say what a feature is for before or after ingestion opens it, and last
    # one wins either way. A description naming a scope no run ever opened is
    # inert -- the scope has no identity to attach it to, exactly as an
    # assignment to such a scope is inert. Raising instead would make an
    # append-only log unreadable forever over a piece of orientation text.
    described: dict[uuid.UUID, str] = {}

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
            # Only a stated product is recorded. `None` is an absence, not a
            # claim that the feature belongs nowhere, so a pre-product run
            # replaying after an assignment must not unfile the feature.
            if run.product_id is not None:
                defaulted[run.feature_scope_id] = run.product_id
            # An `ingestion_run` written before slice 2B (or by a CLI command
            # with no job around it) names no run, and must not conjure one.
            if run.run_id is not None and run.run_id in runs:
                job = runs[run.run_id]
                runs[run.run_id] = replace(
                    job,
                    artifacts=job.artifacts + 1,
                    feature_scope_ids=tuple(
                        dict.fromkeys((*job.feature_scope_ids, run.feature_scope_id))
                    ),
                )
        elif event_type == EventType.INGESTION_RUN_STARTED:
            started = RunStartedPayload.model_validate(event.payload)
            runs[started.run_id] = Run(
                id=started.run_id,
                feature_scope_id=started.feature_scope_id,
                product_id=started.product_id,
                connection_id=started.connection_id,
                target_kind=started.target_kind,
                target=started.target,
                started_at=event.timestamp,
                started_by=event.actor,
            )
        elif event_type == EventType.INGESTION_RUN_FINISHED:
            done = RunFinishedPayload.model_validate(event.payload)
            runs[done.run_id] = replace(
                _require_run(runs, done.run_id, event_type),
                finished_at=event.timestamp,
                outcome=RunState.SUCCEEDED,
                nodes=done.nodes,
                edges=done.edges,
            )
        elif event_type == EventType.INGESTION_RUN_FAILED:
            broke = RunFailedPayload.model_validate(event.payload)
            runs[broke.run_id] = replace(
                _require_run(runs, broke.run_id, event_type),
                finished_at=event.timestamp,
                outcome=RunState.FAILED,
                error=broke.error,
            )
        elif event_type == EventType.PRODUCT_CREATED:
            created = ProductPayload.model_validate(event.payload)
            products[created.product_id] = Product(id=created.product_id, name=created.name)
        elif event_type == EventType.PRODUCT_RENAMED:
            renamed = ProductPayload.model_validate(event.payload)
            if renamed.product_id not in products:
                raise ValueError(
                    f"'product_renamed' names unknown product {renamed.product_id}: "
                    "the log has no product_created for it"
                )
            products[renamed.product_id] = replace(products[renamed.product_id], name=renamed.name)
        elif event_type == EventType.PRODUCT_DESCRIBED:
            described_product = ProductDescribedPayload.model_validate(event.payload)
            if described_product.product_id not in products:
                raise ValueError(
                    f"'product_described' names unknown product "
                    f"{described_product.product_id}: the log has no product_created for it"
                )
            products[described_product.product_id] = replace(
                products[described_product.product_id],
                # Empty is how a wrong description is removed, and `None` is what
                # "nobody has said" looks like everywhere else -- so the two
                # collapse here rather than leaving an empty string for every
                # reader to special-case.
                description=described_product.description or None,
            )
        elif event_type == EventType.FEATURE_SCOPE_DESCRIBED:
            described_scope = FeatureScopeDescribedPayload.model_validate(event.payload)
            described[described_scope.feature_scope_id] = described_scope.description
        elif event_type == EventType.FEATURE_SCOPE_ASSIGNED:
            assignment = FeatureScopeAssignedPayload.model_validate(event.payload)
            assigned[assignment.feature_scope_id] = assignment.product_id
        elif event_type in _NO_OP_EVENTS:
            continue
        else:  # pragma: no cover - guards against a new EventType with no handler
            raise ValueError(f"no projection handler for event type {event_type!r}")

    # An assignment outranks a run's default, in either order. A scope named by
    # an assignment but never opened by a run stays absent: it has no title, and
    # inventing one would be exactly the fabrication the rest of this module
    # refuses.
    feature_scopes = {
        scope_id: replace(
            scope,
            product_id=assigned.get(scope_id, defaulted.get(scope_id)),
            description=described.get(scope_id) or None,
        )
        for scope_id, scope in feature_scopes.items()
    }
    return Projection(
        nodes=nodes, edges=edges, feature_scopes=feature_scopes, products=products, runs=runs
    )


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
