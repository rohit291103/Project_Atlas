"""Build the browser suite its own workspace, from recorded extraction output.

Slice 6 of `docs/decisions/2026-08-19-product-orientation-rerun-safety-and-demo-data.md`.

`X-Atlas-Automated` (2026-08-18) fixed *attribution*: the Playwright suite's
writes stopped masquerading as a person's rulings. It did nothing about
*mutation*. Two of the suite's tests confirm a claim, and a confirmation is a
real, irreversible event in an append-only log -- so a 37-test suite was running
against the same workspace the demo is given from, and the only defence was a
line in the tracker saying "exclude the two mutating tests".

This script removes the shared surface instead of asking people to remember. It
provisions **one workspace that exists only for the suite**, seats its own
editor and viewer in it, and rebuilds its contents from scratch on every run.
Nothing outside `FIXTURE_WORKSPACE_ID` is read or written.

**Where the data comes from, and why it is not invented.** Every claim here is
*recorded output of a real extraction run* -- `tests/evals/golden_set/`, the same
files the eval harness grades against. A fixture of hand-written claims would
have hand-written provenance, which is a fabricated `SourceRef` sitting in the
database of a product whose entire argument is that provenance is real
(Engineering Philosophy Sec4). So the excerpts, URLs and confidence scores below
are what the agent actually returned on 2026-07-27; only the identifiers are
re-stamped, deterministically, so the fixture cannot collide with a real
workspace's rows. Every node and edge is re-validated through `Node`/`Edge`
before it is written, and written through `pipeline.record_extraction` -- the
same gate ingestion passes, because "nothing unvalidated reaches storage" has no
exemption for a seed script.

**Why deleting is allowed here, in an append-only log.** It is not history being
rewritten: it is a fixture being rebuilt. The log is the source of truth about
*what people decided*, and nobody decided anything in this workspace -- every
event it holds was written by this file or by a test harness declaring itself
automated. The script refuses to delete anything written by a human actor
(`--force` to override), so the one way this could destroy real work is closed.
The delete needs `SUPABASE_DB_ADMIN_URL`: `atlas_app` holds `SELECT, INSERT` on
`event_log` and nothing else (`c3d8e1f60b21`), so the application role
*structurally cannot* do this, which is exactly the property to keep.

Usage:

    set -a && source .env && set +a
    uv run python scripts/seed_test_workspace.py --dry-run   # print, write nothing
    uv run python scripts/seed_test_workspace.py

`frontend/tests/global-setup.ts` runs it before every suite, so a run always
starts from the same fixture no matter what the previous run confirmed.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, sessionmaker

from atlas.extraction.agent import ExtractionResult
from atlas.models.schema import (
    ActorKind,
    Edge,
    IngestionRunPayload,
    Node,
    NodeStatus,
    RelationType,
    Role,
    SourceType,
)
from atlas.pipeline import record_extraction
from atlas.storage.confirmations import confirm_node, edit_node, reject_node
from atlas.storage.connections import Connection
from atlas.storage.db import get_engine, get_sessionmaker, session_scope
from atlas.storage.products import (
    assign_feature_scope,
    create_product,
    describe_feature_scope,
    describe_product,
)
from atlas.storage.projections import load_projection
from atlas.storage.rbac import workspace_session
from atlas.storage.tables import EventLog, Workspace, WorkspaceMember

# --- identity -------------------------------------------------------------------

#: Namespace for every id this fixture mints. UUID5 rather than UUID4 so a
#: rebuild reproduces the same workspace, feature, claim and edge ids -- a test
#: that fails can be re-run against a fixture that is identical rather than
#: merely similar -- and so nothing here can ever collide with a real row, which
#: is minted from `uuid4`. Product ids are the one exception: they come from
#: `create_product`, which mints its own, deliberately.
_NS = uuid.uuid5(uuid.NAMESPACE_URL, "https://project-atlas.local/fixture/browser-suite")

#: The one workspace this script may touch. A constant, not an argument: an id
#: passed in is an id that can be pointed at production by a typo.
FIXTURE_WORKSPACE_ID = uuid.uuid5(_NS, "workspace")
FIXTURE_WORKSPACE_NAME = "Browser suite fixture"

#: The suite's own actors. They are members of nothing else, so a test signing
#: in as one cannot reach the demo workspace even if it tries -- membership is
#: what resolves a session to a workspace (`api/deps.py::get_principal`).
#:
#: Mirrored in `frontend/tests/fixture.ts`; `tests/test_seed_test_workspace.py`
#: fails if the two ever disagree.
EDITOR = "Suite Editor (automated)"
VIEWER = "Suite Viewer (automated)"

#: Who the seed writes as. Not `EDITOR`: the fixture's rulings were made by this
#: script, and an audit trail that says otherwise is the exact defect
#: `actor_kind` was added to close.
SEED_ACTOR = "fixture-seed"

_GOLDEN_SET = Path(__file__).resolve().parents[1] / "tests" / "evals" / "golden_set"


def fixture_id(*parts: str) -> uuid.UUID:
    """A deterministic id for one piece of the fixture."""
    return uuid.uuid5(_NS, "/".join(parts))


# --- the plan -------------------------------------------------------------------


@dataclass(frozen=True)
class Artifact:
    """One recorded extraction run: a golden-set case, and what it was pulled from.

    The `source_type`/`external_id`/`url` triple is stated here rather than
    derived from the recording, because it is the *run's* provenance and a run
    can cite an artifact its nodes never quote. `build_feature` checks the URL
    against the recorded `SourceRef`s anyway, so a plan that drifts from the
    file it names fails loudly instead of seeding a mislabelled feature.
    """

    case: str
    source_type: SourceType
    external_id: str
    url: str


@dataclass(frozen=True)
class Rulings:
    """How much of a feature has already been reviewed.

    A fixture with nothing ruled cannot exercise About or the spec export; one
    with everything ruled cannot exercise the review queue. Both states have to
    exist, and *which* claims are in which state has to be the same on every
    rebuild, so the counts are declared rather than discovered.
    """

    confirm: int = 0
    edit: int = 0
    reject: int = 0
    #: Confirm one side of each disagreement, leaving it live: neither side
    #: rejected, one side ruled, which is what `assembly._live_conflicts` reads.
    take_a_side: bool = False


@dataclass(frozen=True)
class FeaturePlan:
    slug: str
    title: str
    description: str
    artifacts: tuple[Artifact, ...]
    rulings: Rulings = Rulings()


@dataclass(frozen=True)
class ProductPlan:
    slug: str
    name: str
    description: str
    features: tuple[FeaturePlan, ...]


#: What the fixture contains, in the order it is written -- which is the order
#: the rail and the product switcher show, so the *first* of everything is the
#: one the suite lands on by default. That is why the cross-source, conflict-
#: bearing feature is first: half a dozen tests open `.rail__item` first and
#: would otherwise skip themselves.
PLAN: tuple[ProductPlan, ...] = (
    ProductPlan(
        slug="ripgrep",
        name="ripgrep",
        description=(
            "Fixture data for Atlas's browser test suite. Every claim below is recorded "
            "output of a real extraction run over public ripgrep artifacts and a seeded "
            "Jira project (tests/evals/golden_set/), replayed into a workspace that exists "
            "only for the tests. It is rebuilt from scratch on every run, so nothing "
            "confirmed here is a ruling anyone made."
        ),
        features=(
            FeaturePlan(
                slug="max-depth",
                title="Max depth option",
                description=(
                    "Limiting how far ripgrep descends into a directory tree. Assembled "
                    "from a GitHub pull request and a Jira ticket that disagree about it "
                    "— the cross-source case, and the reason this feature is first."
                ),
                artifacts=(
                    Artifact(
                        case="pr-111",
                        source_type=SourceType.GITHUB_PR,
                        external_id="BurntSushi/ripgrep#111",
                        url="https://github.com/BurntSushi/ripgrep/pull/111",
                    ),
                    Artifact(
                        case="cross-SCRUM-8",
                        source_type=SourceType.JIRA_TICKET,
                        external_id="SCRUM-8",
                        url="https://rohitg291103.atlassian.net/browse/SCRUM-8",
                    ),
                ),
                rulings=Rulings(confirm=4, edit=1, reject=1, take_a_side=True),
            ),
            FeaturePlan(
                slug="line-numbers",
                title="Fixed width line number display",
                description=(
                    "Padding line numbers to a fixed column so output stays aligned. One "
                    "source, no disagreements — the feature that must sort *below* a "
                    "contested one on the product home."
                ),
                artifacts=(
                    Artifact(
                        case="pr-723",
                        source_type=SourceType.GITHUB_PR,
                        external_id="BurntSushi/ripgrep#723",
                        url="https://github.com/BurntSushi/ripgrep/pull/723",
                    ),
                ),
                rulings=Rulings(confirm=3),
            ),
        ),
    ),
    ProductPlan(
        slug="atlas-import",
        name="Atlas import",
        description=(
            "A second product, so the switcher has something to switch between and "
            "'All products' is not a view of one thing. Nothing here has been ruled on: "
            "the state every product starts in, and the one that renders About's empty "
            "state honestly rather than as a blank page."
        ),
        features=(
            FeaturePlan(
                slug="csv-import",
                title="Import existing work from a CSV",
                description="Bringing a backlog in from another tool.",
                artifacts=(
                    Artifact(
                        case="jira-SCRUM-1",
                        source_type=SourceType.JIRA_TICKET,
                        external_id="SCRUM-1",
                        url="https://rohitg291103.atlassian.net/browse/SCRUM-1",
                    ),
                ),
            ),
        ),
    ),
)


# --- building -------------------------------------------------------------------


@dataclass
class BuiltRun:
    """One artifact's recorded output: the run event, and what that run produced.

    Kept per-artifact rather than flattened, so the log reads the way a real
    ingestion wrote it -- a run, then its claims, then its edges -- instead of
    one run appearing to have produced two sources' worth of work.
    """

    payload: IngestionRunPayload
    result: ExtractionResult


@dataclass
class BuiltFeature:
    """One feature scope, ready to write: its runs, its claims, its edges."""

    scope_id: uuid.UUID
    plan: FeaturePlan
    runs: list[BuiltRun] = field(default_factory=list)

    @property
    def nodes(self) -> list[Node]:
        return [node for run in self.runs for node in run.result.nodes]

    @property
    def edges(self) -> list[Edge]:
        return [edge for run in self.runs for edge in run.result.edges]


def load_case(case: str) -> dict[str, Any]:
    """The recorded extraction output for one golden-set case."""
    path = _GOLDEN_SET / case / "extraction.json"
    if not path.exists():
        raise SystemExit(f"no recorded extraction for {case!r} at {path}")
    loaded: dict[str, Any] = json.loads(path.read_text())
    return loaded


def build_feature(
    plan: FeaturePlan, *, workspace_id: uuid.UUID, product_id: uuid.UUID
) -> BuiltFeature:
    """Re-stamp one feature's recorded output onto this workspace.

    Content, excerpts, URLs, confidence scores and relation types are carried
    over untouched -- they are the recording, and rewriting any of them would
    make the fixture a fabrication. Identifiers are the only thing replaced, and
    they are replaced deterministically (`fixture_id`), so the same case seeded
    into two features gets two sets of ids and neither can collide with a real
    `uuid4` row. The **product** id is the exception: `create_product` mints it,
    because a caller choosing its own product id is the hole that function
    exists to close, and a fixture is not a reason to reach around it.

    Status is forced back to `unconfirmed` regardless of what the recording says:
    a `node_created` event that arrives already-confirmed would be a ruling
    nobody made, and every ruling in this fixture is written as its own event
    below.
    """
    scope_id = fixture_id("feature", plan.slug)
    built = BuiltFeature(scope_id=scope_id, plan=plan)
    ids: dict[str, uuid.UUID] = {}

    for artifact in plan.artifacts:
        recorded = load_case(artifact.case)
        result = ExtractionResult()
        urls: set[str] = set()

        for raw in recorded["nodes"]:
            node = dict(raw)
            recorded_id = str(node["id"])
            if recorded_id in ids:
                # Two cases in one feature emitting the same node. The replay
                # would supersede rather than complain, so the fixture would hold
                # one claim where the plan meant two, silently.
                raise SystemExit(
                    f"{artifact.case}: node {recorded_id} was already seeded into "
                    f"{plan.slug} by an earlier case"
                )
            ids[recorded_id] = fixture_id("node", plan.slug, recorded_id)
            node["id"] = ids[recorded_id]
            node["status"] = NodeStatus.UNCONFIRMED.value
            node["workspace_id"] = str(workspace_id)
            node["feature_scope_id"] = str(scope_id)
            node["source_refs"] = [
                {
                    **ref,
                    "id": str(fixture_id("ref", plan.slug, str(ref["id"]))),
                    "workspace_id": str(workspace_id),
                }
                for ref in node["source_refs"]
            ]
            urls.update(str(ref["url"]) for ref in node["source_refs"])
            # The schema gate, applied to a seed exactly as it is to extraction.
            result.nodes.append(Node.model_validate(node))

        if artifact.url not in urls:
            # The plan names an artifact the recording never cites. Either the
            # case was re-recorded against something else or the plan was typed
            # from memory; both produce a feature whose run event lies about
            # where its claims came from.
            raise SystemExit(
                f"{artifact.case}: plan cites {artifact.url}, "
                f"which no recorded source_ref mentions ({sorted(urls)})"
            )

        for raw_edge in recorded.get("edges", []):
            edge = dict(raw_edge)
            endpoints = (str(edge["from_node_id"]), str(edge["to_node_id"]))
            if any(end not in ids for end in endpoints):
                # `cross-SCRUM-8`'s edges reach back into `pr-111`'s nodes, which
                # is the whole point of it -- but only because both cases are
                # seeded into this same feature, in that order. An endpoint that
                # is still unknown means the plan dropped the case it belongs to,
                # and an edge to a node that does not exist is a broken graph.
                raise SystemExit(
                    f"{artifact.case}: edge {edge['id']} points at a node this "
                    f"feature never seeded ({endpoints})"
                )
            edge["id"] = str(fixture_id("edge", plan.slug, str(edge["id"])))
            edge["from_node_id"] = str(ids[endpoints[0]])
            edge["to_node_id"] = str(ids[endpoints[1]])
            result.edges.append(Edge.model_validate(edge))

        built.runs.append(
            BuiltRun(
                payload=IngestionRunPayload(
                    feature_scope_id=scope_id,
                    title=plan.title,
                    source_type=artifact.source_type,
                    external_id=artifact.external_id,
                    url=artifact.url,
                    product_id=product_id,
                ),
                result=result,
            )
        )

    return built


@dataclass(frozen=True)
class RulingPlan:
    """Which claims of a feature get ruled on, and how."""

    confirm: tuple[uuid.UUID, ...] = ()
    edit: tuple[uuid.UUID, ...] = ()
    reject: tuple[uuid.UUID, ...] = ()


def plan_rulings(built: BuiltFeature) -> RulingPlan:
    """Choose the fixture's rulings, deterministically.

    Three properties the browser suite depends on, in order of how easy they are
    to break by accident:

    1. **A disagreement stays live.** One side of each `conflicts_with` is
       confirmed and neither side is ever rejected, because a rejection settles
       the conflict and About would then have nothing to show
       (`assembly._live_conflicts`).
    2. **Something is always still unruled**, in the first feature especially:
       the review screen stages the first claim needing a ruling, and two tests
       confirm it.
    3. **Nothing contested is confirmed twice.** A claim disagreeing with two
       others is one claim, and confirming it once is what the reviewer would do.
    """
    contested: list[uuid.UUID] = []
    for edge in built.edges:
        if edge.relation_type is not RelationType.CONFLICTS_WITH:
            continue
        if built.plan.rulings.take_a_side and edge.from_node_id not in contested:
            contested.append(edge.from_node_id)

    settled = set(contested)
    for edge in built.edges:
        if edge.relation_type is RelationType.CONFLICTS_WITH:
            settled.update({edge.from_node_id, edge.to_node_id})

    # Rule only on claims no disagreement touches, so the recipe below can never
    # reject one side of a conflict the fixture needs left open.
    free = [node.id for node in built.nodes if node.id not in settled]
    recipe = built.plan.rulings
    wanted = recipe.confirm + recipe.edit + recipe.reject
    if wanted > max(len(free) - 2, 0):
        # Two spare claims: one to stage, one to advance to when the suite
        # confirms it.
        raise SystemExit(
            f"{built.plan.slug}: {wanted} rulings over {len(free)} free claims leaves "
            "the review queue empty"
        )

    take = iter(free)
    confirm = [next(take) for _ in range(recipe.confirm)]
    edit = [next(take) for _ in range(recipe.edit)]
    reject = [next(take) for _ in range(recipe.reject)]
    return RulingPlan(confirm=tuple(contested + confirm), edit=tuple(edit), reject=tuple(reject))


# --- writing --------------------------------------------------------------------


@dataclass
class Summary:
    """What a run of this script did, for the line it prints at the end."""

    removed: int = 0
    products: int = 0
    features: int = 0
    claims: int = 0
    conflicts: int = 0
    ruled: int = 0


def provision(admin_sessions: sessionmaker[Session]) -> None:
    """Create the workspace row and seat its two members.

    Runs as the owner because `atlas_app` holds `SELECT` on `workspace` and
    `workspace_member` and nothing more (`c3d8e1f60b21`): membership is
    provisioned out of band, deliberately, so a compromised application process
    cannot grant itself a tenant. Idempotent -- the workspace outlives any single
    rebuild of its contents.
    """
    with session_scope(admin_sessions) as session:
        if session.get(Workspace, FIXTURE_WORKSPACE_ID) is None:
            session.add(Workspace(id=FIXTURE_WORKSPACE_ID, name=FIXTURE_WORKSPACE_NAME))
            session.flush()
        seated = {
            row.actor
            for row in session.execute(
                select(WorkspaceMember).where(WorkspaceMember.workspace_id == FIXTURE_WORKSPACE_ID)
            ).scalars()
        }
        for actor, role in ((EDITOR, Role.EDITOR), (VIEWER, Role.VIEWER)):
            if actor not in seated:
                session.add(
                    WorkspaceMember(workspace_id=FIXTURE_WORKSPACE_ID, actor=actor, role=role)
                )


def clear(admin_sessions: sessionmaker[Session], *, force: bool) -> int:
    """Empty the fixture workspace, and refuse to empty anyone's real work.

    The `actor_kind` check is the guard: every event this fixture holds was
    written by this script or by a browser suite that declares itself automated
    (`X-Atlas-Automated`), so a *human* event here means a person signed in and
    reviewed something in the fixture. That is worth stopping for -- a log only
    moves forward, and a deleted confirmation cannot be recovered from it.
    """
    with session_scope(admin_sessions) as session:
        human = session.execute(
            select(EventLog.actor)
            .where(EventLog.workspace_id == FIXTURE_WORKSPACE_ID)
            .where(EventLog.actor_kind == ActorKind.HUMAN)
            .limit(5)
        ).scalars()
        actors = sorted(set(human))
        if actors and not force:
            raise SystemExit(
                f"{FIXTURE_WORKSPACE_NAME} holds events written by a human actor "
                f"({', '.join(actors)}). Rebuilding would delete real rulings. "
                "Re-run with --force if they are genuinely disposable."
            )
        removed = session.execute(
            select(func.count())
            .select_from(EventLog)
            .where(EventLog.workspace_id == FIXTURE_WORKSPACE_ID)
        ).scalar_one()
        session.execute(delete(EventLog).where(EventLog.workspace_id == FIXTURE_WORKSPACE_ID))
        session.execute(delete(Connection).where(Connection.workspace_id == FIXTURE_WORKSPACE_ID))
        return int(removed)


def seed(sessions: sessionmaker[Session]) -> Summary:
    """Write the fixture, as the application role, through the sanctioned paths.

    Every write here goes through `record_extraction`, `storage/products.py` or
    `storage/confirmations.py` -- the same functions ingestion and the API use.
    Nothing reaches a table directly, so a fixture cannot hold a shape the
    product could not have produced.
    """
    summary = Summary()

    for product in PLAN:
        with workspace_session(sessions, FIXTURE_WORKSPACE_ID) as session:
            product_id, _ = create_product(
                session,
                workspace_id=FIXTURE_WORKSPACE_ID,
                name=product.name,
                actor=SEED_ACTOR,
                actor_kind=ActorKind.AUTOMATED,
            )
            describe_product(
                session,
                workspace_id=FIXTURE_WORKSPACE_ID,
                product_id=product_id,
                description=product.description,
                actor=SEED_ACTOR,
                actor_kind=ActorKind.AUTOMATED,
            )
        summary.products += 1

        for plan in product.features:
            built = build_feature(plan, workspace_id=FIXTURE_WORKSPACE_ID, product_id=product_id)
            rulings = plan_rulings(built)

            with workspace_session(sessions, FIXTURE_WORKSPACE_ID) as session:
                # One `ingestion_run` per artifact, each followed by what that
                # run produced -- the order `record_extraction` writes and
                # `replay` expects, and the order a real ingestion leaves behind.
                for run in built.runs:
                    record_extraction(
                        session,
                        run.result,
                        workspace_id=FIXTURE_WORKSPACE_ID,
                        ingestion_run=run.payload,
                    )
                assign_feature_scope(
                    session,
                    workspace_id=FIXTURE_WORKSPACE_ID,
                    feature_scope_id=built.scope_id,
                    product_id=product_id,
                    actor=SEED_ACTOR,
                    actor_kind=ActorKind.AUTOMATED,
                )
                describe_feature_scope(
                    session,
                    workspace_id=FIXTURE_WORKSPACE_ID,
                    feature_scope_id=built.scope_id,
                    description=plan.description,
                    actor=SEED_ACTOR,
                    actor_kind=ActorKind.AUTOMATED,
                )

            summary.features += 1
            summary.claims += len(built.nodes)
            summary.conflicts += sum(
                1 for edge in built.edges if edge.relation_type is RelationType.CONFLICTS_WITH
            )
            summary.ruled += _rule(sessions, built, rulings)

    return summary


def _rule(sessions: sessionmaker[Session], built: BuiltFeature, rulings: RulingPlan) -> int:
    """Apply the planned rulings, each as its own event.

    Loads the projection first, because `confirm_node` and friends take the
    `Node` rather than an id -- so a ruling cannot name a claim that does not
    exist, and `workspace_id` comes off the node instead of being passed
    alongside it where the two could disagree.
    """
    if not (rulings.confirm or rulings.edit or rulings.reject):
        return 0

    with workspace_session(sessions, FIXTURE_WORKSPACE_ID) as session:
        projection = load_projection(session, workspace_id=FIXTURE_WORKSPACE_ID)
        ruled = 0
        for node_id in rulings.confirm:
            confirm_node(
                session,
                node=projection.nodes[node_id],
                actor=SEED_ACTOR,
                actor_kind=ActorKind.AUTOMATED,
            )
            ruled += 1
        for node_id in rulings.edit:
            node = projection.nodes[node_id]
            edit_node(
                session,
                node=node,
                content=f"{node.content.rstrip('.')} (edited by the fixture seed).",
                actor=SEED_ACTOR,
                actor_kind=ActorKind.AUTOMATED,
            )
            ruled += 1
        for node_id in rulings.reject:
            reject_node(
                session,
                node=projection.nodes[node_id],
                actor=SEED_ACTOR,
                actor_kind=ActorKind.AUTOMATED,
            )
            ruled += 1
        return ruled


# --- entry point ----------------------------------------------------------------


def _dry_run() -> Summary:
    """Build everything and write nothing, so the plan can be checked offline."""
    summary = Summary()
    for product in PLAN:
        summary.products += 1
        product_id = fixture_id("product", product.slug)
        for plan in product.features:
            built = build_feature(plan, workspace_id=FIXTURE_WORKSPACE_ID, product_id=product_id)
            rulings = plan_rulings(built)
            summary.features += 1
            summary.claims += len(built.nodes)
            summary.conflicts += sum(
                1 for edge in built.edges if edge.relation_type is RelationType.CONFLICTS_WITH
            )
            summary.ruled += len(rulings.confirm) + len(rulings.edit) + len(rulings.reject)
            print(
                f"  {product.name} / {plan.title}: {len(built.nodes)} claims, "
                f"{len(built.edges)} edges, {len(rulings.confirm)} confirmed, "
                f"{len(rulings.edit)} edited, {len(rulings.reject)} rejected"
            )
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--dry-run", action="store_true", help="build the fixture and print it, writing nothing"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="rebuild even though the fixture holds events written by a human actor",
    )
    args = parser.parse_args(argv)

    print(f"{FIXTURE_WORKSPACE_NAME} ({FIXTURE_WORKSPACE_ID})")
    if args.dry_run:
        summary = _dry_run()
        print(
            f"would write {summary.products} products, {summary.features} features, "
            f"{summary.claims} claims, {summary.conflicts} conflicts, {summary.ruled} rulings"
        )
        return 0

    admin_url = os.environ.get("SUPABASE_DB_ADMIN_URL")
    app_url = os.environ.get("SUPABASE_DB_URL")
    if not admin_url or not app_url:
        raise SystemExit(
            "SUPABASE_DB_ADMIN_URL and SUPABASE_DB_URL must both be set "
            "(`set -a && source .env && set +a`). The owner seats membership and "
            "clears the fixture; the application role writes its contents."
        )

    admin_sessions = get_sessionmaker(get_engine(admin_url))
    app_sessions = get_sessionmaker(get_engine(app_url))

    provision(admin_sessions)
    removed = clear(admin_sessions, force=args.force)
    summary = seed(app_sessions)
    summary.removed = removed

    print(
        f"cleared {summary.removed} events; wrote {summary.products} products, "
        f"{summary.features} features, {summary.claims} claims, "
        f"{summary.conflicts} conflicts, {summary.ruled} rulings"
    )
    print(f"members: {EDITOR} (editor), {VIEWER} (viewer)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
