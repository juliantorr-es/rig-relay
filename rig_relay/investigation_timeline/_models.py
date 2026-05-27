from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
import hashlib
import uuid

from pydantic import BaseModel, ConfigDict, Field


class TimelineEventKind(StrEnum):
    SESSION_STARTED = "SESSION_STARTED"
    SESSION_REGISTERED = "SESSION_REGISTERED"
    SESSION_HEARTBEAT = "SESSION_HEARTBEAT"
    SESSION_CLOSED = "SESSION_CLOSED"

    TOOL_CALL_COMPLETED = "TOOL_CALL_COMPLETED"
    TOOL_CALL_REFUSED = "TOOL_CALL_REFUSED"
    TOOL_CALL_FAILED = "TOOL_CALL_FAILED"

    COORDINATION_TASK_CLAIMED = "COORDINATION_TASK_CLAIMED"
    COORDINATION_TASK_RELEASED = "COORDINATION_TASK_RELEASED"
    COORDINATION_PATH_RESERVED = "COORDINATION_PATH_RESERVED"
    COORDINATION_PATH_RELEASED = "COORDINATION_PATH_RELEASED"
    COORDINATION_CONFLICT_REPORTED = "COORDINATION_CONFLICT_REPORTED"
    COORDINATION_RESERVATION_REFUSED = "COORDINATION_RESERVATION_REFUSED"
    COORDINATION_ARTIFACT_PUBLISHED = "COORDINATION_ARTIFACT_PUBLISHED"
    COORDINATION_HANDOFF_REQUESTED = "COORDINATION_HANDOFF_REQUESTED"
    COORDINATION_HANDOFF_ACCEPTED = "COORDINATION_HANDOFF_ACCEPTED"
    COORDINATION_HANDOFF_REJECTED = "COORDINATION_HANDOFF_REJECTED"
    COORDINATION_PROJECTION_READ = "COORDINATION_PROJECTION_READ"
    COORDINATION_LEASE_EXPIRED = "COORDINATION_LEASE_EXPIRED"
    COORDINATION_LEASE_STALE = "COORDINATION_LEASE_STALE"

    CHECKPOINT_COMMITTED = "CHECKPOINT_COMMITTED"
    CHECKPOINT_REFUSED = "CHECKPOINT_REFUSED"

    PUBLICATION_PREVIEW_COMPILED = "PUBLICATION_PREVIEW_COMPILED"
    PUBLICATION_PREVIEW_REFUSED = "PUBLICATION_PREVIEW_REFUSED"

    DISCLOSURE_TRANSITION_INITIATED = "DISCLOSURE_TRANSITION_INITIATED"
    DISCLOSURE_TRANSITION_ADVANCED = "DISCLOSURE_TRANSITION_ADVANCED"
    DISCLOSURE_TRANSITION_COMPLETED = "DISCLOSURE_TRANSITION_COMPLETED"
    DISCLOSURE_TRANSITION_REFUSED = "DISCLOSURE_TRANSITION_REFUSED"

    AUTHORIZATION_REQUESTED = "AUTHORIZATION_REQUESTED"
    AUTHORIZATION_GRANTED = "AUTHORIZATION_GRANTED"
    AUTHORIZATION_REFUSED = "AUTHORIZATION_REFUSED"

    GOVERNANCE_DECISION_RECORDED = "GOVERNANCE_DECISION_RECORDED"
    AUDIT_EVENT_RECORDED = "AUDIT_EVENT_RECORDED"
    OBSERVATION_CAPTURED = "OBSERVATION_CAPTURED"
    RALPH_SCAN_COMPLETED = "RALPH_SCAN_COMPLETED"
    CONTEXT_ASSEMBLY_REPORTED = "CONTEXT_ASSEMBLY_REPORTED"
    STORAGE_LIFECYCLE_EVENT = "STORAGE_LIFECYCLE_EVENT"

    EVIDENCE_DEGRADED = "EVIDENCE_DEGRADED"
    EVIDENCE_MISSING = "EVIDENCE_MISSING"
    EVIDENCE_CONTRADICTORY = "EVIDENCE_CONTRADICTORY"
    EVIDENCE_CORRUPT = "EVIDENCE_CORRUPT"
    EVIDENCE_UNVERIFIED = "EVIDENCE_UNVERIFIED"
    EVIDENCE_UNSUPPORTED = "EVIDENCE_UNSUPPORTED"


