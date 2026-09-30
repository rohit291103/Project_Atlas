"""The browser suite's fixture workspace (slice 6).

`scripts/seed_test_workspace.py` is a script, but what it builds is the ground
every Playwright assertion stands on -- so the properties the suite depends on
are checked here, in pytest, rather than discovered as 37 confusing browser
failures at 11pm. Three kinds of check:

* **The fixture is real data.** Excerpts, URLs and confidence scores are carried
  from `tests/evals/golden_set/` untouched. A fixture with invented provenance
  in a product whose argument *is* provenance would be self-refuting, and the
  cheapest way for it to happen is someone "fixing" a claim's wording.
* **The fixture is deterministic and cannot collide.** Every id is `uuid5` off
  one namespace, so a rebuild reproduces the same workspace and no real row
  (minted `uuid4`) can ever share an id with a fixture row.
* **The fixture satisfies the suite.** Seeded into an in-memory database and
  replayed, it has to hold what the tests look for: two products, an unruled
  claim to stage, a live disagreement, and a confirmed body for About and the
  spec export. That last check is the one worth having -- it fails on the same
  commit that breaks the browser suite, without a browser.
"""

from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session, sessionmaker

# `scripts/` is not a package and deliberately holds no `__init__.py` -- it is
# operator tooling, not importable application code. Reaching it through the
# repo root as a PEP 420 namespace package keeps that true while still letting
# the fixture's logic be tested.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from atlas.assembly import assemble  # noqa: E402
from atlas.models.schema import (  # noqa: E402
    ActorKind,
    EventType,
    NodeStatus,
    RelationType,
    Role,
    SourceType,
)
from atlas.storage.db import Base, get_engine, get_sessionmaker, session_scope  # noqa: E402
from atlas.storage.projections import load_projection  # noqa: E402
from atlas.storage.tables import EventLog, WorkspaceMember, append_event  # noqa: E402
from scripts.seed_test_workspace import (  # noqa: E402
    ADMIN,
    EDITOR,
    FIXTURE_WORKSPACE_ID,
    PLAN,
    VIEWER,
    Artifact,
    BuiltFeature,
    FeaturePlan,
    Rulings,
    build_feature,
    clear,
    fixture_id,
    load_case,
    plan_rulings,
    provision,
    seed,
)

_PRODUCT_ID = uuid.uuid4()
_MAX_DEPTH = PLAN[0].features[0]


@pytest.fixture
def session_factory() -> sessionmaker[Session]:
    engine: Engine = get_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return get_sessionmaker(engine)


def _build(plan: FeaturePlan = _MAX_DEPTH) -> BuiltFeature:
    return build_feature(plan, workspace_id=FIXTURE_WORKSPACE_ID, product_id=_PRODUCT_ID)


# --- the fixture is real data ---------------------------------------------------


def test_every_claim_keeps_the_excerpt_the_extraction_actually_returned() -> None:
    """Provenance is carried over verbatim, not paraphrased into a fixture.

    The excerpt is the evidence (`SourceRef.excerpt` is never normalized), so a
    seed that reworded one would be putting a fabricated citation in the
    database -- the exact failure the whole product exists to prevent.
    """
    built = _build()
    recorded = {
        ref["excerpt"]
        for artifact in _MAX_DEPTH.artifacts
        for node in load_case(artifact.case)["nodes"]
        for ref in node["source_refs"]
    }
    seeded = {ref.excerpt for node in built.nodes for ref in node.source_refs}
    assert seeded <= recorded
    assert len(seeded) > 5


def test_the_content_of_every_claim_is_the_recorded_content() -> None:
    built = _build()
    recorded = {
        node["content"]
        for artifact in _MAX_DEPTH.artifacts
        for node in load_case(artifact.case)["nodes"]
    }
    assert {node.content for node in built.nodes} == recorded


def test_a_plan_citing_an_artifact_the_recording_never_mentions_is_refused() -> None:
    """The one way the plan and the recording can silently disagree.

    A run event states where a feature's claims came from. If the plan's URL is
    typed from memory and the case was re-recorded against something else, the
    feature would carry a run pointing at an artifact none of its claims quote --
    a mislabelled source, which is worse than a missing one.
    """
    drifted = FeaturePlan(
        slug="drifted",
        title="Drifted",
        description="…",
        artifacts=(
            Artifact(
                case="pr-111",
                source_type=SourceType.GITHUB_PR,
                external_id="BurntSushi/ripgrep#999",
                url="https://github.com/BurntSushi/ripgrep/pull/999",
            ),
        ),
    )
    with pytest.raises(SystemExit, match="which no recorded source_ref mentions"):
        _build(drifted)


# --- the fixture is deterministic, and cannot collide ---------------------------


