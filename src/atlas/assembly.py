"""Confirmed Nodes and Edges -> one readable, provenance-carrying document.

Two readers share this module: the `/about` info page (as JSON) and spec export
v0 (as Markdown). It is its own module rather than a function in
`storage/projections.py` or a helper in `api/` for a reason that is not code
reuse -- see `docs/architecture/product-info-and-spec-export-v1.md` Sec4:

`projections.py` replays the log into **state**. `Projection` is state;
`for_product` and `counts_for` narrow state. A document is an *interpretation* of
state, with editorial decisions in it -- what order, what to omit, what counts as
an open disagreement. And `api/` holds no domain logic at all (CLAUDE.md's module
boundary), which those decisions plainly are.

The load-bearing argument is the filter. This is the one boundary where an
unconfirmed claim must not pass (Engineering Philosophy Sec2, "extraction is a
draft, never a fact"). The browser already pairs conflicts in TypeScript
(`frontend/src/review.ts`); if the page filtered there and the export filtered
here, the two would drift, and the drift is an export full of drafts. One place,
one test file.

Nothing here is stored. The document is derived on read like every other
projection -- caching it would be a materialized view that no event invalidates.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum

from atlas.models.schema import (
    Node,
    NodeStatus,
    NodeType,
    RelationType,
    SourceRef,
    SourceType,
)
from atlas.storage.projections import Projection

#: The order claims appear in, regardless of the order they were extracted in.
#:
#: It reads as an argument rather than a database: what we want -> what is wrong
#: -> what we know -> what must be true -> what limits us -> what we chose -> how
#: it is built -> what we did not choose -> what is still open.
#:
#: Evidence and architecture notes get a fixed position here rather than being
#: attached to the claims they `supports`. Following those edges would read
#: better, and it is deliberately not built yet: it is edge-walking machinery for
#: a nicety, and the `codebase-design` checklist is explicit about not adding
#: structure ahead of a need. A test asserts this tuple covers every `NodeType`,
#: so a tenth type has to be given a position on purpose.
DOCUMENT_ORDER: tuple[NodeType, ...] = (
    NodeType.GOAL,
    NodeType.PROBLEM,
    NodeType.EVIDENCE,
    NodeType.REQUIREMENT,
    NodeType.CONSTRAINT,
    NodeType.DECISION,
    NodeType.ARCHITECTURE_NOTE,
    NodeType.REJECTED_ALTERNATIVE,
    NodeType.OPEN_QUESTION,
)

#: A human has acted on these; the claim is the product's, not the extractor's.
#: `EDITED` belongs here because an edit *is* a ruling -- someone read the draft,
#: rewrote it and kept it, which is a stronger endorsement than a bare confirm.
RULED: frozenset[NodeStatus] = frozenset({NodeStatus.CONFIRMED, NodeStatus.EDITED})

#: Headings for each section of the rendered document.
_HEADINGS: dict[NodeType, str] = {
    NodeType.GOAL: "Goals",
    NodeType.PROBLEM: "Problems",
    NodeType.EVIDENCE: "Evidence",
    NodeType.REQUIREMENT: "Requirements",
    NodeType.CONSTRAINT: "Constraints",
    NodeType.DECISION: "Decisions",
    NodeType.ARCHITECTURE_NOTE: "Architecture notes",
    NodeType.REJECTED_ALTERNATIVE: "Rejected alternatives",
    NodeType.OPEN_QUESTION: "Open questions",
}


@dataclass(frozen=True)
class Claim:
    """One claim as it appears in a document, with its provenance attached.

    `status` is carried rather than dropped because the unruled side of a live
    disagreement is rendered too, and rendering it without saying it is unruled
    would be the dishonest half of showing it at all.
    """

    node_id: uuid.UUID
    type: NodeType
    content: str
    status: NodeStatus
    sources: tuple[SourceRef, ...]
    #: Which feature this claim belongs to. Only interesting when a disagreement
    #: reaches across two of them, which is the case worth not hiding.
    feature_title: str
    #: Evidence density (roadmap v2 2A, [+2026-09-02]): how many *distinct*
    #: artifacts back this claim. Two excerpts from one PR are one source -- the
    #: count is of independent places a reader could go and check, not of quotes.
    source_count: int
    #: Which systems those artifacts live in, sorted -- "across 2 systems" is the
    #: stronger half of the claim, since two tools agreeing is harder to fake
    #: than one tool repeating itself.
    systems: tuple[str, ...]


@dataclass(frozen=True)
class Disagreement:
    """A `conflicts_with` nobody has settled, carrying both sides.

    Confirming one side does not resolve a conflict (TRD Sec5.2) -- only a
    rejection does, because rejecting is the act that says which side lost. So a
    disagreement stands while neither endpoint is rejected.
    """

    edge_id: uuid.UUID
    left: Claim
    right: Claim


@dataclass(frozen=True)
class FeatureSection:
    """One feature's part of the document."""

    feature_scope_id: uuid.UUID
    title: str
    #: The PM's own words, not an extracted summary.
    description: str | None
    claims: tuple[Claim, ...]
    disagreements: tuple[Disagreement, ...]
    #: How many claims were withheld for want of a ruling. Reported rather than
    #: swallowed: a document that silently omits half its material is worse than
    #: a short one that says how short it is. Required, with no default, so it
    #: cannot be omitted and read as zero -- and so the generated TypeScript
    #: types mark it present rather than possibly-undefined.
    unreviewed: int
    #: Which claims those are, so a readiness gap can point at real nodes.
    unreviewed_node_ids: tuple[uuid.UUID, ...]


