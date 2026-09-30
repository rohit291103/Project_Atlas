"""Record a doc-shaped golden fixture for Google Docs extraction (Phase 3).

Evaluates **extraction over a document** -- the doc prompt (rule 3 swapped),
verbatim excerpts, `gdoc` citations -- without a Google account: a stub client
hands `extract_from_gdoc` the document text, so the path from `fetch_document`
onward is the production one. The connector's own HTTP, JWT and flattening
are covered by `tests/test_gdocs.py`.

The text must be a real document, not one written for the test
(`writing-evals`: team-authored fixtures inflate scores).

    uv run python -m scripts.record_gdoc_golden gdoc-rfc-1869 <path-to-text> <title> <url>
"""

from __future__ import annotations

import asyncio
import json
import sys
import uuid
from pathlib import Path

from atlas.extraction.agent import extract_from_gdoc
from atlas.ingestion.gdocs import GoogleDoc

GOLDEN = Path(__file__).resolve().parents[1] / "tests" / "evals" / "golden_set"


class _Stub:
    def __init__(self, doc: GoogleDoc) -> None:
        self.doc = doc

    def fetch_document(self, doc_id: str) -> GoogleDoc:
        return self.doc


async def record(name: str, text_path: Path, title: str, url: str) -> Path:
    directory = GOLDEN / name
    directory.mkdir(parents=True, exist_ok=True)
    doc = GoogleDoc(id=name, title=title, url=url, text=text_path.read_text(), revision_id=None)
    _, result = await extract_from_gdoc(
        client=_Stub(doc),  # type: ignore[arg-type]
        doc_id=doc.id,
        workspace_id=uuid.UUID(int=0),
        feature_scope_id=uuid.uuid4(),
    )
    (directory / "raw.json").write_text(
        json.dumps({"id": doc.id, "title": doc.title, "url": doc.url, "text": doc.text}, indent=1)
        + "\n"
    )
    (directory / "extraction.json").write_text(
        json.dumps(
            {
                "nodes": [json.loads(n.model_dump_json()) for n in result.nodes],
                "edges": [json.loads(e.model_dump_json()) for e in result.edges],
            },
            indent=1,
        )
        + "\n"
    )
    return directory


def main(argv: list[str]) -> int:
    if len(argv) != 4:
        print(__doc__)
        return 2
    print(asyncio.run(record(argv[0], Path(argv[1]), argv[2], argv[3])))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