class AuthorityClassification(StrEnum):
    CANONICAL_LIVE = "CANONICAL_LIVE"
    CANONICAL_DEGRADED = "CANONICAL_DEGRADED"
    CONTROLLED_BOUNDARY = "CONTROLLED_BOUNDARY"
    FIXTURE_DEFERRED = "FIXTURE_DEFERRED"
    MISSING = "MISSING"
    STALE = "STALE"
    CORRUPT = "CORRUPT"
    CONTRADICTORY = "CONTRADICTORY"


class VerificationClass(StrEnum):
    """How the timeline event's relationship to its canonical source was verified."""

    VERIFIED_CANONICAL = "VERIFIED_CANONICAL"
    PARSED_UNVERIFIED = "PARSED_UNVERIFIED"
    CANONICAL_DEGRADED = "CANONICAL_DEGRADED"
    CORRUPT = "CORRUPT"
    UNSUPPORTED = "UNSUPPORTED"
    MISSING = "MISSING"


class SourceDomain(StrEnum):
    OBSERVABILITY = "observability"
    COORDINATION = "coordination"
    RECEIPT_STORE = "receipt_store"
    AUDIT_TRAIL = "audit_trail"
    DISCLOSURE = "disclosure"
    CHECKPOINT = "checkpoint"
    PUBLICATION = "publication"
    TOOL_RECEIPT_INDEX = "tool_receipt_index"
    RALPH = "ralph"
    GOVERNANCE = "governance"
    STORAGE_LIFECYCLE = "storage_lifecycle"
    TIMELINE_DEGRADED = "timeline_degraded"


class InvestigationTimelineEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(
        default="rig.relay.investigation_timeline_event.v1", frozen=True
    )
    event_id: str = Field(
        default_factory=lambda: f"tle_{uuid.uuid4().hex[:16]}",
        pattern=r"^tle_[a-f0-9]{16}$",
    )
    timeline_sequence: int = Field(default=0, ge=0)
    observed_at: str = Field()
    event_kind: TimelineEventKind
    source_domain: SourceDomain
    source_event_id: str | None = Field(default=None)
    source_digest: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    source_sequence: int | None = Field(default=None)
    producer_digest: str | None = Field(
        default=None, pattern=r"^(sha256:[a-f0-9]{64})?$"
    )
    producer_digest_verified: bool = Field(default=False)
    verification_class: VerificationClass = Field(
        default=VerificationClass.PARSED_UNVERIFIED
    )
    authority_classification: AuthorityClassification = Field()
    degradation_detail: str | None = Field(default=None)
    session_id: str | None = Field(default=None)
    project_id: str | None = Field(default=None)
    investigation_id: str | None = Field(default=None)
    parent_session_id: str | None = Field(default=None)
    task_id: str | None = Field(default=None)
    operation_id: str | None = Field(default=None)
    outcome: str | None = Field(default=None)
    status: str | None = Field(default=None)
    latency_ms: float | None = Field(default=None)
    path_count: int | None = Field(default=None)
    artifact_kind: str | None = Field(default=None)
    artifact_sha256: str | None = Field(default=None, pattern=r"^sha256:[a-f0-9]{64}$")
    commit_sha: str | None = Field(default=None, pattern=r"^[a-f0-9]{7,40}$")
    refusal_code: str | None = Field(default=None)
    content_light_guarantee: bool = Field(default=True, frozen=True)

    def compute_digest(self) -> str:
        fields = self.model_dump(exclude={"event_id"}, exclude_none=True)
        fields.pop("content_light_guarantee", None)
        canonical = _canonicalize_json(fields)
        return f"sha256:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}"


