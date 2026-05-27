from __future__ import annotations

import hashlib
import json
from pathlib import Path

from rig_relay.investigation_timeline._models import (
    AuthorityClassification,
    InvestigationTimelineEvent,
    SourceDomain,
    TimelineEventKind,
    VerificationClass,
)
from rig_relay.investigation_timeline._source_verification import (
    verify_checkpoint_event,
    verify_coordination_event,
    verify_disclosure_event,
    verify_observability_event,
    verify_publication_event,
)


def adapt_observability_events(
    observability_path: str | Path, investigation_id: str | None = None
) -> tuple[list[InvestigationTimelineEvent], list[str]]:
    path = _resolve_path(observability_path)
    if not path.exists():
        return [], [f"observability file not found: {path}"]

    events: list[InvestigationTimelineEvent] = []
    errors: list[str] = []
    session_id = _extract_session_id_from_path(path)

    try:
        with path.open("r", encoding="utf-8") as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    record: dict = json.loads(line)
                except json.JSONDecodeError as e:
                    events.append(
                        _build_corrupt_event(
                            SourceDomain.OBSERVABILITY,
                            f"line {line_num}: malformed JSON: {e}",
                            line_num,
                        )
                    )
                    errors.append(f"observability line {line_num}: malformed JSON: {e}")
                    continue

                event_name = record.get("event_name", "")
                observed_at = record.get("created_at", "")
                source_event_id = record.get("event_id", "")
                source_sequence = record.get("sequence", None)

                payload = record.get("payload", {})
                status = payload.get("status", None)

                kind = _map_observability_event_kind(event_name, status)
                if kind is None:
                    events.append(
                        _build_unverified_event(
                            SourceDomain.OBSERVABILITY,
                            f"unmapped event_name: {event_name}",
                            source_event_id,
                            observed_at,
                            investigation_id,
                            session_id,
                            source_sequence,
                        )
                    )
                    continue

                computed_digest = _compute_digest(record)
                verification, producer_digest, verified = verify_observability_event(
                    record, computed_digest
                )

                authority = _verification_to_authority(verification)

                tl_event = InvestigationTimelineEvent(
                    observed_at=observed_at,
                    event_kind=kind,
                    source_domain=SourceDomain.OBSERVABILITY,
                    source_event_id=source_event_id,
                    source_digest=computed_digest,
                    source_sequence=source_sequence,
                    producer_digest=producer_digest,
                    producer_digest_verified=verified,
                    verification_class=verification,
                    authority_classification=authority,
                    session_id=session_id or record.get("session_id"),
                    investigation_id=investigation_id,
                    parent_session_id=record.get("parent_session_id"),
                    outcome=_map_observability_outcome(status, payload),
                    status=status,
                    latency_ms=payload.get("latency_ms"),
                    artifact_kind=payload.get("artifact_kind"),
                    artifact_sha256=payload.get("artifact_record_sha256"),
                    refusal_code=payload.get("refusal_reason"),
                )
                events.append(tl_event)

    except OSError as e:
        errors.append(f"observability read error: {e}")

    return events, errors


