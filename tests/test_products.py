"""Tests for the product layer: `product_created` / `product_renamed` /
`feature_scope_assigned` replaying into `Projection.products`, and the binding
between a feature scope and the product that owns it.

A product is what a PM actually works on -- one has its own GitHub org and its
own Jira site, with no overlap between them (`docs/architecture/
product-model-and-frontend-rebuild-v1.md` §2). It is deliberately a *projection*
from the event log, not a table: the same pattern slice 1A' used for feature-scope
identity, so there is no migration and no state living outside the log.

The rule these tests pin down, and the one worth reading carefully:

    An explicit `feature_scope_assigned` event always beats the `product_id`
    carried on an `ingestion_run`, in either order.

An assignment is a deliberate act by a person; a run's `product_id` is a default
supplied by whatever triggered ingestion. If ingestion could overwrite it, then
re-ingesting a feature would silently move it out of the product someone filed
it under -- the same class of bug slice 1C fixed for titles, where a Jira ticket
must not rename a feature a GitHub PR named.
"""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from atlas.models.schema import (
    DESCRIPTION_MAX_LENGTH as DESCRIPTION_MAX,
)
from atlas.models.schema import (
    ActorKind,
    CreatedBy,
    Event,
    EventType,
    FeatureScopeAssignedPayload,
    FeatureScopeDescribedPayload,
    IngestionRunPayload,
    Node,
    NodeStatus,
    NodeType,
    ProductDescribedPayload,
    ProductPayload,
    SourceRef,
    SourceType,
)
from atlas.storage.projections import Product, replay

WORKSPACE_ID = uuid.UUID("00000000-0000-0000-0000-000000000000")
PRODUCT_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
OTHER_PRODUCT_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")
SCOPE_ID = uuid.UUID("33333333-3333-3333-3333-333333333333")
OTHER_SCOPE_ID = uuid.UUID("44444444-4444-4444-4444-444444444444")


# --- builders ------------------------------------------------------------------


def product_created(
    *, product_id: uuid.UUID = PRODUCT_ID, name: str = "Acme Web", actor: str = "priya"
) -> Event:
    return Event(
        event_type=EventType.PRODUCT_CREATED,
        payload=ProductPayload(product_id=product_id, name=name).model_dump(mode="json"),
        actor=actor,
        actor_kind=ActorKind.HUMAN,
        workspace_id=WORKSPACE_ID,
    )


def product_renamed(
    *, product_id: uuid.UUID = PRODUCT_ID, name: str = "Acme Web (v2)", actor: str = "priya"
) -> Event:
    return Event(
        event_type=EventType.PRODUCT_RENAMED,
        payload=ProductPayload(product_id=product_id, name=name).model_dump(mode="json"),
        actor=actor,
        actor_kind=ActorKind.HUMAN,
        workspace_id=WORKSPACE_ID,
    )


def feature_scope_assigned(
    *,
    feature_scope_id: uuid.UUID = SCOPE_ID,
    product_id: uuid.UUID = PRODUCT_ID,
    actor: str = "priya",
) -> Event:
    payload = FeatureScopeAssignedPayload(feature_scope_id=feature_scope_id, product_id=product_id)
    return Event(
        event_type=EventType.FEATURE_SCOPE_ASSIGNED,
        payload=payload.model_dump(mode="json"),
        actor=actor,
        actor_kind=ActorKind.HUMAN,
        workspace_id=WORKSPACE_ID,
    )


def ingestion_run(
    *,
    feature_scope_id: uuid.UUID = SCOPE_ID,
    product_id: uuid.UUID | None = None,
    title: str = "ripgrep #111 -- add a --pre preprocessor flag",
    external_id: str = "BurntSushi/ripgrep#111",
) -> Event:
    payload = IngestionRunPayload(
        feature_scope_id=feature_scope_id,
        product_id=product_id,
        title=title,
        source_type=SourceType.GITHUB_PR,
        external_id=external_id,
        url=f"https://github.com/{external_id.split('#')[0]}/pull/111",
    )
    return Event(
        event_type=EventType.INGESTION_RUN,
        payload=payload.model_dump(mode="json"),
        actor="system",
        actor_kind=ActorKind.AUTOMATED,
        workspace_id=WORKSPACE_ID,
    )


