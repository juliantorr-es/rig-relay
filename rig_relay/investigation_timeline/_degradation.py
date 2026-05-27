from __future__ import annotations

from datetime import UTC, datetime

from rig_relay.investigation_timeline._models import (
    AuthorityClassification,
    InvestigationTimelineEvent,
    SourceDomain,
    TimelineDegradationMarker,
    TimelineEventKind,
    VerificationClass,
)


def build_missing_evidence_event(
    domain: SourceDomain,
    detail: str,
    investigation_id: str | None = None,
    session_id: str | None = None,
    observed_at: str | None = None,
) -> InvestigationTimelineEvent:
    return InvestigationTimelineEvent(
        observed_at=observed_at or datetime.now(UTC).isoformat(),
        event_kind=TimelineEventKind.EVIDENCE_MISSING,
        source_domain=SourceDomain.TIMELINE_DEGRADED,
        source_digest=_placeholder_digest(domain.value, "missing"),
        verification_class=VerificationClass.MISSING,
        authority_classification=AuthorityClassification.MISSING,
        degradation_detail=detail,
        investigation_id=investigation_id,
        session_id=session_id,
    )


def build_degraded_evidence_event(
    domain: SourceDomain,
    detail: str,
    investigation_id: str | None = None,
    session_id: str | None = None,
    observed_at: str | None = None,
) -> InvestigationTimelineEvent:
    return InvestigationTimelineEvent(
        observed_at=observed_at or datetime.now(UTC).isoformat(),
        event_kind=TimelineEventKind.EVIDENCE_DEGRADED,
        source_domain=SourceDomain.TIMELINE_DEGRADED,
        source_digest=_placeholder_digest(domain.value, "degraded"),
        verification_class=VerificationClass.CANONICAL_DEGRADED,
        authority_classification=AuthorityClassification.CANONICAL_DEGRADED,
        degradation_detail=detail,
        investigation_id=investigation_id,
        session_id=session_id,
    )


def build_contradictory_evidence_event(
    domain: SourceDomain,
    detail: str,
    investigation_id: str | None = None,
    session_id: str | None = None,
    observed_at: str | None = None,
) -> InvestigationTimelineEvent:
    return InvestigationTimelineEvent(
        observed_at=observed_at or datetime.now(UTC).isoformat(),
        event_kind=TimelineEventKind.EVIDENCE_CONTRADICTORY,
        source_domain=SourceDomain.TIMELINE_DEGRADED,
        source_digest=_placeholder_digest(domain.value, "contradictory"),
        verification_class=VerificationClass.CANONICAL_DEGRADED,
        authority_classification=AuthorityClassification.CONTRADICTORY,
        degradation_detail=detail,
        investigation_id=investigation_id,
        session_id=session_id,
    )


def build_degradation_marker(
    degradation_kind: str,
    source_domain: SourceDomain,
    detail: str,
    source_event_id: str | None = None,
) -> TimelineDegradationMarker:
    return TimelineDegradationMarker(
        degradation_kind=degradation_kind,
        source_domain=source_domain,
        detail=detail,
        source_event_id=source_event_id,
    )


def detect_degradation(
    events: list[InvestigationTimelineEvent],
) -> list[TimelineDegradationMarker]:
    markers: list[TimelineDegradationMarker] = []
    for event in events:
        if event.authority_classification != AuthorityClassification.CANONICAL_LIVE:
            markers.append(
                TimelineDegradationMarker(
                    degradation_kind=_classification_to_kind(
                        event.authority_classification
                    ),
                    source_domain=event.source_domain,
                    detail=event.degradation_detail
                    or f"event {event.event_id} classified as {event.authority_classification.value}",
                    source_event_id=event.event_id,
                    observed_at=event.observed_at,
                )
            )
    return markers


def _classification_to_kind(cls: AuthorityClassification) -> str:
    match cls:
        case AuthorityClassification.MISSING:
            return "missing"
        case AuthorityClassification.CORRUPT:
            return "corrupt"
        case AuthorityClassification.CONTRADICTORY:
            return "contradictory"
        case AuthorityClassification.STALE:
            return "stale"
        case AuthorityClassification.CANONICAL_DEGRADED:
            return "degraded"
        case AuthorityClassification.FIXTURE_DEFERRED:
            return "fixture_deferred"
        case AuthorityClassification.CONTROLLED_BOUNDARY:
            return "controlled_boundary"
    return "degraded"


def _placeholder_digest(domain: str, reason: str) -> str:
    import hashlib

    return (
        f"sha256:"
        f"{hashlib.sha256(f'timeline_{domain}_{reason}_placeholder'.encode()).hexdigest()}"
    )