def adapt_coordination_events(
    coordination_path: str | Path, investigation_id: str | None = None
) -> tuple[list[InvestigationTimelineEvent], list[str]]:
    path = _resolve_path(coordination_path)
    if not path.exists():
        return [], [f"coordination events file not found: {path}"]

    events: list[InvestigationTimelineEvent] = []
    errors: list[str] = []

    try:
        with path.open("r", encoding="utf-8") as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    record: dict = json.loads(line)
                except json.JSONDecodeError as e:
                    events.append(
                        _build_corrupt_event(
                            SourceDomain.COORDINATION,
                            f"line {line_num}: malformed JSON: {e}",
                            line_num,
                        )
                    )
                    errors.append(f"coordination line {line_num}: malformed JSON: {e}")
                    continue

                event_name = record.get("event_name", "")
                observed_at = record.get("created_at", "")
                source_event_id = record.get("event_id", "")
                source_sequence = record.get("sequence", None)
                payload = record.get("payload", {})

                kind = _map_coordination_event_kind(event_name)
                if kind is None:
                    events.append(
                        _build_unverified_event(
                            SourceDomain.COORDINATION,
                            f"unmapped event_name: {event_name}",
                            source_event_id,
                            observed_at,
                            investigation_id,
                            record.get("session_id"),
                            source_sequence,
                        )
                    )
                    continue

                computed_digest = _compute_digest(record)
                verification, producer_digest, verified = verify_coordination_event(
                    record, computed_digest
                )

                authority = _verification_to_authority(verification)

                tl_event = InvestigationTimelineEvent(
                    observed_at=observed_at,
                    event_kind=kind,
                    source_domain=SourceDomain.COORDINATION,
                    source_event_id=source_event_id,
                    source_digest=computed_digest,
                    source_sequence=source_sequence,
                    producer_digest=producer_digest,
                    producer_digest_verified=verified,
                    verification_class=verification,
                    authority_classification=authority,
                    session_id=record.get("session_id"),
                    investigation_id=investigation_id,
                    task_id=record.get("task_id"),
                    outcome=_first_truthy(
                        payload.get("outcome"), payload.get("status")
                    ),
                    status=payload.get("status"),
                    path_count=payload.get("path_count"),
                    artifact_kind=payload.get("artifact_kind"),
                    artifact_sha256=payload.get("artifact_sha256"),
                )
                events.append(tl_event)

    except OSError as e:
        errors.append(f"coordination read error: {e}")

    return events, errors


def adapt_disclosure_transitions(
    transitions_path: str | Path, investigation_id: str | None = None
) -> tuple[list[InvestigationTimelineEvent], list[str]]:
    path = _resolve_path(transitions_path)
    if not path.exists():
        return [], [f"disclosure transitions file not found: {path}"]

    events: list[InvestigationTimelineEvent] = []
    errors: list[str] = []

    try:
        with path.open("r", encoding="utf-8") as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    record: dict = json.loads(line)
                except json.JSONDecodeError as e:
                    events.append(
                        _build_corrupt_event(
                            SourceDomain.DISCLOSURE,
                            f"line {line_num}: malformed JSON: {e}",
                            line_num,
                        )
                    )
                    errors.append(f"disclosure line {line_num}: malformed JSON: {e}")
                    continue

                transition_id = record.get("transition_id", "")
                status = record.get("status", "")
                observed_at = record.get("created_at", "")

                if not transition_id or not status:
                    events.append(
                        _build_corrupt_event(
                            SourceDomain.DISCLOSURE,
                            f"line {line_num}: missing transition_id or status",
                            str(line_num),
                        )
                    )
                    continue

                kind = _map_disclosure_status_to_kind(status)
                if kind is None:
                    events.append(
                        _build_unverified_event(
                            SourceDomain.DISCLOSURE,
                            f"unmapped status: {status}",
                            transition_id,
                            observed_at,
                            investigation_id,
                            None,
                            record.get("sequence"),
                        )
                    )
                    continue

                verification, producer_digest, verified = verify_disclosure_event(
                    record
                )

                if not producer_digest:
                    producer_digest = record.get("transition_digest")

                authority = _verification_to_authority(verification)

                computed_digest = _compute_digest(record)

                tl_event = InvestigationTimelineEvent(
                    observed_at=observed_at,
                    event_kind=kind,
                    source_domain=SourceDomain.DISCLOSURE,
                    source_event_id=transition_id,
                    source_digest=computed_digest,
                    source_sequence=record.get("sequence"),
                    producer_digest=producer_digest,
                    producer_digest_verified=verified,
                    verification_class=verification,
                    authority_classification=authority,
                    investigation_id=investigation_id,
                    outcome=status if status == "completed" else None,
                    status=status,
                    refusal_code=(
                        status if status in {"refused", "conflict", "corrupt"} else None
                    ),
                    degradation_detail=(
                        f"disclosure transition status: {status}"
                        if verification != VerificationClass.VERIFIED_CANONICAL
                        else None
                    ),
                )
                events.append(tl_event)

    except OSError as e:
        errors.append(f"disclosure read error: {e}")

    return events, errors


