"""Tests for `qa.py` -- contextual Q&A with citations (Phase 3).

The model is stubbed: these pin the *gate* around it, which is where the
product's guarantees live. An answer may cite only claims it was shown; the
evidence label is computed from the cited claims, never taken from the model;
and a product with nothing confirmed gets no model call at all.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Coroutine
from typing import Any

import pytest

from atlas.assembly import assemble
from atlas.models.schema import NodeStatus, NodeType, SourceType
from atlas.qa import Answer, AnswerError, Evidence, ask, build_context
from tests.test_assembly import PRODUCT_ID, conflict, make_node, make_projection


class _Call:
    """A stand-in model that returns `payload` and records every prompt."""

    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload
        self.prompts: list[str] = []

    async def __call__(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return json.dumps(self.payload)


def _call(payload: dict[str, object]) -> _Call:
    return _Call(payload)


def _run(coro: Coroutine[Any, Any, Answer]) -> Answer:
    return asyncio.run(coro)


def test_the_context_labels_every_claim_with_its_status_and_excerpt() -> None:
    node = make_node(content="Plot visitors", excerpt="plot the visitors graph")

    context, labels = build_context(assemble(make_projection([node]), PRODUCT_ID))

    assert "[C1]" in context and "Plot visitors" in context
    assert "plot the visitors graph" in context
    assert labels["C1"].node_id == node.id


def test_unreviewed_claims_are_not_given_to_the_model() -> None:
    draft = make_node(content="DRAFT ONLY", status=NodeStatus.UNCONFIRMED)
    ruled = make_node(content="Confirmed")

    context, _ = build_context(assemble(make_projection([draft, ruled]), PRODUCT_ID))

    assert "DRAFT ONLY" not in context


def test_an_answer_carries_the_cited_claims_and_their_sources() -> None:
    node = make_node(content="Plot visitors")
    call = _call({"answer": "It plots visitors [C1].", "citations": ["C1"]})

    answer = _run(ask("What does it plot?", assemble(make_projection([node]), PRODUCT_ID), call))

    assert answer.answer == "It plots visitors [C1]."
    (cited,) = answer.citations
    assert cited.node_id == node.id
    assert cited.sources[0].url == "https://github.com/acme/repo/pull/42"


def test_a_citation_to_a_claim_that_was_not_shown_is_refused() -> None:
    """The Q&A equivalent of a hallucinated SourceRef: Critical tier."""
    node = make_node()
    call = _call({"answer": "Per [C7].", "citations": ["C7"]})

    with pytest.raises(AnswerError, match="C7"):
        _run(ask("?", assemble(make_projection([node]), PRODUCT_ID), call))


def test_a_malformed_response_is_refused() -> None:
    async def call(prompt: str) -> str:
        return "not json at all"

    with pytest.raises(AnswerError):
        _run(ask("?", assemble(make_projection([make_node()]), PRODUCT_ID), call))


def test_an_answer_wrapped_in_a_code_fence_is_accepted() -> None:
    async def call(prompt: str) -> str:
        return '```json\n{"answer": "Yes [C1].", "citations": ["C1"]}\n```'

    answer = _run(ask("?", assemble(make_projection([make_node()]), PRODUCT_ID), call))

    assert answer.answer == "Yes [C1]."


def test_evidence_is_thin_when_one_source_backs_the_answer() -> None:
    call = _call({"answer": "Yes [C1].", "citations": ["C1"]})

    answer = _run(ask("?", assemble(make_projection([make_node()]), PRODUCT_ID), call))

    assert answer.evidence is Evidence.THIN


def test_evidence_is_supported_when_independent_sources_agree() -> None:
    node = make_node(
        sources=[(SourceType.GITHUB_PR, "acme/web#1"), (SourceType.JIRA_TICKET, "PA-1")]
    )
    call = _call({"answer": "Yes [C1].", "citations": ["C1"]})

    answer = _run(ask("?", assemble(make_projection([node]), PRODUCT_ID), call))

    assert answer.evidence is Evidence.SUPPORTED


def test_evidence_is_conflicting_when_a_cited_claim_is_disputed() -> None:
    """Confidence-aware, not asserting: a disputed claim is never 'supported'."""
    left = make_node(content="Ships at launch")
    right = make_node(content="Deferred")
    doc = assemble(make_projection([left, right], edges=[conflict(left, right)]), PRODUCT_ID)
    context, labels = build_context(doc)
    label = next(key for key, claim in labels.items() if claim.node_id == left.id)
    call = _call({"answer": f"At launch [{label}].", "citations": [label]})

    answer = _run(ask("When?", doc, call))

    assert answer.evidence is Evidence.CONFLICTING
    assert "disagree" in context.lower()


def test_an_answer_citing_nothing_has_no_evidence() -> None:
    call = _call({"answer": "The confirmed claims do not say.", "citations": []})

    answer = _run(ask("?", assemble(make_projection([make_node()]), PRODUCT_ID), call))

    assert answer.evidence is Evidence.NONE


def test_nothing_confirmed_means_no_model_call() -> None:
    draft = make_node(status=NodeStatus.UNCONFIRMED)

    async def call(prompt: str) -> str:
        raise AssertionError("the model was called with no confirmed context")

    answer = _run(ask("?", assemble(make_projection([draft]), PRODUCT_ID), call))

    assert answer.evidence is Evidence.NONE
    assert answer.citations == ()


def test_the_question_is_in_the_prompt_after_the_context() -> None:
    call = _call({"answer": "x", "citations": []})
    node = make_node(node_type=NodeType.CONSTRAINT, content="No cookies")

    _run(ask("Can we use cookies?", assemble(make_projection([node]), PRODUCT_ID), call))

    (prompt,) = call.prompts
    assert prompt.index("No cookies") < prompt.index("Can we use cookies?")


def test_a_blank_question_is_refused() -> None:
    with pytest.raises(AnswerError):
        _run(ask("   ", assemble(make_projection([make_node()]), PRODUCT_ID), _call({})))


# --- the model call's tool surface (backend review 2026-09-28) -----------------


def test_the_qa_gate_denies_every_tool() -> None:
    """Q&A needs no tools, so the gate is the authority and it denies all of
    them -- including ones the deny-list does not name, such as `Task`."""
    from atlas.qa import _deny_all

    async def run() -> list[str]:
        return [
            str((await _deny_all(name, {}, None)).behavior)  # type: ignore[arg-type]
            for name in ("Task", "Bash", "WebFetch", "mcp__anything__at_all")
        ]

    assert asyncio.run(run()) == ["deny"] * 4


def test_the_model_call_streams_its_prompt_so_the_gate_is_consulted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A string prompt silently bypasses `can_use_tool` (see test_extraction's
    streaming-seam test); the call must hand `query` a stream, with the gate set."""
    from atlas import qa

    seen: dict[str, Any] = {}

    async def fake_query(*, prompt: Any, options: Any) -> Any:
        seen["prompt"] = prompt
        seen["options"] = options
        if False:
            yield None

    monkeypatch.setattr(qa, "query", fake_query)

    async def run() -> str:
        return await qa.model_call()("hello")

    asyncio.run(run())

    assert not isinstance(seen["prompt"], str)
    assert seen["options"].can_use_tool is qa._deny_all
