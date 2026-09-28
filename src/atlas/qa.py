"""Contextual Q&A over a product's confirmed claims, with citations (Phase 3).

The model answers from the assembled document and nothing else: the settled
claims plus both sides of every open disagreement, each labelled `[C1]`, `[C2]`
... with its status, its literal excerpt and its URL. Unreviewed drafts are not
shown to it (Engineering Philosophy §2 -- a draft is not a fact, and an answer
built on one would present it as settled).

The model is untrusted in exactly the way the extraction agent is, so the
guarantees live in the gate around it, not in the prompt:

- **A citation must name a claim the model was shown.** An unknown label is
  refused outright -- the Q&A form of a fabricated `SourceRef`, and treated with
  the same severity.
- **The evidence label is computed, never taken from the model.** `CONFLICTING`
  when any cited claim is in an open disagreement; `SUPPORTED` when the cited
  claims rest on two or more independent artifacts; `THIN` on one; `NONE` when
  nothing is cited. That is what "confidence-aware" means here: countable facts
  about the cited evidence, not the model's opinion of itself.
- **Nothing confirmed, no call.** An empty context gets a fixed answer without
  spending a token.

Its own module rather than part of `extraction/`: extraction turns sources into
Nodes that go to storage; this reads assembled state and writes nothing. It
reads through `assembly` so that "what counts as confirmed" is decided in one
place for the page, the export, and the answers.
"""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    PermissionResultDeny,
    TextBlock,
    ToolPermissionContext,
    query,
)
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from atlas.assembly import RULED, Claim, ProductDocument
from atlas.models.schema import SourceRef

#: Claude Opus 5 -- the current default for a new LLM path. Extraction pins its
#: own model separately; the two are graded by different evals.
DEFAULT_MODEL = "claude-opus-5"

MAX_QUESTION = 500

#: One prompt in, the model's final text out. Injected so the gate is testable
#: without a model, exactly as `extraction.agent.AgentCall` is.
AnswerCall = Callable[[str], Awaitable[str]]

SYSTEM_PROMPT = """\
You answer questions about a software product using ONLY the claims listed in \
the context. Each claim has a label like [C3], a status, the literal source \
excerpt it came from, and a URL.

Rules:
1. Every factual statement in your answer must be followed by the label(s) of \
the claim(s) that support it, e.g. "Sessions expire after 30 minutes [C4]."
2. Never state anything the claims do not support. If they do not answer the \
question, say so plainly and cite nothing.
3. If the claims you rely on are in a listed disagreement, say that the sources \
disagree and present both sides; do not pick one.
4. Be brief: a few sentences.

Respond with a single JSON object and nothing else:
{"answer": "<text with [Cn] labels>", "citations": ["C1", ...]}
"""

_NO_CONTEXT = (
    "Nothing about this product has been confirmed yet, so there is nothing to "
    "answer from. Review the extracted claims first."
)


class AnswerError(ValueError):
    """The question or the model's response failed the gate."""


class Evidence(StrEnum):
    SUPPORTED = "supported"
    THIN = "thin"
    CONFLICTING = "conflicting"
    NONE = "none"


@dataclass(frozen=True)
class Citation:
    label: str
    node_id: uuid.UUID
    content: str
    feature_title: str
    sources: tuple[SourceRef, ...]
    #: Whether this claim sits in an open disagreement.
    disputed: bool


@dataclass(frozen=True)
class Answer:
    question: str
    answer: str
    citations: tuple[Citation, ...]
    evidence: Evidence


