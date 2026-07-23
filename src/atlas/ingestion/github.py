"""Read-only GitHub REST connector (TRD Sec4.1, Phase0_Architecture.md Sec2/Sec4).

This module owns *all* GitHub HTTP and response parsing for Phase 0. The
extraction agent's tools (`extraction/tools.py`, later) are thin wrappers over
these methods, so the read-only guarantee -- no write scope to GitHub, ever
(CLAUDE.md Engineering Philosophy Sec1/Sec6) -- lives in one auditable place:
`GitHubClient` only ever issues GET requests.

The returned objects (`PullRequest`, `Issue`, `Commit`, `IssueComment`) are
*transient raw content*, not domain `Node`s. Per TRD Sec4.2 they exist only long
enough for extraction to run against them; only extracted Nodes + SourceRefs are
persisted. They carry exactly the provenance handles a SourceRef needs -- the
number/sha (external_id), the html url, and the literal text -- and nothing
that would require its own validation gate (this content comes from GitHub, not
from an LLM).

Deliberately out of scope for Phase 0 (built when the phase that needs them
arrives, not ahead -- CLAUDE.md Non-Goals):
  * incremental sync / `last_synced_at` deltas (Phase 1),
  * `search_repo` (lands with the extraction agent tools that use it),
  * automatic retry/backoff (rate limiting is *surfaced* via GitHubError, not
    silently retried, so a caller decides -- adequate at Phase 0's handful-of-PRs
    scale).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from types import TracebackType
from typing import Any

import httpx

__all__ = [
    "Commit",
    "GitHubClient",
    "GitHubError",
    "Issue",
    "IssueComment",
    "PullRequest",
]

DEFAULT_BASE_URL = "https://api.github.com"
API_VERSION = "2022-11-28"
_MAX_PAGES = 20  # hard stop so a paginated fetch can never loop unbounded


class GitHubError(RuntimeError):
    """A non-success response from the GitHub API.

    `is_rate_limited` distinguishes the one failure a caller may want to treat
    specially (wait and retry) from a genuine 4xx/5xx -- surfaced, never retried
    automatically in Phase 0.
    """

    def __init__(self, status_code: int, message: str, *, is_rate_limited: bool = False) -> None:
        super().__init__(f"GitHub API {status_code}: {message}")
        self.status_code = status_code
        self.is_rate_limited = is_rate_limited


# --- transient raw-content DTOs ------------------------------------------------


@dataclass(frozen=True, slots=True)
class IssueComment:
    id: int
    author: str | None
    body: str
    url: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class PullRequest:
    number: int
    title: str
    body: str
    state: str
    url: str
    author: str | None
    created_at: datetime
    merged_at: datetime | None
    comments: tuple[IssueComment, ...]


@dataclass(frozen=True, slots=True)
class Issue:
    number: int
    title: str
    body: str
    state: str
    url: str
    author: str | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class Commit:
    sha: str
    message: str
    url: str
    author: str | None
    authored_at: datetime | None


# --- parse helpers -------------------------------------------------------------


def _parse_dt(value: str | None) -> datetime | None:
    # GitHub timestamps are RFC3339 with a trailing "Z"; fromisoformat handles
    # "Z" natively on Python 3.11+.
    return datetime.fromisoformat(value) if value else None


def _login(user: dict[str, Any] | None) -> str | None:
    return user.get("login") if user else None


def _require_dt(data: dict[str, Any], field: str, kind: str) -> datetime:
    parsed = _parse_dt(data.get(field))
    if parsed is None:
        raise GitHubError(200, f"{kind} payload missing {field}")
    return parsed


def _parse_comment(data: dict[str, Any]) -> IssueComment:
    return IssueComment(
        id=data["id"],
        author=_login(data.get("user")),
        body=data.get("body") or "",
        url=data["html_url"],
        created_at=_require_dt(data, "created_at", "comment"),
    )


def _parse_pull_request(data: dict[str, Any], comments: tuple[IssueComment, ...]) -> PullRequest:
    return PullRequest(
        number=data["number"],
        title=data.get("title") or "",
        body=data.get("body") or "",
        state=data.get("state") or "",
        url=data["html_url"],
        author=_login(data.get("user")),
        created_at=_require_dt(data, "created_at", "pull request"),
        merged_at=_parse_dt(data.get("merged_at")),
        comments=comments,
    )


def _parse_issue(data: dict[str, Any]) -> Issue:
    return Issue(
        number=data["number"],
        title=data.get("title") or "",
        body=data.get("body") or "",
        state=data.get("state") or "",
        url=data["html_url"],
        author=_login(data.get("user")),
        created_at=_require_dt(data, "created_at", "issue"),
    )


def _parse_commit(data: dict[str, Any]) -> Commit:
    commit = data.get("commit") or {}
    git_author = commit.get("author") or {}
    # Prefer the git author name on the commit object; fall back to the linked
    # GitHub account login when the commit isn't attributed to a git identity.
    author = git_author.get("name") or _login(data.get("author"))
    return Commit(
        sha=data["sha"],
        message=commit.get("message") or "",
        url=data["html_url"],
        author=author,
        authored_at=_parse_dt(git_author.get("date")),
    )


# --- client --------------------------------------------------------------------


class GitHubClient:
    """A thin, read-only GitHub REST client.

    Construct with a token (a Personal Access Token or app-install token scoped
    to the repos being read -- least privilege, TRD Sec9). `transport` is a test
    seam for `httpx.MockTransport`; production callers leave it None.
    """

    def __init__(
        self,
        token: str,
        *,
        base_url: str = DEFAULT_BASE_URL,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 30.0,
        page_size: int = 100,
    ) -> None:
        self._client = httpx.Client(
            base_url=base_url,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": API_VERSION,
            },
            transport=transport,
            timeout=timeout,
        )
        self._page_size = page_size

    def __enter__(self) -> GitHubClient:
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

    def fetch_pull_request(self, owner: str, repo: str, number: int) -> PullRequest:
        """Fetch a PR's title/body/state plus its full conversation-comment thread."""
        data = self._get(f"/repos/{owner}/{repo}/pulls/{number}")
        # A PR is an issue for the comments endpoint; conversation comments live
        # under /issues/{number}/comments and are paginated.
        raw_comments = self._get_paginated(f"/repos/{owner}/{repo}/issues/{number}/comments")
        comments = tuple(_parse_comment(c) for c in raw_comments)
        return _parse_pull_request(data, comments)

    def fetch_issue(self, owner: str, repo: str, number: int) -> Issue:
        return _parse_issue(self._get(f"/repos/{owner}/{repo}/issues/{number}"))

    def fetch_commit(self, owner: str, repo: str, sha: str) -> Commit:
        return _parse_commit(self._get(f"/repos/{owner}/{repo}/commits/{sha}"))

    def search_issues(self, query: str, *, limit: int = 20) -> tuple[Issue, ...]:
        """Read-only issue/PR search (GitHub `GET /search/issues`).

        Backs the extraction agent's `search_repo` tool: it lets the agent chase
        a reference it reads in a PR ("see the auth epic") without the connector
        eagerly crawling. `query` is GitHub's search syntax, e.g.
        ``repo:acme/gateway rate limiting``. Results are the same shape as an
        issue, so they reuse the issue parser.
        """
        data = self._get("/search/issues", params={"q": query, "per_page": limit})
        return tuple(_parse_issue(item) for item in data.get("items", []))

    # -- HTTP -------------------------------------------------------------------

    def _get(self, path: str, *, params: dict[str, Any] | None = None) -> Any:
        response = self._client.get(path, params=params)
        if response.status_code >= 400:
            raise self._error(response)
        return response.json()

    def _get_paginated(self, path: str) -> list[dict[str, Any]]:
        """Follow `?per_page=&page=` until a short (final) page. Bounded by
        `_MAX_PAGES` so a misbehaving endpoint can't spin forever."""
        items: list[dict[str, Any]] = []
        for page in range(1, _MAX_PAGES + 1):
            batch = self._get(path, params={"per_page": self._page_size, "page": page})
            items.extend(batch)
            if len(batch) < self._page_size:
                break
        return items

    @staticmethod
    def _error(response: httpx.Response) -> GitHubError:
        remaining = response.headers.get("X-RateLimit-Remaining")
        is_rate_limited = response.status_code in (403, 429) and remaining == "0"
        try:
            message = response.json().get("message", response.reason_phrase)
        except ValueError:
            message = response.reason_phrase
        return GitHubError(response.status_code, message, is_rate_limited=is_rate_limited)