@dataclass(frozen=True)
class ProductDocument:
    """What a product is, assembled from what has actually been confirmed."""

    product_id: uuid.UUID
    name: str
    description: str | None
    features: tuple[FeatureSection, ...]
    #: Computed once, in `assemble`, so the page and the export cannot score two
    #: different assemblies. Forward reference: `Readiness` is defined below.
    readiness: Readiness
    generated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def unreviewed(self) -> int:
        return sum(section.unreviewed for section in self.features)


def assemble(projection: Projection, product_id: uuid.UUID) -> ProductDocument:
    """Build the document for one product.

    Narrows the projection itself rather than trusting the caller to have done
    it: passing a projection narrowed to the wrong product would produce a
    plausible document about someone else's work, which is the worst kind of
    wrong output to hand a PM.
    """
    product = projection.products.get(product_id)
    if product is None:
        raise KeyError(f"no product {product_id} in this projection")

    scoped = projection.for_product(product_id)
    titles = {scope_id: scope.title for scope_id, scope in projection.feature_scopes.items()}

    contested = _contested_node_ids(projection, scoped)
    sections = tuple(
        _section(scope_id, scoped, projection, titles, contested)
        for scope_id in scoped.feature_scopes
    )
    return ProductDocument(
        product_id=product_id,
        name=product.name,
        description=product.description,
        features=sections,
        readiness=_readiness(sections),
    )


def _live_conflicts(
    projection: Projection, scoped: Projection
) -> list[tuple[uuid.UUID, Node, Node]]:
    """Every unsettled disagreement touching this product, from-side first.

    Read against the *whole* projection, not the narrowed one, so a conflict
    reaching a feature in another product is still seen from this side. What
    makes one live: it is a `conflicts_with`, neither side has been rejected, and
    at least one side has been ruled on -- a conflict between two drafts is still
    review work rather than something a document has an opinion about.
    """
    live: list[tuple[uuid.UUID, Node, Node]] = []
    for edge in projection.edges.values():
        if edge.relation_type is not RelationType.CONFLICTS_WITH:
            continue
        left = projection.nodes.get(edge.from_node_id)
        right = projection.nodes.get(edge.to_node_id)
        if left is None or right is None:
            continue
        if left.feature_scope_id not in scoped.feature_scopes:
            continue
        if NodeStatus.REJECTED in (left.status, right.status):
            continue
        if not (left.status in RULED or right.status in RULED):
            continue
        live.append((edge.id, left, right))
    return live