def node_created(*, feature_scope_id: uuid.UUID = SCOPE_ID) -> Event:
    node = Node(
        workspace_id=WORKSPACE_ID,
        feature_scope_id=feature_scope_id,
        type=NodeType.REQUIREMENT,
        content="Must stream stdin rather than buffering the whole file.",
        status=NodeStatus.UNCONFIRMED,
        created_by=CreatedBy.SYSTEM,
        confidence_score=0.9,
        source_refs=[
            SourceRef(
                workspace_id=WORKSPACE_ID,
                source_type=SourceType.GITHUB_PR,
                external_id="BurntSushi/ripgrep#111",
                url="https://github.com/BurntSushi/ripgrep/pull/111",
                excerpt="we should stream stdin rather than buffering",
            )
        ],
    )
    return Event(
        event_type=EventType.NODE_CREATED,
        payload=node.model_dump(mode="json"),
        actor="system",
        actor_kind=ActorKind.AUTOMATED,
        workspace_id=WORKSPACE_ID,
    )


# --- the product projection ----------------------------------------------------


def test_product_created_materializes_a_product() -> None:
    projection = replay([product_created()])
    assert projection.products == {PRODUCT_ID: Product(id=PRODUCT_ID, name="Acme Web")}


def test_product_renamed_supersedes_the_name() -> None:
    projection = replay([product_created(), product_renamed(name="Acme Platform")])
    assert projection.products[PRODUCT_ID].name == "Acme Platform"


def test_renaming_an_unknown_product_raises() -> None:
    """Same rule as a status transition naming an unknown node: a rename with no
    creation means a corrupt log or an upstream bug, and swallowing it would make
    the rename silently vanish."""
    with pytest.raises(ValueError, match="unknown product"):
        replay([product_renamed()])


def test_a_blank_product_name_is_refused() -> None:
    with pytest.raises(ValidationError):
        ProductPayload(product_id=PRODUCT_ID, name="   ")


def test_products_are_independent_of_feature_scopes() -> None:
    """A product exists the moment it is created -- before anything is ingested
    into it. That ordering is the whole reason a product cannot be derived from
    `external_id`: it has to exist before the first connection does."""
    projection = replay([product_created()])
    assert projection.products
    assert projection.feature_scopes == {}


# --- binding a feature scope to a product --------------------------------------


def test_a_run_carrying_a_product_id_binds_the_scope() -> None:
    projection = replay([product_created(), ingestion_run(product_id=PRODUCT_ID)])
    assert projection.feature_scopes[SCOPE_ID].product_id == PRODUCT_ID


def test_a_run_without_a_product_id_replays_cleanly() -> None:
    """Every `ingestion_run` already in the live log predates the product layer.
    `product_id` is optional for exactly that reason -- the same shape slice 1D's
    tool-call manifest used -- and such a scope projects as unassigned rather
    than crashing the replay or inventing a product."""
    projection = replay([ingestion_run()])
    assert projection.feature_scopes[SCOPE_ID].product_id is None


def test_assignment_binds_a_scope_opened_before_products_existed() -> None:
    """The migration path for the four scopes already in the live database: one
    event each, appended -- never a rewrite of the log."""
    projection = replay([ingestion_run(), product_created(), feature_scope_assigned()])
    assert projection.feature_scopes[SCOPE_ID].product_id == PRODUCT_ID


def test_assignment_beats_a_runs_product_id_when_the_run_comes_first() -> None:
    projection = replay(
        [
            product_created(),
            product_created(product_id=OTHER_PRODUCT_ID, name="Acme Mobile"),
            ingestion_run(product_id=OTHER_PRODUCT_ID),
            feature_scope_assigned(product_id=PRODUCT_ID),
        ]
    )
    assert projection.feature_scopes[SCOPE_ID].product_id == PRODUCT_ID


def test_assignment_beats_a_runs_product_id_when_the_run_comes_last() -> None:
    """The order-independent half of the rule. A re-ingestion arriving after a
    deliberate filing must not move the feature back."""
    projection = replay(
        [
            product_created(),
            product_created(product_id=OTHER_PRODUCT_ID, name="Acme Mobile"),
            feature_scope_assigned(product_id=PRODUCT_ID),
            ingestion_run(product_id=OTHER_PRODUCT_ID),
        ]
    )
    assert projection.feature_scopes[SCOPE_ID].product_id == PRODUCT_ID


def test_a_later_run_without_a_product_id_does_not_clear_an_assignment() -> None:
    """`product_id=None` is an absence, not a statement that the scope belongs
    nowhere. Treating it as last-write-wins would let any pre-product ingestion
    path silently unfile a feature."""
    projection = replay([product_created(), feature_scope_assigned(), ingestion_run()])
    assert projection.feature_scopes[SCOPE_ID].product_id == PRODUCT_ID


