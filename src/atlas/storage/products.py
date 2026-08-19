"""The write side of the product layer.

A product is what a PM actually works on: one has its own GitHub org and its own
Jira site, with no overlap between them (`docs/architecture/
product-model-and-frontend-rebuild-v1.md` §2). Like the confirmation loop, this
module is the *only* sanctioned way to change one, and every function bottoms out
in `append_event` -- a product is a projection, so there is nothing to mutate.

Plain functions over a `Session`, matching `storage/confirmations.py`, because
both the CLI and the API call them and neither should reimplement a payload
shape. The matching reducer lives in `storage/projections.py`; the two are only
ever correct together.

`assign_feature_scope` is the one that carries a rule worth restating: filing a
feature under a product is a *deliberate act* and outranks the `product_id` an
`ingestion_run` supplies as a default, whichever arrives later. Without that, a
re-ingestion would silently move a feature out of the product a person put it in
-- the same class of bug slice 1C fixed for titles.
"""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from atlas.models.schema import (
    ActorKind,
    EventType,
    FeatureScopeAssignedPayload,
    FeatureScopeDescribedPayload,
    ProductDescribedPayload,
    ProductPayload,
)
from atlas.storage.tables import EventLog, append_event

__all__ = [
    "assign_feature_scope",
    "create_product",
    "describe_feature_scope",
    "describe_product",
    "rename_product",
]


def create_product(
    session: Session, *, workspace_id: uuid.UUID, name: str, actor: str, actor_kind: ActorKind
) -> tuple[uuid.UUID, EventLog]:
    """Open a new product and return its id alongside the event that created it.

    The id is minted here rather than taken from the caller: a product is created
    exactly once, so letting an API body choose its own identifier would be the
    same hole `add_node` closes by building the Node from fields.
    """
    product_id = uuid.uuid4()
    payload = ProductPayload(product_id=product_id, name=name)
    event = append_event(
        session,
        event_type=EventType.PRODUCT_CREATED,
        payload=payload.model_dump(mode="json"),
        actor=actor,
        actor_kind=actor_kind,
        workspace_id=workspace_id,
    )
    return product_id, event


def rename_product(
    session: Session,
    *,
    workspace_id: uuid.UUID,
    product_id: uuid.UUID,
    name: str,
    actor: str,
    actor_kind: ActorKind,
) -> EventLog:
    """Rename an existing product.

    Deliberately does not check that the product exists: the caller loaded the
    projection to get here, and the replay raises on a rename with no creation
    rather than swallowing it -- so a bad rename fails loudly at read time
    instead of being silently dropped at write time.
    """
    payload = ProductPayload(product_id=product_id, name=name)
    return append_event(
        session,
        event_type=EventType.PRODUCT_RENAMED,
        payload=payload.model_dump(mode="json"),
        actor=actor,
        actor_kind=actor_kind,
        workspace_id=workspace_id,
    )


def assign_feature_scope(
    session: Session,
    *,
    workspace_id: uuid.UUID,
    feature_scope_id: uuid.UUID,
    product_id: uuid.UUID,
    actor: str,
    actor_kind: ActorKind,
) -> EventLog:
    """File a feature under a product.

    This is how the feature scopes ingested before products existed get a home:
    one event each, appended. The `ingestion_run` events that opened them are
    never rewritten -- the log is append-only, and that is not negotiable for a
    convenience.
    """
    payload = FeatureScopeAssignedPayload(feature_scope_id=feature_scope_id, product_id=product_id)
    return append_event(
        session,
        event_type=EventType.FEATURE_SCOPE_ASSIGNED,
        payload=payload.model_dump(mode="json"),
        actor=actor,
        actor_kind=actor_kind,
        workspace_id=workspace_id,
    )


def describe_product(
    session: Session,
    *,
    workspace_id: uuid.UUID,
    product_id: uuid.UUID,
    description: str,
    actor: str,
    actor_kind: ActorKind,
) -> EventLog:
    """Say what a product is, in the PM's own words.

    An empty `description` clears it -- the only way to remove a wrong one, in a
    log that only moves forward (`models/schema.py` `DescriptionStr`).

    Like `rename_product`, this deliberately does not check that the product
    exists: the caller loaded the projection to get here, and the replay raises
    on a description with no creation rather than swallowing it.
    """
    payload = ProductDescribedPayload(product_id=product_id, description=description)
    return append_event(
        session,
        event_type=EventType.PRODUCT_DESCRIBED,
        payload=payload.model_dump(mode="json"),
        actor=actor,
        actor_kind=actor_kind,
        workspace_id=workspace_id,
    )


def describe_feature_scope(
    session: Session,
    *,
    workspace_id: uuid.UUID,
    feature_scope_id: uuid.UUID,
    description: str,
    actor: str,
    actor_kind: ActorKind,
) -> EventLog:
    """Say what a feature is *for*.

    Not a rename: the scope's `title` stays the artifact's, fixed to the run that
    opened it (`storage/projections.py`), so a feature keeps the name a reviewer
    recognises while gaining the sentence that says why it exists.
    """
    payload = FeatureScopeDescribedPayload(
        feature_scope_id=feature_scope_id, description=description
    )
    return append_event(
        session,
        event_type=EventType.FEATURE_SCOPE_DESCRIBED,
        payload=payload.model_dump(mode="json"),
        actor=actor,
        actor_kind=actor_kind,
        workspace_id=workspace_id,
    )