def _contested_node_ids(projection: Projection, scoped: Projection) -> set[uuid.UUID]:
    """Nodes under live dispute, which the settled body must not contain.

    This is rule 4 enforced structurally: a contested claim appears *only* inside
    its disagreement, so no reader can mistake it for settled fact. Dropping it
    from the disagreement instead -- keeping the confirmed side in the body and
    saying nothing -- would be silently resolving the conflict in favour of
    whichever side happened to be confirmed first.
    """
    return {
        node.id for _, left, right in _live_conflicts(projection, scoped) for node in (left, right)
    }


def _section(
    scope_id: uuid.UUID,
    scoped: Projection,
    projection: Projection,
    titles: dict[uuid.UUID, str],
    contested: set[uuid.UUID],
) -> FeatureSection:
    scope = scoped.feature_scopes[scope_id]
    mine = [node for node in scoped.nodes.values() if node.feature_scope_id == scope_id]

    settled = [node for node in mine if node.status in RULED and node.id not in contested]
    settled.sort(key=lambda node: (DOCUMENT_ORDER.index(node.type), node.created_at, str(node.id)))

    disagreements = tuple(
        Disagreement(
            edge_id=edge_id,
            left=_claim(left, titles),
            right=_claim(right, titles),
        )
        for edge_id, left, right in _live_conflicts(projection, scoped)
        if left.feature_scope_id == scope_id
    )

    unreviewed = sorted(
        (node for node in mine if node.status is NodeStatus.UNCONFIRMED),
        key=lambda node: (node.created_at, str(node.id)),
    )
    return FeatureSection(
        feature_scope_id=scope_id,
        title=scope.title,
        description=scope.description,
        claims=tuple(_claim(node, titles) for node in settled),
        disagreements=disagreements,
        unreviewed=len(unreviewed),
        unreviewed_node_ids=tuple(node.id for node in unreviewed),
    )


#: The system a source type belongs to, for "N sources across M systems".
_SYSTEMS: dict[SourceType, str] = {
    SourceType.GITHUB_PR: "github",
    SourceType.GITHUB_ISSUE: "github",
    SourceType.GITHUB_COMMIT: "github",
    SourceType.JIRA_TICKET: "jira",
    SourceType.NOTION_PAGE: "notion",
    SourceType.GDOC: "gdoc",
    SourceType.HUMAN_ASSERTION: "human",
}


def _claim(node: Node, titles: dict[uuid.UUID, str]) -> Claim:
    distinct = {(ref.source_type, ref.external_id) for ref in node.source_refs}
    return Claim(
        node_id=node.id,
        type=node.type,
        content=node.content,
        status=node.status,
        sources=tuple(node.source_refs),
        feature_title=titles.get(node.feature_scope_id, "Unfiled"),
        source_count=len(distinct),
        systems=tuple(sorted({_SYSTEMS[source_type] for source_type, _ in distinct})),
    )


# --- Readiness -----------------------------------------------------------------


class GapKind(StrEnum):
    """Something a spec is missing that a reader can go and fix.

    Each kind is a countable fact about confirmed state, never an estimate --
    that is what separates this from the impact scoring rejected in
    `docs/decisions/2026-09-02-product-decision-engine-scope-assessment.md` Sec4.
    """

    NO_FEATURES = "no_features"
    UNREVIEWED = "unreviewed"
    DISAGREEMENT = "disagreement"
    NO_CONSTRAINT = "no_constraint"
    OPEN_QUESTION = "open_question"


#: The checks run against every feature, in the order gaps are reported.
_FEATURE_CHECKS: tuple[GapKind, ...] = (
    GapKind.UNREVIEWED,
    GapKind.DISAGREEMENT,
    GapKind.NO_CONSTRAINT,
    GapKind.OPEN_QUESTION,
)


@dataclass(frozen=True)
class Gap:
    """One named gap. `node_ids` is what it clicks back to; for
    `NO_CONSTRAINT` the referent is the feature itself, since the gap is an
    absence and there is no node to point at."""

    kind: GapKind
    feature_scope_id: uuid.UUID | None
    feature_title: str | None
    node_ids: tuple[uuid.UUID, ...]
    detail: str


@dataclass(frozen=True)
class Readiness:
    """How ready a spec is to hand to a coding agent, and why not.

    `score` is `passed / checks` as a percentage -- four checks per feature,
    equally weighted. Deliberately not a weighted model: weights would be an
    opinion dressed as a number, and the point is that a reader can recompute
    the score by hand from the gaps listed beside it.
    """

    score: int
    checks: int
    passed: int
    gaps: tuple[Gap, ...]


