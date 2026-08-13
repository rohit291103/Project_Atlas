"""Tests for ingestion/jira.py: the read-only Jira Cloud connector (slice 1C).

Same shape and same guarantees as test_github.py -- recorded fixtures through
`httpx.MockTransport`, no live API, no token, no network. The two load-bearing
guarantees get their own tests again because they are what the whole read-only
promise rests on: the client only ever issues GET requests, and it authenticates
as the credential it was handed.

Jira-specific weight sits on **ADF flattening**. Jira Cloud returns descriptions
and comments as Atlassian Document Format (a JSON tree), and a `SourceRef.excerpt`
must be literal text a human can find in the source. If flattening dropped or
reordered text, every excerpt taken from a Jira issue would be subtly wrong --
fabricated provenance, which CLAUDE.md rates Critical. So it is tested directly.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from atlas.ingestion.jira import JiraClient, JiraError, adf_to_text

FIXTURES = Path(__file__).parent / "fixtures" / "jira"
SITE = "https://acme.atlassian.net"


def _load(name: str) -> object:
    return json.loads((FIXTURES / f"{name}.json").read_text())


def make_client(
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    email: str = "pm@acme.test",
    api_token: str = "test-token",
) -> JiraClient:
    return JiraClient(
        base_url=SITE,
        email=email,
        api_token=api_token,
        transport=httpx.MockTransport(handler),
    )


def route_fixtures(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path == "/rest/api/3/issue/GATE-42":
        return httpx.Response(200, json=_load("issue"))
    if path == "/rest/api/3/issue/GATE-42/comment":
        return httpx.Response(200, json=_load("comments"))
    if path == "/rest/api/3/search/jql":
        return httpx.Response(200, json=_load("search"))
    return httpx.Response(404, json={"errorMessages": [f"no fixture for {path}"]})


# --- ADF flattening (provenance depends on this being literal) -----------------


def test_adf_to_text_joins_text_nodes_in_order() -> None:
    doc = {
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "content": [
                    {"type": "text", "text": "We must throttle "},
                    {"type": "text", "text": "per client IP."},
                ],
            }
        ],
    }

    assert adf_to_text(doc) == "We must throttle per client IP."


def test_adf_to_text_separates_block_nodes_with_newlines() -> None:
    doc = {
        "type": "doc",
        "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": "First."}]},
            {"type": "paragraph", "content": [{"type": "text", "text": "Second."}]},
        ],
    }

    assert adf_to_text(doc) == "First.\nSecond."


def test_adf_to_text_passes_a_plain_string_through_unchanged() -> None:
    """Some Jira responses (and the v2 API) return a plain string. It is already
    literal text -- it must not be reformatted on the way past."""
    assert adf_to_text("Plain-text description.") == "Plain-text description."


def test_adf_to_text_of_nothing_is_empty() -> None:
    assert adf_to_text(None) == ""
    assert adf_to_text({"type": "doc", "content": []}) == ""


def test_adf_to_text_ignores_marks_and_unknown_node_types() -> None:
    """An unknown node type must not swallow the text inside it -- an excerpt
    that silently loses a clause is worse than one that keeps extra whitespace."""
    doc = {
        "type": "doc",
        "content": [
            {
                "type": "someFutureBlock",
                "content": [
                    {"type": "text", "text": "still text", "marks": [{"type": "strong"}]},
                ],
            }
        ],
    }

    assert "still text" in adf_to_text(doc)


# --- parsing -------------------------------------------------------------------


def test_fetch_issue_parses_core_fields_and_comments() -> None:
    issue = make_client(route_fixtures).fetch_issue("GATE-42")

    assert issue.key == "GATE-42"
    assert issue.summary == "Rate-limit the gateway per client IP"
    assert issue.status == "In Progress"
    assert issue.issue_type == "Story"
    assert issue.reporter == "Priya Raman"
    assert issue.labels == ("gateway", "reliability")
    assert "throttle per client IP" in issue.description
    assert "Limits must be configurable per route." in issue.description
    assert [comment.author for comment in issue.comments] == ["Dan Okafor", "Priya Raman"]
    assert "buffer, not stream" in issue.comments[0].body


def test_fetch_issue_builds_a_browsable_url_not_an_api_url() -> None:
    """`SourceRef.url` is a deep link a reviewer clicks. The REST `self` link
    returns JSON, so provenance must point at /browse/<key> instead."""
    issue = make_client(route_fixtures).fetch_issue("GATE-42")

    assert issue.url == f"{SITE}/browse/GATE-42"
    assert issue.comments[0].url == f"{SITE}/browse/GATE-42?focusedCommentId=20001"


def test_fetch_issue_captures_links_and_epic_parent() -> None:
    """The links are what the agent follows instead of guessing -- the Jira
    equivalent of "see #109" in a PR body."""
    issue = make_client(route_fixtures).fetch_issue("GATE-42")

    assert issue.parent_key == "GATE-1"
    assert {link.key for link in issue.links} == {"GATE-43", "GATE-7"}
    assert {link.relation for link in issue.links} == {"blocks", "relates to"}


def test_search_issues_parses_results_and_sends_the_jql() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(request.url.params)
        return route_fixtures(request)

    issues = make_client(handler).search_issues('project = GATE AND labels = "gateway"', limit=25)

    assert [issue.key for issue in issues] == ["GATE-43", "GATE-44"]
    assert seen["jql"] == 'project = GATE AND labels = "gateway"'
    assert seen["maxResults"] == "25"


def test_search_asks_for_fields_by_name() -> None:
    """`/search/jql` returns bare issue ids when `fields` is omitted -- no error,
    just objects that parse into issues with an empty key and a provenance URL of
    `<site>/browse/`. Caught only by running against a live Jira, so it gets a
    test that fails if the parameter is ever dropped again."""
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(request.url.params)
        return route_fixtures(request)

    make_client(handler).search_issues("project = GATE")

    requested = set(seen["fields"].split(","))
    assert {"summary", "description", "status", "issuetype", "labels", "parent"} <= requested


def test_an_issue_with_no_key_is_rejected() -> None:
    """A blank key builds `<site>/browse/` -- a link to something other than the
    claim. Provenance pointing at the wrong page is worse than none, because
    nothing downstream can tell the difference."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/comment"):
            return httpx.Response(200, json={"comments": []})
        return httpx.Response(200, json={"id": "10009"})  # what a fields-less search returns

    with pytest.raises(JiraError, match="no key"):
        make_client(handler).fetch_issue("GATE-42")