def test_rebuilding_reproduces_the_same_ids() -> None:
    first, second = _build(), _build()
    assert [node.id for node in first.nodes] == [node.id for node in second.nodes]
    assert [edge.id for edge in first.edges] == [edge.id for edge in second.edges]
    assert first.scope_id == second.scope_id


def test_no_seeded_id_is_a_recorded_id() -> None:
    """Recorded ids are `uuid4` from real runs and could collide with live rows.

    Every id is re-stamped through `fixture_id`, which is `uuid5` off one
    namespace -- a space nothing in production ever mints from.
    """
    recorded = {
        node["id"]
        for artifact in _MAX_DEPTH.artifacts
        for node in load_case(artifact.case)["nodes"]
    }
    assert {str(node.id) for node in _build().nodes}.isdisjoint(recorded)
    assert fixture_id("node", "a") != fixture_id("node", "b")


def test_every_claim_lands_in_this_workspace_and_its_own_feature() -> None:
    built = _build()
    for node in built.nodes:
        assert node.workspace_id == FIXTURE_WORKSPACE_ID
        assert node.feature_scope_id == built.scope_id
        assert all(ref.workspace_id == FIXTURE_WORKSPACE_ID for ref in node.source_refs)
        # Status comes from a ruling event, never from the recording.
        assert node.status is NodeStatus.UNCONFIRMED


def test_the_cross_source_feature_really_spans_two_tools_and_disagrees() -> None:
    """The feature half the suite's assertions open by default.

    `cross-SCRUM-8`'s edges reach back into `pr-111`'s nodes, which only works
    because both are seeded into this one feature in that order. If the plan ever
    drops one, this fails rather than the conflict quietly disappearing.
    """
    built = _build()
    sources = {ref.source_type for node in built.nodes for ref in node.source_refs}
    assert {SourceType.GITHUB_PR, SourceType.JIRA_TICKET} <= sources

    ids = {node.id for node in built.nodes}
    conflicts = [edge for edge in built.edges if edge.relation_type is RelationType.CONFLICTS_WITH]
    assert conflicts
    for edge in conflicts:
        assert {edge.from_node_id, edge.to_node_id} <= ids
        by_id = {node.id: node for node in built.nodes}
        left = {ref.source_type for ref in by_id[edge.from_node_id].source_refs}
        right = {ref.source_type for ref in by_id[edge.to_node_id].source_refs}
        assert left != right, "a cross-source conflict has to cross a source"


# --- the rulings leave the suite something to do --------------------------------


def test_no_disagreement_is_settled_by_the_seed() -> None:
    """A rejected side settles a conflict, and About then has nothing to show.

    `assembly._live_conflicts` needs neither side rejected and one side ruled, so
    the recipe rules on *free* claims only and takes one side of each conflict
    deliberately.
    """
    built = _build()
    rulings = plan_rulings(built)
    endpoints = {
        node_id
        for edge in built.edges
        if edge.relation_type is RelationType.CONFLICTS_WITH
        for node_id in (edge.from_node_id, edge.to_node_id)
    }
    assert endpoints & set(rulings.confirm)
    assert not endpoints & set(rulings.reject)
    assert not endpoints & set(rulings.edit)


def test_something_is_always_left_to_review() -> None:
    """Two spare claims: one for the suite to confirm, one to advance onto."""
    built = _build()
    rulings = plan_rulings(built)
    ruled = set(rulings.confirm) | set(rulings.edit) | set(rulings.reject)
    assert len({node.id for node in built.nodes} - ruled) >= 2


def test_a_recipe_that_would_empty_the_queue_is_refused() -> None:
    greedy = FeaturePlan(
        slug="greedy",
        title="Greedy",
        description="…",
        artifacts=_MAX_DEPTH.artifacts,
        rulings=Rulings(confirm=99),
    )
    with pytest.raises(SystemExit, match="leaves the review queue empty"):
        plan_rulings(_build(greedy))


# --- seeded, replayed, and shaped the way the browser suite expects -------------


