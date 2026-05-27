from __future__ import annotations

from rig_relay.investigation_timeline._degradation import (
    build_contradictory_evidence_event,
    build_degradation_marker,
    build_degraded_evidence_event,
    build_missing_evidence_event,
    detect_degradation,
)
from rig_relay.investigation_timeline._models import (
    AuthorityClassification,
    InvestigationTimelineEvent,
    SourceDomain,
    TimelineEventKind,
)


def test_build_missing_evidence_event():
    event = build_missing_evidence_event(
        domain=SourceDomain.OBSERVABILITY,
        detail="observability file not found on disk",
        investigation_id="inv-miss-001",
    )
    assert event.event_kind == TimelineEventKind.EVIDENCE_MISSING
    assert event.authority_classification == AuthorityClassification.MISSING
    assert event.source_domain == SourceDomain.TIMELINE_DEGRADED
    assert event.degradation_detail == "observability file not found on disk"
    assert event.investigation_id == "inv-miss-001"
    assert event.source_digest.startswith("sha256:")


def test_build_degraded_evidence_event():
    event = build_degraded_evidence_event(
        domain=SourceDomain.COORDINATION,
        detail="coordination events file is corrupt",
        investigation_id="inv-deg-001",
        session_id="s-1",
    )
    assert event.event_kind == TimelineEventKind.EVIDENCE_DEGRADED
    assert event.authority_classification == AuthorityClassification.CANONICAL_DEGRADED
    assert event.source_domain == SourceDomain.TIMELINE_DEGRADED
    assert event.degradation_detail == "coordination events file is corrupt"
    assert event.investigation_id == "inv-deg-001"
    assert event.session_id == "s-1"


def test_build_contradictory_evidence_event():
    event = build_contradictory_evidence_event(
        domain=SourceDomain.DISCLOSURE,
        detail="two sources disagree on refusal count",
        investigation_id="inv-con-001",
    )
    assert event.event_kind == TimelineEventKind.EVIDENCE_CONTRADICTORY
    assert event.authority_classification == AuthorityClassification.CONTRADICTORY
    assert event.source_domain == SourceDomain.TIMELINE_DEGRADED
    assert event.degradation_detail == "two sources disagree on refusal count"


def test_detect_degradation_on_mixed_events():
    canonical = InvestigationTimelineEvent(
        observed_at="2025-01-15T10:00:00Z",
        event_kind=TimelineEventKind.TOOL_CALL_COMPLETED,
        source_domain=SourceDomain.OBSERVABILITY,
        source_digest="sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        authority_classification=AuthorityClassification.CANONICAL_LIVE,
    )
    missing = InvestigationTimelineEvent(
        observed_at="2025-01-15T10:00:05Z",
        event_kind=TimelineEventKind.EVIDENCE_MISSING,
        source_domain=SourceDomain.TIMELINE_DEGRADED,
        source_digest="sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
        authority_classification=AuthorityClassification.MISSING,
    )
    contradictory = InvestigationTimelineEvent(
        observed_at="2025-01-15T10:00:10Z",
        event_kind=TimelineEventKind.EVIDENCE_CONTRADICTORY,
        source_domain=SourceDomain.TIMELINE_DEGRADED,
        source_digest="sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
        authority_classification=AuthorityClassification.CONTRADICTORY,
    )

    events = [canonical, canonical, missing, canonical, contradictory]
    markers = detect_degradation(events)
    assert len(markers) == 2
    degradation_kinds = {m.degradation_kind for m in markers}
    assert "missing" in degradation_kinds
    assert "contradictory" in degradation_kinds


def test_build_degradation_marker():
    marker = build_degradation_marker(
        degradation_kind="missing",
        source_domain=SourceDomain.OBSERVABILITY,
        detail="file not found",
        source_event_id="evt_missing_01",
    )
    assert marker.degradation_kind == "missing"
    assert marker.source_domain == SourceDomain.OBSERVABILITY
    assert marker.detail == "file not found"
    assert marker.source_event_id == "evt_missing_01"
    assert marker.observed_at
