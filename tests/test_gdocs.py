"""Tests for `ingestion/gdocs.py` -- the read-only Google Docs connector (Phase 3).

`httpx.MockTransport`, a throwaway RSA key, no network. The load-bearing
properties: text is flattened *verbatim* (an excerpt must be findable in the
doc), only GET reaches the Docs API, the service-account sign-in is a correctly
signed JWT for the read-only scope, and a doc nobody shared says so plainly.
"""

from __future__ import annotations

import base64
import json
from typing import Any
from urllib.parse import parse_qs

import httpx
import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from atlas.ingestion.gdocs import (
    DOCS_SCOPE,
    MAX_DOCUMENT_CHARS,
    GoogleDocsClient,
    GoogleDocsError,
    document_text,
    parse_doc_id,
)

DOC_ID = "1AbCdEfGhIjKlMnOpQrStUvWxYz0123456789_-abc"
_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
SERVICE_ACCOUNT = {
    "type": "service_account",
    "client_email": "atlas-reader@atlas-demo.iam.gserviceaccount.com",
    "private_key": _KEY.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode(),
    "token_uri": "https://oauth2.googleapis.com/token",
}


def _paragraph(*runs: str) -> dict[str, Any]:
    return {"paragraph": {"elements": [{"textRun": {"content": run}} for run in runs]}}


def _doc(*content: dict[str, Any], title: str = "Checkout interviews") -> dict[str, Any]:
    return {
        "documentId": DOC_ID,
        "title": title,
        "revisionId": "rev-7",
        "body": {"content": content},
    }


# --- flattening --------------------------------------------------------------


def test_text_is_the_runs_in_document_order_unaltered() -> None:
    body = _doc(
        _paragraph("Customer said: ", "“the export ", "is too slow”.\n"),
        _paragraph("Next steps\n"),
    )["body"]

    assert document_text(body) == "Customer said: “the export is too slow”.\nNext steps\n"


def test_table_cells_are_read_in_order() -> None:
    body = _doc(
        {
            "table": {
                "tableRows": [
                    {
                        "tableCells": [
                            {"content": [_paragraph("Q\n")]},
                            {"content": [_paragraph("A\n")]},
                        ]
                    },
                    {
                        "tableCells": [
                            {"content": [_paragraph("Why?\n")]},
                            {"content": [_paragraph("Speed.\n")]},
                        ]
                    },
                ]
            }
        }
    )["body"]

    assert document_text(body) == "Q\nA\nWhy?\nSpeed.\n"


def test_non_text_elements_are_skipped_not_invented() -> None:
    body = _doc({"sectionBreak": {}}, _paragraph("Only this.\n"), {"tableOfContents": {}})["body"]

    assert document_text(body) == "Only this.\n"


# --- targets -----------------------------------------------------------------


@pytest.mark.parametrize(
    "target",
    [
        f"https://docs.google.com/document/d/{DOC_ID}/edit",
        f"https://docs.google.com/document/d/{DOC_ID}/edit?tab=t.0#heading=h.x",
        f"https://docs.google.com/document/d/{DOC_ID}",
        f"  {DOC_ID}  ",
    ],
)
def test_a_doc_url_or_bare_id_names_the_doc(target: str) -> None:
    assert parse_doc_id(target) == DOC_ID


@pytest.mark.parametrize(
    "target",
    [
        "https://docs.google.com/spreadsheets/d/1AbCdEfGhIjKlMnOpQrStUvWxYz0123/edit",
        "https://evil.example/document/d/1AbCdEfGhIjKlMnOpQrStUvWxYz0123/edit",
        "http://docs.google.com/document/d/1AbCdEfGhIjKlMnOpQrStUvWxYz0123/edit",
        "short",
        "has spaces in it and is long enough to pass",
    ],
)
def test_anything_else_is_refused(target: str) -> None:
    with pytest.raises(ValueError):
        parse_doc_id(target)


# --- the client --------------------------------------------------------------