def adapt_checkpoint_events(
    observability_path: str | Path, investigation_id: str | None = None
) -> tuple[list[InvestigationTimelineEvent], list[str]]:
    path = _resolve_path(observability_path)
    if not path.exists():
        return [], [f"observability file for checkpoints not found: {path}"]

    events: list[InvestigationTimelineEvent] = []
    errors: list[str] = []
    checkpoint_event_names = {
        "rig.relay.checkpoint.committed",
        "rig.relay.checkpoint.refused",
    }

    try:
        with path.open("r", encoding="utf-8") as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    record: dict = json.loads(line)
                except json.JSONDecodeError as e:
                    errors.append(f"checkpoint line {line_num}: malformed JSON: {e}")
                    continue

                event_name = record.get("event_name", "")
                if event_name not in checkpoint_event_names:
                    continue

                observed_at = record.get("created_at", "")
                source_event_id = record.get("event_id", "")
                source_sequence = record.get("sequence", None)
                payload = record.get("payload", {})

                kind = (
                    TimelineEventKind.CHECKPOINT_COMMITTED
                    if event_name == "rig.relay.checkpoint.committed"
                    else TimelineEventKind.CHECKPOINT_REFUSED
                )

                computed_digest = _compute_digest(record)
                verification, producer_digest, verified = verify_checkpoint_event(
                    record
                )

                authority = _verification_to_authority(verification)

                tl_event = InvestigationTimelineEvent(
                    observed_at=observed_at,
                    event_kind=kind,
                    source_domain=SourceDomain.CHECKPOINT,
                    source_event_id=source_event_id,
                    source_digest=computed_digest,
                    source_sequence=source_sequence,
                    producer_digest=producer_digest,
                    producer_digest_verified=verified,
                    verification_class=verification,
                    authority_classification=authority,
                    session_id=payload.get("session_id"),
                    investigation_id=investigation_id,
                    task_id=payload.get("task_id"),
                    outcome=(
                        "committed"
                        if kind == TimelineEventKind.CHECKPOINT_COMMITTED
                        else "refused"
                    ),
                    commit_sha=payload.get("commit_sha"),
                    refusal_code=payload.get("refusal_code"),
                )
                events.append(tl_event)

    except OSError as e:
        errors.append(f"checkpoint read error: {e}")

    return events, errors


def adapt_publication_preview_events(
    publication_ledger_path: str | Path, investigation_id: str | None = None
) -> tuple[list[InvestigationTimelineEvent], list[str]]:
    path = _resolve_path(publication_ledger_path)
    if not path.exists():
        return [], [f"publication ledger not found: {path}"]

    events: list[InvestigationTimelineEvent] = []
    errors: list[str] = []

    try:
        with path.open("r", encoding="utf-8") as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    record: dict = json.loads(line)
                except json.JSONDecodeError as e:
                    events.append(
                        _build_corrupt_event(
                            SourceDomain.PUBLICATION,
                            f"line {line_num}: malformed JSON: {e}",
                            line_num,
                        )
                    )
                    errors.append(f"publication line {line_num}: malformed JSON: {e}")
                    continue

                receipt = record.get("receipt", {})

                operation_id = record.get("operation_id")
                compiled_at = receipt.get("compiled_at", "")
                receipt_id = receipt.get("receipt_id", "")
                compilation_successful = receipt.get("compilation_successful", False)
                refusal_code = receipt.get("refusal_code")
                refusal_reasons = receipt.get("refusal_reasons", [])
                deployment_ready = receipt.get("deployment_ready", False)
                source_sequence = line_num

                if not compiled_at or not receipt_id:
                    events.append(
                        _build_corrupt_event(
                            SourceDomain.PUBLICATION,
                            f"line {line_num}: missing compiled_at or receipt_id in nested receipt",
                            str(line_num),
                        )
                    )
                    continue

                if compilation_successful:
                    kind = TimelineEventKind.PUBLICATION_PREVIEW_COMPILED
                    outcome = "compiled"
                elif refusal_code:
                    kind = TimelineEventKind.PUBLICATION_PREVIEW_REFUSED
                    outcome = "refused"
                else:
                    events.append(
                        _build_unverified_event(
                            SourceDomain.PUBLICATION,
                            f"line {line_num}: neither compiled nor refused",
                            receipt_id,
                            compiled_at,
                            investigation_id,
                            None,
                            source_sequence,
                        )
                    )
                    continue

                verification, producer_digest, verified = verify_publication_event(
                    record
                )

                authority = _verification_to_authority(verification)

                computed_digest = _compute_digest(receipt)

                tl_event = InvestigationTimelineEvent(
                    observed_at=compiled_at,
                    event_kind=kind,
                    source_domain=SourceDomain.PUBLICATION,
                    source_event_id=receipt_id,
                    source_digest=computed_digest,
                    source_sequence=source_sequence,
                    producer_digest=producer_digest,
                    producer_digest_verified=verified,
                    verification_class=verification,
                    authority_classification=authority,
                    investigation_id=investigation_id,
                    operation_id=operation_id,
                    outcome=outcome,
                    status="deployment_ready" if deployment_ready else "preview_only",
                    refusal_code=refusal_code,
                    degradation_detail=(
                        f"refused: {refusal_code}, reasons: {refusal_reasons}"
                        if refusal_code
                        else None
                    ),
                )
                events.append(tl_event)

    except OSError as e:
        errors.append(f"publication read error: {e}")

    return events, errors


