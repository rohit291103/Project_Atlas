"""Tests for atlas.config.

The single meaningful invariant to guard here is that DEFAULT_WORKSPACE_ID is a
*stable* constant, not accidentally a factory call. If someone ever changes it to
`uuid.uuid4()`, every ingestion run would land in a different phantom workspace
and the Phase 0 single-workspace assumption would silently break -- this test
fails loudly if that happens.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest

from atlas.config import DEFAULT_WORKSPACE_ID, google_service_accounts


def test_default_workspace_id_is_the_nil_sentinel() -> None:
    assert uuid.UUID(int=0) == DEFAULT_WORKSPACE_ID
    assert str(DEFAULT_WORKSPACE_ID) == "00000000-0000-0000-0000-000000000000"


def test_default_workspace_id_is_stable_across_imports() -> None:
    from atlas.config import DEFAULT_WORKSPACE_ID as reimported

    assert reimported == DEFAULT_WORKSPACE_ID


# --- Google service accounts, one per workspace (Phase 4) ------------------------

A, B = uuid.uuid4(), uuid.uuid4()


def _key(email: str) -> dict[str, str]:
    return {"client_email": email, "private_key": "-----BEGIN PRIVATE KEY-----\nx\n"}


def test_each_workspace_gets_its_own_account() -> None:
    raw = json.dumps(
        {str(A): _key("a@x.iam.gserviceaccount.com"), str(B): _key("b@x.iam.gserviceaccount.com")}
    )

    accounts = google_service_accounts(raw)

    assert accounts[A]["client_email"] == "a@x.iam.gserviceaccount.com"
    assert accounts[B]["client_email"] == "b@x.iam.gserviceaccount.com"


def test_a_key_may_be_given_as_a_path(tmp_path: Path) -> None:
    path = tmp_path / "a.json"
    path.write_text(json.dumps(_key("a@x.iam.gserviceaccount.com")))

    accounts = google_service_accounts(json.dumps({str(A): str(path)}))

    assert accounts[A]["client_email"] == "a@x.iam.gserviceaccount.com"


def test_unset_means_no_workspace_has_google_docs() -> None:
    assert google_service_accounts(None) == {}
    assert google_service_accounts("  ") == {}


def test_two_workspaces_sharing_one_account_is_refused() -> None:
    """That configuration is exactly the cross-tenant gap this closes."""
    shared = _key("same@x.iam.gserviceaccount.com")

    with pytest.raises(ValueError, match="same@x.iam.gserviceaccount.com"):
        google_service_accounts(json.dumps({str(A): shared, str(B): shared}))


def test_a_key_that_is_not_keyed_by_workspace_is_refused() -> None:
    with pytest.raises(ValueError, match="workspace id"):
        google_service_accounts(json.dumps({"not-a-uuid": _key("a@x.iam.gserviceaccount.com")}))


def test_a_malformed_key_is_refused_without_repeating_it() -> None:
    with pytest.raises(ValueError) as raised:
        google_service_accounts(json.dumps({str(A): {"private_key": "SECRETVALUE"}}))

    assert "SECRETVALUE" not in str(raised.value)