def readiness(doc: ProductDocument) -> Readiness:
    """Score a document and name what it is missing. Pure; predicts nothing."""
    return _readiness(doc.features)


def _readiness(features: tuple[FeatureSection, ...]) -> Readiness:
    if not features:
        return Readiness(
            score=0,
            checks=0,
            passed=0,
            gaps=(
                Gap(
                    kind=GapKind.NO_FEATURES,
                    feature_scope_id=None,
                    feature_title=None,
                    node_ids=(),
                    detail="No features yet — nothing has been ingested for this product.",
                ),
            ),
        )

    gaps: list[Gap] = []
    for section in features:
        for kind in _FEATURE_CHECKS:
            gap = _check(kind, section)
            if gap is not None:
                gaps.append(gap)

    checks = len(features) * len(_FEATURE_CHECKS)
    passed = checks - len(gaps)
    return Readiness(
        score=round(100 * passed / checks),
        checks=checks,
        passed=passed,
        gaps=tuple(gaps),
    )


def _check(kind: GapKind, section: FeatureSection) -> Gap | None:
    def gap(node_ids: tuple[uuid.UUID, ...], detail: str) -> Gap:
        return Gap(
            kind=kind,
            feature_scope_id=section.feature_scope_id,
            feature_title=section.title,
            node_ids=node_ids,
            detail=detail,
        )

    if kind is GapKind.UNREVIEWED:
        if section.unreviewed_node_ids:
            return gap(
                section.unreviewed_node_ids,
                f"{section.unreviewed} claim(s) still await review.",
            )
    elif kind is GapKind.DISAGREEMENT:
        if section.disagreements:
            ids = tuple(
                dict.fromkeys(
                    node_id
                    for d in section.disagreements
                    for node_id in (d.left.node_id, d.right.node_id)
                )
            )
            return gap(ids, f"{len(section.disagreements)} unresolved disagreement(s).")
    elif kind is GapKind.NO_CONSTRAINT:
        if not any(claim.type is NodeType.CONSTRAINT for claim in section.claims):
            return gap((), "No constraint confirmed — nothing says what this must not do.")
    elif kind is GapKind.OPEN_QUESTION:
        questions = tuple(
            claim.node_id for claim in section.claims if claim.type is NodeType.OPEN_QUESTION
        )
        if questions:
            return gap(questions, f"{len(questions)} confirmed open question(s) unanswered.")
    return None


# --- Markdown ------------------------------------------------------------------