def _b64url_decode(part: str) -> bytes:
    return base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))


def _transport(
    document: dict[str, Any] | None = None, status: int = 200
) -> tuple[httpx.MockTransport, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.host == "oauth2.googleapis.com":
            return httpx.Response(200, json={"access_token": "ya29.token", "expires_in": 3600})
        if status != 200:
            return httpx.Response(status, json={"error": {"code": status, "message": "denied"}})
        return httpx.Response(200, json=document or _doc(_paragraph("Hello.\n")))

    return httpx.MockTransport(handler), seen


def test_sign_in_is_a_jwt_for_the_read_only_scope_signed_by_the_key() -> None:
    transport, seen = _transport()
    client = GoogleDocsClient(SERVICE_ACCOUNT, transport=transport)
    client.fetch_document(DOC_ID)

    token_request = seen[0]
    form = parse_qs(token_request.content.decode())
    assert form["grant_type"] == ["urn:ietf:params:oauth:grant-type:jwt-bearer"]
    header, claims, signature = form["assertion"][0].split(".")
    payload = json.loads(_b64url_decode(claims))
    assert payload["iss"] == SERVICE_ACCOUNT["client_email"]
    assert payload["scope"] == DOCS_SCOPE
    assert payload["aud"] == SERVICE_ACCOUNT["token_uri"]
    assert payload["exp"] - payload["iat"] <= 3600
    _KEY.public_key().verify(
        _b64url_decode(signature),
        f"{header}.{claims}".encode(),
        padding.PKCS1v15(),
        hashes.SHA256(),
    )


def test_the_docs_api_is_only_ever_read() -> None:
    transport, seen = _transport()
    client = GoogleDocsClient(SERVICE_ACCOUNT, transport=transport)

    doc = client.fetch_document(DOC_ID)

    docs_calls = [r for r in seen if r.url.host == "docs.googleapis.com"]
    assert [r.method for r in docs_calls] == ["GET"]
    assert docs_calls[0].headers["authorization"] == "Bearer ya29.token"
    assert (doc.id, doc.title, doc.text) == (DOC_ID, "Checkout interviews", "Hello.\n")
    assert doc.url == f"https://docs.google.com/document/d/{DOC_ID}/edit"


def test_the_token_is_reused_across_fetches() -> None:
    transport, seen = _transport()
    client = GoogleDocsClient(SERVICE_ACCOUNT, transport=transport)

    client.fetch_document(DOC_ID)
    client.fetch_document(DOC_ID)

    assert sum(r.url.host == "oauth2.googleapis.com" for r in seen) == 1


def test_an_unshared_doc_says_to_share_it_with_the_atlas_account() -> None:
    transport, _ = _transport(status=403)
    client = GoogleDocsClient(SERVICE_ACCOUNT, transport=transport)

    with pytest.raises(GoogleDocsError) as raised:
        client.fetch_document(DOC_ID)

    assert raised.value.status_code == 403
    assert SERVICE_ACCOUNT["client_email"] in str(raised.value)


def test_a_document_too_long_to_extract_is_refused_not_truncated() -> None:
    """Silently truncating would drop claims *and* leave excerpts pointing at a
    text the reviewer can see but the agent never read."""
    huge = _doc(_paragraph("x" * (MAX_DOCUMENT_CHARS + 1)))
    transport, _ = _transport(huge)
    client = GoogleDocsClient(SERVICE_ACCOUNT, transport=transport)

    with pytest.raises(GoogleDocsError, match="too long"):
        client.fetch_document(DOC_ID)


def test_the_account_email_is_public_but_the_key_never_appears_in_an_error() -> None:
    transport, _ = _transport(status=500)
    client = GoogleDocsClient(SERVICE_ACCOUNT, transport=transport)

    with pytest.raises(GoogleDocsError) as raised:
        client.fetch_document(DOC_ID)

    assert "PRIVATE KEY" not in str(raised.value)
    assert client.account == SERVICE_ACCOUNT["client_email"]
