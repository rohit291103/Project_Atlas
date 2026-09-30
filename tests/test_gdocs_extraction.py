"""Tests for Google Docs extraction wiring (Phase 3).

The model is stubbed. What is pinned: the doc's text reaches the agent
verbatim, the doc prompt shares every rule with the other sources except the
one about following references (a doc has no tools to follow them with), the
GitHub prompt is unchanged by this, and an unchanged doc is never re-extracted.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import pytest

from atlas.extraction import prompts
from atlas.extraction.agent import ExtractionResult, content_hash, extract_from_gdoc
from atlas.extraction.tools import EMIT_TOOL, build_gdoc_extraction_tools
from atlas.ingestion.gdocs import GoogleDoc
from atlas.models.schema import SourceType

DOC = GoogleDoc(
    id="1AbCdEfGhIjKlMnOpQrStUvWxYz0123",
    title="Checkout interviews",
    url="https://docs.google.com/document/d/1AbCdEfGhIjKlMnOpQrStUvWxYz0123/edit",
    text="Customer said: “the export is too slow”.\n",
    revision_id="rev-7",
)


class _Client:
    def fetch_document(self, doc_id: str) -> GoogleDoc:
        return DOC


def test_the_seed_prompt_carries_the_doc_text_verbatim() -> None:
    seed = prompts.build_gdoc_seed_prompt(DOC)

    assert DOC.text in seed
    assert DOC.url in seed and DOC.title in seed
    # The agent writes each source_ref itself; it is told the exact values.
    assert f'source_type "gdoc", external_id "{DOC.id}"' in seed


def test_the_doc_prompt_keeps_every_shared_rule_but_offers_no_tools() -> None:
    doc_prompt = prompts.GDOC_SYSTEM_PROMPT

    assert "PROVENANCE IS MANDATORY" in doc_prompt
    assert "ONE CLAIM, ONE NODE" in doc_prompt
    assert "fetch_linked_issue" not in doc_prompt
    assert "no tools" in doc_prompt.lower()


def test_adding_the_doc_source_leaves_the_github_prompt_untouched() -> None:
    """The Phase 0 eval evidence was gathered against this exact text."""
    assert (
        prompts._build_system_prompt(
            reads="a GitHub pull request",
            references="a linked \
issue, a commit sha, or another PR",
            tool_list="`fetch_linked_issue`, `fetch_commit`, `search_repo`",
        )
        == prompts.SYSTEM_PROMPT
    )
    assert "Follow references, don't fabricate them" in prompts.SYSTEM_PROMPT


def test_a_doc_run_is_given_only_the_emit_tool() -> None:
    assert [t.name for t in build_gdoc_extraction_tools()] == [EMIT_TOOL]


def test_an_extracted_doc_run_names_the_doc_with_its_hash(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    async def fake(**kwargs: Any) -> ExtractionResult:
        seen.update(kwargs)
        return ExtractionResult()

    monkeypatch.setattr("atlas.extraction.agent.run_extraction", fake)

    run, _ = asyncio.run(
        extract_from_gdoc(
            client=_Client(),  # type: ignore[arg-type]
            doc_id=DOC.id,
            workspace_id=uuid.uuid4(),
            feature_scope_id=uuid.uuid4(),
        )
    )

    assert run.source_type is SourceType.GDOC
    assert (run.external_id, run.url, run.title) == (DOC.id, DOC.url, DOC.title)
    assert run.content_hash == content_hash(prompts.build_gdoc_seed_prompt(DOC))
    assert DOC.text in seen["seed_prompt"]


def test_an_unchanged_doc_is_not_re_extracted(monkeypatch: pytest.MonkeyPatch) -> None:
    async def must_not_run(**kwargs: Any) -> ExtractionResult:
        raise AssertionError("the agent ran over an unchanged doc")

    monkeypatch.setattr("atlas.extraction.agent.run_extraction", must_not_run)

    _, result = asyncio.run(
        extract_from_gdoc(
            client=_Client(),  # type: ignore[arg-type]
            doc_id=DOC.id,
            workspace_id=uuid.uuid4(),
            feature_scope_id=uuid.uuid4(),
            previous_hash=content_hash(prompts.build_gdoc_seed_prompt(DOC)),
        )
    )

    assert result.unchanged
