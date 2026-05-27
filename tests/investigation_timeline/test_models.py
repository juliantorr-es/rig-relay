from __future__ import annotations

from pydantic import ValidationError
import pytest

from rig_relay.investigation_timeline._models import (
    AuthorityClassification,
    DegradationSummary,
    DuckDBAuthorityAssertion,
    InvestigationTimeline,
    InvestigationTimelineEvent,
    PostgresTimelineProjection,
    SourceDomain,
    TimelineEventKind,
    VerificationClass,
)


def test_investigation_timeline_event_creates_valid():
    event = InvestigationTimelineEvent(
        observed_at="2025-01-15T10:00:00Z",
        event_kind=TimelineEventKind.TOOL_CALL_COMPLETED,
        source_domain=SourceDomain.OBSERVABILITY,
        source_digest="sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        authority_classification=AuthorityClassification.CANONICAL_LIVE,
    )
    assert event.event_id.startswith("tle_")
    assert event.observed_at == "2025-01-15T10:00:00Z"
    assert event.event_kind == TimelineEventKind.TOOL_CALL_COMPLETED
    assert event.source_domain == SourceDomain.OBSERVABILITY
    assert event.authority_classification == AuthorityClassification.CANONICAL_LIVE
    assert event.content_light_guarantee is True
    assert event.timeline_sequence == 0


def test_investigation_timeline_event_compute_digest_is_deterministic():
    event1 = InvestigationTimelineEvent(
        observed_at="2025-01-15T10:00:00Z",
        event_kind=TimelineEventKind.TOOL_CALL_COMPLETED,
        source_domain=SourceDomain.OBSERVABILITY,
        source_digest="sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        authority_classification=AuthorityClassification.CANONICAL_LIVE,
    )
    event2 = InvestigationTimelineEvent(
        observed_at="2025-01-15T10:00:00Z",
        event_kind=TimelineEventKind.TOOL_CALL_COMPLETED,
        source_domain=SourceDomain.OBSERVABILITY,
        source_digest="sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        authority_classification=AuthorityClassification.CANONICAL_LIVE,
    )
    digest1 = event1.compute_digest()
    digest2 = event2.compute_digest()
    assert digest1 == digest2
    assert digest1.startswith("sha256:")
    assert len(digest1) == 71


def test_investigation_timeline_event_rejects_invalid_authority():
    with pytest.raises(ValidationError):
        InvestigationTimelineEvent.model_validate({
            "observed_at": "2025-01-15T10:00:00Z",
            "event_kind": "TOOL_CALL_COMPLETED",
            "source_domain": "observability",
            "source_digest": "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "authority_classification": "INVALID_AUTHORITY",
        })


def test_investigation_timeline_assembles():
    events = [
        InvestigationTimelineEvent(
            observed_at="2025-01-15T10:00:00Z",
            event_kind=TimelineEventKind.SESSION_STARTED,
            source_domain=SourceDomain.OBSERVABILITY,
            source_digest="sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            authority_classification=AuthorityClassification.CANONICAL_LIVE,
        ),
        InvestigationTimelineEvent(
            observed_at="2025-01-15T10:00:05Z",
            event_kind=TimelineEventKind.TOOL_CALL_COMPLETED,
            source_domain=SourceDomain.OBSERVABILITY,
            source_digest="sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
            authority_classification=AuthorityClassification.CANONICAL_LIVE,
        ),
    ]
    for i, e in enumerate(events):
        e.timeline_sequence = i
    timeline = InvestigationTimeline(
        investigation_id="inv-001",
        events=events,
        event_count=len(events),
        domain_coverage={"observability": 2},
    )
    assert timeline.investigation_id == "inv-001"
    assert timeline.event_count == 2
    assert len(timeline.events) == 2
    assert timeline.domain_coverage == {"observability": 2}
    assert timeline.projection_digest is None


def test_degradation_summary_defaults():
    summary = DegradationSummary()
    assert summary.total_events == 0
    assert summary.canonical_live_count == 0
    assert summary.verified_canonical_count == 0
    assert summary.parsed_unverified_count == 0
    assert summary.canonical_degraded_count == 0
    assert summary.missing_count == 0
    assert summary.contradictory_count == 0
    assert summary.corrupt_count == 0
    assert summary.stale_count == 0