class InvestigationTimeline(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(
        default="rig.relay.investigation_timeline_projection.v1", frozen=True
    )
    timeline_id: str = Field(
        default_factory=lambda: f"tl_{uuid.uuid4().hex[:16]}",
        pattern=r"^tl_[a-f0-9]{16}$",
    )
    investigation_id: str | None = Field(default=None)
    session_id: str | None = Field(default=None)
    project_id: str | None = Field(default=None)
    assembled_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    evidence_freshness_cutoff: str | None = Field(default=None)
    events: list[InvestigationTimelineEvent] = Field(default_factory=list)
    event_count: int = Field(default=0)
    domain_coverage: dict[str, int] = Field(default_factory=dict)
    unsupported_domains: list[str] = Field(default_factory=list)
    degradation_summary: DegradationSummary = Field(
        default_factory=lambda: DegradationSummary()
    )
    content_light_guarantee: bool = Field(default=True, frozen=True)
    projection_digest: str | None = Field(default=None)

    def compute_projection_digest(self) -> str:
        events_serialized = [
            e.model_dump(exclude={"event_id", "timeline_sequence"}, exclude_none=True)
            for e in self.events
        ]
        payload = {
            "schema_version": self.schema_version,
            "timeline_id": self.timeline_id,
            "assembled_at": self.assembled_at,
            "event_count": len(self.events),
            "events": events_serialized,
        }
        canonical = _canonicalize_json(payload)
        return f"sha256:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}"


class DegradationSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total_events: int = 0
    verified_canonical_count: int = 0
    parsed_unverified_count: int = 0
    canonical_degraded_count: int = 0
    corrupt_count: int = 0
    unsupported_count: int = 0
    missing_count: int = 0
    contradictory_count: int = 0
    stale_count: int = 0
    canonical_live_count: int = 0


class TimelineEvidenceSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_domain: SourceDomain
    source_path: str | None = None
    events_ingested: int = 0
    errors: int = 0
    schema_version: str | None = None
    status: str = "ok"
    producer_digests_verified: int = 0


class TimelineAssemblyResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timeline: InvestigationTimeline
    sources: list[TimelineEvidenceSource] = Field(default_factory=list)
    assembly_duration_ms: float | None = None
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class TimelineDegradationMarker(BaseModel):
    model_config = ConfigDict(extra="forbid")

    degradation_kind: str
    source_domain: SourceDomain | None = None
    detail: str
    source_event_id: str | None = None
    observed_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


class PostgresTimelineProjection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "rig.relay.investigation_timeline_postgres_projection.v1"
    projection_id: str = Field(default_factory=lambda: f"pgp_{uuid.uuid4().hex[:16]}")
    timeline_id: str
    generated_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    rows: list[dict[str, object]] = Field(default_factory=list)
    row_count: int = 0
    column_definitions: list[PostgresColumnDefinition] = Field(default_factory=list)
    indexing_requirements: list[PostgresIndexDefinition] = Field(default_factory=list)
    query_capabilities: list[str] = Field(default_factory=list)
    authority_separation: str = (
        "derived_projection: this is a disposable read-side projection. "
        "Canonical evidence ledgers remain the sole authority. "
        "This projection may be rebuilt at any time from canonical evidence."
    )
    content_light_guarantee: bool = Field(default=True, frozen=True)


class PostgresColumnDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    column_name: str
    column_type: str
    nullable: bool = True
    description: str = ""


class PostgresIndexDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    index_name: str
    columns: list[str]
    index_type: str = "btree"
    unique: bool = False
    purpose: str = ""


class DuckDBAuthorityAssertion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    read_side_only: bool = Field(default=True, frozen=True)
    mutation_authority: bool = Field(default=False, frozen=True)
    derived_from: str = "canonical evidence ledgers"
    rebuild_procedure: str = (
        "run InvestigationEvidenceTimelineService.export_duckdb_dataset()"
    )


class DuckDBDatasetDescriptor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset_name: str
    relative_path: str
    row_count: int = 0
    dataset_sha256: str = ""
    schema_version: str | None = None
    description: str = ""


class DuckDBViewDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    view_name: str
    sql: str
    purpose: str
    query_example: str | None = None


class TimelineDuckDBExport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "rig.relay.investigation_timeline_duckdb_export.v1"
    export_id: str = Field(default_factory=lambda: f"dde_{uuid.uuid4().hex[:16]}")
    timeline_id: str | None = None
    generated_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    datasets: list[DuckDBDatasetDescriptor] = Field(default_factory=list)
    row_counts: dict[str, int] = Field(default_factory=dict)
    view_definitions: list[DuckDBViewDefinition] = Field(default_factory=list)
    authority_separation: DuckDBAuthorityAssertion = Field(
        default_factory=DuckDBAuthorityAssertion
    )
    content_light_guarantee: bool = Field(default=True, frozen=True)
    rebuildable: bool = Field(default=True, frozen=True)


def _canonicalize_json(obj: object) -> str:
    import json

    return json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str)
