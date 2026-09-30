"""Record live answers for the Q&A golden set (`tests/evals/qa_golden/`).

Each question is asked through `atlas.qa.ask` -- the production path, gate and
all -- over a document assembled from real recorded extractions with every
claim treated as confirmed in memory (nothing is written to Atlas's log). The
answers are stored verbatim so `tests/evals/test_qa_golden.py` can grade them
offline, with no model and no cost, on every test run.

    uv run python -m scripts.record_qa_golden
"""

from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path
from typing import Any

import yaml

from atlas.assembly import ProductDocument, assemble
from atlas.models.schema import Edge, IngestionRunPayload, Node, NodeStatus, SourceType
from atlas.qa import DEFAULT_MODEL, AnswerError, ask, model_call
from atlas.storage.projections import FeatureScope, Product, Projection

EVALS = Path(__file__).resolve().parents[1] / "tests" / "evals"
GOLDEN = EVALS / "golden_set"
QA = EVALS / "qa_golden"


def _fixture(name: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    directory = GOLDEN / name
    extraction = json.loads((directory / "extraction.json").read_text())
    nodes, edges = list(extraction["nodes"]), list(extraction["edges"])
    known = directory / "known.json"
    if known.exists():  # a cross-source recording: the nodes it was offered
        nodes += json.loads(known.read_text())["nodes"]
    return nodes, edges


def document(name: str, fixtures: list[str]) -> ProductDocument:
    """All claims confirmed, in memory, in one feature of one product."""
    product_id, scope_id = uuid.uuid5(uuid.NAMESPACE_URL, name), uuid.uuid4()
    nodes: dict[uuid.UUID, Node] = {}
    edges: dict[uuid.UUID, Edge] = {}
    for fixture in fixtures:
        raw_nodes, raw_edges = _fixture(fixture)
        for raw in raw_nodes:
            node = Node.model_validate(raw).model_copy(
                update={"status": NodeStatus.CONFIRMED, "feature_scope_id": scope_id}
            )
            nodes[node.id] = node
        for raw in raw_edges:
            edge = Edge.model_validate(raw)
            edges[edge.id] = edge
    scope = FeatureScope(
        id=scope_id,
        title=name,
        runs=(
            IngestionRunPayload(
                feature_scope_id=scope_id,
                title=name,
                source_type=SourceType.GITHUB_PR,
                external_id=name,
                url="https://github.com/BurntSushi/ripgrep",
                product_id=product_id,
            ),
        ),
        product_id=product_id,
        description=None,
    )
    projection = Projection(
        nodes=nodes,
        edges=edges,
        feature_scopes={scope_id: scope},
        products={product_id: Product(id=product_id, name=name, description=None)},
    )
    return assemble(projection, product_id)


async def record() -> list[dict[str, Any]]:
    spec = yaml.safe_load((QA / "questions.yaml").read_text())
    docs = {name: document(name, fixtures) for name, fixtures in spec["documents"].items()}
    call = model_call()
    answers: list[dict[str, Any]] = []
    for item in spec["questions"]:
        try:
            answer = await ask(item["question"], docs[item["document"]], call)
            answers.append(
                {
                    "id": item["id"],
                    "answer": answer.answer,
                    "evidence": answer.evidence.value,
                    "citations": [
                        {"label": c.label, "content": c.content, "disputed": c.disputed}
                        for c in answer.citations
                    ],
                }
            )
        except AnswerError as refused:
            # A gate refusal is a result, and graded as a failure -- recorded,
            # not retried, so a flaky model cannot be re-rolled into a pass.
            answers.append({"id": item["id"], "refused": str(refused)})
    return answers


def main() -> int:
    answers = asyncio.run(record())
    (QA / "answers.json").write_text(
        json.dumps({"model": DEFAULT_MODEL, "answers": answers}, indent=1) + "\n"
    )
    print(f"recorded {len(answers)} answers")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
