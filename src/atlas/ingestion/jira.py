"""Read-only Jira Cloud connector (TRD Sec4.1, Phase1_Architecture.md Sec6).

The second source, built to the same shape as `ingestion/github.py`: this module
owns *all* Jira HTTP and JSON parsing, returns transient frozen DTOs rather than
domain Nodes, and only ever issues GET requests -- so the read-only guarantee
(CLAUDE.md Philosophy Sec1/Sec6) stays checkable in one place.

**Authentication is an email + API token** (HTTP Basic), not OAuth 3LO --
resolving `Phase1_Architecture.md` Sec10 Q4. A Jira Cloud API token carries
exactly the permissions of the person who minted it, which *is* least privilege
(Philosophy Sec6) with no scope negotiation: Atlas cannot see a project its
holder could not already open. OAuth 3LO would add an app registration, a
callback URL and refresh-token storage -- config surface on the very demo whose
success criterion is "a PM, unassisted" -- to buy a token model that is not
actually more restricted. Enterprise auth (SSO/SAML, per-connector OAuth) is
Phase 4 in the Roadmap, and this decision does not foreclose it.

The one thing here with no GitHub counterpart is **ADF flattening**. Jira Cloud
returns rich text as Atlassian Document Format -- a JSON tree -- and a
`SourceRef.excerpt` has to be literal text a human can find on the page. So
`adf_to_text` walks the tree and concatenates its text nodes in document order,
without rewriting, summarising or dropping any of them: an excerpt that silently
loses a clause is fabricated provenance, which CLAUDE.md rates Critical.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime
from types import TracebackType
from typing import Any

import httpx

__all__ = [
    "IssueLink",
    "JiraClient",
    "JiraComment",
    "JiraError",
    "JiraIssue",
    "ProjectAccess",
    "adf_to_text",
]

API_ROOT = "/rest/api/3"
_MAX_SEARCH_RESULTS = 50  # hard ceiling; scoped ingestion (slice 1D) sets its own

#: What `/search/jql` must be asked for by name -- it returns bare ids otherwise.
#: Exactly the fields `_Parser.issue` reads, so search results and `fetch_issue`
#: produce the same shape of issue (minus comments, which search never returns).
_SEARCH_FIELDS = (
    "summary",
    "description",
    "status",
    "issuetype",
    "reporter",
    "created",
    "labels",
    "parent",
    "issuelinks",
)


class JiraError(RuntimeError):
    """A non-success response from the Jira API.

    Mirrors `GitHubError`, including `is_rate_limited`: surfaced to the caller,
    never silently retried, at Phase 1's handful-of-issues scale.
    """

    def __init__(self, status_code: int, message: str, *, is_rate_limited: bool = False) -> None:
        super().__init__(f"Jira API {status_code}: {message}")
        self.status_code = status_code
        self.is_rate_limited = is_rate_limited


# --- transient raw-content DTOs ------------------------------------------------


@dataclass(frozen=True, slots=True)
class JiraComment:
    id: str
    author: str | None
    body: str
    url: str
    created_at: datetime | None


@dataclass(frozen=True, slots=True)
class IssueLink:
    """One end of a Jira issue link -- what the agent follows instead of guessing.

    The Jira equivalent of "see #109" in a PR body: `relation` is Jira's own
    wording for the link ("blocks", "relates to"), kept verbatim so the agent
    reads what a human would.
    """

    key: str
    summary: str
    relation: str


@dataclass(frozen=True, slots=True)
class JiraIssue:
    key: str
    summary: str
    description: str
    status: str
    issue_type: str
    url: str
    reporter: str | None
    created_at: datetime | None
    labels: tuple[str, ...]
    parent_key: str | None
    links: tuple[IssueLink, ...]
    comments: tuple[JiraComment, ...]


# --- ADF ------------------------------------------------------------------------

#: Node types that end a line of text. Everything else is inline, so its text
#: joins the surrounding run without a separator.
_BLOCK_TYPES = frozenset(
    {
        "paragraph",
        "heading",
        "blockquote",
        "codeBlock",
        "listItem",
        "tableRow",
        "rule",
        "mediaSingle",
    }
)


def adf_to_text(document: Any) -> str:
    """Flatten Atlassian Document Format to the literal text it renders as.

    Unknown node types are *descended into* rather than skipped: ADF gains node
    types over time, and dropping one would silently truncate an excerpt. The
    result is deliberately plain -- no markdown reconstruction, because an
    excerpt is evidence, and decorating it would make it no longer verbatim.
    """
    if document is None:
        return ""
    if isinstance(document, str):
        return document  # already literal text (API v2, and some v3 responses)

    lines: list[str] = []
    current: list[str] = []

    def flush() -> None:
        if current:
            lines.append("".join(current).strip())
            current.clear()

    def walk(node: Any) -> None:
        if isinstance(node, list):
            for item in node:
                walk(item)
            return
        if not isinstance(node, dict):
            return
        node_type = node.get("type")
        if node_type == "text":
            current.append(str(node.get("text", "")))
            return
        if node_type == "hardBreak":
            flush()
            return
        # `mention` and `emoji` render as their text attribute, not as children.
        attrs = node.get("attrs")
        if node_type in {"mention", "emoji"} and isinstance(attrs, dict):
            current.append(str(attrs.get("text", "")))
            return
        walk(node.get("content", []))
        if node_type in _BLOCK_TYPES:
            flush()

    walk(document)
    flush()
    return "\n".join(line for line in lines if line)


# --- parse helpers -------------------------------------------------------------


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        # Jira sends "+0000" rather than "+00:00"; fromisoformat wants the colon.
        return datetime.fromisoformat(value[:-5] + value[-5:-2] + ":" + value[-2:])
    except ValueError:
        return None


def _display_name(person: Any) -> str | None:
    return person.get("displayName") if isinstance(person, dict) else None


def _parse_links(raw_links: Any) -> tuple[IssueLink, ...]:
    links: list[IssueLink] = []
    for raw in raw_links if isinstance(raw_links, list) else []:
        if not isinstance(raw, dict):
            continue
        link_type = raw.get("type") or {}
        for direction, wording in (("outwardIssue", "outward"), ("inwardIssue", "inward")):
            other = raw.get(direction)
            if not isinstance(other, dict):
                continue
            links.append(
                IssueLink(
                    key=str(other.get("key", "")),
                    summary=str((other.get("fields") or {}).get("summary", "")),
                    relation=str(link_type.get(wording) or link_type.get("name") or "relates to"),
                )
            )
    return tuple(links)


class _Parser:
    """Parsing needs the site URL to build browsable links, so it hangs off the
    client's base URL rather than living as free functions."""

    def __init__(self, site_url: str) -> None:
        self._site = site_url

    def issue_url(self, key: str) -> str:
        return f"{self._site}/browse/{key}"

    def comment(self, key: str, data: dict[str, Any]) -> JiraComment:
        comment_id = str(data.get("id", ""))
        return JiraComment(
            id=comment_id,
            author=_display_name(data.get("author")),
            body=adf_to_text(data.get("body")),
            url=f"{self.issue_url(key)}?focusedCommentId={comment_id}",
            created_at=_parse_dt(data.get("created")),
        )

    def issue(self, data: dict[str, Any], comments: tuple[JiraComment, ...]) -> JiraIssue:
        fields = data.get("fields") or {}
        key = str(data.get("key", ""))
        if not key:
            # The key is what every provenance URL for this issue is built from, so
            # a blank one yields `<site>/browse/` -- a link that resolves to a page
            # having nothing to do with the claim. Provenance that points at the
            # wrong thing is worse than provenance that is missing, because nothing
            # downstream can tell. Fail here instead (CLAUDE.md: a Node without a
            # sound SourceRef is a bug, not an edge case).
            raise JiraError(0, f"Jira returned an issue with no key: {sorted(data)}")
        parent = fields.get("parent")
        labels = fields.get("labels")
        return JiraIssue(
            key=key,
            summary=str(fields.get("summary") or ""),
            description=adf_to_text(fields.get("description")),
            status=str((fields.get("status") or {}).get("name") or ""),
            issue_type=str((fields.get("issuetype") or {}).get("name") or ""),
            # Not `self`: that is the REST endpoint, which serves JSON. Provenance
            # is a link a reviewer clicks, so it must be the browsable page.
            url=self.issue_url(key),
            reporter=_display_name(fields.get("reporter")),
            created_at=_parse_dt(fields.get("created")),
            labels=tuple(str(label) for label in labels) if isinstance(labels, list) else (),
            parent_key=str(parent["key"]) if isinstance(parent, dict) and "key" in parent else None,
            links=_parse_links(fields.get("issuelinks")),
            comments=comments,
        )