def test_the_last_assignment_wins() -> None:
    projection = replay(
        [
            product_created(),
            product_created(product_id=OTHER_PRODUCT_ID, name="Acme Mobile"),
            ingestion_run(),
            feature_scope_assigned(product_id=PRODUCT_ID),
            feature_scope_assigned(product_id=OTHER_PRODUCT_ID),
        ]
    )
    assert projection.feature_scopes[SCOPE_ID].product_id == OTHER_PRODUCT_ID


def test_assigning_a_scope_that_has_no_run_projects_no_scope() -> None:
    """A scope with no `ingestion_run` has no identity to attach a product to --
    the pre-1A' case the projection already tolerates. An assignment does not
    conjure one with a fabricated title."""
    projection = replay([product_created(), feature_scope_assigned(), node_created()])
    assert projection.feature_scopes == {}
    assert projection.nodes


def test_assignment_does_not_disturb_the_title_rule() -> None:
    """Slice 1C fixed the title to the run that opened the scope. Filing the
    feature under a product must not reopen that."""
    projection = replay(
        [
            product_created(),
            ingestion_run(title="ripgrep #111 -- add a --pre preprocessor flag"),
            feature_scope_assigned(),
            ingestion_run(title="SCRUM-7 -- ship a --maxdepth flag", external_id="SCRUM-7"),
        ]
    )
    scope = projection.feature_scopes[SCOPE_ID]
    assert scope.title == "ripgrep #111 -- add a --pre preprocessor flag"
    assert len(scope.runs) == 2


# --- narrowing to one product --------------------------------------------------


def test_for_product_keeps_only_that_products_scopes_and_their_nodes() -> None:
    projection = replay(
        [
            product_created(),
            product_created(product_id=OTHER_PRODUCT_ID, name="Acme Mobile"),
            ingestion_run(product_id=PRODUCT_ID),
            node_created(),
            ingestion_run(
                feature_scope_id=OTHER_SCOPE_ID,
                product_id=OTHER_PRODUCT_ID,
                external_id="acme/mobile#4",
            ),
            node_created(feature_scope_id=OTHER_SCOPE_ID),
        ]
    )
    narrowed = projection.for_product(PRODUCT_ID)

    assert set(narrowed.feature_scopes) == {SCOPE_ID}
    assert all(node.feature_scope_id == SCOPE_ID for node in narrowed.nodes.values())
    # The product list itself is not narrowed -- the switcher still needs it.
    assert set(narrowed.products) == {PRODUCT_ID, OTHER_PRODUCT_ID}


def test_for_product_excludes_unassigned_scopes() -> None:
    projection = replay([product_created(), ingestion_run()])
    assert projection.for_product(PRODUCT_ID).feature_scopes == {}


# --- what a product and a feature *are* (slice 3) -------------------------------
#
# `description` is PM-authored plain text, not a Node: it carries no provenance
# and never enters the confirmation loop, per decision 4 of
# `docs/decisions/2026-08-19-product-orientation-rerun-safety-and-demo-data.md`.
# Extracting it instead would have made orientation a *claim about the feature*,
# obliged to start unconfirmed like anything else -- machine-written text in the
# one place a first-time visitor goes to find out what they are looking at.


def product_described(
    *,
    product_id: uuid.UUID = PRODUCT_ID,
    description: str = "The billing surface Acme's customers actually see.",
    actor: str = "priya",
) -> Event:
    payload = ProductDescribedPayload(product_id=product_id, description=description)
    return Event(
        event_type=EventType.PRODUCT_DESCRIBED,
        payload=payload.model_dump(mode="json"),
        actor=actor,
        actor_kind=ActorKind.HUMAN,
        workspace_id=WORKSPACE_ID,
    )


def feature_scope_described(
    *,
    feature_scope_id: uuid.UUID = SCOPE_ID,
    description: str = "Why we are letting users search inside archives.",
    actor: str = "priya",
) -> Event:
    payload = FeatureScopeDescribedPayload(
        feature_scope_id=feature_scope_id, description=description
    )
    return Event(
        event_type=EventType.FEATURE_SCOPE_DESCRIBED,
        payload=payload.model_dump(mode="json"),
        actor=actor,
        actor_kind=ActorKind.HUMAN,
        workspace_id=WORKSPACE_ID,
    )


def test_a_product_starts_with_no_description() -> None:
    """Absent, not empty. Nothing is invented for a product nobody has described,
    and the Overview renders the absence rather than a placeholder sentence."""
    assert replay([product_created()]).products[PRODUCT_ID].description is None


