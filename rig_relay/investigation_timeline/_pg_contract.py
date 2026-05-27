from __future__ import annotations

from rig_relay.investigation_timeline._models import (
    InvestigationTimeline,
    PostgresColumnDefinition,
    PostgresIndexDefinition,
    PostgresTimelineProjection,
)


def build_postgres_projection(
    timeline: InvestigationTimeline,
) -> PostgresTimelineProjection:
    rows: list[dict[str, object]] = []
    for event in timeline.events:
        row: dict[str, object] = {
            "event_id": event.event_id,
            "timeline_sequence": event.timeline_sequence,
            "observed_at": event.observed_at,
            "event_kind": event.event_kind.value,
            "source_domain": event.source_domain.value,
            "source_event_id": event.source_event_id,
            "source_digest": event.source_digest,
            "source_sequence": event.source_sequence,
            "authority_classification": event.authority_classification.value,
            "degradation_detail": event.degradation_detail,
            "session_id": event.session_id,
            "project_id": event.project_id,
            "investigation_id": event.investigation_id,
            "parent_session_id": event.parent_session_id,
            "task_id": event.task_id,
            "operation_id": event.operation_id,
            "outcome": event.outcome,
            "status": event.status,
            "latency_ms": event.latency_ms,
            "path_count": event.path_count,
            "artifact_kind": event.artifact_kind,
            "artifact_sha256": event.artifact_sha256,
            "commit_sha": event.commit_sha,
            "refusal_code": event.refusal_code,
            "producer_digest": event.producer_digest,
            "producer_digest_verified": event.producer_digest_verified,
            "verification_class": event.verification_class.value,
            "content_light_guarantee": True,
        }
        rows.append(row)

    projection = PostgresTimelineProjection(
        timeline_id=timeline.timeline_id,
        rows=rows,
        row_count=len(rows),
        column_definitions=build_postgres_column_definitions(),
        indexing_requirements=build_postgres_indexing_requirements(),
        query_capabilities=build_query_capabilities(),
    )
    return projection


def build_postgres_column_definitions() -> list[PostgresColumnDefinition]:
    return [
        PostgresColumnDefinition(
            column_name="event_id",
            column_type="TEXT PRIMARY KEY",
            nullable=False,
            description="Stable derived event ID.",
        ),
        PostgresColumnDefinition(
            column_name="timeline_sequence",
            column_type="INTEGER NOT NULL",
            nullable=False,
            description="Monotonic position in timeline.",
        ),
        PostgresColumnDefinition(
            column_name="observed_at",
            column_type="TIMESTAMPTZ NOT NULL",
            nullable=False,
            description="ISO 8601 timestamp of event observation.",
        ),
        PostgresColumnDefinition(
            column_name="event_kind",
            column_type="TEXT NOT NULL",
            nullable=False,
            description="Normalized event kind.",
        ),
        PostgresColumnDefinition(
            column_name="source_domain",
            column_type="TEXT NOT NULL",
            nullable=False,
            description="Canonical evidence domain.",
        ),
        PostgresColumnDefinition(
            column_name="source_event_id",
            column_type="TEXT",
            nullable=True,
            description="Original event ID from source domain.",
        ),
        PostgresColumnDefinition(
            column_name="source_digest",
            column_type="TEXT NOT NULL",
            nullable=False,
            description="SHA256 digest of source event/receipt.",
        ),
        PostgresColumnDefinition(
            column_name="source_sequence",
            column_type="INTEGER",
            nullable=True,
            description="Original sequence number.",
        ),
        PostgresColumnDefinition(
            column_name="authority_classification",
            column_type="TEXT NOT NULL",
            nullable=False,
            description="Provenance authority classification.",
        ),
        PostgresColumnDefinition(
            column_name="degradation_detail",
            column_type="TEXT",
            nullable=True,
            description="Degradation explanation.",
        ),
        PostgresColumnDefinition(
            column_name="session_id",
            column_type="TEXT",
            nullable=True,
            description="Session identifier.",
        ),
        PostgresColumnDefinition(
            column_name="project_id",
            column_type="TEXT",
            nullable=True,
            description="Project identifier.",
        ),
        PostgresColumnDefinition(
            column_name="investigation_id",
            column_type="TEXT",
            nullable=True,
            description="Investigation identifier.",
        ),
        PostgresColumnDefinition(
            column_name="parent_session_id",
            column_type="TEXT",
            nullable=True,
            description="Parent session identifier.",
        ),
        PostgresColumnDefinition(
            column_name="task_id",
            column_type="TEXT",
            nullable=True,
            description="Task identifier.",
        ),
        PostgresColumnDefinition(
            column_name="operation_id",
            column_type="TEXT",
            nullable=True,
            description="Exactly-once operation identifier from producer domain.",
        ),
        PostgresColumnDefinition(
            column_name="outcome",
            column_type="TEXT",
            nullable=True,
            description="Outcome label.",
        ),
        PostgresColumnDefinition(
            column_name="status",
            column_type="TEXT",
            nullable=True,
            description="Status label.",
        ),
        PostgresColumnDefinition(
            column_name="latency_ms",
            column_type="DOUBLE PRECISION",
            nullable=True,
            description="Wall-clock latency in milliseconds.",
        ),
        PostgresColumnDefinition(
            column_name="path_count",
            column_type="INTEGER",
            nullable=True,
            description="Number of paths affected.",
        ),
        PostgresColumnDefinition(
            column_name="artifact_kind",
            column_type="TEXT",
            nullable=True,
            description="Artifact kind.",
        ),
        PostgresColumnDefinition(
            column_name="artifact_sha256",
            column_type="TEXT",
            nullable=True,
            description="Artifact SHA256.",
        ),
        PostgresColumnDefinition(
            column_name="commit_sha",
            column_type="TEXT",
            nullable=True,
            description="Git commit SHA.",
        ),
        PostgresColumnDefinition(
            column_name="refusal_code",
            column_type="TEXT",
            nullable=True,
            description="Refusal reason code.",
        ),
        PostgresColumnDefinition(
            column_name="producer_digest",
            column_type="TEXT",
            nullable=True,
            description="Producer's canonical event/receipt digest.",
        ),
        PostgresColumnDefinition(
            column_name="producer_digest_verified",
            column_type="BOOLEAN",
            nullable=True,
            description="Whether the producer digest was cryptographically verified.",
        ),
        PostgresColumnDefinition(
            column_name="verification_class",
            column_type="TEXT NOT NULL",
            nullable=False,
            description="Source verification classification.",
        ),
        PostgresColumnDefinition(
            column_name="content_light_guarantee",
            column_type="BOOLEAN NOT NULL DEFAULT TRUE",
            nullable=False,
            description="Content-light guarantee assertion.",
        ),
    ]