def test_the_seeded_workspace_holds_what_the_browser_suite_looks_for(
    session_factory: sessionmaker[Session],
) -> None:
    summary = seed(session_factory)
    assert (summary.products, summary.features) == (2, 3)

    with session_factory() as session:
        projection = load_projection(session, workspace_id=FIXTURE_WORKSPACE_ID)

    # Two products, so the switcher switches and "All products" is not a view of
    # one thing; the first is the one every test lands on.
    products = list(projection.products.values())
    assert len(products) == 2
    assert products[0].name == PLAN[0].name
    assert products[0].description

    # Three features, each named and described -- orientation renders at both
    # layers, and a feature with no run event has no identity to render.
    assert len(projection.feature_scopes) == 3
    assert all(scope.title and scope.description for scope in projection.feature_scopes.values())

    # A claim to stage, and one to advance onto when the suite confirms it.
    unruled = [node for node in projection.nodes.values() if node.status is NodeStatus.UNCONFIRMED]
    assert len(unruled) >= 2

    document = assemble(projection, products[0].id)
    # About and the spec export both read this: confirmed claims in the body…
    claims = [claim for section in document.features for claim in section.claims]
    assert claims
    assert all(claim.sources for claim in claims)
    # …and a disagreement nobody has settled, rendered as an object with both
    # sides rather than resolved in favour of whichever side was confirmed.
    assert [pair for section in document.features for pair in section.disagreements]
    # An unruled claim is in none of it. This is the assertion the browser test
    # "About never shows a claim nobody has ruled on" makes through the DOM.
    drafts = {node.content for node in unruled}
    assert drafts.isdisjoint({claim.content for claim in claims})


def test_seeding_twice_over_the_same_database_would_duplicate(
    session_factory: sessionmaker[Session],
) -> None:
    """`seed` appends; it does not reconcile.

    Stated as a test rather than a comment because it is the reason the script
    clears the workspace first, and the reason that clearing needs the owner's
    credential rather than the application role's.
    """
    first = seed(session_factory)
    second = seed(session_factory)
    with session_factory() as session:
        projection = load_projection(session, workspace_id=FIXTURE_WORKSPACE_ID)
    assert len(projection.products) == first.products + second.products


# --- the destructive half -------------------------------------------------------


def test_membership_is_seated_once_and_survives_a_rebuild(
    session_factory: sessionmaker[Session],
) -> None:
    """The workspace outlives any rebuild of its contents.

    `provision` runs before every suite, so seating a duplicate member -- or
    raising on the second run -- would break the thing it exists to make
    routine.
    """
    provision(session_factory)
    provision(session_factory)
    with session_factory() as session:
        members = session.execute(
            select(WorkspaceMember).where(WorkspaceMember.workspace_id == FIXTURE_WORKSPACE_ID)
        ).scalars()
        seated = {member.actor: member.role for member in members}
    assert seated == {ADMIN: Role.ADMIN, EDITOR: Role.EDITOR, VIEWER: Role.VIEWER}


def test_clearing_refuses_to_delete_what_a_human_wrote(
    session_factory: sessionmaker[Session],
) -> None:
    """The one guard on the only destructive path in the repo.

    Everything this fixture holds is written by the seed or by a suite declaring
    itself automated, so a `human` event here means a person signed in and ruled
    on something. A log only moves forward: a deleted confirmation is not
    recoverable from it, and "it was only the test workspace" is not something
    you can check after the fact.
    """
    provision(session_factory)
    seed(session_factory)
    with session_scope(session_factory) as session:
        append_event(
            session,
            event_type=EventType.NODE_CONFIRMED,
            payload={"node_id": str(uuid.uuid4())},
            actor="Priya (PM)",
            actor_kind=ActorKind.HUMAN,
            workspace_id=FIXTURE_WORKSPACE_ID,
        )

    with pytest.raises(SystemExit, match="Priya"):
        clear(session_factory, force=False)

    # And gives way when the operator says the rulings are disposable.
    assert clear(session_factory, force=True) > 0
    with session_factory() as session:
        assert load_projection(session, workspace_id=FIXTURE_WORKSPACE_ID).nodes == {}


def test_clearing_touches_no_other_workspace(session_factory: sessionmaker[Session]) -> None:
    """A constant workspace id, not an argument: nothing else is reachable."""
    other = uuid.uuid4()
    with session_scope(session_factory) as session:
        append_event(
            session,
            event_type=EventType.NODE_CONFIRMED,
            payload={"node_id": str(uuid.uuid4())},
            actor="someone else",
            actor_kind=ActorKind.HUMAN,
            workspace_id=other,
        )
    provision(session_factory)
    seed(session_factory)
    clear(session_factory, force=False)

    with session_factory() as session:
        surviving = session.execute(
            select(EventLog).where(EventLog.workspace_id == other)
        ).scalars()
        assert len(list(surviving)) == 1


# --- the suite and the seed agree on who they are -------------------------------


def test_the_playwright_fixture_module_names_the_same_actors() -> None:
    """Membership is what resolves a session to a workspace.

    If the suite signs in as a name this script never seated, every test fails
    with a 403 that says nothing about why -- so the two files are pinned to each
    other here rather than by comment.
    """
    source = (Path(__file__).resolve().parents[1] / "frontend" / "tests" / "fixture.ts").read_text()
    assert json.dumps(EDITOR) in source
    assert json.dumps(VIEWER) in source
    assert json.dumps(ADMIN) in source
    assert str(FIXTURE_WORKSPACE_ID) in source