# --- client --------------------------------------------------------------------


@dataclass(frozen=True)
class ProjectAccess:
    """What a credential can see in one Jira project. Shown, never stored."""

    key: str
    name: str
    project_type: str | None


class JiraClient:
    """A thin, read-only Jira Cloud REST client.

    Construct with the site URL, the account email, and that account's API token
    (least privilege, TRD Sec9 -- the token can reach exactly what its owner can).
    `transport` is a test seam for `httpx.MockTransport`.
    """

    def __init__(
        self,
        *,
        base_url: str,
        email: str,
        api_token: str,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 30.0,
    ) -> None:
        site = base_url.rstrip("/")
        credential = base64.b64encode(f"{email}:{api_token}".encode()).decode()
        self._parser = _Parser(site)
        self._client = httpx.Client(
            base_url=site,
            headers={
                "Authorization": f"Basic {credential}",
                "Accept": "application/json",
            },
            transport=transport,
            timeout=timeout,
        )

    def __enter__(self) -> JiraClient:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def describe_project(self, key: str) -> ProjectAccess:
        """What this credential can actually see in one Jira project.

        The Jira half of the connect flow's trust moment (slice 2B). A Jira API
        token carries exactly its owner's permissions, so this answers "what does
        Atlas get" with the site's own answer rather than with a promise.
        """
        data = self._get(f"{API_ROOT}/project/{key}")
        return ProjectAccess(
            key=data.get("key") or key,
            name=data.get("name") or key,
            project_type=data.get("projectTypeKey") or None,
        )

    def fetch_issue(self, key: str) -> JiraIssue:
        """Fetch an issue's fields plus its full comment thread."""
        data = self._get(f"{API_ROOT}/issue/{key}")
        raw = self._get(f"{API_ROOT}/issue/{key}/comment")
        comments = tuple(self._parser.comment(key, comment) for comment in raw.get("comments", []))
        return self._parser.issue(data, comments)

    def search_issues(self, jql: str, *, limit: int = _MAX_SEARCH_RESULTS) -> tuple[JiraIssue, ...]:
        """Read-only JQL search -- the scoping primitive (TRD Sec4.2).

        Backs both the agent's `search_project` tool and slice 1D's ingest-by-
        epic/label, so a scope is pulled deliberately rather than by crawling a
        whole Jira site. Results carry no comments (the search endpoint doesn't
        return them); `fetch_issue` gets those when an issue is actually read.

        `fields` is not optional. `/search/jql` returns **only issue ids** when it
        is omitted -- not an error, just objects with nothing in them, which parse
        into issues whose key, summary and provenance URL are all empty strings.
        The predecessor endpoint returned a default field set, which is why this
        reads like a redundant parameter and is not one.
        """
        data = self._get(
            f"{API_ROOT}/search/jql",
            params={
                "jql": jql,
                "maxResults": min(limit, _MAX_SEARCH_RESULTS),
                "fields": ",".join(_SEARCH_FIELDS),
            },
        )
        return tuple(self._parser.issue(issue, ()) for issue in data.get("issues", []))

    # -- HTTP -------------------------------------------------------------------

    def _get(self, path: str, *, params: dict[str, Any] | None = None) -> Any:
        response = self._client.get(path, params=params)
        if response.status_code >= 400:
            raise self._error(response)
        return response.json()

    @staticmethod
    def _error(response: httpx.Response) -> JiraError:
        try:
            body = response.json()
            messages = body.get("errorMessages") or []
            message = messages[0] if messages else body.get("message", response.reason_phrase)
        except ValueError:
            message = response.reason_phrase
        return JiraError(
            response.status_code,
            str(message),
            is_rate_limited=response.status_code == 429,
        )