def _build_corrupt_event(
    domain: SourceDomain, detail: str, line_num: int | str
) -> InvestigationTimelineEvent:
    return InvestigationTimelineEvent(
        observed_at="",
        event_kind=TimelineEventKind.EVIDENCE_CORRUPT,
        source_domain=SourceDomain.TIMELINE_DEGRADED,
        source_event_id=f"corrupt_{line_num}",
        source_digest=_placeholder_digest(domain.value, "corrupt"),
        verification_class=VerificationClass.CORRUPT,
        authority_classification=AuthorityClassification.CORRUPT,
        degradation_detail=detail,
    )


def _build_unverified_event(
    domain: SourceDomain,
    detail: str,
    source_event_id: str | None,
    observed_at: str,
    investigation_id: str | None,
    session_id: str | None,
    source_sequence: int | None,
) -> InvestigationTimelineEvent:
    return InvestigationTimelineEvent(
        observed_at=observed_at or _now_iso(),
        event_kind=TimelineEventKind.EVIDENCE_UNVERIFIED,
        source_domain=domain,
        source_event_id=source_event_id,
        source_digest=_placeholder_digest(domain.value, "unverified"),
        source_sequence=source_sequence,
        verification_class=VerificationClass.PARSED_UNVERIFIED,
        authority_classification=AuthorityClassification.CANONICAL_DEGRADED,
        degradation_detail=detail,
        investigation_id=investigation_id,
        session_id=session_id,
    )


def _verification_to_authority(vc: VerificationClass) -> AuthorityClassification:
    match vc:
        case VerificationClass.VERIFIED_CANONICAL:
            return AuthorityClassification.CANONICAL_LIVE
        case VerificationClass.CANONICAL_DEGRADED:
            return AuthorityClassification.CANONICAL_DEGRADED
        case VerificationClass.CORRUPT:
            return AuthorityClassification.CORRUPT
        case VerificationClass.UNSUPPORTED:
            return AuthorityClassification.MISSING
        case VerificationClass.MISSING:
            return AuthorityClassification.MISSING
        case VerificationClass.PARSED_UNVERIFIED:
            return AuthorityClassification.CANONICAL_DEGRADED


def _map_observability_event_kind(
    event_name: str, status: str | None
) -> TimelineEventKind | None:
    if event_name == "rig.relay.tool.call_completed":
        if status == "refused":
            return TimelineEventKind.TOOL_CALL_REFUSED
        if status == "failure":
            return TimelineEventKind.TOOL_CALL_FAILED
        return TimelineEventKind.TOOL_CALL_COMPLETED
    if event_name == "rig.relay.context.request_accounted":
        return TimelineEventKind.OBSERVATION_CAPTURED
    if event_name == "rig.relay.model_observation.captured":
        return TimelineEventKind.OBSERVATION_CAPTURED
    if event_name == "rig.relay.session.started":
        return TimelineEventKind.SESSION_STARTED
    if event_name == "rig.relay.session.closed":
        return TimelineEventKind.SESSION_CLOSED
    if event_name == "rig.relay.context.assembly_reported":
        return TimelineEventKind.CONTEXT_ASSEMBLY_REPORTED
    if event_name in {"rig.relay.governance.gate.decision", "GOVERNANCE_GATE_DECISION"}:
        return TimelineEventKind.GOVERNANCE_DECISION_RECORDED
    return None


