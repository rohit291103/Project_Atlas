"""Core data-model entities (Pydantic v2), mirroring TRD Sec3.1 exactly.

This module is the project's validation gate. Per CLAUDE.md's Engineering
Philosophy, extraction output must pass through these models before anything
is persisted -- so the rules that matter (provenance present, confidence in
range, no unknown fields) are enforced structurally here, not by convention
downstream. `extra="forbid"` is deliberate: an extraction agent that emits an
unexpected key should be rejected, not silently truncated.

Enums use the exact lowercase string values from TRD Sec3.1. `EventType` is
defined here (not in storage/) because the schema is the single source of
truth; storage/tables.py imports it so the Postgres enum can never drift from
the domain definition.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Any

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _reject_blank(value: str) -> str:
    if not value.strip():
        raise ValueError("must not be blank or whitespace-only")
    return value  # returned unchanged -- an excerpt's provenance must stay verbatim


#: A required string that cannot be empty *or* whitespace-only. `min_length=1`
#: alone lets `"   "` through, which is how a blank claim or an unattributed audit
#: record gets stored. Defined once and reused so the rule cannot drift between
#: the entities, the event payloads, and the API request bodies that all rely on
#: it -- `api/` reuses this rather than re-deriving the check at the wire.
NonBlankStr = Annotated[str, Field(min_length=1), AfterValidator(_reject_blank)]


class AtlasModel(BaseModel):
    """Shared config for every entity: reject unknown fields at the gate."""

    model_config = ConfigDict(extra="forbid")


# --- enums (TRD Sec3.1) --------------------------------------------------------


class SourceType(StrEnum):
    """Where a Node's evidence lives.

    Every member but the last points *outward*, at an artifact in a connected
    tool. `HUMAN_ASSERTION` is the one that points at a person: it is the
    provenance of a node a human typed directly into Atlas (PRD R10 -- "a
    constraint mentioned verbally in a meeting"), where no artifact exists to
    cite. It is an addition to TRD Sec3.1's list, made deliberately -- see
    `docs/decisions/2026-08-03-manual-node-provenance.md`.

    Without it, PRD R10 and CLAUDE.md's zero-exception "every Node carries a
    SourceRef" rule are jointly unsatisfiable, and the way that resolves in
    practice is a user pasting an unrelated URL to get past a required field --
    fabricated provenance, which is worse than none because it is
    indistinguishable from the real thing.
    """

    GITHUB_PR = "github_pr"
    GITHUB_ISSUE = "github_issue"
    GITHUB_COMMIT = "github_commit"
    JIRA_TICKET = "jira_ticket"
    NOTION_PAGE = "notion_page"
    GDOC = "gdoc"
    HUMAN_ASSERTION = "human_assertion"


class NodeType(StrEnum):
    GOAL = "goal"
    PROBLEM = "problem"
    EVIDENCE = "evidence"
    DECISION = "decision"
    REQUIREMENT = "requirement"
    CONSTRAINT = "constraint"
    ARCHITECTURE_NOTE = "architecture_note"
    OPEN_QUESTION = "open_question"
    REJECTED_ALTERNATIVE = "rejected_alternative"


class NodeStatus(StrEnum):
    UNCONFIRMED = "unconfirmed"
    CONFIRMED = "confirmed"
    EDITED = "edited"
    REJECTED = "rejected"


class CreatedBy(StrEnum):
    SYSTEM = "system"
    USER = "user"


class RelationType(StrEnum):
    SUPPORTS = "supports"
    DERIVES_FROM = "derives_from"
    CONFLICTS_WITH = "conflicts_with"
    IMPLEMENTS = "implements"
    REJECTS = "rejects"
    DEPENDS_ON = "depends_on"


class Role(StrEnum):
    """What a member may do in a workspace (TRD Sec9 -- RBAC at workspace level).

    Three roles, and the split that matters is `VIEWER` vs. the rest: a viewer
    can read the extracted draft but cannot rule on it. That is the distinction
    the product actually needs, because a confirmation *is* the product's unit of
    truth -- "extraction is a draft until a human acts on it" means little if any
    reader can act. `ADMIN` differs from `EDITOR` only in managing the workspace
    itself (members, and connected sources when that surface arrives).

    Feature-level scoping is explicitly Phase 4 (TRD Sec9); this is the workspace
    -level MVP and nothing more.
    """

    ADMIN = "admin"
    EDITOR = "editor"
    VIEWER = "viewer"

    @property
    def can_write(self) -> bool:
        """Whether this role may confirm, edit, reject or add a claim."""
        return self is not Role.VIEWER


class EventType(StrEnum):
    """Matches TRD Sec3.1 Event.event_type. storage/tables.py imports this."""

    NODE_CREATED = "node_created"
    NODE_CONFIRMED = "node_confirmed"
    NODE_EDITED = "node_edited"
    NODE_REJECTED = "node_rejected"
    EDGE_CREATED = "edge_created"
    SPEC_EXPORTED = "spec_exported"
    INGESTION_RUN = "ingestion_run"


# --- entities ------------------------------------------------------------------


class SourceRef(AtlasModel):
    """A literal, provenance-bearing pointer into a source document (TRD Sec3.1).

    `excerpt` is the specific text span that supports an extraction and is never
    stripped or normalized -- the eval harness verifies it appears verbatim in
    the raw source, so any mutation here would corrupt provenance.
    """

    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    source_type: SourceType
    external_id: NonBlankStr
    url: NonBlankStr
    excerpt: NonBlankStr
    fetched_at: datetime = Field(default_factory=_utcnow)
    workspace_id: uuid.UUID


class Node(AtlasModel):
    """A typed knowledge element (TRD Sec3.1).

    `source_refs` requires at least one entry: a Node without provenance is
    structurally impossible to construct, per CLAUDE.md's non-negotiable rule.
    """

    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    type: NodeType
    content: NonBlankStr
    #: The *machine's* confidence in an extraction, so it exists only for
    #: system-extracted nodes -- see `_confidence_score_belongs_to_extraction`.
    confidence_score: float | None = Field(default=None, ge=0.0, le=1.0)
    status: NodeStatus = NodeStatus.UNCONFIRMED
    source_refs: list[SourceRef] = Field(min_length=1)
    created_by: CreatedBy = CreatedBy.SYSTEM
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)
    updated_by: str | None = None
    workspace_id: uuid.UUID
    feature_scope_id: uuid.UUID

    @model_validator(mode="after")
    def _confidence_score_belongs_to_extraction(self) -> Node:
        """`confidence_score` is present exactly when the system extracted the
        node (TRD Sec6: manually-added nodes skip confidence scoring).

        Both directions are enforced. Requiring it on `system` nodes keeps an
        agent that omits the field from being stored as unscored; forbidding it
        on `user` nodes keeps the field meaning one thing -- how confident the
        extractor was -- rather than silently becoming "how sure the human felt"
        on some rows. Editing a system node does not change `created_by`, so an
        edited node keeps the score its extraction earned.
        """
        if self.created_by is CreatedBy.SYSTEM and self.confidence_score is None:
            raise ValueError("confidence_score is required for system-extracted nodes")
        if self.created_by is CreatedBy.USER and self.confidence_score is not None:
            raise ValueError("confidence_score must be omitted for manually-added nodes")
        return self


class Edge(AtlasModel):
    """A typed relationship between two Nodes (TRD Sec3.1)."""

    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    from_node_id: uuid.UUID
    to_node_id: uuid.UUID
    relation_type: RelationType
    confidence_score: float = Field(ge=0.0, le=1.0)
    created_at: datetime = Field(default_factory=_utcnow)

    @model_validator(mode="after")
    def _reject_self_reference(self) -> Edge:
        if self.from_node_id == self.to_node_id:
            raise ValueError("from_node_id and to_node_id must differ (no self-referential edge)")
        return self


class NodeStatusChangePayload(AtlasModel):
    """Payload of a `node_confirmed` or `node_rejected` Event (TRD Sec6).

    Both actions say the same thing structurally -- "a human ruled on this node"
    -- and carry no new content, so they share a payload. *Who* ruled and *when*
    are not repeated here: they're the Event's own `actor`/`timestamp`, and
    duplicating them into the payload would let the two disagree.
    """

    node_id: uuid.UUID


class NodeEditPayload(AtlasModel):
    """Payload of a `node_edited` Event (TRD Sec6).

    Carries `previous_content` -- the content this edit replaced -- alongside the
    new `content`. A projection holds only current state, so the before-image has
    to live in the event itself; that is what makes an edit auditable rather than
    a silent overwrite. `previous_content` is the value that was actually current
    when the edit happened, not the system-extracted original: walking the chain
    of `node_edited` events back to the `node_created` that started it recovers
    the original (TRD Sec6), and no single event claims a before-image that was
    never true.

    Only `content` is editable. Re-typing a node (goal -> constraint) or altering
    its provenance are separate questions the confirmation UX (slice 1B) hasn't
    answered yet; adding an optional field to this payload later replays cleanly
    over events written today, whereas guessing now does not.
    """

    node_id: uuid.UUID
    content: NonBlankStr
    previous_content: NonBlankStr


class ToolCallRecord(AtlasModel):
    """One tool call an extraction run made -- or was refused (TRD Sec9 audit).

    `Phase0_Architecture.md` Sec2 lists "every tool call is logged" as a guardrail
    alongside the call cap, and it was the one guardrail not implemented
    (`docs/decisions/2026-07-28-extraction-tool-call-audit-logging.md`). Without
    it the read-only, least-privilege promise is *enforced* by the permission
    gate but not **observable after the fact**, and observability is the whole
    point of a guardrail someone else has to trust.

    `allowed = False` entries are the valuable ones: they are the record of the
    gate actually refusing something. Arguments are the agent's own (an issue
    number, a search string) -- never credentials, which live in the client and
    never pass through a tool call.
    """

    tool: NonBlankStr
    arguments: dict[str, Any] = Field(default_factory=dict)
    allowed: bool


class IngestionRunPayload(AtlasModel):
    """Payload of an `ingestion_run` Event -- what a feature scope *is*.

    A feature scope is minted as a bare UUID by whatever triggers ingestion, and
    without this event the log records only that some nodes share that UUID:
    nothing names the feature, so the confirmation UI's left rail and page header
    have nothing to render and a reviewer navigates by raw UUID
    (`docs/architecture/Phase1_Architecture.md` Sec4.4).

    Scope identity therefore lives *in the event log*, like everything else --
    not in a registry table or a name map inside the API. `title` is the
    human-facing name of the feature (the PR/issue title, as fetched); the
    `source_type`/`external_id`/`url` triple is the provenance of the run itself,
    the same shape a `SourceRef` carries for a Node. `external_id` fully
    qualifies the artifact within its source (`owner/repo#111`, not `111`),
    because a feature scope is workspace-global while a bare PR number is only
    unique inside one repository.

    One scope can be fed by many runs -- that is the cross-source thesis (a
    feature assembled from GitHub *and* Jira), so the projection accumulates them
    rather than replacing. Slice 1D's per-run tool-call manifest
    (`docs/decisions/2026-07-28-extraction-tool-call-audit-logging.md`) lands
    here as an optional field, which replays cleanly over events written today;
    `extra="forbid"` means it arrives declared rather than smuggled in.
    """

    feature_scope_id: uuid.UUID
    title: NonBlankStr
    source_type: SourceType
    external_id: NonBlankStr
    url: NonBlankStr
    #: The run's tool-call manifest. Optional with an empty default, exactly as
    #: slice 1A' planned for: events written before slice 1D carry no manifest and
    #: still replay cleanly, and no backfill invents calls that were never made.
    tool_calls: list[ToolCallRecord] = Field(default_factory=list)


class Event(AtlasModel):
    """An append-only log entry -- the source of truth (TRD Sec3.1, Sec3.2).

    `payload` is an opaque JSON object here; for node/edge events it carries the
    `model_dump()` of an already-validated Node/Edge (see storage.append_event),
    and for confirmation events the dump of a `NodeStatusChangePayload` /
    `NodeEditPayload`.
    """

    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    event_type: EventType
    payload: dict[str, Any] = Field(default_factory=dict)
    actor: NonBlankStr
    timestamp: datetime = Field(default_factory=_utcnow)
    workspace_id: uuid.UUID
