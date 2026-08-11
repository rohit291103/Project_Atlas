/* Presentation rules for the review page — grouping, ordering, conflicts.
 *
 * These live on the client on purpose. Node-type ordering (why → what → how),
 * unconfirmed-first sort and the progress meter are presentation decisions fixed
 * in docs/ux/confirmation-flow-spec-v1.md §3.2–3.3; putting them behind an
 * endpoint would move a UX decision into the backend
 * (docs/decisions/2026-08-11-api-frontend-module-boundary.md §5).
 */

import type { Edge, FeatureScopeDetail, Node, NodeType, SourceRef } from "./api";

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

const sourcesOf = (node: Node) => new Set(node.source_refs.map((ref) => SOURCE_LABELS[ref.source_type]));

export const sourceLabel = (node: Node): string => [...sourcesOf(node)].join(" + ");

/** True when two nodes have no source tool in common — i.e. this is the
 * cross-source disagreement Atlas exists to surface (TRD §5.2), not two claims
 * from the same PR contradicting each other. */
export function crossesSource(node: Node, other: Node): boolean {
  const mine = sourcesOf(node);
  return [...sourcesOf(other)].every((source) => !mine.has(source));
}

export type Section = { type: NodeType; nodes: Node[] };

const isReviewed = (node: Node) => node.status !== "unconfirmed";

/** Group into sections, dropping empty types; unconfirmed first within each. */
export function toSections(nodes: Node[]): Section[] {
  return SECTION_ORDER.map((type) => ({
    type,
    nodes: nodes
      .filter((node) => node.type === type)
      .sort((a, b) => Number(isReviewed(a)) - Number(isReviewed(b))),
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

/** Non-conflict relationships, rendered as inline text refs — there is no graph
 * canvas in Phase 1 (design baseline §8). */
export function relationsOf(node: Node, edges: Edge[], nodes: Node[]): string[] {
  const byId = new Map(nodes.map((n) => [n.id, n]));
  return edges
    .filter((edge) => edge.relation_type !== "conflicts_with" && edge.from_node_id === node.id)
    .map((edge) => {
      const target = byId.get(edge.to_node_id);
      return target ? `${edge.relation_type} → ${target.content}` : "";
    })
    .filter(Boolean);
}

/** Three pips for the three extraction confidence levels; an em dash for a
 * manually-added node, which is unscored by design (TRD §6). */
export function pipsFor(node: Node): string {
  if (node.confidence_score === null || node.confidence_score === undefined) return "—";
  if (node.confidence_score >= 0.8) return "●●●";
  if (node.confidence_score >= 0.5) return "●●○";
  return "●○○";
}