def test_product_described_gives_the_product_its_description() -> None:
    projection = replay([product_created(), product_described()])
    assert (
        projection.products[PRODUCT_ID].description
        == "The billing surface Acme's customers actually see."
    )


def test_describing_an_unknown_product_raises() -> None:
    """Same rule as a rename: a description with no creation means a corrupt log
    or an upstream bug, and swallowing it would make the write silently vanish."""
    with pytest.raises(ValueError, match="unknown product"):
        replay([product_described()])


def test_the_last_product_description_wins() -> None:
    projection = replay(
        [product_created(), product_described(), product_described(description="Rewritten.")]
    )
    assert projection.products[PRODUCT_ID].description == "Rewritten."


def test_a_product_description_can_be_cleared() -> None:
    """An empty description is how a PM removes a wrong one. Refusing blank here
    would make a bad description permanent, which is worse than allowing the
    field to return to absent."""
    projection = replay([product_created(), product_described(), product_described(description="")])
    assert projection.products[PRODUCT_ID].description is None


def test_renaming_a_product_keeps_its_description() -> None:
    """The two events say different things about the same product, so neither may
    overwrite the other's field. A rename that silently blanked the description
    is exactly the bug a wholesale re-construction of the projected object
    produces."""
    projection = replay([product_created(), product_described(), product_renamed()])
    assert projection.products[PRODUCT_ID].name == "Acme Web (v2)"
    assert projection.products[PRODUCT_ID].description is not None


def test_a_feature_scope_starts_with_no_description() -> None:
    assert replay([ingestion_run()]).feature_scopes[SCOPE_ID].description is None


def test_feature_scope_described_gives_the_feature_its_description() -> None:
    projection = replay([ingestion_run(), feature_scope_described()])
    assert (
        projection.feature_scopes[SCOPE_ID].description
        == "Why we are letting users search inside archives."
    )


def test_a_description_written_before_the_run_still_lands() -> None:
    """Order-independent for the same reason `feature_scope_assigned` is: a
    person's statement about a feature must not depend on whether ingestion
    happened to be replayed first."""
    projection = replay([feature_scope_described(), ingestion_run()])
    assert projection.feature_scopes[SCOPE_ID].description is not None


def test_a_later_run_does_not_clear_a_feature_description() -> None:
    """A second source joining a feature adds evidence; it does not un-say what a
    person wrote about it -- the same instinct as the first-run-wins title rule."""
    projection = replay(
        [
            ingestion_run(),
            feature_scope_described(),
            ingestion_run(title="SCRUM-7 -- ship a --maxdepth flag", external_id="SCRUM-7"),
        ]
    )
    assert projection.feature_scopes[SCOPE_ID].description is not None
    assert projection.feature_scopes[SCOPE_ID].title.startswith("ripgrep #111")


def test_a_feature_description_survives_being_filed_under_a_product() -> None:
    projection = replay(
        [ingestion_run(), feature_scope_described(), product_created(), feature_scope_assigned()]
    )
    scope = projection.feature_scopes[SCOPE_ID]
    assert scope.product_id == PRODUCT_ID
    assert scope.description is not None


def test_describing_a_scope_that_has_no_run_projects_no_scope() -> None:
    """The pre-1A' case, handled exactly as an assignment to such a scope is: a
    description does not conjure a feature with a fabricated title. The event is
    inert rather than fatal -- the log is append-only, so a replay that raised
    here would make the whole workspace unreadable forever."""
    projection = replay([feature_scope_described(), node_created()])
    assert projection.feature_scopes == {}
    assert projection.nodes


def test_a_description_may_be_blank_but_not_unbounded() -> None:
    """Blank is meaningful (it clears). Unbounded is not: the payload lands in
    JSONB in an append-only log, so there is no later opportunity to trim it."""
    assert ProductDescribedPayload(product_id=PRODUCT_ID, description="").description == ""
    with pytest.raises(ValidationError):
        ProductDescribedPayload(product_id=PRODUCT_ID, description="x" * (DESCRIPTION_MAX + 1))


def test_surrounding_whitespace_is_trimmed_from_a_description() -> None:
    """Unlike a `SourceRef.excerpt`, an authored description carries no provenance
    obligation to stay verbatim -- and a description of only spaces means
    cleared, not "described as blank"."""
    payload = FeatureScopeDescribedPayload(feature_scope_id=SCOPE_ID, description="  spaced  ")
    assert payload.description == "spaced"
    assert (
        FeatureScopeDescribedPayload(feature_scope_id=SCOPE_ID, description="   ").description == ""
    )
