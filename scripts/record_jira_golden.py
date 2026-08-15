"""(Re-)record the Jira golden-set fixtures under `tests/evals/golden_set/`.

Two files per issue, and the split matters:

* `raw.json` -- what the connector actually fetched. It is the corpus every
  provenance check is run against, so it must be recorded from the live site and
  never hand-edited. Edit it and the provenance check starts grading excerpts
  against fiction.
* `extraction.json` -- what the agent actually produced. Recorded here so the
  deterministic tier (`tests/evals/test_golden_set.py`) can be re-run any number
  of times, on any machine, with no API key and no token cost (Phase0 Sec5).

Nothing is written to the database. Extraction returns its result before any
event is appended, and this script simply never appends one -- so re-recording
cannot disturb the live event log or the workspace a reviewer is looking at.

Re-record when the extraction prompt or its tools change, and review the new
`extraction.json` **in the same diff** as the change that caused it (the
`writing-evals` skill: expectations are versioned alongside the code they grade).
Re-recording after a change and committing it without reading the diff is how an
eval harness quietly stops being one.

Usage:

    set -a && source .env && set +a
    uv run python scripts/record_jira_golden.py                # all of them
    uv run python scripts/record_jira_golden.py SCRUM-8        # just one
    uv run python scripts/record_jira_golden.py --corpus-only SCRUM-6
    uv run python scripts/record_jira_golden.py --cross        # the cross-source one

`--corpus-only` records `raw.json` and no extraction -- for an issue that is part
of the corpus (an epic other issues quote) but is not itself graded.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import sys
import uuid
from pathlib import Path
from typing import Any

from atlas.config import JiraSettings
from atlas.extraction.agent import extract_from_jira_issue
from atlas.ingestion.jira import JiraClient, JiraIssue
from atlas.models.schema import Node

GOLDEN_ROOT = Path(__file__).resolve().parents[1] / "tests" / "evals" / "golden_set"

#: The seeded `maxdepth` epic (see docs/research/2026-08-13-jira-live-run.md).
#: SCRUM-6 is the epic itself: corpus only, because nothing is ingested from it
#: directly -- but a child's excerpt may legitimately quote it, and an excerpt
#: whose source was never recorded cannot be verified either way.
DEFAULT_KEYS = ("SCRUM-7", "SCRUM-8", "SCRUM-9", "SCRUM-10")
CORPUS_ONLY_KEYS = ("SCRUM-6",)

#: The cross-source fixture: which Jira issue is ingested into a scope that
#: already holds the claims from which recorded GitHub extraction.
#:
#: Cross-source `conflicts_with` is the most valuable thing this product does and
#: was, until this fixture, the least tested -- the five conflicts found live on
#: 2026-08-13 were judged by eye and never recorded
#: (`docs/research/2026-08-13-jira-live-run.md`). The pairing is not arbitrary:
#: ripgrep PR #111 ("Max depth option") and the seeded SCRUM epic describe the
#: same feature, which is exactly the situation a conflict can arise in.
#:
#: The known nodes are read from `pr-111/extraction.json` -- **real recorded
#: agent output**, not a hand-built set. A hand-built one would let the fixture
#: pose a conflict the live path would never see.
CROSS_SOURCE = ("SCRUM-8", "pr-111")


def _json_safe(value: Any) -> Any:
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {f.name: _json_safe(getattr(value, f.name)) for f in dataclasses.fields(value)}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def raw_document(issue: JiraIssue, site: str) -> dict[str, Any]:
    """The recorded corpus for one issue.

    Deliberately the whole DTO rather than a hand-picked subset: the fields the
    agent is shown may grow, and a corpus narrower than what the agent read would
    make a perfectly good excerpt look unprovenanced.
    """
    return {"issue_key": issue.key, "site": site, "issue": _json_safe(issue)}


def _known_nodes(golden: str) -> list[Node]:
    """The claims a recorded GitHub extraction produced, re-validated.

    Through `Node.model_validate` on purpose: the fixture is fed to the agent as
    context and its ids become the only ones an edge may point at, so it has to
    be the same shape the live path hands over.
    """
    data = json.loads((GOLDEN_ROOT / golden / "extraction.json").read_text())
    return [Node.model_validate(node) for node in data["nodes"]]


async def record_cross_source(key: str, from_golden: str) -> None:
    """Record one Jira ingestion into a scope that already holds GitHub claims.

    This is the only recording that exercises the cross-source path end to end:
    the known-node block is built, the agent is offered real ids, and whatever it
    emits -- conflict or no conflict -- is what gets written down. Nothing here
    steers it toward finding one; the rubric grades what it actually did.
    """
    settings = JiraSettings.from_env()
    directory = GOLDEN_ROOT / f"cross-{key}"
    directory.mkdir(parents=True, exist_ok=True)
    known = _known_nodes(from_golden)

    with JiraClient(
        base_url=settings.base_url, email=settings.email, api_token=settings.api_token
    ) as client:
        issue = client.fetch_issue(key)
        _, result = await extract_from_jira_issue(
            client=client,
            key=key,
            workspace_id=uuid.UUID(int=0),
            feature_scope_id=uuid.uuid4(),
            known_nodes=known,
        )

    offered = {node.id for node in known}
    crossing = [edge for edge in result.edges if edge.to_node_id in offered]
    (directory / "raw.json").write_text(
        json.dumps(raw_document(issue, settings.base_url), indent=1, sort_keys=True) + "\n"
    )
    (directory / "known.json").write_text(
        json.dumps(
            {
                "from": from_golden,
                "nodes": [json.loads(node.model_dump_json()) for node in known],
            },
            indent=1,
        )
        + "\n"
    )
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
    print(
        f"cross-{key}: {len(result.nodes)} nodes, {len(result.edges)} edges, "
        f"{len(crossing)} pointing at {from_golden}"
    )


async def record(key: str, *, corpus_only: bool) -> None:
    settings = JiraSettings.from_env()
    directory = GOLDEN_ROOT / f"jira-{key}"
    directory.mkdir(parents=True, exist_ok=True)

    with JiraClient(
        base_url=settings.base_url, email=settings.email, api_token=settings.api_token
    ) as client:
        issue = client.fetch_issue(key)
        (directory / "raw.json").write_text(
            json.dumps(raw_document(issue, settings.base_url), indent=1, sort_keys=True) + "\n"
        )
        print(
            f"{key}: recorded raw.json ({len(issue.description)} chars, "
            f"{len(issue.comments)} comments)"
        )
        if corpus_only:
            return

        # A fresh scope id per recording: these ids exist only inside the fixture
        # and must not collide with a real feature scope in the live database.
        _, result = await extract_from_jira_issue(
            client=client,
            key=key,
            workspace_id=uuid.UUID(int=0),
            feature_scope_id=uuid.uuid4(),
        )

    payload = {
        "nodes": [json.loads(node.model_dump_json()) for node in result.nodes],
        "edges": [json.loads(edge.model_dump_json()) for edge in result.edges],
    }
    (directory / "extraction.json").write_text(json.dumps(payload, indent=1) + "\n")
    print(f"{key}: recorded extraction.json ({len(result.nodes)} nodes, {len(result.edges)} edges)")


async def main(argv: list[str]) -> int:
    corpus_only = "--corpus-only" in argv
    keys = tuple(arg for arg in argv if not arg.startswith("-"))
    if "--cross" in argv:
        key, from_golden = CROSS_SOURCE
        await record_cross_source(keys[0] if keys else key, from_golden)
        return 0
    if not keys:
        for key in CORPUS_ONLY_KEYS:
            await record(key, corpus_only=True)
        keys = DEFAULT_KEYS
        for key in keys:
            await record(key, corpus_only=corpus_only)
        await record_cross_source(*CROSS_SOURCE)
        return 0
    for key in keys:
        await record(key, corpus_only=corpus_only)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1:])))