def test_timeline_duckdb_export_authority_separation_assertions():
    authority = DuckDBAuthorityAssertion()
    assert authority.read_side_only is True
    assert authority.mutation_authority is False
    assert authority.derived_from == "canonical evidence ledgers"
    assert "export" in authority.rebuild_procedure.lower()


def test_postgres_timeline_projection_authority_separation():
    event = InvestigationTimelineEvent(
        observed_at="2025-01-15T10:00:00Z",
        event_kind=TimelineEventKind.TOOL_CALL_COMPLETED,
        source_domain=SourceDomain.OBSERVABILITY,
        source_digest="sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        authority_classification=AuthorityClassification.CANONICAL_LIVE,
    )
    timeline = InvestigationTimeline(
        events=[event], event_count=1, investigation_id="inv-001"
    )
    projection = PostgresTimelineProjection(
        timeline_id=timeline.timeline_id, rows=[], row_count=0
    )
    authority_str = projection.authority_separation
    assert isinstance(authority_str, str)
    assert len(authority_str) > 0
    assert "derived_projection" in authority_str
    assert "canonical evidence" in authority_str.lower()


def test_timeline_event_kind_enum_covers_degradation():
    assert hasattr(TimelineEventKind, "EVIDENCE_DEGRADED")
    assert hasattr(TimelineEventKind, "EVIDENCE_MISSING")
    assert hasattr(TimelineEventKind, "EVIDENCE_CONTRADICTORY")
    assert TimelineEventKind.EVIDENCE_DEGRADED.value == "EVIDENCE_DEGRADED"
    assert TimelineEventKind.EVIDENCE_MISSING.value == "EVIDENCE_MISSING"
    assert TimelineEventKind.EVIDENCE_CONTRADICTORY.value == "EVIDENCE_CONTRADICTORY"


def test_verification_class_enum_exists():
    assert hasattr(VerificationClass, "VERIFIED_CANONICAL")
    assert hasattr(VerificationClass, "PARSED_UNVERIFIED")
    assert hasattr(VerificationClass, "CANONICAL_DEGRADED")
    assert hasattr(VerificationClass, "CORRUPT")
    assert hasattr(VerificationClass, "UNSUPPORTED")
    assert hasattr(VerificationClass, "MISSING")
    assert VerificationClass.VERIFIED_CANONICAL.value == "VERIFIED_CANONICAL"
    assert VerificationClass.PARSED_UNVERIFIED.value == "PARSED_UNVERIFIED"


def test_investigation_timeline_event_has_producer_digest_field():
    event = InvestigationTimelineEvent(
        observed_at="2025-01-15T10:00:00Z",
        event_kind=TimelineEventKind.TOOL_CALL_COMPLETED,
        source_domain=SourceDomain.OBSERVABILITY,
        source_digest="sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        authority_classification=AuthorityClassification.CANONICAL_LIVE,
        producer_digest="sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
    )
    assert (
        event.producer_digest
        == "sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"
    )


def test_verification_class_defaults_to_parsed_unverified():
    event = InvestigationTimelineEvent(
        observed_at="2025-01-15T10:00:00Z",
        event_kind=TimelineEventKind.TOOL_CALL_COMPLETED,
        source_domain=SourceDomain.OBSERVABILITY,
        source_digest="sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        authority_classification=AuthorityClassification.CANONICAL_LIVE,
    )
    assert event.verification_class == VerificationClass.PARSED_UNVERIFIED


def test_investigation_timeline_event_accepts_operation_id():
    event = InvestigationTimelineEvent(
        observed_at="2025-01-15T10:00:00Z",
        event_kind=TimelineEventKind.PUBLICATION_PREVIEW_COMPILED,
        source_domain=SourceDomain.PUBLICATION,
        source_digest="sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        authority_classification=AuthorityClassification.CANONICAL_LIVE,
        operation_id="op_001",
    )
    assert event.operation_id == "op_001"
