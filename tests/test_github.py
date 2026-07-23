"""Tests for ingestion/github.py: the read-only GitHub REST connector
(TRD Sec4.1, Phase0_Architecture.md Sec2/Sec4).

Every test replays recorded fixtures via `httpx.MockTransport` -- no live API,
no token, no network (the VCR-style approach decided in Phase0_Architecture.md
Sec3). Fixtures live in tests/fixtures/github/. Alongside parsing, two guarantees
get their own tests because they're load-bearing for the whole product: the
client is *read-only* (only GET requests ever leave it) and it authenticates
with the supplied token.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from atlas.ingestion.github import GitHubClient, GitHubError

FIXTURES = Path(__file__).parent / "fixtures" / "github"


def _load(name: str) -> object:
    return json.loads((FIXTURES / f"{name}.json").read_text())


def make_client(
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    token: str = "test-token",
    page_size: int = 100,
) -> GitHubClient:
    return GitHubClient(
        token,
        transport=httpx.MockTransport(handler),
        page_size=page_size,
    )


def route_fixtures(request: httpx.Request) -> httpx.Response:
    """Map request paths to recorded fixtures, mimicking the real endpoints."""
    path = request.url.path
    if path == "/repos/acme/gateway/pulls/42":
        return httpx.Response(200, json=_load("pull_request"))
    if path == "/repos/acme/gateway/issues/42/comments":
        # Single short page -> pagination stops after it.
        return httpx.Response(200, json=_load("pr_comments"))
    if path == "/repos/acme/gateway/issues/17":
        return httpx.Response(200, json=_load("issue"))
    if path.startswith("/repos/acme/gateway/commits/"):
        return httpx.Response(200, json=_load("commit"))
    return httpx.Response(404, json={"message": f"no fixture for {path}"})


# --- parsing -------------------------------------------------------------------


def test_fetch_pull_request_parses_core_fields_and_comments() -> None:
    with make_client(route_fixtures) as client:
        pr = client.fetch_pull_request("acme", "gateway", 42)

    assert pr.number == 42
    assert pr.title == "Add token-bucket rate limiting to the API gateway"
    assert pr.body.startswith("## Summary")
    assert pr.state == "closed"
    assert pr.url == "https://github.com/acme/gateway/pull/42"
    assert pr.author == "alice"
    assert pr.merged_at is not None
    assert [c.author for c in pr.comments] == ["bob", "alice"]
    assert pr.comments[0].body.startswith("Should this be a token bucket")


def test_fetch_issue_parses_core_fields() -> None:
    with make_client(route_fixtures) as client:
        issue = client.fetch_issue("acme", "gateway", 17)

    assert issue.number == 17
    assert issue.title == "API gateway falls over under burst traffic"
    assert issue.state == "closed"
    assert issue.url == "https://github.com/acme/gateway/issues/17"
    assert issue.author == "carol"


def test_fetch_commit_parses_nested_message_and_author() -> None:
    with make_client(route_fixtures) as client:
        commit = client.fetch_commit("acme", "gateway", "abc123def4567890abc123def4567890abc123de")

    assert commit.sha == "abc123def4567890abc123def4567890abc123de"
    assert commit.message.startswith("Implement token-bucket rate limiter")
    # nested commit.author.name, not the top-level GitHub account login
    assert commit.author == "Alice Dev"
    assert commit.authored_at is not None
    assert commit.url.endswith("/commit/abc123def4567890abc123def4567890abc123de")


def test_parsing_ignores_unmodeled_fields() -> None:
    """GitHub payloads carry dozens of fields we don't model; parsing must not
    choke on them (the fixtures include extra keys like `additions`/`_note`)."""
    with make_client(route_fixtures) as client:
        pr = client.fetch_pull_request("acme", "gateway", 42)
    assert pr.number == 42  # parsed cleanly despite extra keys in the fixture


# --- pagination ----------------------------------------------------------------


def test_fetch_pull_request_paginates_comments() -> None:
    """With page_size=1 the two-comment thread spans two full pages plus a final
    empty page; all comments must be assembled in order."""
    comments = _load("pr_comments")
    assert isinstance(comments, list)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/repos/acme/gateway/pulls/42":
            return httpx.Response(200, json=_load("pull_request"))
        if request.url.path == "/repos/acme/gateway/issues/42/comments":
            page = int(request.url.params["page"])
            start = page - 1
            return httpx.Response(200, json=comments[start : start + 1])
        return httpx.Response(404, json={"message": "unexpected"})

    with make_client(handler, page_size=1) as client:
        pr = client.fetch_pull_request("acme", "gateway", 42)

    assert [c.id for c in pr.comments] == [100, 101]


# --- errors --------------------------------------------------------------------


def test_not_found_raises_github_error_with_status() -> None:
    with make_client(route_fixtures) as client, pytest.raises(GitHubError) as exc:
        client.fetch_issue("acme", "gateway", 9999)

    assert exc.value.status_code == 404
    assert exc.value.is_rate_limited is False


def test_rate_limited_response_is_flagged() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            403,
            headers={"X-RateLimit-Remaining": "0"},
            json={"message": "API rate limit exceeded"},
        )

    with make_client(handler) as client, pytest.raises(GitHubError) as exc:
        client.fetch_issue("acme", "gateway", 17)

    assert exc.value.status_code == 403
    assert exc.value.is_rate_limited is True


def test_forbidden_without_rate_limit_header_is_not_flagged_as_rate_limit() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"message": "Resource not accessible"})

    with make_client(handler) as client, pytest.raises(GitHubError) as exc:
        client.fetch_issue("acme", "gateway", 17)

    assert exc.value.is_rate_limited is False


# --- read-only + auth guarantees ----------------------------------------------


def test_client_only_ever_issues_get_requests() -> None:
    """The whole connector's read-only guarantee (CLAUDE.md Philosophy Sec1):
    no method may emit anything but GET."""
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.method)
        return route_fixtures(request)

    with make_client(handler) as client:
        client.fetch_pull_request("acme", "gateway", 42)
        client.fetch_issue("acme", "gateway", 17)
        client.fetch_commit("acme", "gateway", "abc123def4567890abc123def4567890abc123de")

    assert seen  # sanity: requests actually happened
    assert set(seen) == {"GET"}


def test_client_sends_bearer_token_and_api_version() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(request.headers)
        return route_fixtures(request)

    with make_client(handler, token="secret-pat") as client:
        client.fetch_issue("acme", "gateway", 17)

    assert seen["authorization"] == "Bearer secret-pat"
    assert seen["x-github-api-version"] == "2022-11-28"
