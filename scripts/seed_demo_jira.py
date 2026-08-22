"""Create the demo product's Jira side: one epic and its children.

**This script writes to Jira. Atlas does not, and must not.** It lives in
`scripts/` rather than `src/atlas/` for exactly that reason — Engineering
Philosophy §1 is "read-only by default, no write-back to any source system,
ever", and that rule is about the *product*. Standing up a demo environment is
an operator task, the same category as `verify_rls.py`. Nothing importable from
`atlas.*` gains a write path because this file exists.

## Why this exists

The Phase 1 exit criterion is *a PM outside the build team, unassisted, under 20
minutes*. Staged against `ripgrep` — a Rust CLI tool whose PRs argue about
`--maxdepth` traversal semantics — that measurement would have told us whether a
non-engineer can follow a systems-programming thread, not whether Atlas helps
them (`docs/decisions/2026-08-19-product-orientation-rerun-safety-and-demo-data
.md` F3). ripgrep stays exactly where it belongs: the Phase 0 validation fixture
and the Phase 2 proof set. This replaces the *demo*.

## What it creates, and why this shape

The GitHub half is real and public: `plausible/analytics` PRs **#1364** (which
metric the main dashboard graph plots) and **#1574** (the graph's time detail).
Both are genuinely product-shaped — 49 and 22 *human* comments arguing about
UX tradeoffs, not CI noise — and web analytics is a domain any PM reads without
translation.

The Jira half is written here, in a PM's voice, as the tickets that would have
preceded those PRs. It is **authored demo data, not a reconstruction of
Plausible's real backlog** — nobody should read these as that company's
decisions.

Three of the acceptance criteria below **deliberately disagree with what the PRs
decided**:

* PM: conversion rate is selectable at launch.
  PR #1364: conversion and time-on-page excluded, "not well supported (at all)
  in the new timeseries interface".
* PM: a shared link reproduces the sender's view, interval included.
  PR #1574: interval held at the graph level rather than in the query object,
  deliberately, so it is not in the URL.
* PM: the graph stays on screen.
  PR #1364: deselecting the plotted stat hides the graph.

Those are the demo's whole point: two sources that each look reasonable alone
and cannot both be true. They are real disagreements with real public text, not
strawmen planted to make a screenshot.

## Usage

    set -a && source .env && set +a
    uv run python scripts/seed_demo_jira.py --dry-run   # print, write nothing
    uv run python scripts/seed_demo_jira.py

Idempotent by summary: an issue whose summary already exists in the project is
skipped, so a re-run repairs a partial seed instead of doubling it.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from base64 import b64encode
from dataclasses import dataclass, field
from typing import Any

PROJECT_KEY = "PA"
PROJECT_NAME = "Plausible Analytics"
LABEL = "graph-detail"


@dataclass(frozen=True)
class Ticket:
    """One Jira issue to create. `body` is plain text; blank lines split
    paragraphs and `- ` lines become bullets, which is all the ADF this needs."""

    summary: str
    issue_type: str
    body: str
    children: tuple[Ticket, ...] = field(default_factory=tuple)


EPIC = Ticket(
    summary="Make the dashboard graph answer more than one question",
    issue_type="Epic",
    body="""
Today the main graph on the dashboard plots one thing: unique visitors over time. It is the
first thing every visitor to the dashboard looks at, and it can only answer one question.

The questions people actually arrive with are broader. Did the traffic we got convert? Is our
bounce rate getting worse or is it just noise? Do we have a weekly pattern that a daily line
hides? Every one of those is already in the top stats row directly above the graph, and none of
them can be plotted.

Goal: a viewer can choose what the graph plots and at what time detail, without leaving the
dashboard and without waiting for a page load.

Out of scope for this epic: comparison against a previous period, and anything that changes what
we collect. This is about showing data we already have.""",
    children=(
        Ticket(
            summary="Choose which metric the main graph plots",
            issue_type="Task",
            body="""
As a site owner, I want to click a top stat and see it plotted on the main graph, so that I can
read the trend behind the number rather than just the number.

Acceptance criteria:

- The four primary top stats — unique visitors, pageviews, bounce rate and visit duration — can
  each be plotted.
- Conversion rate must be selectable at launch. Goal conversion is the metric our paying
  customers ask about most, and shipping a metric picker that cannot show it will read as an
  unfinished feature.
