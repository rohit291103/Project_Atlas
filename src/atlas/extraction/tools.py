"""Claude Agent SDK tools for the extraction agent (Phase0_Architecture.md Sec2).

Three read-only tools wrap `ingestion.github.GitHubClient` so the agent can
follow references it finds in a PR -- `fetch_linked_issue`, `fetch_commit`,
`search_repo` -- plus `emit_extraction`, the forced final tool the agent calls
to hand back its result. All four are read-only: the fetch tools only ever GET
(the connector guarantees it), and `emit_extraction` writes nothing -- it just
carries the payload, which `agent.build_result` captures from the transcript and
validates.

Tool handlers return the MCP result shape `{"content": [{"type": "text", ...}]}`.
On a GitHub error they return `is_error` rather than raising, so the agent sees
the failure and can adapt instead of the run crashing.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
from claude_agent_sdk import SdkMcpTool, tool

from atlas.ingestion.github import Commit, GitHubClient, GitHubError, Issue
from atlas.ingestion.jira import JiraClient, JiraError, JiraIssue

EMIT_TOOL = "emit_extraction"

# Failures the fetch tools surface to the agent (as is_error) instead of raising:
# a connector's own errors *and* httpx transport errors (connect/read timeouts,
# resets), so a network blip mid-run doesn't crash the whole extraction.
_FETCH_ERRORS = (GitHubError, JiraError, httpx.HTTPError)

# Hint schema for emit_extraction. The authoritative contract is
# `agent.RawExtraction`; this mirrors its shape for the agent's benefit, and any
# drift is caught by the validation gate, which is the real check.
_EMIT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "nodes": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "ref": {"type": "string", "description": "local id, e.g. 'n1'"},
                    "type": {"type": "string"},
                    "content": {"type": "string"},
                    "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
                    "source_refs": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "source_type": {"type": "string"},
                                "external_id": {"type": "string"},
                                "url": {"type": "string"},
                                "excerpt": {
                                    "type": "string",
                                    "description": "verbatim span from the source",
                                },
                            },
                            "required": ["source_type", "external_id", "url", "excerpt"],
                        },
                    },
                },
                "required": ["ref", "type", "content", "confidence", "source_refs"],
            },
        },
        "edges": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "from_ref": {"type": "string"},
                    "to_ref": {"type": "string"},
                    "relation_type": {"type": "string"},
                    "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
                },
                "required": ["from_ref", "to_ref", "relation_type", "confidence"],
            },
        },
    },
    "required": ["nodes", "edges"],
}


def _ok(text: str) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": text}]}


def _error(text: str) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": text}], "is_error": True}


def format_issue(issue: Issue) -> str:
    return (
        f"Issue #{issue.number} [{issue.state}] by {issue.author or 'unknown'}\n"
        f"URL: {issue.url}\n"
        f"Title: {issue.title}\n\n"
        f"{issue.body or '(no description)'}"
    )


def format_commit(commit: Commit) -> str:
    return (
        f"Commit {commit.sha} by {commit.author or 'unknown'}\n"
        f"URL: {commit.url}\n\n"
        f"{commit.message}"
    )


def format_search(results: tuple[Issue, ...]) -> str:
    if not results:
        return "No matching issues or pull requests."
    lines = [f"- #{issue.number} [{issue.state}] {issue.title} ({issue.url})" for issue in results]
    return "\n".join(lines)


def format_jira_issue(issue: JiraIssue) -> str:
    lines = [
        f"Issue {issue.key} [{issue.status}] ({issue.issue_type}) by {issue.reporter or 'unknown'}",
        f"URL: {issue.url}",
        f"Summary: {issue.summary}",
        "",
        issue.description or "(no description)",
    ]
    if issue.comments:
        lines.append("")
        lines += [f"- [{comment.author or 'unknown'}] {comment.body}" for comment in issue.comments]
    return "\n".join(lines)


def format_jira_search(results: tuple[JiraIssue, ...]) -> str:
    if not results:
        return "No matching issues."
    return "\n".join(
        f"- {issue.key} [{issue.status}] {issue.summary} ({issue.url})" for issue in results
    )


def _emit_tool() -> SdkMcpTool[Any]:
    """The forced final tool, shared by every source's tool set -- the emit
    contract is a property of the extraction gate, not of the connector."""

    @tool(EMIT_TOOL, "Emit the final extracted nodes and edges. Call exactly once.", _EMIT_SCHEMA)
    async def emit_extraction(args: dict[str, Any]) -> dict[str, Any]:
        # The payload is captured from the transcript and validated in
        # agent.build_result; this handler only acknowledges the call.
        node_count = len(args.get("nodes", []))
        edge_count = len(args.get("edges", []))
        return _ok(f"Received {node_count} nodes and {edge_count} edges.")

    return emit_extraction


def build_jira_extraction_tools(client: JiraClient, project_key: str) -> list[SdkMcpTool[Any]]:
    """Read-only Jira fetch tools plus `emit_extraction`, bound to one project.

    Same two tools GitHub gets, minus a commit fetch (Jira has no commits): read
    a linked issue the ticket actually names, and search *within this project*.
    The project scoping is applied here rather than trusted to the agent's JQL --
    a tool that can be talked into querying another project is not scoped.
    """

    @tool("fetch_linked_issue", "Fetch a linked Jira issue by key, e.g. GATE-43.", {"key": str})
    async def fetch_linked_issue(args: dict[str, Any]) -> dict[str, Any]:
        try:
            issue = await asyncio.to_thread(client.fetch_issue, str(args["key"]))
            return _ok(format_jira_issue(issue))
        except _FETCH_ERRORS as exc:
            return _error(str(exc))

    @tool("search_project", "Search this Jira project's issues by text.", {"query": str})
    async def search_project(args: dict[str, Any]) -> dict[str, Any]:
        try:
            # The agent supplies free text, never raw JQL: the project clause is
            # ours, and `text ~` keeps a crafted query from becoming a new clause.
            escaped = str(args["query"]).replace('"', " ")
            jql = f'project = "{project_key}" AND text ~ "{escaped}"'
            results = await asyncio.to_thread(client.search_issues, jql)
            return _ok(format_jira_search(results))
        except _FETCH_ERRORS as exc:
            return _error(str(exc))

    return [fetch_linked_issue, search_project, _emit_tool()]


def build_extraction_tools(client: GitHubClient, owner: str, repo: str) -> list[SdkMcpTool[Any]]:
    """Build the read-only fetch tools plus `emit_extraction`, bound to one repo."""

    # The connector is synchronous httpx; run each call in a thread so it never
    # blocks the event loop the agent SDK is driving.
    @tool("fetch_linked_issue", "Fetch a linked issue by number.", {"number": int})
    async def fetch_linked_issue(args: dict[str, Any]) -> dict[str, Any]:
        try:
            issue = await asyncio.to_thread(client.fetch_issue, owner, repo, int(args["number"]))
            return _ok(format_issue(issue))
        except _FETCH_ERRORS as exc:
            return _error(str(exc))

    @tool("fetch_commit", "Fetch a commit's message by sha.", {"sha": str})
    async def fetch_commit(args: dict[str, Any]) -> dict[str, Any]:
        try:
            commit = await asyncio.to_thread(client.fetch_commit, owner, repo, str(args["sha"]))
            return _ok(format_commit(commit))
        except _FETCH_ERRORS as exc:
            return _error(str(exc))

    @tool("search_repo", "Search this repo's issues and PRs.", {"query": str})
    async def search_repo(args: dict[str, Any]) -> dict[str, Any]:
        try:
            scoped = f"repo:{owner}/{repo} {args['query']}"
            results = await asyncio.to_thread(client.search_issues, scoped)
            return _ok(format_search(results))
        except _FETCH_ERRORS as exc:
            return _error(str(exc))

    return [fetch_linked_issue, fetch_commit, search_repo, _emit_tool()]
