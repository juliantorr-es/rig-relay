from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from vibe.core.telemetry.local import dump_canonical_json


def _sha256_payload(payload: dict[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(dump_canonical_json(payload).encode("utf-8")).hexdigest()


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
    active_path_reservations: dict[str, CoordinationPathReservation] = Field(default_factory=dict)
    recent_artifacts: list[CoordinationArtifactRef] = Field(default_factory=list)
    conflicts: list[CoordinationConflict] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    projection_sha256: str | None = None

    def with_hash(self) -> CoordinationStateProjection:
        payload = self.model_dump(exclude_none=True, exclude={"projection_sha256"})
        return self.model_copy(
            update={"projection_sha256": _sha256_payload(payload)}
        )


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
