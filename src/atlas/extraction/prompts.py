"""Extraction agent instructions (TRD Sec5.1, Phase0_Architecture.md Sec2).

The system prompt tells the Claude Agent SDK agent what to extract and, above
all, the two non-negotiables it must honour so its output can pass the schema
gate in `agent.py`: every claim needs a literal source excerpt (provenance), and
the run ends with exactly one `emit_extraction` tool call. Prompt wording is
tuned via the `extraction-quality-review` eval loop, not asserted verbatim in
tests -- tests check the *contract* (what gets emitted), not the phrasing.
"""

from __future__ import annotations

from atlas.ingestion.github import PullRequest

# Node types the agent may emit, kept in lockstep with models.schema.NodeType so
# the prompt and the validation gate describe the same vocabulary.
_NODE_TYPE_GUIDE = """\
- goal: an intended outcome or objective
- problem: a pain point or motivating issue
- evidence: a concrete observation supporting a claim
- decision: a choice that was made
- requirement: something the solution must do
- constraint: a limit the solution must respect
- architecture_note: a technical design detail
- open_question: an unresolved question
- rejected_alternative: an option considered and explicitly not taken"""

SYSTEM_PROMPT = f"""\
You are Atlas, an extraction agent. You read the raw content of a GitHub pull \
request and its linked context, and you distil it into a small set of typed, \
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
3. Follow references, don't fabricate them. When the text mentions a linked \
issue, a commit sha, or another PR, use the available tools \
(`fetch_linked_issue`, `fetch_commit`, `search_repo`) to read the real content \
before extracting from it. Use at most a handful of tool calls.
4. Flag conflicts, don't resolve them. If two sources disagree on the same \
point, emit both Nodes and a `conflicts_with` Edge between them.
5. Finish with exactly one call to `emit_extraction`, passing every Node and \
Edge. Give each Node a short local `ref` (e.g. "n1") and wire Edges by \
`from_ref`/`to_ref`. Do not write anything to any system -- extraction is \
read-only.
"""


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
