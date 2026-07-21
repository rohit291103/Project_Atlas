"""Tests for atlas.config.

The single meaningful invariant to guard here is that DEFAULT_WORKSPACE_ID is a
*stable* constant, not accidentally a factory call. If someone ever changes it to
`uuid.uuid4()`, every ingestion run would land in a different phantom workspace
and the Phase 0 single-workspace assumption would silently break -- this test
fails loudly if that happens.
"""

from __future__ import annotations

import uuid

from atlas.config import DEFAULT_WORKSPACE_ID


def test_default_workspace_id_is_the_nil_sentinel() -> None:
    assert uuid.UUID(int=0) == DEFAULT_WORKSPACE_ID
    assert str(DEFAULT_WORKSPACE_ID) == "00000000-0000-0000-0000-000000000000"


def test_default_workspace_id_is_stable_across_imports() -> None:
    from atlas.config import DEFAULT_WORKSPACE_ID as reimported

    assert reimported == DEFAULT_WORKSPACE_ID