def to_markdown(doc: ProductDocument) -> str:
    """Render the document as Markdown -- spec export v0.

    A plain function, not a `Renderer` implementation: there are two output
    formats and the `codebase-design` checklist is explicit that a strategy
    pattern for two concrete variants is the abstraction to skip. If a third
    format ever appears, that is the moment to reconsider, not before.
    """
    lines: list[str] = [f"# {doc.name}", ""]
    if doc.description:
        lines += [doc.description, ""]

    # Say what is missing, in the document itself. A reader who does not know a
    # third of the material was withheld will read the rest as complete -- and
    # the one exception (a draft that contradicts a confirmed claim is shown, as
    # a disagreement) has to be stated too, or the count looks like a lie.
    lines += [
        f"*Assembled {doc.generated_at:%Y-%m-%d} from confirmed claims only. "
        f"{doc.unreviewed} claim(s) still await review and are omitted, except "
        f"where one contradicts a confirmed claim — those appear below as "
        f"unresolved disagreements.*",
        "",
    ]

    # Readiness goes at the head, before any claim, so an agent handed this file
    # is told what the spec is missing before it reads what the spec says.
    ready = doc.readiness
    lines += [
        f"**Readiness: {ready.score}/100** ({ready.passed} of {ready.checks} checks pass)",
        "",
    ]
    for gap in ready.gaps:
        where = f"*{gap.feature_title}*: " if gap.feature_title else ""
        lines.append(f"- {where}{gap.detail}")
    if ready.gaps:
        lines.append("")

    for section in doc.features:
        lines += [f"## {section.title}", ""]
        if section.description:
            lines += [section.description, ""]

        for node_type in DOCUMENT_ORDER:
            of_type = [claim for claim in section.claims if claim.type is node_type]
            if not of_type:
                continue
            lines += [f"### {_HEADINGS[node_type]}", ""]
            lines += [line for claim in of_type for line in _claim_lines(claim)]

        if section.disagreements:
            # The explanation belongs once under the heading, not above every
            # pair: one claim can be in several disagreements at once (it really
            # can contradict two different things), and repeating the banner six
            # times buries the claims it is meant to frame.
            #
            # Not "nobody has ruled" either -- a side is usually confirmed. What
            # makes it unresolved is that confirming a side does not settle a
            # conflict (TRD Sec5.2); only ruling the other side out does.
            lines += [
                "### Unresolved disagreements",
                "",
                "> The sources disagree and nothing here has been settled. "
                "Confirming one side of a disagreement does not resolve it — only "
                "ruling the other side out does. These claims are listed here "
                "rather than above so that nothing still in dispute reads as "
                "settled.",
                "",
            ]
            for number, disagreement in enumerate(section.disagreements, start=1):
                lines += [
                    f"**{number}.**",
                    "",
                    *_side_lines(disagreement.left, section.title),
                    *_side_lines(disagreement.right, section.title),
                ]

        if not section.claims and not section.disagreements:
            lines += [
                f"*Nothing confirmed yet — {section.unreviewed} claim(s) awaiting review.*",
                "",
            ]

    return "\n".join(lines).rstrip() + "\n"


def _provenance_lines(claim: Claim) -> list[str]:
    """Where the claim came from, quoted.

    The excerpt is reproduced verbatim and never trimmed, wrapped or normalized:
    it is the `SourceRef.excerpt`, which the eval harness verifies appears
    literally in the raw source. Editing it for presentation here would corrupt
    provenance exactly as surely as editing it at extraction would.
    """
    return [
        f'  - > "{source.excerpt}" — '
        f"[{source.source_type.value} {source.external_id}]({source.url})"
        for source in claim.sources
    ]


def _density(claim: Claim) -> str:
    """ "(3 sources across 2 systems)" -- said only when there is corroboration,
    since "(1 source)" on every line is noise that teaches the reader to skip it."""
    if claim.source_count < 2:
        return ""
    systems = len(claim.systems)
    return f" *({claim.source_count} sources across {systems} system{'s' if systems != 1 else ''})*"


def _claim_lines(claim: Claim) -> list[str]:
    return [f"- {claim.content}{_density(claim)}", *_provenance_lines(claim), ""]


def _side_lines(claim: Claim, section_title: str) -> list[str]:
    ruling = "confirmed" if claim.status in RULED else "unreviewed"
    where = "" if claim.feature_title == section_title else f", in *{claim.feature_title}*"
    return [f"- **{claim.content}** ({ruling}{where})", *_provenance_lines(claim), ""]


# --- Spec versioning ------------------------------------------------------------
#
# A version of a spec is the document assembled from the log *as of* a moment
# (`load_projection(..., as_of=...)`). Nothing is snapshotted: the log already is
# the history, and a stored copy would be a second source of truth that no event
# invalidates. So "what changed since v1" is two assemblies and one comparison.


@dataclass(frozen=True)
class ClaimChange:
    """A claim that stayed in the spec but was reworded by a human edit."""

    node_id: uuid.UUID
    feature_title: str
    type: NodeType
    before: str
    after: str


@dataclass(frozen=True)
class SpecChanges:
    """What moved between two versions of one product's spec."""

    #: Newly settled -- confirmed, edited, or no longer in dispute.
    added: tuple[Claim, ...]
    #: No longer settled and not now contested either -- in practice, ruled out.
    #: A claim that moved into a disagreement is reported there instead, since
    #: "it is now disputed" is the news and "it vanished" would be misleading.
    removed: tuple[Claim, ...]
    reworded: tuple[ClaimChange, ...]
    disagreements_opened: tuple[Disagreement, ...]
    disagreements_resolved: tuple[Disagreement, ...]
    readiness_before: int
    readiness_after: int

    @property
    def unchanged(self) -> bool:
        return not (
            self.added
            or self.removed
            or self.reworded
            or self.disagreements_opened
            or self.disagreements_resolved
        )


