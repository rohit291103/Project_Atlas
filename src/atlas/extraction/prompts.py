"""Extraction agent instructions (TRD Sec5.1, Phase0_Architecture.md Sec2).

The system prompt tells the Claude Agent SDK agent what to extract and, above
all, the two non-negotiables it must honour so its output can pass the schema
gate in `agent.py`: every claim needs a literal source excerpt (provenance), and
the run ends with exactly one `emit_extraction` tool call. Prompt wording is
tuned via the `extraction-quality-review` eval loop, not asserted verbatim in
tests -- tests check the *contract* (what gets emitted), not the phrasing.

Slice 1C added a second source. The rules are shared -- they are properties of
the product, not of GitHub -- so `_build_system_prompt` templates only the two
source-specific spans: what the agent is reading, and which tools it has.
**The GitHub prompt renders byte-identically to the version the Phase 0 eval runs
validated**, and `tests/test_jira_extraction.py` asserts that against a golden
copy: adding a source must not silently re-word the prompt the extraction-quality
evidence was gathered against.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable

from atlas.ingestion.github import PullRequest
from atlas.ingestion.jira import JiraIssue
from atlas.models.schema import SourceType

# Node types the agent may emit, kept in lockstep with models.schema.NodeType so
# the prompt and the validation gate describe the same vocabulary.
_NODE_TYPE_GUIDE = """\
- goal: the outcome the work is meant to achieve -- why it is being done
- problem: a pain point or motivating issue
- evidence: a concrete observation supporting a claim
- decision: a choice that was made
- requirement: something the solution must do -- what it must do
- constraint: a limit the solution must respect
- architecture_note: a technical design detail
- open_question: an unresolved question
- rejected_alternative: an option considered and explicitly not taken"""


def _build_system_prompt(*, reads: str, references: str, tool_list: str) -> str:
    """The shared prompt, with only the source-specific spans templated."""
    return f"""\
You are Atlas, an extraction agent. You read the raw content of {reads} \
and its linked context, and you distil it into a small set of typed, \
provenance-linked knowledge elements (Nodes) and the relationships between them \
(Edges). You never invent information.

Node types:
{_NODE_TYPE_GUIDE}

Edge relation types: supports, derives_from, conflicts_with, implements, \
rejects, depends_on.

Rules you must follow exactly:
1. PROVENANCE IS MANDATORY. Every Node must carry at least one source_ref whose \
`excerpt` is a *verbatim* span copied from the source text -- never a paraphrase \
or summary. If you cannot point to literal text, do not create the Node.
2. Extract a draft, not a fact. Prefer omitting a weak claim over guessing. \
Assess your confidence for each Node and Edge as low, medium, or high.
3. Follow references, don't fabricate them. When the text mentions {references}, \
use the available tools \
({tool_list}) to read the real content \
before extracting from it. Use at most a handful of tool calls.
4. Flag conflicts, don't resolve them. If two sources disagree on the same \
point, emit both Nodes and a `conflicts_with` Edge between them.
5. ONE CLAIM, ONE NODE. Never emit two Nodes that assert the same thing in \
different words, and never emit two Nodes from the same excerpt unless they \
genuinely say different things. A sentence often states an outcome *and* what \
must be built to reach it -- pick the single type that fits it best and emit it \
once. A `goal` that restates a `requirement` or `decision` you have already \
emitted is a duplicate, not a second claim, and it forces a reviewer to rule \
twice on one idea.
6. Finish with exactly one call to `emit_extraction`, passing every Node and \
Edge. Give each Node a short local `ref` (e.g. "n1") and wire Edges by \
`from_ref`/`to_ref`. Do not write anything to any system -- extraction is \
read-only.
"""


SYSTEM_PROMPT = _build_system_prompt(
    reads="a GitHub pull request",
    references="a linked \
issue, a commit sha, or another PR",
    tool_list="`fetch_linked_issue`, `fetch_commit`, `search_repo`",
)

JIRA_SYSTEM_PROMPT = _build_system_prompt(
    reads="a Jira issue",
    references="a linked \
issue key, an epic, or another ticket",
    tool_list="`fetch_linked_issue`, `search_project`",
)


def build_seed_prompt(pr: PullRequest) -> str:
    """The initial user turn: the seed PR's own content (TRD Sec4.1 -- title,
    description, comments). The agent fetches any linked issues/commits itself."""
    lines = [
        f"Extract knowledge from this GitHub pull request (#{pr.number}).",
        f"URL: {pr.url}",
        f"Title: {pr.title}",
        "",
        "Description:",
        pr.body or "(no description)",
    ]
    if pr.comments:
        lines.append("")
        lines.append("Comments:")
        for comment in pr.comments:
            author = comment.author or "unknown"
            lines.append(f"- [{author}] {comment.body}")
    return "\n".join(lines)


def build_jira_seed_prompt(issue: JiraIssue) -> str:
    """The initial user turn for a Jira issue.

    The issue's links are listed explicitly rather than left to be inferred from
    prose: Jira states relationships structurally, and handing the agent the real
    keys is what stops it inventing one (rule 3).
    """
    lines = [
        f"Extract knowledge from this Jira issue ({issue.key}).",
        f"URL: {issue.url}",
        f"Type: {issue.issue_type or 'unknown'} | Status: {issue.status or 'unknown'}",
        f"Summary: {issue.summary}",
        "",
        "Description:",
        issue.description or "(no description)",
    ]
    if issue.parent_key:
        lines += ["", f"Parent / epic: {issue.parent_key}"]
    if issue.labels:
        lines.append(f"Labels: {', '.join(issue.labels)}")
    if issue.links:
        lines += ["", "Linked issues (use fetch_linked_issue to read one):"]
        lines += [f"- {link.relation} {link.key}: {link.summary}" for link in issue.links]
    if issue.comments:
        lines += ["", "Comments:"]
        lines += [f"- [{comment.author or 'unknown'}] {comment.body}" for comment in issue.comments]
    return "\n".join(lines)


def build_known_nodes_block(
    known: Iterable[tuple[uuid.UUID, str, str, SourceType]],
) -> str:
    """The cross-source context block (TRD Sec5.2).

    When a second source is ingested into a feature scope that already has
    claims, the run is told what is already established -- otherwise a
    contradiction between GitHub and Jira is simply invisible, because each run
    only ever sees its own artifact.

    The agent may point a `conflicts_with` edge at one of these ids. It cannot
    invent one: `agent.build_result` only accepts an id that is actually in this
    list, so a hallucinated relationship fails the gate rather than being stored.
    Empty when the scope is new, so a first ingestion is unchanged.
    """
    entries = list(known)
    if not entries:
        return ""
    lines = [
        "",
        "Already extracted for this feature, from other sources:",
    ]
    lines += [
        f"- [{node_id}] ({source.value} · {node_type}) {content}"
        for node_id, node_type, content, source in entries
    ]
    lines += [
        "",
        "If a claim you extract contradicts one of the above, emit your own Node "
        "and a `conflicts_with` Edge whose `to_ref` is that claim's bracketed id, "
        "copied exactly. Never invent an id, and never edit or resolve an existing "
        "claim -- surfacing the disagreement is the job.",
    ]
    return "\n".join(lines)