def _map_coordination_event_kind(event_name: str) -> TimelineEventKind | None:
    mapping: dict[str, TimelineEventKind] = {
        "coord.session.registered": TimelineEventKind.SESSION_REGISTERED,
        "coord.session.heartbeat": TimelineEventKind.SESSION_HEARTBEAT,
        "coord.task.claimed": TimelineEventKind.COORDINATION_TASK_CLAIMED,
        "coord.task.released": TimelineEventKind.COORDINATION_TASK_RELEASED,
        "coord.path.reserved": TimelineEventKind.COORDINATION_PATH_RESERVED,
        "coord.path.released": TimelineEventKind.COORDINATION_PATH_RELEASED,
        "coord.conflict.reported": TimelineEventKind.COORDINATION_CONFLICT_REPORTED,
        "coord.path.reservation_refused": TimelineEventKind.COORDINATION_RESERVATION_REFUSED,
        "coord.artifact.published": TimelineEventKind.COORDINATION_ARTIFACT_PUBLISHED,
        "coord.handoff.requested": TimelineEventKind.COORDINATION_HANDOFF_REQUESTED,
        "coord.handoff.accepted": TimelineEventKind.COORDINATION_HANDOFF_ACCEPTED,
        "coord.handoff.rejected": TimelineEventKind.COORDINATION_HANDOFF_REJECTED,
        "coord.projection.read": TimelineEventKind.COORDINATION_PROJECTION_READ,
        "coord.lease.expired": TimelineEventKind.COORDINATION_LEASE_EXPIRED,
        "coord.lease.marked_stale": TimelineEventKind.COORDINATION_LEASE_STALE,
    }
    return mapping.get(event_name)


def _map_disclosure_status_to_kind(status: str) -> TimelineEventKind | None:
    mapping: dict[str, TimelineEventKind] = {
        "prepared": TimelineEventKind.DISCLOSURE_TRANSITION_INITIATED,
        "authorization_consumed": TimelineEventKind.DISCLOSURE_TRANSITION_ADVANCED,
        "projection_receipt_persisted": TimelineEventKind.DISCLOSURE_TRANSITION_ADVANCED,
        "manifest_applied": TimelineEventKind.DISCLOSURE_TRANSITION_ADVANCED,
        "disclosure_event_recorded": TimelineEventKind.DISCLOSURE_TRANSITION_ADVANCED,
        "completed": TimelineEventKind.DISCLOSURE_TRANSITION_COMPLETED,
        "refused": TimelineEventKind.DISCLOSURE_TRANSITION_REFUSED,
        "conflict": TimelineEventKind.DISCLOSURE_TRANSITION_REFUSED,
        "corrupt": TimelineEventKind.DISCLOSURE_TRANSITION_REFUSED,
        "recovery_required": TimelineEventKind.DISCLOSURE_TRANSITION_REFUSED,
    }
    return mapping.get(status)


def _map_observability_outcome(status: str | None, payload: dict) -> str | None:
    if status == "refused":
        return "refused"
    if status == "failure":
        return "failed"
    if status == "success":
        return "completed"
    return status


def _compute_digest(record: dict) -> str:
    canonical = json.dumps(record, sort_keys=True, ensure_ascii=False, default=str)
    return f"sha256:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}"


def _extract_session_id_from_path(path: Path) -> str | None:
    parts = path.parts
    for i, part in enumerate(parts):
        if part == "sessions" and i + 1 < len(parts):
            return parts[i + 1]
    return None


def _resolve_path(raw: str | Path) -> Path:
    return Path(raw) if isinstance(raw, str) else raw


def _placeholder_digest(domain: str, reason: str) -> str:
    return (
        f"sha256:"
        f"{hashlib.sha256(f'timeline_{domain}_{reason}_placeholder'.encode()).hexdigest()}"
    )


def _now_iso() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat()


def _first_truthy(*values: object) -> str | None:
    for v in values:
        if v:
            return str(v)
    return None
