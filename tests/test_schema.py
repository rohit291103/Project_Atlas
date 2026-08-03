"""Tests for models/schema.py: the Pydantic v2 core entities (TRD Sec3.1).

These are the project's non-negotiable validation gate -- CLAUDE.md: "A Node
without a SourceRef is a bug, not an edge case -- schema validation should make
it structurally impossible." So the emphasis here is on what must FAIL to
construct (empty provenance, out-of-range confidence, unknown enum values,
hallucinated extra fields), not just what succeeds.
"""

from __future__ import annotations

import json
import uuid

import pytest
from pydantic import ValidationError

from atlas.models.schema import (
    CreatedBy,
    Edge,
    Event,
    EventType,
    Node,
    NodeStatus,
    NodeType,
    RelationType,
    SourceRef,
    SourceType,
)

# --- factories for valid instances (keep the failure-case tests uncluttered) --


def make_source_ref(**overrides: object) -> SourceRef:
    data: dict[str, object] = {
        "source_type": SourceType.GITHUB_PR,
        "external_id": "42",
        "url": "https://github.com/owner/repo/pull/42",
        "excerpt": "We should cache the results to avoid the N+1 query.",
        "workspace_id": uuid.uuid4(),
    }
    data.update(overrides)
    return SourceRef(**data)  # type: ignore[arg-type]


def make_node(**overrides: object) -> Node:
    data: dict[str, object] = {
        "type": NodeType.REQUIREMENT,
        "content": "Results must be cached to avoid N+1 queries.",
        "confidence_score": 0.8,
        "source_refs": [make_source_ref()],
        "workspace_id": uuid.uuid4(),
        "feature_scope_id": uuid.uuid4(),
    }
    data.update(overrides)
    return Node(**data)  # type: ignore[arg-type]


# --- SourceRef -----------------------------------------------------------------


def test_source_ref_valid_construction_autopopulates_id_and_fetched_at() -> None:
    ref = make_source_ref()
    assert isinstance(ref.id, uuid.UUID)
    assert ref.fetched_at is not None
    assert ref.excerpt == "We should cache the results to avoid the N+1 query."


def test_source_ref_rejects_empty_excerpt() -> None:
    with pytest.raises(ValidationError):
        make_source_ref(excerpt="")


def test_source_ref_rejects_whitespace_only_excerpt() -> None:
    with pytest.raises(ValidationError):
        make_source_ref(excerpt="   \n\t ")


def test_source_ref_preserves_excerpt_verbatim_for_provenance() -> None:
    """The excerpt is a literal source span the eval harness checks appears
    verbatim in the raw source -- it must not be stripped/mutated."""
    literal = "  leading and trailing spaces are part of the span  "
    ref = make_source_ref(excerpt=literal)
    assert ref.excerpt == literal


def test_source_ref_rejects_empty_url() -> None:
    with pytest.raises(ValidationError):
        make_source_ref(url="")


def test_source_ref_rejects_unknown_source_type() -> None:
    with pytest.raises(ValidationError):
        make_source_ref(source_type="bitbucket_pr")


def test_source_ref_rejects_blank_external_id() -> None:
    with pytest.raises(ValidationError):
        make_source_ref(external_id="   ")


def test_source_ref_forbids_extra_fields() -> None:
    with pytest.raises(ValidationError):
        make_source_ref(hallucinated_field="oops")


# --- Node ----------------------------------------------------------------------


def test_node_valid_construction() -> None:
    node = make_node()
    assert node.type is NodeType.REQUIREMENT
    assert isinstance(node.id, uuid.UUID)


def test_node_without_source_refs_is_structurally_impossible() -> None:
    """The single most important rule in the codebase (CLAUDE.md)."""
    with pytest.raises(ValidationError):
        make_node(source_refs=[])


def test_node_missing_source_refs_field_raises() -> None:
    data = {
        "type": NodeType.GOAL,
        "content": "x",
        "confidence_score": 0.5,
        "workspace_id": uuid.uuid4(),
        "feature_scope_id": uuid.uuid4(),
    }
    with pytest.raises(ValidationError):
        Node(**data)  # type: ignore[arg-type]


def test_node_defaults_to_unconfirmed_status() -> None:
    """Extraction is a draft, never a fact (CLAUDE.md / TRD Sec6)."""
    assert make_node().status is NodeStatus.UNCONFIRMED


def test_node_defaults_to_system_created_by() -> None:
    assert make_node().created_by is CreatedBy.SYSTEM


@pytest.mark.parametrize("score", [-0.1, 1.1, 2.0, -1.0])
def test_node_rejects_confidence_score_out_of_range(score: float) -> None:
    with pytest.raises(ValidationError):
        make_node(confidence_score=score)


@pytest.mark.parametrize("score", [0.0, 1.0, 0.5])
def test_node_accepts_confidence_score_at_and_within_bounds(score: float) -> None:
    assert make_node(confidence_score=score).confidence_score == score


# --- confidence_score is the *machine's* confidence (TRD Sec6) -----------------


def test_system_node_without_a_confidence_score_is_rejected() -> None:
    """An extraction agent that omits the score must fail the gate, not be
    silently stored as unscored."""
    with pytest.raises(ValidationError, match="confidence_score"):
        make_node(created_by=CreatedBy.SYSTEM, confidence_score=None)


