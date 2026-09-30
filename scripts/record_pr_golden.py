"""Record one GitHub PR into the golden set: `raw.json` + a live `extraction.json`.

The PR-side counterpart of `record_jira_golden.py`, written 2026-09-30 to add a
fifth ripgrep feature for the Phase 2B proof (roadmap v2 needs N >= 5; the
Phase 0 set has four). Same shape as the four already recorded:

- `raw.json` holds the PR's title, body and conversation comments plus the
  issues its body closes -- the corpus a provenance excerpt may come from. The
  **commits are deliberately not recorded**: they are what was actually built,
  i.e. the answer the proof grades against.
- `extraction.json` is one real, unedited agent run over that PR.

Read-only: GitHub GETs through `GitHubClient`, and the agent under the same
permission gate as production. Writes only inside `tests/evals/golden_set/`.

    uv run python -m scripts.record_pr_golden BurntSushi/ripgrep 2957
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import uuid
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from atlas.extraction.agent import extract_from_pull_request
from atlas.ingestion.github import GitHubClient

GOLDEN_ROOT = Path(__file__).resolve().parents[1] / "tests" / "evals" / "golden_set"
_CLOSES = re.compile(r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+#(\d+)", re.IGNORECASE)


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


async def record(repo_full: str, number: int) -> Path:
    owner, repo = repo_full.split("/", 1)
    directory = GOLDEN_ROOT / f"pr-{number}"
    directory.mkdir(parents=True, exist_ok=True)

    with GitHubClient(os.environ["GITHUB_TOKEN"]) as client:
        pr = client.fetch_pull_request(owner, repo, number)
        issues = [
            client.fetch_issue(owner, repo, int(linked))
            for linked in dict.fromkeys(_CLOSES.findall(pr.body or ""))
        ]
        _, result = await extract_from_pull_request(
            client=client,
            owner=owner,
            repo=repo,
            number=number,
            workspace_id=uuid.UUID(int=0),
            feature_scope_id=uuid.uuid4(),
        )

    raw = {
        "repo": repo_full,
        "pr_number": number,
        "pull_request": {
            "number": str(pr.number),
            "title": pr.title,
            "body": pr.body,
            "state": pr.state,
            "url": pr.url,
            "author": pr.author,
            "created_at": _iso(pr.created_at),
            "merged_at": _iso(pr.merged_at),
            "comments": [
                {
                    "id": comment.id,
                    "author": comment.author,
                    "body": comment.body,
                    "url": comment.url,
                    "created_at": _iso(comment.created_at),
                }
                for comment in pr.comments
            ],
        },
        "linked_issues": [
            {
                "number": issue.number,
                "title": issue.title,
                "body": issue.body,
                "state": issue.state,
                "url": issue.url,
                "author": issue.author,
                "created_at": _iso(issue.created_at),
            }
            for issue in issues
        ],
        "commits": [],
    }
    (directory / "raw.json").write_text(json.dumps(raw, indent=1, sort_keys=True) + "\n")
    (directory / "extraction.json").write_text(
        json.dumps(
            {
                "nodes": [json.loads(node.model_dump_json()) for node in result.nodes],
                "edges": [json.loads(edge.model_dump_json()) for edge in result.edges],
            },
            indent=1,
        )
        + "\n"
    )
    return directory


def main(argv: list[str]) -> int:
    load_dotenv()
    if len(argv) != 2:
        print(__doc__)
        return 2
    directory = asyncio.run(record(argv[0], int(argv[1])))
    print(f"recorded {directory}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
