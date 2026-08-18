/* Presentation rules for the review page — grouping, ordering, conflicts.
 *
 * These live on the client on purpose. Node-type ordering (why → what → how),
 * unconfirmed-first sort and the progress meter are presentation decisions fixed
 * in docs/ux/confirmation-flow-spec-v1.md §3.2–3.3; putting them behind an
 * endpoint would move a UX decision into the backend
 * (docs/decisions/2026-08-11-api-frontend-module-boundary.md §5).
 */

import type { Edge, FeatureScope, FeatureScopeDetail, Node, NodeType, SourceRef } from "./api";

/** Fixed section order: how a reader reconstructs a feature (flow spec §3.2). */
export const SECTION_ORDER: NodeType[] = [
  "goal",
  "problem",
  "requirement",
  "decision",
  "rejected_alternative",
  "constraint",
  "open_question",
  "architecture_note",
  "evidence",
];

export const TYPE_LABELS: Record<NodeType, string> = {
  goal: "Goals",
  problem: "Problems",
  requirement: "Requirements",
  decision: "Decisions",
  rejected_alternative: "Rejected alternatives",
  constraint: "Constraints",
  open_question: "Open questions",
  architecture_note: "Architecture notes",
  evidence: "Evidence",
};

export const TYPE_TAGS: Record<NodeType, string> = {
  goal: "Goal",
  problem: "Problem",
  requirement: "Requirement",
  decision: "Decision",
  rejected_alternative: "Rejected alt.",
  constraint: "Constraint",
  open_question: "Open question",
  architecture_note: "Arch. note",
  evidence: "Evidence",
};

/** Source badges (design baseline §6.6a). Only GitHub and manual are live in
 * slice 1B; the rest are declared because the schema already allows them and a
 * new connector must not require a redesign. */
export const SOURCE_BADGES: Record<SourceRef["source_type"], string> = {
  github_pr: "gh",
  github_issue: "gh",
  github_commit: "gh",
  jira_ticket: "jr",
  notion_page: "nt",
  gdoc: "gd",
  human_assertion: "you",
};

/** Human names for the tools a claim can come from — what the conflict banner
 * says when the two sides of a disagreement came from different places. */
export const SOURCE_LABELS: Record<SourceRef["source_type"], string> = {
  github_pr: "GitHub",
  github_issue: "GitHub",
  github_commit: "GitHub",
  jira_ticket: "Jira",
  notion_page: "Notion",
  gdoc: "Google Docs",
  human_assertion: "a person",
};

const sourcesOf = (node: Node) =>
  new Set(node.source_refs.map((ref) => SOURCE_LABELS[ref.source_type]));

export const sourceLabel = (node: Node): string => [...sourcesOf(node)].join(" + ");

/** True when two nodes have no source tool in common — i.e. this is the
 * cross-source disagreement Atlas exists to surface (TRD §5.2), not two claims
 * from the same PR contradicting each other. */
export function crossesSource(node: Node, other: Node): boolean {
  const mine = sourcesOf(node);
  return [...sourcesOf(other)].every((source) => !mine.has(source));
}

/** The four groups that replaced nine section headers.
 *
 * The old build rendered one header per `NodeType`, straight off the storage
 * enum — "rejected alternative", "architecture note" and all. That is the schema
 * shown to a PM, and nine buckets is more than anyone holds while reading. These
 * four are the same why→what→how editorial order the flow spec fixed (§3.2),
 * collapsed to categories a person already thinks in; the precise type survives
 * as a tag on the claim, so nothing is lost from the record.
 *
 * `open_question` earns its own group rather than sitting under "how": what is
 * still undecided is the thing a PM most needs pulled out of the pile.
 */
export type GroupKey = "why" | "what" | "how" | "open";

export const GROUPS: { key: GroupKey; label: string; types: NodeType[] }[] = [
  { key: "why", label: "Why this exists", types: ["goal", "problem"] },
  { key: "what", label: "What it must do", types: ["requirement", "constraint"] },
  {
    key: "how",
    label: "How it was decided",
    types: ["decision", "rejected_alternative", "architecture_note", "evidence"],
  },
  { key: "open", label: "Unresolved", types: ["open_question"] },
];

export type Section = { key: GroupKey; label: string; nodes: Node[] };

const isReviewed = (node: Node) => node.status !== "unconfirmed";

/** Within a group, keep the fixed type order, then unconfirmed first. */
const rank = (node: Node) => SECTION_ORDER.indexOf(node.type as NodeType);