def build_postgres_indexing_requirements() -> list[PostgresIndexDefinition]:
    return [
        PostgresIndexDefinition(
            index_name="idx_timeline_sequence",
            columns=["timeline_sequence"],
            purpose="Ordered chronological scans.",
        ),
        PostgresIndexDefinition(
            index_name="idx_timeline_observed_at",
            columns=["observed_at"],
            purpose="Time-range filtering.",
        ),
        PostgresIndexDefinition(
            index_name="idx_timeline_event_kind",
            columns=["event_kind"],
            purpose="Event-kind filtering (e.g., all refusals, all checkpoints).",
        ),
        PostgresIndexDefinition(
            index_name="idx_timeline_authority_classification",
            columns=["authority_classification"],
            purpose="Authority/degradation filtering.",
        ),
        PostgresIndexDefinition(
            index_name="idx_timeline_session_id",
            columns=["session_id"],
            purpose="Session-scoped queries.",
        ),
        PostgresIndexDefinition(
            index_name="idx_timeline_investigation_id",
            columns=["investigation_id"],
            purpose="Investigation-scoped queries.",
        ),
        PostgresIndexDefinition(
            index_name="idx_timeline_project_id",
            columns=["project_id"],
            purpose="Project-scoped queries.",
        ),
        PostgresIndexDefinition(
            index_name="idx_timeline_outcome",
            columns=["outcome"],
            purpose="Outcome filtering (completed, refused, failed).",
        ),
        PostgresIndexDefinition(
            index_name="idx_timeline_refusal_code",
            columns=["refusal_code"],
            purpose="Refusal reason queries.",
        ),
        PostgresIndexDefinition(
            index_name="idx_timeline_verification_class",
            columns=["verification_class"],
            purpose="Verification-class filtering.",
        ),
        PostgresIndexDefinition(
            index_name="idx_timeline_operation_id",
            columns=["operation_id"],
            purpose="Operation-identity queries.",
        ),
        PostgresIndexDefinition(
            index_name="idx_timeline_kind_observed",
            columns=["event_kind", "observed_at"],
            purpose="Common composite: kind + time range.",
        ),
    ]


def build_query_capabilities() -> list[str]:
    return [
        "chronological timeline by investigation/session/project",
        "event-kind filtering (all refusals, all checkpoints, all tool calls)",
        "authority/degradation filtering (only CANONICAL_LIVE, only MISSING, etc.)",
        "time-range queries",
        "outcome aggregation (completed vs. refused vs. failed)",
        "refusal rate computation per domain/kind",
        "tool-outcome distribution",
        "investigation duration computation",
        "degradation incidence reporting",
        "checkpoint commit/refusal reporting",
        "publication preview trajectory",
        "source digest provenance tracing",
    ]