def compare(before: ProductDocument, after: ProductDocument) -> SpecChanges:
    """Diff two assemblies of the same product. Pure; order follows `after`."""
    old = _settled(before)
    new = _settled(after)
    old_disputes = _disputes(before)
    new_disputes = _disputes(after)
    contested_now = {
        node_id for d in new_disputes.values() for node_id in (d.left.node_id, d.right.node_id)
    }

    return SpecChanges(
        added=tuple(claim for node_id, claim in new.items() if node_id not in old),
        removed=tuple(
            claim
            for node_id, claim in old.items()
            if node_id not in new and node_id not in contested_now
        ),
        reworded=tuple(
            ClaimChange(
                node_id=node_id,
                feature_title=claim.feature_title,
                type=claim.type,
                before=old[node_id].content,
                after=claim.content,
            )
            for node_id, claim in new.items()
            if node_id in old and old[node_id].content != claim.content
        ),
        disagreements_opened=tuple(
            d for edge_id, d in new_disputes.items() if edge_id not in old_disputes
        ),
        disagreements_resolved=tuple(
            d for edge_id, d in old_disputes.items() if edge_id not in new_disputes
        ),
        readiness_before=before.readiness.score,
        readiness_after=after.readiness.score,
    )


def _settled(doc: ProductDocument) -> dict[uuid.UUID, Claim]:
    return {claim.node_id: claim for section in doc.features for claim in section.claims}


def _disputes(doc: ProductDocument) -> dict[uuid.UUID, Disagreement]:
    return {d.edge_id: d for section in doc.features for d in section.disagreements}


def changes_to_markdown(changes: SpecChanges, *, name: str = "", since: str = "") -> str:
    """Render a spec diff for a reader -- or an agent -- already holding the old
    version. Provenance is carried on every added claim, exactly as in the full
    export: a claim new to the spec has to show where it came from, and
    `_provenance_lines` never edits the excerpt."""
    title = f"# Spec changes{f' — {name}' if name else ''}"
    lines = [title, ""]
    if since:
        lines += [f"*Changes since {since}.*", ""]
    lines += [f"**Readiness: {changes.readiness_before} → {changes.readiness_after}/100**", ""]
    if changes.unchanged:
        return "\n".join([*lines, "Nothing in the spec has changed."]) + "\n"

    if changes.added:
        lines += ["### Added", ""]
        for claim in changes.added:
            lines += [
                f"- [{_HEADINGS[claim.type]}, *{claim.feature_title}*] {claim.content}",
                *_provenance_lines(claim),
                "",
            ]
    if changes.reworded:
        lines += ["### Reworded", ""]
        for change in changes.reworded:
            lines += [f"- ~~{change.before}~~ → {change.after} (*{change.feature_title}*)", ""]
    if changes.removed:
        lines += ["### Removed", ""]
        lines += [f"- ~~{claim.content}~~ (*{claim.feature_title}*)" for claim in changes.removed]
        lines.append("")
    if changes.disagreements_opened:
        lines += ["### Newly disputed", ""]
        for d in changes.disagreements_opened:
            lines += [f"- {d.left.content} **vs.** {d.right.content}", ""]
    if changes.disagreements_resolved:
        lines += ["### Disputes settled", ""]
        for d in changes.disagreements_resolved:
            lines += [f"- {d.left.content} **vs.** {d.right.content}", ""]
    return "\n".join(lines).rstrip() + "\n"


def changes(before: Projection, after: Projection, product_id: uuid.UUID) -> SpecChanges:
    """What changed in one product's spec between two replays of the log.

    A product absent from `before` (created since) diffs against an empty spec,
    so everything it now holds reads as added rather than raising.
    """
    current = assemble(after, product_id)
    if product_id in before.products:
        previous = assemble(before, product_id)
    else:
        previous = ProductDocument(
            product_id=product_id,
            name=current.name,
            description=None,
            features=(),
            readiness=_readiness(()),
        )
    return compare(previous, current)