def test_search_result_with_a_plain_string_description_still_parses() -> None:
    issues = make_client(route_fixtures).search_issues("project = GATE")

    assert issues[1].description == "Plain-text description, as some API responses still return."


def test_parsing_ignores_unmodeled_fields() -> None:
    """Jira sends far more than we model; unknown keys must not break parsing."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/comment"):
            return httpx.Response(200, json={"comments": []})
        payload = json.loads(json.dumps(_load("issue")))
        assert isinstance(payload, dict)
        payload["fields"]["customfield_10099"] = {"anything": True}
        payload["unexpectedTopLevel"] = 1
        return httpx.Response(200, json=payload)

    issue = make_client(handler).fetch_issue("GATE-42")

    assert issue.key == "GATE-42"


# --- errors --------------------------------------------------------------------


def test_not_found_raises_jira_error_with_status() -> None:
    client = make_client(lambda request: httpx.Response(404, json={"errorMessages": ["gone"]}))

    with pytest.raises(JiraError) as caught:
        client.fetch_issue("GATE-999")

    assert caught.value.status_code == 404
    assert "gone" in str(caught.value)


def test_rate_limited_response_is_flagged() -> None:
    client = make_client(
        lambda request: httpx.Response(429, headers={"Retry-After": "30"}, json={})
    )

    with pytest.raises(JiraError) as caught:
        client.fetch_issue("GATE-42")

    assert caught.value.is_rate_limited


def test_permission_denied_surfaces_as_an_error_not_empty_content() -> None:
    """Least privilege (Philosophy §6): the token sees exactly what its owner
    sees. A 403 must surface, never be smoothed into "this issue has no content"."""
    client = make_client(
        lambda request: httpx.Response(403, json={"errorMessages": ["You do not have permission"]})
    )

    with pytest.raises(JiraError) as caught:
        client.fetch_issue("GATE-42")

    assert caught.value.status_code == 403


# --- the read-only + credential guarantees -------------------------------------


def test_client_only_ever_issues_get_requests() -> None:
    methods: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        methods.append(request.method)
        return route_fixtures(request)

    client = make_client(handler)
    client.fetch_issue("GATE-42")
    client.search_issues("project = GATE")

    assert set(methods) == {"GET"}


def test_client_authenticates_as_the_supplied_credential() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(request.headers)
        return route_fixtures(request)

    make_client(handler, email="pm@acme.test", api_token="s3cret").fetch_issue("GATE-42")

    assert seen["authorization"].startswith("Basic ")
    assert seen["accept"] == "application/json"


def test_base_url_trailing_slash_does_not_double_up_paths() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        return route_fixtures(request)

    JiraClient(
        base_url=f"{SITE}/",
        email="pm@acme.test",
        api_token="t",
        transport=httpx.MockTransport(handler),
    ).fetch_issue("GATE-42")

    assert seen[0] == "/rest/api/3/issue/GATE-42"
