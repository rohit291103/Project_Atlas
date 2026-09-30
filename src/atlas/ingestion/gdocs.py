"""Read-only Google Docs connector (Phase 3, the third source).

Built to the shape of `github.py` and `jira.py`: this module owns all Google
HTTP and JSON parsing, returns a frozen DTO rather than domain Nodes, and only
ever issues GET to the Docs API -- the one POST is the OAuth token exchange,
which reads nothing and writes nothing.

**Access is "share with Atlas"** (decided 2026-09-28): Atlas has one Google
service account, and a PM shares specific docs with its email exactly as they
would with a teammate. Atlas can read what was shared and nothing else, and
the scope requested is `documents.readonly`, so least privilege holds twice
over (Philosophy §6). The key lives in the environment
(`ATLAS_GOOGLE_SERVICE_ACCOUNT`), never in the database -- it is an application
secret, not a per-product credential.

**Known limit, recorded rather than hidden:** one service account is shared by
every workspace, so any workspace holding a doc's URL could ingest a doc
someone else shared with Atlas. Doc ids are long and unguessable, which makes
the URL a capability, but that is not tenant isolation. Acceptable for a
single-team pilot; must be closed (a service account per workspace, or OAuth)
before Atlas has more than one customer -- see
`docs/decisions/2026-09-28-google-docs-source.md`.

**Signing in without a Google library.** A service account authenticates by
signing a short-lived JWT with its RSA key and exchanging it for an access
token. `cryptography` is already a dependency (it seals connection secrets),
so the whole flow is ~20 lines here instead of `google-auth` plus `requests`.

**Flattening is verbatim.** A `SourceRef.excerpt` must be findable in the doc,
so `document_text` concatenates text runs in document order without rewriting,
summarising or dropping any of them -- the same rule as Jira's ADF.
"""

from __future__ import annotations

import base64
import json
import re
import time
from dataclasses import dataclass
from types import TracebackType
from typing import Any

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

__all__ = [
    "DOCS_SCOPE",
    "MAX_DOCUMENT_CHARS",
    "GoogleDoc",
    "GoogleDocsClient",
    "GoogleDocsError",
    "document_text",
    "parse_doc_id",
]

DOCS_SCOPE = "https://www.googleapis.com/auth/documents.readonly"
DOCS_API = "https://docs.googleapis.com/v1/documents"
_TOKEN_LIFETIME = 3600
#: Refresh this long before Google's stated expiry, so a token never lapses
#: between being checked and being used.
_TOKEN_MARGIN = 60

#: Roughly a 45-minute interview transcript, twice over. Longer is refused, not
#: truncated: a cut document drops claims *and* leaves a reviewer looking at text
#: the agent never read.
MAX_DOCUMENT_CHARS = 120_000

#: Google document ids are URL-safe base64-ish and long; nothing shorter is one.
_DOC_ID = re.compile(r"^[A-Za-z0-9_-]{25,}$")
_DOC_URL = re.compile(r"^https://docs\.google\.com/document/d/([A-Za-z0-9_-]{25,})(?:[/?#].*)?$")


class GoogleDocsError(Exception):
    def __init__(self, status_code: int, message: str, *, is_rate_limited: bool = False) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.is_rate_limited = is_rate_limited


@dataclass(frozen=True, slots=True)
class GoogleDoc:
    id: str
    title: str
    url: str
    text: str
    revision_id: str | None


def parse_doc_id(target: str) -> str:
    """A Google Docs URL or bare id -> the id. Strict, like every target parser:
    this is where a string from a browser becomes something fetched."""
    cleaned = target.strip()
    match = _DOC_URL.match(cleaned)
    if match:
        return match.group(1)
    if _DOC_ID.match(cleaned):
        return cleaned
    raise ValueError(
        f"{target!r} is not a Google Doc — expected a docs.google.com/document/d/… link"
    )


def doc_url(doc_id: str) -> str:
    return f"https://docs.google.com/document/d/{doc_id}/edit"