def test_manually_added_node_omits_the_confidence_score() -> None:
    """TRD Sec6: manually-added nodes (`created_by: user`) skip confidence
    scoring -- a human assertion isn't a probabilistic guess."""
    node = make_node(created_by=CreatedBy.USER, confidence_score=None)
    assert node.confidence_score is None


def test_manually_added_node_may_not_carry_a_confidence_score() -> None:
    """The inverse of the rule above: allowing a score on a user node would make
    `confidence_score` mean two different things depending on who created it."""
    with pytest.raises(ValidationError, match="confidence_score"):
        make_node(created_by=CreatedBy.USER, confidence_score=0.9)


def test_node_rejects_empty_content() -> None:
    with pytest.raises(ValidationError):
        make_node(content="")


def test_node_rejects_unknown_type() -> None:
    with pytest.raises(ValidationError):
        make_node(type="wishlist_item")


def test_node_forbids_extra_fields_to_catch_hallucinated_output() -> None:
    """Strict validation gate: an extraction agent emitting an unexpected key
    should be rejected, not silently accepted."""
    with pytest.raises(ValidationError):
        make_node(hallucinated_field="oops")


# --- Edge ----------------------------------------------------------------------


def test_edge_valid_construction() -> None:
    edge = Edge(
        from_node_id=uuid.uuid4(),
        to_node_id=uuid.uuid4(),
        relation_type=RelationType.SUPPORTS,
        confidence_score=0.7,
    )
    assert edge.relation_type is RelationType.SUPPORTS


def test_edge_rejects_self_reference() -> None:
    node_id = uuid.uuid4()
    with pytest.raises(ValidationError):
        Edge(
            from_node_id=node_id,
            to_node_id=node_id,
            relation_type=RelationType.CONFLICTS_WITH,
            confidence_score=0.9,
        )


def test_edge_rejects_confidence_score_out_of_range() -> None:
    with pytest.raises(ValidationError):
        Edge(
            from_node_id=uuid.uuid4(),
            to_node_id=uuid.uuid4(),
            relation_type=RelationType.DEPENDS_ON,
            confidence_score=1.5,
        )


@pytest.mark.parametrize("score", [0.0, 1.0, 0.5])
def test_edge_accepts_confidence_score_at_and_within_bounds(score: float) -> None:
    edge = Edge(
        from_node_id=uuid.uuid4(),
        to_node_id=uuid.uuid4(),
        relation_type=RelationType.SUPPORTS,
        confidence_score=score,
    )
    assert edge.confidence_score == score


def test_edge_forbids_extra_fields() -> None:
    with pytest.raises(ValidationError):
        Edge(
            from_node_id=uuid.uuid4(),
            to_node_id=uuid.uuid4(),
            relation_type=RelationType.SUPPORTS,
            confidence_score=0.5,
            hallucinated_field="oops",  # type: ignore[call-arg]
        )


def test_edge_rejects_unknown_relation_type() -> None:
    with pytest.raises(ValidationError):
        Edge(
            from_node_id=uuid.uuid4(),
            to_node_id=uuid.uuid4(),
            relation_type="blocks",  # type: ignore[arg-type]
            confidence_score=0.5,
        )


# --- Event ---------------------------------------------------------------------


def test_event_valid_construction() -> None:
    event = Event(
        event_type=EventType.NODE_CREATED,
        payload={"node_id": str(uuid.uuid4())},
        actor="system",
        workspace_id=uuid.uuid4(),
    )
    assert event.event_type is EventType.NODE_CREATED
    assert event.payload["node_id"]


def test_event_rejects_unknown_event_type() -> None:
    with pytest.raises(ValidationError):
        Event(
            event_type="node_archived",  # type: ignore[arg-type]
            payload={},
            actor="system",
            workspace_id=uuid.uuid4(),
        )


def test_event_rejects_blank_actor() -> None:
    with pytest.raises(ValidationError):
        Event(
            event_type=EventType.INGESTION_RUN,
            payload={},
            actor="   ",
            workspace_id=uuid.uuid4(),
        )


def test_event_forbids_extra_fields() -> None:
    with pytest.raises(ValidationError):
        Event(
            event_type=EventType.INGESTION_RUN,
            payload={},
            actor="system",
            workspace_id=uuid.uuid4(),
            hallucinated_field="oops",  # type: ignore[call-arg]
        )


def test_schema_event_type_is_the_same_enum_storage_uses() -> None:
    """Single source of truth: storage/tables.py must not define its own
    parallel EventType that can silently drift from the schema's."""
    from atlas.storage.tables import EventType as StorageEventType

    assert StorageEventType is EventType


# --- serialization (this is what lands in event_log.payload) -------------------


def test_node_json_round_trips_for_event_payload_storage() -> None:
    """append_event() stores model_dump output as JSONB -- it must be
    json-serializable (UUIDs -> str, datetimes -> ISO, enums -> values)."""
    node = make_node()
    dumped = node.model_dump(mode="json")
    # Must survive a real json.dumps without a custom encoder.
    encoded = json.dumps(dumped)
    reloaded = json.loads(encoded)
    assert reloaded["type"] == "requirement"
    assert reloaded["status"] == "unconfirmed"
    assert reloaded["source_refs"][0]["source_type"] == "github_pr"

    # And it must validate back into an equal Node.
    assert Node.model_validate(dumped) == node