- Switching metric must not reload the page. The whole point is that the dashboard feels
  responsive enough to explore.

The selected metric should be obvious at a glance — a viewer should never have to guess which
number the line refers to.""",
        ),
        Ticket(
            summary="Change the graph's time detail",
            issue_type="Task",
            body="""
As a site owner, I want to switch the graph between daily, weekly and monthly detail, so that a
weekly pattern is visible instead of being buried in day-to-day noise.

This came from customers directly. Sites with a strong weekly rhythm — B2B tools, newsletters —
say the daily line is unreadable and they end up exporting to a spreadsheet to see the shape.

Acceptance criteria:

- Daily, weekly and monthly detail are available, with the sensible default chosen from the
  selected date range.
- A shared dashboard link must reproduce exactly what the sender saw, including the selected
  interval. Sharing a link is how these dashboards get discussed internally, and a link that
  silently reverts to a different view makes the conversation about the wrong chart.
- Changing the detail must not reset the metric the viewer has selected.""",
        ),
        Ticket(
            summary="The graph stays on screen",
            issue_type="Task",
            body="""
The graph is the anchor of the dashboard. Everything else on the page is read in relation to it.

Requirement: the graph must remain visible at all times, including when a viewer deselects the
stat currently being plotted. Emptying the main panel of the dashboard in response to a click on
a stat tile is disorienting — the viewer has to work out what they broke and how to undo it.

If nothing is selected, plot the default metric rather than showing nothing.""",
        ),
        Ticket(
            summary="Decided: the detail control sits in the top right of the graph",
            issue_type="Task",
            body="""
Decision, taken after looking at three options.

The graph detail control will be a dropdown in the upper right corner of the graph panel,
matching the dropdown people already use on the Top Sources panel.

We rejected a segmented control along the bottom of the graph — it competes with the x-axis
labels and does not survive narrow screens. We also rejected putting the control inside the date
picker, because the date range and the time detail are different questions and bundling them
made both harder to find in testing.

Consistency with a control the user has already learned elsewhere on the same page beats a
bespoke control that is marginally better in isolation.""",
        ),
        Ticket(
            summary="Do we need hourly detail for the realtime view?",
            issue_type="Task",
            body="""
Open question, not yet decided.

The realtime dashboard covers the last 30 minutes and the day view covers 24 hours, so there is
a gap: someone watching a launch wants hourly resolution over the last day or two, and neither
view gives it.

