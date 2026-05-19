"""Rig Relay Coordination Models — Governance Seam.

Owned by ``rig_relay.coordination``. Legacy adapter at ``vibe.core.coordination``.

Provides Pydantic models, payload builders, and path hashing for the
coordination store and coordination-tool protocol.

Usage:
    from rig_relay.coordination.models import CoordinationSession, CoordinationStore
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
import os
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from rig_relay.coordination._canonical_json import dump_canonical_json

# ── Salted path hashing ──────────────────────────────────────────────────

_PATH_SALT: str | None = None


def _get_path_salt() -> str:
    global _PATH_SALT
    if _PATH_SALT is None:
        _PATH_SALT = hashlib.sha256(os.urandom(32)).hexdigest()[:16]
    return _PATH_SALT


def salted_path_hash(path: str) -> str:
    """Return a salted SHA256 hex digest for an exportable path hash."""
    raw = f"{_get_path_salt()}:{path}"
    return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def reset_path_salt_for_testing() -> None:
    """Reset the path salt (for test isolation)."""
    global _PATH_SALT
    _PATH_SALT = None


def _repo_root() -> Path:
    """Return the repo root by walking up from this file."""
    return Path(__file__).resolve().parent.parent.parent.parent


def stable_path_key(path: str | Path) -> str:
    """Return a deterministic path key for internal coordination comparisons.

    Uses repo-root-relative POSIX path — stable across processes for the same repo.
    This is for RUNTIME coordination only, NOT for export/privacy hashing.
    For export datasets, use salted_path_hash().
    """
    normalized = Path(path).resolve().as_posix()
    repo = _repo_root().resolve().as_posix()
    if normalized.startswith(repo + "/"):
        relative = normalized[len(repo) + 1 :]
    elif normalized == repo:
        relative = "."
    else:
        relative = normalized
    return "coord:" + hashlib.sha256(relative.encode("utf-8")).hexdigest()


def _sha256_payload(payload: dict[str, Any]) -> str:
    return (
        "sha256:"
        + hashlib.sha256(dump_canonical_json(payload).encode("utf-8")).hexdigest()
    )


class CoordinationSession(BaseModel):
    schema_version: str = "rig.relay.coordination.session.v1"
    session_id: str
    task_id: str | None = None
    agent_profile: str | None = None
    status: str
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    reserved_paths: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    state_sha256: str | None = None


class CoordinationHeartbeat(BaseModel):
    schema_version: str = "rig.relay.coordination.heartbeat.v1"
    session_id: str
    task_id: str | None = None
    status: str
    current_step: str | None = None
    reserved_paths: list[str] = Field(default_factory=list)
    last_artifact_sha256: str | None = None
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    state_sha256: str | None = None


class CoordinationTaskClaim(BaseModel):
    schema_version: str = "rig.relay.coordination.task_claim.v1"
    session_id: str
    task_id: str
    claim_kind: str
    ttl_seconds: int
    scope_allowed_paths: list[str] = Field(default_factory=list)
    status: Literal["active", "stale", "released"] = "active"
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    expires_at: str | None = None
    state_sha256: str | None = None


class CoordinationPathReservation(BaseModel):
    schema_version: str = "rig.relay.coordination.path_reservation.v1"
    session_id: str
    task_id: str
    mode: Literal["read", "write"]
    paths: list[str] = Field(default_factory=list)
    ttl_seconds: int
    status: Literal["active", "stale", "released", "conflicted"] = "active"
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    expires_at: str | None = None
    state_sha256: str | None = None


class CoordinationArtifactRef(BaseModel):
    schema_version: str = "rig.relay.coordination.artifact_ref.v1"
    session_id: str
    task_id: str | None = None
    artifact_kind: str
    artifact_uri: str
    artifact_sha256: str
    schema_id: str | None = None
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    state_sha256: str | None = None


class CoordinationConflict(BaseModel):
    schema_version: str = "rig.relay.coordination.conflict.v1"
    conflict_id: str
    kind: str
    session_id: str
    other_session_id: str | None = None
    task_id: str | None = None
    paths: list[str] = Field(default_factory=list)
    recommended_resolution: str | None = None
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    state_sha256: str | None = None


class CoordinationClaimResult(BaseModel):
    allowed: bool
    claim: CoordinationTaskClaim | None = None
    conflict: CoordinationConflict | None = None
    warnings: list[str] = Field(default_factory=list)


class CoordinationReservationResult(BaseModel):
    allowed: bool
    reservation: CoordinationPathReservation | None = None
    conflict: CoordinationConflict | None = None
    warnings: list[str] = Field(default_factory=list)


class CoordinationStateProjection(BaseModel):
    schema_version: str = "rig.relay.coordination.state_projection.v1"
    active_sessions: dict[str, CoordinationSession] = Field(default_factory=dict)
    active_task_claims: dict[str, CoordinationTaskClaim] = Field(default_factory=dict)
    active_path_reservations: dict[str, CoordinationPathReservation] = Field(
        default_factory=dict
    )
    recent_artifacts: list[CoordinationArtifactRef] = Field(default_factory=list)
    conflicts: list[CoordinationConflict] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    projection_sha256: str | None = None

    def with_hash(self) -> CoordinationStateProjection:
        payload = self.model_dump(exclude_none=True, exclude={"projection_sha256"})
        return self.model_copy(update={"projection_sha256": _sha256_payload(payload)})


class CoordinationEvent(BaseModel):
    schema_version: str = "rig.relay.coordination.event.v1"
    event_id: str
    session_id: str | None = None
    task_id: str | None = None
    sequence: int
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    event_name: str
    payload: dict[str, Any] = Field(default_factory=dict)
    event_hash: str | None = None


def now_plus(seconds: int) -> str:
    return (datetime.now(UTC) + timedelta(seconds=seconds)).isoformat()


def normalize_path(path: str | Path) -> str:
    return Path(path).as_posix()


# ── Normalized payload builders for coordination events ─────────────────


def _path_hashes_from_list(paths: list[str]) -> list[str]:
    return sorted(salted_path_hash(p) for p in paths)


def build_session_registered_payload(session: CoordinationSession) -> dict[str, Any]:
    return {
        "session_id": session.session_id,
        "task_id": session.task_id,
        "agent_profile_name": session.agent_profile,
        "event_kind": "session_registered",
        "status": session.status,
        "path_hashes": _path_hashes_from_list(session.reserved_paths),
        "path_count": len(session.reserved_paths),
        "warnings": session.warnings or None,
    }


def build_heartbeat_payload(heartbeat: CoordinationHeartbeat) -> dict[str, Any]:
    return {
        "session_id": heartbeat.session_id,
        "task_id": heartbeat.task_id,
        "event_kind": "heartbeat",
        "status": heartbeat.status,
        "current_step": heartbeat.current_step,
        "path_hashes": _path_hashes_from_list(heartbeat.reserved_paths),
        "path_count": len(heartbeat.reserved_paths),
        "last_artifact_sha256": heartbeat.last_artifact_sha256,
    }


def build_task_claim_payload(claim: CoordinationTaskClaim) -> dict[str, Any]:
    return {
        "session_id": claim.session_id,
        "task_id": claim.task_id,
        "event_kind": "task_claimed",
        "claim_kind": claim.claim_kind,
        "status": claim.status,
        "ttl_seconds": claim.ttl_seconds,
        "scope_path_hashes": _path_hashes_from_list(claim.scope_allowed_paths),
        "scope_path_count": len(claim.scope_allowed_paths),
        "expires_at": claim.expires_at,
    }


def build_task_released_payload(session_id: str, task_id: str) -> dict[str, Any]:
    return {
        "session_id": session_id,
        "task_id": task_id,
        "event_kind": "task_released",
        "status": "released",
    }


def build_path_reserved_payload(
    reservation: CoordinationPathReservation,
) -> dict[str, Any]:
    return {
        "session_id": reservation.session_id,
        "task_id": reservation.task_id,
        "event_kind": "path_reserved",
        "reservation_mode": reservation.mode,
        "reservation_status": reservation.status,
        "path_hashes": _path_hashes_from_list(reservation.paths),
        "path_count": len(reservation.paths),
        "ttl_seconds": reservation.ttl_seconds,
        "expires_at": reservation.expires_at,
    }


def build_path_released_payload(
    session_id: str, task_id: str, paths: list[str]
) -> dict[str, Any]:
    return {
        "session_id": session_id,
        "task_id": task_id,
        "event_kind": "path_released",
        "reservation_status": "released",
        "path_hashes": _path_hashes_from_list(paths),
        "path_count": len(paths),
    }


def build_reservation_refused_payload(conflict: CoordinationConflict) -> dict[str, Any]:
    return {
        "session_id": conflict.session_id,
        "task_id": conflict.task_id,
        "event_kind": "reservation_refused",
        "reservation_status": "refused",
        "conflict_kind": conflict.kind,
        "conflict_id": conflict.conflict_id,
        "other_session_id": conflict.other_session_id,
        "resolution_kind": conflict.recommended_resolution,
        "path_hashes": _path_hashes_from_list(conflict.paths),
        "path_count": len(conflict.paths),
    }


def build_artifact_published_payload(
    artifact: CoordinationArtifactRef,
) -> dict[str, Any]:
    return {
        "session_id": artifact.session_id,
        "task_id": artifact.task_id,
        "event_kind": "artifact_published",
        "artifact_kind": artifact.artifact_kind,
        "artifact_sha256": artifact.artifact_sha256,
        "artifact_uri": artifact.artifact_uri,
        "schema_id": artifact.schema_id,
    }


def build_conflict_reported_payload(conflict: CoordinationConflict) -> dict[str, Any]:
    return {
        "conflict_id": conflict.conflict_id,
        "session_id": conflict.session_id,
        "task_id": conflict.task_id,
        "event_kind": "conflict_reported",
        "conflict_kind": conflict.kind,
        "other_session_id": conflict.other_session_id,
        "resolution_kind": conflict.recommended_resolution,
        "path_hashes": _path_hashes_from_list(conflict.paths),
        "path_count": len(conflict.paths),
    }


def build_handoff_requested_payload(
    session_id: str,
    target_session_id: str,
    task_id: str | None = None,
    scope: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "session_id": session_id,
        "task_id": task_id,
        "event_kind": "handoff_requested",
        "handoff_from_session_id": session_id,
        "handoff_to_session_id": target_session_id,
        "status": "requested",
    }


def build_handoff_accepted_payload(
    session_id: str, from_session_id: str, task_id: str | None = None
) -> dict[str, Any]:
    return {
        "session_id": session_id,
        "task_id": task_id,
        "event_kind": "handoff_accepted",
        "handoff_from_session_id": from_session_id,
        "handoff_to_session_id": session_id,
        "status": "accepted",
    }


def build_handoff_rejected_payload(
    session_id: str, from_session_id: str, task_id: str | None = None
) -> dict[str, Any]:
    return {
        "session_id": session_id,
        "task_id": task_id,
        "event_kind": "handoff_rejected",
        "handoff_from_session_id": from_session_id,
        "handoff_to_session_id": session_id,
        "status": "rejected",
    }


def build_projection_read_payload(
    session_id: str | None, projection_sha256: str | None
) -> dict[str, Any]:
    return {
        "session_id": session_id,
        "event_kind": "projection_read",
        "projection_sha256": projection_sha256,
    }


def build_task_claim_refused_payload(conflict: CoordinationConflict) -> dict[str, Any]:
    return {
        "session_id": conflict.session_id,
        "task_id": conflict.task_id,
        "event_kind": "task_claim_refused",
        "conflict_kind": conflict.kind,
        "conflict_id": conflict.conflict_id,
        "other_session_id": conflict.other_session_id,
        "resolution_kind": conflict.recommended_resolution,
    }


def build_lease_expired_payload(
    session_id: str, task_id: str, path_hashes: list[str]
) -> dict[str, Any]:
    return {
        "session_id": session_id,
        "task_id": task_id,
        "event_kind": "lease_expired",
        "reservation_status": "expired",
        "path_hashes": sorted(path_hashes),
        "path_count": len(path_hashes),
    }


def build_lease_marked_stale_payload(
    session_id: str, task_id: str, reason: str
) -> dict[str, Any]:
    return {
        "session_id": session_id,
        "task_id": task_id,
        "event_kind": "lease_marked_stale",
        "reservation_status": "stale",
        "status": reason,
    }


def build_checkpoint_committed_payload(
    session_id: str,
    task_id: str,
    branch: str,
    pre_commit_head: str,
    post_commit_head: str,
    commit_sha: str,
    files_committed: list[str],
    validation_summary: list[str],
    artifact_sha256: str | None = None,
) -> dict[str, Any]:
    return {
        "session_id": session_id,
        "task_id": task_id,
        "event_kind": "checkpoint_committed",
        "branch": branch,
        "pre_commit_head": pre_commit_head,
        "post_commit_head": post_commit_head,
        "commit_sha": commit_sha,
        "files_committed_count": len(files_committed),
        "validation_summary_hash": (
            "sha256:"
            + hashlib.sha256(
                dump_canonical_json(validation_summary).encode("utf-8")
            ).hexdigest()
            if validation_summary
            else None
        ),
        "checkpoint_artifact_sha256": artifact_sha256,
        "status": "committed",
        "warnings": [],
        "file_hash": salted_path_hash(",".join(sorted(files_committed)))
        if files_committed
        else None,
    }


def build_checkpoint_refused_payload(
    session_id: str, task_id: str, refusal_code: str, warnings: list[str] | None = None
) -> dict[str, Any]:
    return {
        "session_id": session_id,
        "task_id": task_id,
        "event_kind": "checkpoint_refused",
        "refusal_code": refusal_code,
        "status": "refused",
        "warnings": warnings or [],
    }


# ── Coordination Event Ledger Contract v1 payload builders ──────────────

_SEAM_SCHEMA_VERSION = "rig.relay.coordination.seam_event.v1"
_PROOF_CHAIN_SCHEMA_VERSION = "rig.relay.coordination.proof_chain_event.v1"
_FAKE_GREEN_SCHEMA_VERSION = "rig.relay.coordination.fake_green_event.v1"


def _hash_file_paths(paths: list[str]) -> list[str]:
    return sorted(salted_path_hash(p) for p in paths)


def _canonical_event_id(payload: dict[str, Any]) -> str:
    return _sha256_payload(payload)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def build_seam_discovered_payload(
    *,
    contract_family_id: str,
    seam_class: str,
    severity: str,
    proof_chain_status: str,
    fake_green_risk: str,
    affected_file_hashes: list[str],
    evidence_file_hashes: list[str] | None = None,
    schema_file_hashes: list[str] | None = None,
    implementation_file_hashes: list[str] | None = None,
    validator_file_hashes: list[str] | None = None,
    test_file_hashes: list[str] | None = None,
    release_blocker_ids: list[str] | None = None,
    trace_fields_observed: list[str] | None = None,
    trace_fields_missing: list[str] | None = None,
    telemetry_redaction_implications: str = "",
    concurrency_implications: str = "",
    recommended_next_action: str = "",
    detected_by: str = "",
) -> dict[str, Any]:
    payload = {
        "event_kind": "contract_seam_discovered",
        "contract_family_id": contract_family_id,
        "seam_class": seam_class,
        "severity": severity,
        "proof_chain_status": proof_chain_status,
        "fake_green_risk": fake_green_risk,
        "affected_file_hashes": sorted(affected_file_hashes),
        "evidence_file_hashes": sorted(evidence_file_hashes)
        if evidence_file_hashes
        else [],
        "schema_file_hashes": sorted(schema_file_hashes) if schema_file_hashes else [],
        "implementation_file_hashes": (
            sorted(implementation_file_hashes) if implementation_file_hashes else []
        ),
        "validator_file_hashes": sorted(validator_file_hashes)
        if validator_file_hashes
        else [],
        "test_file_hashes": sorted(test_file_hashes) if test_file_hashes else [],
        "release_blocker_ids": release_blocker_ids or [],
        "trace_fields_observed": trace_fields_observed or [],
        "trace_fields_missing": trace_fields_missing or [],
        "telemetry_redaction_implications": telemetry_redaction_implications,
        "concurrency_implications": concurrency_implications,
        "recommended_next_action": recommended_next_action,
        "detected_by": detected_by,
        "generated_at": _now_iso(),
    }
    event_id = _canonical_event_id(payload)
    return {"schema_version": _SEAM_SCHEMA_VERSION, "event_id": event_id, **payload}


def build_proof_chain_incomplete_payload(
    *,
    surface_id: str,
    contract_family_id: str,
    proof_chain_status: str,
    authority_file_hashes: list[str] | None = None,
    schema_file_hashes: list[str] | None = None,
    producer_file_hashes: list[str] | None = None,
    consumer_file_hashes: list[str] | None = None,
    validator_file_hashes: list[str] | None = None,
    test_file_hashes: list[str] | None = None,
    evidence_file_hashes: list[str] | None = None,
    missing_schema_validation: bool = False,
    missing_artifact_hash_validation: bool = False,
    missing_trace_or_correlation_validation: bool = False,
    missing_telemetry_or_redaction_validation: bool = False,
    concrete_failure_mode: str = "",
    recommended_next_action: str = "",
) -> dict[str, Any]:
    payload = {
        "surface_id": surface_id,
        "contract_family_id": contract_family_id,
        "proof_chain_status": proof_chain_status,
        "authority_file_hashes": sorted(authority_file_hashes)
        if authority_file_hashes
        else [],
        "schema_file_hashes": sorted(schema_file_hashes) if schema_file_hashes else [],
        "producer_file_hashes": sorted(producer_file_hashes)
        if producer_file_hashes
        else [],
        "consumer_file_hashes": sorted(consumer_file_hashes)
        if consumer_file_hashes
        else [],
        "validator_file_hashes": sorted(validator_file_hashes)
        if validator_file_hashes
        else [],
        "test_file_hashes": sorted(test_file_hashes) if test_file_hashes else [],
        "evidence_file_hashes": sorted(evidence_file_hashes)
        if evidence_file_hashes
        else [],
        "missing_schema_validation": missing_schema_validation,
        "missing_artifact_hash_validation": missing_artifact_hash_validation,
        "missing_trace_or_correlation_validation": missing_trace_or_correlation_validation,
        "missing_telemetry_or_redaction_validation": missing_telemetry_or_redaction_validation,
        "concrete_failure_mode": concrete_failure_mode,
        "recommended_next_action": recommended_next_action,
        "generated_at": _now_iso(),
    }
    event_id = _canonical_event_id(payload)
    return {
        "schema_version": _PROOF_CHAIN_SCHEMA_VERSION,
        "event_id": event_id,
        **payload,
    }


def build_fake_green_test_detected_payload(
    *,
    contract_family_id: str,
    test_file_hash: str,
    test_function: str,
    fake_green_pattern: str,
    why_theatrical: str,
    what_would_still_pass_description: str,
    missing_adversarial_test_description: str,
    release_blocker_ids: list[str] | None = None,
    severity: str = "high",
) -> dict[str, Any]:
    payload = {
        "contract_family_id": contract_family_id,
        "test_file_hash": test_file_hash,
        "test_function": test_function,
        "fake_green_pattern": fake_green_pattern,
        "why_theatrical": why_theatrical,
        "what_would_still_pass_description": what_would_still_pass_description,
        "missing_adversarial_test_description": missing_adversarial_test_description,
        "release_blocker_ids": release_blocker_ids or [],
        "severity": severity,
        "generated_at": _now_iso(),
    }
    event_id = _canonical_event_id(payload)
    return {
        "schema_version": _FAKE_GREEN_SCHEMA_VERSION,
        "event_id": event_id,
        **payload,
    }


def build_release_blocker_unverifiable_payload(
    *,
    contract_family_id: str,
    blocker_id: str,
    seam_class: str,
    severity: str,
    proof_chain_status: str,
    fake_green_risk: str,
    affected_file_hashes: list[str],
    evidence_file_hashes: list[str] | None = None,
    schema_file_hashes: list[str] | None = None,
    implementation_file_hashes: list[str] | None = None,
    validator_file_hashes: list[str] | None = None,
    test_file_hashes: list[str] | None = None,
    trace_fields_observed: list[str] | None = None,
    trace_fields_missing: list[str] | None = None,
    telemetry_redaction_implications: str = "",
    concurrency_implications: str = "",
    recommended_next_action: str = "",
    detected_by: str = "",
) -> dict[str, Any]:
    payload = {
        "event_kind": "release_blocker_unverifiable",
        "contract_family_id": contract_family_id,
        "seam_class": seam_class,
        "severity": severity,
        "proof_chain_status": proof_chain_status,
        "fake_green_risk": fake_green_risk,
        "affected_file_hashes": sorted(affected_file_hashes),
        "evidence_file_hashes": sorted(evidence_file_hashes)
        if evidence_file_hashes
        else [],
        "schema_file_hashes": sorted(schema_file_hashes) if schema_file_hashes else [],
        "implementation_file_hashes": (
            sorted(implementation_file_hashes) if implementation_file_hashes else []
        ),
        "validator_file_hashes": sorted(validator_file_hashes)
        if validator_file_hashes
        else [],
        "test_file_hashes": sorted(test_file_hashes) if test_file_hashes else [],
        "trace_fields_observed": trace_fields_observed or [],
        "trace_fields_missing": trace_fields_missing or [],
        "telemetry_redaction_implications": telemetry_redaction_implications,
        "concurrency_implications": concurrency_implications,
        "release_blocker_ids": [blocker_id],
        "recommended_next_action": recommended_next_action,
        "detected_by": detected_by,
        "generated_at": _now_iso(),
    }
    event_id = _canonical_event_id(payload)
    return {"schema_version": _SEAM_SCHEMA_VERSION, "event_id": event_id, **payload}


from rig_relay.coordination.fleet_models import (
    CreateProposalResult,
    FleetAgentMessage,
    FleetAgentSession,
    FleetCoordinationEvent,
    FleetMergeDecision,
    FleetPatchProposal,
    FleetPathLease,
    FleetWorkClaim,
    PatchDecision,
    PatchProposal,
    PatchProposalArtifactRef,
    compute_proposal_fingerprint,
)
from rig_relay.coordination.fleet_queue import (
    FleetQueue,
    FleetQueueEvent,
    FleetQueueEventKind,
    FleetQueueItem,
    FleetQueueItemKind,
    FleetQueueItemStatus,
    FleetQueueSnapshot,
)

__all__ = [
    "CoordinationArtifactRef",
    "CoordinationClaimResult",
    "CoordinationConflict",
    "CoordinationEvent",
    "CoordinationHeartbeat",
    "CoordinationPathReservation",
    "CoordinationReservationResult",
    "CoordinationSession",
    "CoordinationStateProjection",
    "CoordinationTaskClaim",
    "CreateProposalResult",
    "FleetAgentMessage",
    "FleetAgentSession",
    "FleetCoordinationEvent",
    "FleetMergeDecision",
    "FleetPatchProposal",
    "FleetPathLease",
    "FleetQueue",
    "FleetQueueEvent",
    "FleetQueueEventKind",
    "FleetQueueItem",
    "FleetQueueItemKind",
    "FleetQueueItemStatus",
    "FleetQueueSnapshot",
    "FleetWorkClaim",
    "PatchDecision",
    "PatchProposal",
    "PatchProposalArtifactRef",
    "build_artifact_published_payload",
    "build_checkpoint_committed_payload",
    "build_checkpoint_refused_payload",
    "build_conflict_reported_payload",
    "build_fake_green_test_detected_payload",
    "build_handoff_accepted_payload",
    "build_handoff_rejected_payload",
    "build_handoff_requested_payload",
    "build_heartbeat_payload",
    "build_lease_expired_payload",
    "build_lease_marked_stale_payload",
    "build_path_released_payload",
    "build_path_reserved_payload",
    "build_projection_read_payload",
    "build_proof_chain_incomplete_payload",
    "build_release_blocker_unverifiable_payload",
    "build_reservation_refused_payload",
    "build_seam_discovered_payload",
    "build_session_registered_payload",
    "build_task_claim_payload",
    "build_task_claim_refused_payload",
    "build_task_released_payload",
    "compute_proposal_fingerprint",
    "normalize_path",
    "now_plus",
    "reset_path_salt_for_testing",
    "salted_path_hash",
    "stable_path_key",
]