/** Group into the four sections, dropping empty ones.
 *
 * Order within a group: **contested, then unruled, then settled**, and only
 * then the fixed type order. A disagreement outranks a backlog for the same
 * reason it does on the product home — an unreviewed claim is work somebody has
 * yet to do, a conflict is a decision nobody has made. Passing no conflict map
 * keeps the previous unconfirmed-first behaviour exactly.
 */
export function toSections(nodes: Node[], conflicts?: Map<string, Node[]>): Section[] {
  const contested = (node: Node) => (conflicts?.has(node.id) ? 0 : 1);
  return GROUPS.map(({ key, label, types }) => ({
    key,
    label,
    nodes: nodes
      .filter((node) => types.includes(node.type as NodeType))
      .sort(
        (a, b) =>
          contested(a) - contested(b) ||
          Number(isReviewed(a)) - Number(isReviewed(b)) ||
          rank(a) - rank(b),
      ),
  })).filter((section) => section.nodes.length > 0);
}

/** Display order flattened — the sequence `j`/`k` walk. */
export const toOrderedNodes = (sections: Section[]): Node[] =>
  sections.flatMap((section) => section.nodes);

export function progressOf(nodes: Node[]): { reviewed: number; total: number } {
  return { reviewed: nodes.filter(isReviewed).length, total: nodes.length };
}

/** node id → the nodes it conflicts with. `conflicts_with` is undirected in
 * meaning, so both endpoints show the banner (flow spec §4.5). */
export function conflictMap(detail: FeatureScopeDetail): Map<string, Node[]> {
  const byId = new Map(detail.nodes.map((node) => [node.id, node]));
  const conflicts = new Map<string, Node[]>();
  const link = (from: string, to: string) => {
    const other = byId.get(to);
    if (!other) return;
    conflicts.set(from, [...(conflicts.get(from) ?? []), other]);
  };
  for (const edge of detail.edges) {
    if (edge.relation_type !== "conflicts_with") continue;
    link(edge.from_node_id, edge.to_node_id);
    link(edge.to_node_id, edge.from_node_id);
  }
  return conflicts;
}

export type ConflictPair = { id: string; a: Node; b: Node; crossSource: boolean };

/** Each `conflicts_with` edge as one pair, counted once.
 *
 * `conflictMap` intentionally reports both endpoints so either card can show a
 * banner. That is right for the review screen and wrong for the conflicts
 * screen, where it would list every disagreement twice — five conflicts became
 * ten amber lines in the old build, which is most of why they read as noise
 * rather than as the product's headline capability.
 */
export function conflictPairs(detail: FeatureScopeDetail): ConflictPair[] {
  const byId = new Map(detail.nodes.map((node) => [node.id, node]));
  const pairs: ConflictPair[] = [];
  for (const edge of detail.edges) {
    if (edge.relation_type !== "conflicts_with") continue;
    const a = byId.get(edge.from_node_id);
    const b = byId.get(edge.to_node_id);
    if (!a || !b) continue;
    pairs.push({ id: edge.id, a, b, crossSource: crossesSource(a, b) });
  }
  // A cross-source disagreement is the one no single tool could have shown you,
  // so it leads.
  return pairs.sort((x, y) => Number(y.crossSource) - Number(x.crossSource));
}

/** Work still owed across a set of features.
 *
 * One helper because three surfaces read the same figures — the rail's per-row
 * badge, the `Conflicts (n)` nav entry, and the product home's worklist — and
 * three private copies is how they start disagreeing with each other.
 *
 * The counts themselves come from the API (`FeatureScopeRow.counts`), so
 * "unreviewed" is defined once, in `storage/projections.py`, rather than
 * re-derived per component.
 */
export type WorkSummary = {
  features: number;
  total: number;
  unreviewed: number;
  conflicts: number;
};

export function summarize(scopes: FeatureScope[]): WorkSummary {
  return scopes.reduce<WorkSummary>(
    (sum, scope) => ({
      features: sum.features + 1,
      total: sum.total + scope.counts.total,
      unreviewed: sum.unreviewed + scope.counts.unreviewed,
      conflicts: sum.conflicts + scope.counts.conflicts,
    }),
    { features: 0, total: 0, unreviewed: 0, conflicts: 0 },
  );
}

/** Features that still want a person, most urgent first.
 *
 * A disagreement outranks a backlog: an unreviewed claim is work, but a
 * conflict is a decision nobody has made and the one thing no single source
 * tool could have surfaced. Within each band, more outstanding work first.
 */
