"""Tests for `assembly.py`: confirmed Nodes/Edges -> a readable document.

This is the module both the `/about` info page and spec export v0 read through,
and the reason it is one module rather than two code paths is the filter: an
unconfirmed claim must not reach either output (CLAUDE.md Engineering Philosophy
Sec2, "extraction is a draft, never a fact"). Duplicating that rule in React and
in Python would let the two drift, and the drift is an export full of drafts.

Everything here is a pure function over an in-memory `Projection` -- no DB, no
network, no secrets.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from atlas.assembly import (
    DOCUMENT_ORDER,
    FeatureSection,
    GapKind,
    ProductDocument,
    assemble,
    changes,
    changes_to_markdown,
    compare,
    readiness,
    to_markdown,
)
from atlas.models.schema import (
    Edge,
    IngestionRunPayload,
    Node,
    NodeStatus,
    NodeType,
    RelationType,
    SourceRef,
    SourceType,
)
from atlas.storage.projections import FeatureScope, Product, Projection

WORKSPACE_ID = uuid.UUID(int=0)
PRODUCT_ID = uuid.uuid4()
SCOPE_ID = uuid.uuid4()
OTHER_SCOPE_ID = uuid.uuid4()

_CLOCK = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)


# --- builders ------------------------------------------------------------------


def make_node(
    *,
    node_type: NodeType = NodeType.GOAL,
    content: str = "Ship the thing",
    status: NodeStatus = NodeStatus.CONFIRMED,
    scope_id: uuid.UUID = SCOPE_ID,
    excerpt: str = "We want to ship the thing.",
    url: str = "https://github.com/acme/repo/pull/42",
    created_at: datetime = _CLOCK,
    sources: list[tuple[SourceType, str]] | None = None,
) -> Node:
    sources = sources if sources is not None else [(SourceType.GITHUB_PR, "42")]
    return Node(
        type=node_type,
        content=content,
        confidence_score=0.9,
        status=status,
        created_at=created_at,
        source_refs=[
            SourceRef(
                source_type=source_type,
                external_id=external_id,
                url=url,
                excerpt=excerpt,
                workspace_id=WORKSPACE_ID,
            )
            for source_type, external_id in sources
        ],
        workspace_id=WORKSPACE_ID,
        feature_scope_id=scope_id,
    )


def make_scope(
    scope_id: uuid.UUID = SCOPE_ID,
    *,
    title: str = "Main graph metric",
    description: str | None = None,
) -> FeatureScope:
    return FeatureScope(
        id=scope_id,
        title=title,
        runs=(
            IngestionRunPayload(
                feature_scope_id=scope_id,
                title=title,
                source_type=SourceType.GITHUB_PR,
                external_id="acme/repo#42",
                url="https://github.com/acme/repo/pull/42",
                product_id=PRODUCT_ID,
            ),
        ),
        product_id=PRODUCT_ID,
        description=description,
    )


def make_projection(
    nodes: list[Node],
    *,
    edges: list[Edge] | None = None,
    scopes: list[FeatureScope] | None = None,
    product_description: str | None = None,
) -> Projection:
    scopes = scopes if scopes is not None else [make_scope()]
    return Projection(
        nodes={node.id: node for node in nodes},
        edges={edge.id: edge for edge in (edges or [])},
        feature_scopes={scope.id: scope for scope in scopes},
        products={
            PRODUCT_ID: Product(
                id=PRODUCT_ID, name="Plausible Analytics", description=product_description
            )
        },
    )


def conflict(left: Node, right: Node) -> Edge:
    return Edge(
        from_node_id=left.id,
        to_node_id=right.id,
        relation_type=RelationType.CONFLICTS_WITH,
        confidence_score=0.9,
    )


def only_section(doc: ProductDocument) -> FeatureSection:
    assert len(doc.features) == 1
    return doc.features[0]


# --- rule 1: confirmed only ----------------------------------------------------


def test_unconfirmed_claims_are_withheld() -> None:
    """A draft must not reach a document. This is the rule the module exists for."""
    draft = make_node(content="Still a guess", status=NodeStatus.UNCONFIRMED)
    ruled = make_node(content="Actually decided", status=NodeStatus.CONFIRMED)

    section = only_section(assemble(make_projection([draft, ruled]), PRODUCT_ID))

    contents = [claim.content for claim in section.claims]
    assert contents == ["Actually decided"]


def test_rejected_claims_are_withheld() -> None:
    rejected = make_node(content="Ruled out", status=NodeStatus.REJECTED)
    kept = make_node(content="Kept", status=NodeStatus.CONFIRMED)

    section = only_section(assemble(make_projection([rejected, kept]), PRODUCT_ID))

    assert [claim.content for claim in section.claims] == ["Kept"]


def test_edited_claims_appear_because_a_human_ruled_on_them() -> None:
    """EDITED is a ruling, not a pending state -- a person rewrote it and kept it."""
    edited = make_node(content="Rewritten by a person", status=NodeStatus.EDITED)

    section = only_section(assemble(make_projection([edited]), PRODUCT_ID))

    assert [claim.content for claim in section.claims] == ["Rewritten by a person"]
    assert section.claims[0].status is NodeStatus.EDITED


def test_unreviewed_count_reports_what_was_withheld() -> None:
    """A document that silently omits half the claims is worse than a short one."""
    nodes = [
        make_node(content=f"draft {index}", status=NodeStatus.UNCONFIRMED) for index in range(3)
    ]
    nodes.append(make_node(content="ruled", status=NodeStatus.CONFIRMED))

    section = only_section(assemble(make_projection(nodes), PRODUCT_ID))

    assert section.unreviewed == 3


# --- rule 2: provenance --------------------------------------------------------


def test_every_claim_carries_its_excerpt_and_url() -> None:
    node = make_node(excerpt="The graph should plot visitors.", url="https://example.test/pr/9")

    section = only_section(assemble(make_projection([node]), PRODUCT_ID))

    (source,) = section.claims[0].sources
    assert source.excerpt == "The graph should plot visitors."
    assert source.url == "https://example.test/pr/9"


# --- rule 3 + 4: disagreements -------------------------------------------------


def test_a_live_conflict_renders_both_sides_including_the_unconfirmed_one() -> None:
    """Dropping the unruled side would silently resolve the disagreement in favour
    of whichever side happened to be confirmed first -- exactly what roadmap v2
    forbids of a spec export."""
    confirmed = make_node(content="Conversion rate ships at launch")
    draft = make_node(content="Conversion rate is deferred", status=NodeStatus.UNCONFIRMED)

    section = only_section(
        assemble(
            make_projection([confirmed, draft], edges=[conflict(confirmed, draft)]), PRODUCT_ID
        )
    )

    (disagreement,) = section.disagreements
    assert disagreement.left.content == "Conversion rate ships at launch"
    assert disagreement.right.content == "Conversion rate is deferred"
    assert disagreement.right.status is NodeStatus.UNCONFIRMED


def test_a_contested_claim_is_absent_from_the_settled_body() -> None:
    """Structural enforcement of "not silently resolved": a claim under live
    dispute cannot be read as settled fact, because it is not in the settled list
    at all -- it appears only inside the disagreement."""
    confirmed = make_node(content="Conversion rate ships at launch")
    draft = make_node(content="Conversion rate is deferred", status=NodeStatus.UNCONFIRMED)
    unrelated = make_node(content="The graph stays on screen")

    section = only_section(
        assemble(
            make_projection([confirmed, draft, unrelated], edges=[conflict(confirmed, draft)]),
            PRODUCT_ID,
        )
    )

    assert [claim.content for claim in section.claims] == ["The graph stays on screen"]
    assert len(section.disagreements) == 1


def test_rejecting_one_side_resolves_the_disagreement() -> None:
    """A rejection is a ruling on the dispute, so the survivor becomes settled."""
    kept = make_node(content="Conversion rate ships at launch")
    thrown_out = make_node(content="Conversion rate is deferred", status=NodeStatus.REJECTED)

    section = only_section(
        assemble(
            make_projection([kept, thrown_out], edges=[conflict(kept, thrown_out)]), PRODUCT_ID
        )
    )

    assert section.disagreements == ()
    assert [claim.content for claim in section.claims] == ["Conversion rate ships at launch"]


def test_a_conflict_between_two_drafts_is_not_a_document_disagreement() -> None:
    """Nobody has ruled on either side, so it is not yet part of the document --
    it is still review work, and the Conflicts screen is where it belongs."""
    left = make_node(content="a", status=NodeStatus.UNCONFIRMED)
    right = make_node(content="b", status=NodeStatus.UNCONFIRMED)

    section = only_section(
        assemble(make_projection([left, right], edges=[conflict(left, right)]), PRODUCT_ID)
    )

    assert section.disagreements == ()
    assert section.claims == ()


def test_a_cross_feature_disagreement_is_not_dropped() -> None:
    """`counts_for` keeps an edge only when both endpoints are in the scope, which
    is right for a badge. A document must not lose the conflict entirely, so it
    files under the from-side's feature and names the other side's."""
    here = make_node(content="Interval is shared in the link")
    there = make_node(
        content="Interval is not shared", status=NodeStatus.UNCONFIRMED, scope_id=OTHER_SCOPE_ID
    )
    projection = make_projection(
        [here, there],
        edges=[conflict(here, there)],
        scopes=[make_scope(), make_scope(OTHER_SCOPE_ID, title="Shared links")],
    )

    doc = assemble(projection, PRODUCT_ID)

    (disagreement,) = doc.features[0].disagreements
    assert disagreement.right.feature_title == "Shared links"
    assert doc.features[1].disagreements == ()


# --- rule 5: document order ----------------------------------------------------


def test_claims_are_ordered_by_document_order_not_log_order() -> None:
    log_order = [NodeType.OPEN_QUESTION, NodeType.DECISION, NodeType.GOAL, NodeType.REQUIREMENT]
    nodes = [
        make_node(
            node_type=node_type,
            content=node_type.value,
            created_at=_CLOCK + timedelta(minutes=index),
        )
        for index, node_type in enumerate(log_order)
    ]

    section = only_section(assemble(make_projection(nodes), PRODUCT_ID))

    types = [claim.type for claim in section.claims]
    assert types == sorted(types, key=DOCUMENT_ORDER.index)
    assert types[0] is NodeType.GOAL
    assert types[-1] is NodeType.OPEN_QUESTION


def test_claims_of_one_type_keep_a_stable_order() -> None:
    """A Markdown export has to diff cleanly across runs."""
    first = make_node(content="first", created_at=_CLOCK)
    second = make_node(content="second", created_at=_CLOCK + timedelta(minutes=1))

    forwards = only_section(assemble(make_projection([first, second]), PRODUCT_ID))
    backwards = only_section(assemble(make_projection([second, first]), PRODUCT_ID))

    assert [claim.content for claim in forwards.claims] == ["first", "second"]
    assert [claim.content for claim in backwards.claims] == ["first", "second"]


def test_document_order_covers_every_node_type() -> None:
    """A new NodeType must be given a position deliberately, not sorted to the end
    by accident."""
    assert set(DOCUMENT_ORDER) == set(NodeType)


# --- rule 6 + the authored spine -----------------------------------------------


def test_a_feature_with_nothing_confirmed_still_appears() -> None:
    """Omitting it hides work from the person who has to do it."""
    draft = make_node(status=NodeStatus.UNCONFIRMED)

    section = only_section(assemble(make_projection([draft]), PRODUCT_ID))

    assert section.title == "Main graph metric"
    assert section.claims == ()
    assert section.unreviewed == 1


def test_authored_descriptions_are_carried_through() -> None:
    projection = make_projection(
        [make_node()],
        scopes=[make_scope(description="Which metric the main graph plots.")],
        product_description="Privacy-friendly website analytics.",
    )

    doc = assemble(projection, PRODUCT_ID)

    assert doc.name == "Plausible Analytics"
    assert doc.description == "Privacy-friendly website analytics."
    assert doc.features[0].description == "Which metric the main graph plots."


def test_another_products_features_are_not_included() -> None:
    stray = make_scope(uuid.uuid4(), title="Someone else's feature")
    projection = make_projection([make_node()], scopes=[make_scope(), stray])
    projection.feature_scopes[stray.id] = FeatureScope(
        id=stray.id, title=stray.title, runs=stray.runs, product_id=uuid.uuid4()
    )

    doc = assemble(projection, PRODUCT_ID)

    assert [section.title for section in doc.features] == ["Main graph metric"]


# --- the Markdown renderer -----------------------------------------------------


def test_markdown_carries_provenance_inline() -> None:
    node = make_node(excerpt="The graph should plot visitors.", url="https://example.test/pr/9")

    rendered = to_markdown(assemble(make_projection([node]), PRODUCT_ID))

    assert "https://example.test/pr/9" in rendered
    assert "The graph should plot visitors." in rendered


def test_markdown_never_contains_an_unruled_claim() -> None:
    draft = make_node(content="UNRULED DRAFT TEXT", status=NodeStatus.UNCONFIRMED)

    rendered = to_markdown(assemble(make_projection([draft]), PRODUCT_ID))

    assert "UNRULED DRAFT TEXT" not in rendered


def test_markdown_renders_a_disagreement_as_open() -> None:
    confirmed = make_node(content="Ships at launch")
    draft = make_node(content="Deferred", status=NodeStatus.UNCONFIRMED)

    rendered = to_markdown(
        assemble(
            make_projection([confirmed, draft], edges=[conflict(confirmed, draft)]), PRODUCT_ID
        )
    )

    assert "Ships at launch" in rendered
    assert "Deferred" in rendered
    assert "unresolved" in rendered.lower()


# --- evidence density (roadmap v2 2A, [+2026-09-02]) ---------------------------


def test_evidence_density_counts_distinct_artifacts_and_systems() -> None:
    """ "3 sources across 2 systems" -- two excerpts from one PR are one source."""
    node = make_node(
        sources=[
            (SourceType.GITHUB_PR, "acme/repo#42"),
            (SourceType.GITHUB_PR, "acme/repo#42"),
            (SourceType.GITHUB_ISSUE, "acme/repo#7"),
            (SourceType.JIRA_TICKET, "PA-12"),
        ]
    )

    (claim,) = only_section(assemble(make_projection([node]), PRODUCT_ID)).claims

    assert claim.source_count == 3
    assert claim.systems == ("github", "jira")


def test_markdown_states_evidence_density_only_when_corroborated() -> None:
    single = make_node(content="One source only")
    multi = make_node(
        content="Backed twice",
        sources=[(SourceType.GITHUB_PR, "acme/repo#42"), (SourceType.JIRA_TICKET, "PA-1")],
    )

    rendered = to_markdown(assemble(make_projection([single, multi]), PRODUCT_ID))

    assert "2 sources across 2 systems" in rendered
    assert "1 source" not in rendered


# --- readiness score + named gaps (roadmap v2 2A, [+2026-09-02]) ---------------


def _ready_feature() -> list[Node]:
    return [
        make_node(node_type=NodeType.REQUIREMENT, content="Plot visitors"),
        make_node(node_type=NodeType.CONSTRAINT, content="No cookies"),
    ]


def test_a_fully_ready_feature_scores_100_with_no_gaps() -> None:
    result = readiness(assemble(make_projection(_ready_feature()), PRODUCT_ID))

    assert result.score == 100
    assert result.gaps == ()


def test_unreviewed_claims_are_a_named_gap_pointing_at_the_nodes() -> None:
    draft = make_node(content="guess", status=NodeStatus.UNCONFIRMED)

    result = readiness(assemble(make_projection([*_ready_feature(), draft]), PRODUCT_ID))

    (gap,) = result.gaps
    assert gap.kind is GapKind.UNREVIEWED
    assert gap.node_ids == (draft.id,)
    assert gap.feature_scope_id == SCOPE_ID
    assert result.score < 100


def test_an_unsettled_disagreement_is_a_named_gap() -> None:
    left = make_node(content="Ships at launch")
    right = make_node(content="Deferred")

    result = readiness(
        assemble(
            make_projection([*_ready_feature(), left, right], edges=[conflict(left, right)]),
            PRODUCT_ID,
        )
    )

    (gap,) = result.gaps
    assert gap.kind is GapKind.DISAGREEMENT
    assert set(gap.node_ids) == {left.id, right.id}


def test_a_feature_without_a_constraint_is_a_named_gap() -> None:
    only_requirement = make_node(node_type=NodeType.REQUIREMENT)

    result = readiness(assemble(make_projection([only_requirement]), PRODUCT_ID))

    (gap,) = result.gaps
    assert gap.kind is GapKind.NO_CONSTRAINT
    assert gap.feature_scope_id == SCOPE_ID


def test_a_confirmed_open_question_is_a_named_gap() -> None:
    question = make_node(node_type=NodeType.OPEN_QUESTION, content="Which chart lib?")

    result = readiness(assemble(make_projection([*_ready_feature(), question]), PRODUCT_ID))

    (gap,) = result.gaps
    assert gap.kind is GapKind.OPEN_QUESTION
    assert gap.node_ids == (question.id,)


def test_score_is_the_share_of_checks_passed() -> None:
    """Deterministic and explainable: 4 checks per feature, score = passed / total."""
    draft = make_node(content="guess", status=NodeStatus.UNCONFIRMED)
    question = make_node(node_type=NodeType.OPEN_QUESTION, content="Which chart lib?")

    result = readiness(assemble(make_projection([draft, question]), PRODUCT_ID))

    # unreviewed fails, no-constraint fails, open-question fails, disagreement passes
    assert (result.passed, result.checks) == (1, 4)
    assert result.score == 25


def test_a_product_with_no_features_is_not_ready() -> None:
    result = readiness(assemble(make_projection([], scopes=[]), PRODUCT_ID))

    assert result.score == 0
    assert [gap.kind for gap in result.gaps] == [GapKind.NO_FEATURES]


def test_readiness_is_stated_at_the_head_of_the_markdown() -> None:
    """An agent receiving the spec is told what the spec is missing, first."""
    only_requirement = make_node(node_type=NodeType.REQUIREMENT, content="Plot visitors")

    rendered = to_markdown(assemble(make_projection([only_requirement]), PRODUCT_ID))

    head = rendered.split("## Main graph metric")[0]
    assert "Readiness: 75/100" in head
    assert "no constraint" in head.lower()


# --- spec versioning: what changed between two points in the log (Phase 3) -----


def _doc(nodes: list[Node], edges: list[Edge] | None = None) -> ProductDocument:
    return assemble(make_projection(nodes, edges=edges), PRODUCT_ID)


def test_a_newly_confirmed_claim_is_reported_as_added() -> None:
    draft = make_node(content="Plot visitors", status=NodeStatus.UNCONFIRMED)
    confirmed = draft.model_copy(update={"status": NodeStatus.CONFIRMED})

    changes = compare(_doc([draft]), _doc([confirmed]))

    assert [claim.content for claim in changes.added] == ["Plot visitors"]
    assert changes.removed == () and changes.reworded == ()


def test_a_claim_ruled_out_is_reported_as_removed() -> None:
    confirmed = make_node(content="Ship at launch")
    rejected = confirmed.model_copy(update={"status": NodeStatus.REJECTED})

    changes = compare(_doc([confirmed]), _doc([rejected]))

    assert [claim.content for claim in changes.removed] == ["Ship at launch"]


def test_an_edit_is_reported_with_both_wordings() -> None:
    before = make_node(content="Plot visitors")
    after = before.model_copy(
        update={"content": "Plot unique visitors", "status": NodeStatus.EDITED}
    )

    (change,) = compare(_doc([before]), _doc([after])).reworded

    assert (change.before, change.after) == ("Plot visitors", "Plot unique visitors")


def test_opened_and_resolved_disagreements_are_reported() -> None:
    left = make_node(content="Ships at launch")
    right = make_node(content="Deferred")
    edge = conflict(left, right)
    right_rejected = right.model_copy(update={"status": NodeStatus.REJECTED})

    opened = compare(_doc([left, right]), _doc([left, right], [edge]))
    resolved = compare(_doc([left, right], [edge]), _doc([left, right_rejected], [edge]))

    assert [d.edge_id for d in opened.disagreements_opened] == [edge.id]
    assert [d.edge_id for d in resolved.disagreements_resolved] == [edge.id]


def test_a_claim_becoming_contested_is_not_reported_as_removed() -> None:
    """It moved from the body into a disagreement; the disagreement is the news."""
    left = make_node(content="Ships at launch")
    right = make_node(content="Deferred", status=NodeStatus.UNCONFIRMED)

    changes = compare(_doc([left, right]), _doc([left, right], [conflict(left, right)]))

    assert changes.removed == ()
    assert len(changes.disagreements_opened) == 1


def test_readiness_movement_is_reported() -> None:
    requirement = make_node(node_type=NodeType.REQUIREMENT)
    constraint = make_node(node_type=NodeType.CONSTRAINT, content="No cookies")

    changes = compare(_doc([requirement]), _doc([requirement, constraint]))

    assert (changes.readiness_before, changes.readiness_after) == (75, 100)


def test_no_change_is_reported_as_unchanged() -> None:
    node = make_node()

    assert compare(_doc([node]), _doc([node])).unchanged


def test_changes_render_as_markdown_an_agent_can_act_on() -> None:
    draft = make_node(content="Plot visitors", status=NodeStatus.UNCONFIRMED)
    gone = make_node(content="Ship at launch")
    confirmed = draft.model_copy(update={"status": NodeStatus.CONFIRMED})
    rejected = gone.model_copy(update={"status": NodeStatus.REJECTED})

    rendered = changes_to_markdown(compare(_doc([draft, gone]), _doc([confirmed, rejected])))

    assert "### Added" in rendered and "Plot visitors" in rendered
    assert "### Removed" in rendered and "Ship at launch" in rendered
    assert "https://github.com/acme/repo/pull/42" in rendered


def test_changes_since_before_the_product_existed_reports_everything_added() -> None:
    node = make_node(content="Plot visitors")

    result = changes(Projection(), make_projection([node]), PRODUCT_ID)

    assert [claim.content for claim in result.added] == ["Plot visitors"]
    assert result.readiness_before == 0