def document_text(body: dict[str, Any]) -> str:
    """The document's text, runs concatenated in order, nothing altered."""
    out: list[str] = []
    _walk(body.get("content", []), out)
    return "".join(out)


def _walk(content: list[dict[str, Any]], out: list[str]) -> None:
    for element in content:
        if "paragraph" in element:
            for part in element["paragraph"].get("elements", []):
                run = part.get("textRun")
                if run and run.get("content"):
                    out.append(run["content"])
        elif "table" in element:
            for row in element["table"].get("tableRows", []):
                for cell in row.get("tableCells", []):
                    _walk(cell.get("content", []), out)
        # sectionBreak, tableOfContents, images: no text of their own to quote.


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


class GoogleDocsClient:
    """Reads documents shared with one service account. `transport` is a test
    seam for `httpx.MockTransport`."""

    def __init__(
        self,
        service_account: dict[str, Any],
        *,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 30.0,
    ) -> None:
        self.account: str = service_account["client_email"]
        self._token_uri: str = service_account.get(
            "token_uri", "https://oauth2.googleapis.com/token"
        )
        key = serialization.load_pem_private_key(
            service_account["private_key"].encode(), password=None
        )
        if not isinstance(key, rsa.RSAPrivateKey):
            raise ValueError("the service account key is not an RSA key")
        self._key = key
        self._client = httpx.Client(transport=transport, timeout=timeout)
        self._token: str | None = None
        self._token_expires = 0.0

    def __enter__(self) -> GoogleDocsClient:
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

    def fetch_document(self, doc_id: str) -> GoogleDoc:
        response = self._client.get(
            f"{DOCS_API}/{doc_id}", headers={"Authorization": f"Bearer {self._access_token()}"}
        )
        if response.status_code >= 400:
            raise self._error(response)
        data = response.json()
        text = document_text(data.get("body", {}))
        if len(text) > MAX_DOCUMENT_CHARS:
            raise GoogleDocsError(
                413,
                f"“{data.get('title', doc_id)}” is too long to extract in one run "
                f"({len(text):,} characters; the limit is {MAX_DOCUMENT_CHARS:,}). "
                "Split it into smaller docs.",
            )
        return GoogleDoc(
            id=data.get("documentId", doc_id),
            title=data.get("title") or doc_id,
            url=doc_url(doc_id),
            text=text,
            revision_id=data.get("revisionId"),
        )

    # -- auth -------------------------------------------------------------------

    def _access_token(self) -> str:
        now = time.time()
        if self._token and now < self._token_expires - _TOKEN_MARGIN:
            return self._token
        header = _b64url(json.dumps({"alg": "RS256", "typ": "JWT"}).encode())
        claims = _b64url(
            json.dumps(
                {
                    "iss": self.account,
                    "scope": DOCS_SCOPE,
                    "aud": self._token_uri,
                    "iat": int(now),
                    "exp": int(now) + _TOKEN_LIFETIME,
                }
            ).encode()
        )
        signature = self._key.sign(
            f"{header}.{claims}".encode(), padding.PKCS1v15(), hashes.SHA256()
        )
        response = self._client.post(
            self._token_uri,
            data={
                "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                "assertion": f"{header}.{claims}.{_b64url(signature)}",
            },
        )
        if response.status_code >= 400:
            # The body can echo the assertion; never quote it.
            raise GoogleDocsError(
                response.status_code, "Google rejected Atlas's service account sign-in"
            )
        body = response.json()
        self._token = str(body["access_token"])
        self._token_expires = now + float(body.get("expires_in", _TOKEN_LIFETIME))
        return self._token

    def _error(self, response: httpx.Response) -> GoogleDocsError:
        status = response.status_code
        if status in (403, 404):
            message = (
                f"Atlas can't open that doc. Share it with {self.account} "
                "(Viewer is enough) and try again."
            )
        else:
            try:
                message = str(response.json().get("error", {}).get("message", ""))
            except ValueError:
                message = ""
            message = message or response.reason_phrase or "Google Docs request failed"
        return GoogleDocsError(status, message, is_rate_limited=status == 429)