export function needsRuling(scopes: FeatureScope[]): FeatureScope[] {
  return scopes
    .filter((scope) => scope.counts.unreviewed > 0 || scope.counts.conflicts > 0)
    .sort(
      (a, b) =>
        Number(b.counts.conflicts > 0) - Number(a.counts.conflicts > 0) ||
        b.counts.conflicts - a.counts.conflicts ||
        b.counts.unreviewed - a.counts.unreviewed,
    );
}

/** How an edge reads from each end.
 *
 * An edge is directed and its name only makes sense read forwards: `A
 * derives_from B` means B is where A came from. Read from B's end the same edge
 * has to be phrased the other way round, or the claim would appear to derive
 * from the thing that derives from it. The old build sidestepped this by only
 * ever showing outgoing edges — which meant a claim that three other claims
 * depended on displayed no relationships at all, the exact case where knowing
 * them matters most.
 */
const RELATION_PHRASING: Record<string, { out: string; in: string }> = {
  derives_from: { out: "derives from", in: "is the basis for" },
  implements: { out: "implements", in: "is implemented by" },
  supports: { out: "supports", in: "is supported by" },
  depends_on: { out: "depends on", in: "is depended on by" },
  refines: { out: "refines", in: "is refined by" },
  supersedes: { out: "supersedes", in: "is superseded by" },
};

export type Neighbour = { node: Node; relation: string };

/** A claim's non-conflict relationships, both directions, as real neighbours.
 *
 * Still not a graph canvas — that is an explicit non-goal in three places
 * (design baseline §8, flow spec, and the 2026-08-11 UI direction decision) on
 * the grounds that a node-link view reintroduces the overwhelm this screen
 * exists to remove. These are the local edges only: what this one claim touches,
 * as a short list you can click through. Conflicts are excluded because they get
 * their own treatment on the stage rather than a line in a list.
 */
export function neighboursOf(node: Node, edges: Edge[], nodes: Node[]): Neighbour[] {
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const out: Neighbour[] = [];
  for (const edge of edges) {
    if (edge.relation_type === "conflicts_with") continue;
    const phrasing = RELATION_PHRASING[edge.relation_type];
    const forward = edge.from_node_id === node.id;
    const other = byId.get(forward ? edge.to_node_id : edge.from_node_id);
    if (!other || (!forward && edge.to_node_id !== node.id)) continue;
    out.push({
      node: other,
      relation: phrasing
        ? forward
          ? phrasing.out
          : phrasing.in
        : edge.relation_type.replace(/_/g, " "),
    });
  }
  // Deduplicate: two sources can assert the same relationship, and the reader
  // does not care that it was extracted twice.
  const seen = new Set<string>();
  return out.filter(({ node: n, relation }) => {
    const key = `${relation}::${n.id}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

/* --- what the queue is showing -------------------------------------------
 *
 * The queue was one flat list of every claim in display order. That is the
 * right shape on day one and the wrong shape on day two: by the time a feature
 * is 25-of-27 reviewed, the two claims that still want a person are below
 * twenty finished ones, and the eight unresolved conflicts are not distinguished
 * at all. Reviewing is triage, not reading — so the default view is the work,
 * and the finished pile is one line you can open.
 */
export type QueueView = "ruling" | "conflicts" | "all";

export const QUEUE_VIEWS: { key: QueueView; label: string }[] = [
  { key: "ruling", label: "Needs ruling" },
  { key: "conflicts", label: "Conflicts" },
  { key: "all", label: "All" },
];

/** The nodes a view admits. `conflicts` is the map from `conflictMap`.
 *
 * "Needs ruling" deliberately keeps a *confirmed* claim that is still in an
 * unresolved conflict: confirming one side does not settle a disagreement
 * (TRD §5.2), so dropping it here would hide work the rail is still counting.
 */
export function inView(node: Node, view: QueueView, conflicts: Map<string, Node[]>): boolean {
  if (view === "all") return true;
  if (view === "conflicts") return conflicts.has(node.id);
  return node.status === "unconfirmed" || conflicts.has(node.id);
}

/** Three pips for the three extraction confidence levels; `n/a` for a
 * manually-added node, which is unscored by design (TRD §6).
 *
 * `n/a` rather than the bare dash this used to return: a lone dash in a data
 * slot has to be decoded before it can be read as "there is no number here",
 * and it is the same glyph the prose everywhere else has now stopped using. */
export function pipsFor(node: Node): string {
  if (node.confidence_score === null || node.confidence_score === undefined) return "n/a";
  if (node.confidence_score >= 0.8) return "●●●";
  if (node.confidence_score >= 0.5) return "●●○";
  return "●○○";
}
