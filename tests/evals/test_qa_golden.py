"""Tier-1 Q&A eval over recorded answers (`writing-evals`).

Grades `tests/evals/qa_golden/answers.json` against the floors in
`questions.yaml`, which were written before any answer was recorded. Offline:
no model, no cost. Skips until `scripts/record_qa_golden.py` has run. At N=11
this is a smoke test with named failures, not a pass-rate metric.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

QA = Path(__file__).parent / "qa_golden"
QUESTIONS = yaml.safe_load((QA / "questions.yaml").read_text())["questions"]
_ANSWERS = QA / "answers.json"


def _answer(question_id: str) -> dict[str, Any]:
    if not _ANSWERS.exists():
        pytest.skip("no recorded answers.json yet")
    answers: dict[str, dict[str, Any]] = {
        a["id"]: a for a in json.loads(_ANSWERS.read_text())["answers"]
    }
    return answers[question_id]


@pytest.mark.parametrize("item", QUESTIONS, ids=[q["id"] for q in QUESTIONS])
def test_answer_meets_its_floor(item: dict[str, Any]) -> None:
    answer = _answer(item["id"])
    assert "refused" not in answer, f"the gate refused the answer: {answer.get('refused')}"
    citations = answer["citations"]

    if item["expect"] == "none":
        assert citations == [], "the claims do not answer this; nothing may be cited"
        assert answer["evidence"] == "none"
    elif item["expect"] == "conflict":
        assert answer["evidence"] == "conflicting"
    else:
        assert citations, "an answerable question got no citation"
        assert answer["evidence"] != "none"
        keyword = item["keyword"].lower()
        assert any(keyword in c["content"].lower() for c in citations), (
            f"no cited claim mentions {keyword!r}"
        )