Unclear whether that is a real need or whether people asking for it are really asking for the
realtime view to hold a longer window. Needs a look at what people do immediately after they
open the realtime dashboard before we commit either way.""",
        ),
    ),
)


class Jira:
    """The four calls this script needs. Deliberately not `atlas.ingestion.jira`
    — that client is read-only by construction and it stays that way."""

    def __init__(self, base_url: str, email: str, token: str) -> None:
        self.base = base_url.rstrip("/")
        credentials = b64encode(f"{email}:{token}".encode()).decode()
        self.headers = {
            "Authorization": f"Basic {credentials}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def _call(self, method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
        request = urllib.request.Request(
            f"{self.base}{path}",
            method=method,
            headers=self.headers,
            data=None if payload is None else json.dumps(payload).encode(),
        )
        try:
            with urllib.request.urlopen(request) as response:
                raw = response.read()
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as error:
            detail = error.read().decode()[:600]
            raise SystemExit(f"Jira {method} {path} failed ({error.code}): {detail}") from error

    def account_id(self) -> str:
        return str(self._call("GET", "/rest/api/3/myself")["accountId"])

    def project_exists(self, key: str) -> bool:
        found = self._call("GET", "/rest/api/3/project/search?query=" + urllib.parse.quote(key))
        return any(project["key"] == key for project in found.get("values", []))

    def create_project(self, key: str, name: str, lead: str) -> None:
        self._call(
            "POST",
            "/rest/api/3/project",
            {
                "key": key,
                "name": name,
                "projectTypeKey": "software",
                # Team-managed ("simplified"), matching the existing SCRUM
                # project: `pipeline.py` finds an epic's children with
                # `parent = "KEY"`, which is the team-managed relationship.
                "projectTemplateKey": ("com.pyxis.greenhopper.jira:gh-simplified-agility-kanban"),
                "leadAccountId": lead,
                "description": (
                    "Demo environment for Project Atlas. Authored tickets, not a real backlog."
                ),
                "assigneeType": "PROJECT_LEAD",
            },
        )

    def existing_summaries(self, key: str) -> set[str]:
        jql = urllib.parse.quote(f"project = {key}")
        found = self._call("GET", f"/rest/api/3/search/jql?jql={jql}&fields=summary&maxResults=100")
        return {issue["fields"]["summary"] for issue in found.get("issues", [])}

    def create_issue(self, key: str, ticket: Ticket, parent_key: str | None, label: str) -> str:
        fields: dict[str, Any] = {
            "project": {"key": key},
            "summary": ticket.summary,
            "issuetype": {"name": ticket.issue_type},
            "description": to_adf(ticket.body),
            "labels": [label],
        }
        if parent_key:
            fields["parent"] = {"key": parent_key}
        return str(self._call("POST", "/rest/api/3/issue", {"fields": fields})["key"])


def to_adf(text: str) -> dict[str, Any]:
    """Plain text to Atlassian Document Format: blank-line paragraphs, `- `
    bullets. Only what these descriptions actually use — a general Markdown
    converter here would be a library nobody asked for."""
    content: list[dict[str, Any]] = []
    for block in text.strip().split("\n\n"):
        raw = [line.strip() for line in block.strip().split("\n") if line.strip()]
        # Source lines are hard-wrapped to the repo's 100 columns, so a bullet
        # can span several of them: a line starting with "- " opens a bullet and
        # anything after it continues the one above.
        lines: list[str] = []
        for line in raw:
            if line.startswith("- ") or not lines:
                lines.append(line)
            else:
                lines[-1] = f"{lines[-1]} {line}"
        if all(line.startswith("- ") for line in lines):
            content.append(
                {
                    "type": "bulletList",
                    "content": [
                        {
                            "type": "listItem",
                            "content": [
                                {
                                    "type": "paragraph",
                                    "content": [{"type": "text", "text": line[2:]}],
                                }
                            ],
                        }
                        for line in lines
                    ],
                }
            )
        else:
            content.append(
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": " ".join(lines)}],
                }
            )
    return {"type": "doc", "version": 1, "content": content}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="print, write nothing")
    parser.add_argument("--project", default=PROJECT_KEY)
    args = parser.parse_args()

    # Before the credential check, so `--dry-run` reviews the content on any
    # machine — the point of it is to read what would be written.
    if args.dry_run:
        print(f"would create project {args.project} ({PROJECT_NAME}) and:")
        print(f"  [{EPIC.issue_type}] {EPIC.summary}")
        for child in EPIC.children:
            print(f"    [{child.issue_type}] {child.summary}")
        return 0

    missing = [
        name
        for name in ("JIRA_BASE_URL", "JIRA_EMAIL", "JIRA_API_TOKEN")
        if not os.environ.get(name)
    ]
    if missing:
        raise SystemExit(f"missing environment: {', '.join(missing)} (see .env.example)")

    jira = Jira(os.environ["JIRA_BASE_URL"], os.environ["JIRA_EMAIL"], os.environ["JIRA_API_TOKEN"])

    if jira.project_exists(args.project):
        print(f"project {args.project} already exists — reusing it")
    else:
        jira.create_project(args.project, PROJECT_NAME, jira.account_id())
        print(f"created project {args.project} ({PROJECT_NAME})")

    already = jira.existing_summaries(args.project)
    if EPIC.summary in already:
        print(f"epic already present, nothing to do: {EPIC.summary!r}")
        return 0

    epic_key = jira.create_issue(args.project, EPIC, None, LABEL)
    print(f"  {epic_key}  [{EPIC.issue_type}] {EPIC.summary}")
    for child in EPIC.children:
        if child.summary in already:
            print(f"  ---  skipped (exists): {child.summary}")
            continue
        child_key = jira.create_issue(args.project, child, epic_key, LABEL)
        print(f"  {child_key}  [{child.issue_type}] {child.summary}")

    print(f"\nEpic: {os.environ['JIRA_BASE_URL'].rstrip('/')}/browse/{epic_key}")
    print(f"Ingest it in Atlas as target kind 'jira_epic', target {epic_key}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