class _Raw(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer: str = Field(min_length=1)
    citations: list[str] = Field(default_factory=list)


def build_context(doc: ProductDocument) -> tuple[str, dict[str, Citation]]:
    """Label every claim the model may use and render them as context."""
    labels: dict[str, Citation] = {}
    lines: list[str] = [f"# {doc.name}", ""]
    if doc.description:
        lines += [f"(Described by the team, not a claim: {doc.description})", ""]

    def label(claim: Claim, disputed: bool) -> str:
        key = f"C{len(labels) + 1}"
        labels[key] = Citation(
            label=key,
            node_id=claim.node_id,
            content=claim.content,
            feature_title=claim.feature_title,
            sources=claim.sources,
            disputed=disputed,
        )
        status = "confirmed" if claim.status in RULED else "unreviewed"
        excerpts = "; ".join(f'"{s.excerpt}" ({s.url})' for s in claim.sources)
        return f"[{key}] ({claim.type.value}, {status}) {claim.content} — source: {excerpts}"

    for section in doc.features:
        if not section.claims and not section.disagreements:
            continue
        lines += [f"## Feature: {section.title}", ""]
        lines += [label(claim, disputed=False) for claim in section.claims]
        for number, disagreement in enumerate(section.disagreements, start=1):
            lines += [
                "",
                f"Disagreement {number} — the sources disagree; nothing is settled:",
                label(disagreement.left, disputed=True),
                label(disagreement.right, disputed=True),
            ]
        lines.append("")
    return "\n".join(lines).rstrip() + "\n", labels


async def ask(question: str, doc: ProductDocument, call: AnswerCall) -> Answer:
    question = question.strip()
    if not question:
        raise AnswerError("ask a question")
    if len(question) > MAX_QUESTION:
        raise AnswerError(f"a question is at most {MAX_QUESTION} characters")

    context, labels = build_context(doc)
    if not labels:
        return Answer(question=question, answer=_NO_CONTEXT, citations=(), evidence=Evidence.NONE)

    raw = _parse(await call(f"{context}\n# Question\n\n{question}\n"))
    unknown = [key for key in raw.citations if key not in labels]
    if unknown:
        raise AnswerError(f"the answer cited claims it was not shown: {', '.join(unknown)}")

    cited = tuple(labels[key] for key in dict.fromkeys(raw.citations))
    return Answer(question=question, answer=raw.answer, citations=cited, evidence=_evidence(cited))


def _parse(text: str) -> _Raw:
    body = text.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", body, re.DOTALL)
    if fenced:
        body = fenced.group(1)
    try:
        return _Raw.model_validate(json.loads(body))
    except (json.JSONDecodeError, ValidationError) as bad:
        raise AnswerError(f"the model's response was not a valid answer: {bad}") from None


def _evidence(cited: tuple[Citation, ...]) -> Evidence:
    if not cited:
        return Evidence.NONE
    if any(citation.disputed for citation in cited):
        return Evidence.CONFLICTING
    artifacts = {(s.source_type, s.external_id) for c in cited for s in c.sources}
    return Evidence.SUPPORTED if len(artifacts) >= 2 else Evidence.THIN


async def _deny_all(
    tool_name: str, tool_input: dict[str, Any], context: ToolPermissionContext
) -> PermissionResultDeny:
    """The permission gate, and the authority: Q&A needs no tool, so every tool
    -- named in the deny-list or not (`Task`, an MCP tool, one added to the SDK
    later) -- is refused. Same layering as `extraction.agent._agent_call`: the
    deny-list is the first layer, this is the one that cannot be bypassed."""
    return PermissionResultDeny(message=f"Q&A uses no tools; {tool_name} refused")


async def _stream(prompt: str) -> AsyncIterator[dict[str, Any]]:
    """The prompt as streaming input. Required, not stylistic: the SDK consults
    `can_use_tool` only in streaming mode, so a plain string prompt would
    silently bypass `_deny_all` (the defect `extraction.agent._as_stream`
    exists for)."""
    yield {
        "type": "user",
        "session_id": "",
        "message": {"role": "user", "content": prompt},
        "parent_tool_use_id": None,
    }


def model_call(model: str = DEFAULT_MODEL) -> AnswerCall:
    """The real call: Claude via the Agent SDK, one turn, every tool denied."""
    options = ClaudeAgentOptions(
        model=model,
        system_prompt=SYSTEM_PROMPT,
        can_use_tool=_deny_all,
        disallowed_tools=[
            "Bash",
            "Edit",
            "Write",
            "NotebookEdit",
            "Read",
            "Glob",
            "Grep",
            "WebFetch",
            "WebSearch",
            "TodoWrite",
            "Task",
        ],
        setting_sources=[],
        max_turns=1,
    )

    async def call(prompt: str) -> str:
        text = ""
        async for message in query(prompt=_stream(prompt), options=options):
            if isinstance(message, AssistantMessage):
                text = "".join(b.text for b in message.content if isinstance(b, TextBlock)) or text
        return text

    return call
