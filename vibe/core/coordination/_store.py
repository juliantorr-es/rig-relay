from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
from pathlib import Path
from typing import Any, Literal

from vibe.core.coordination._models import (
    CoordinationArtifactRef,
    CoordinationClaimResult,
    CoordinationConflict,
    CoordinationEvent,
    CoordinationHeartbeat,
    CoordinationPathReservation,
    CoordinationReservationResult,
    CoordinationSession,
    CoordinationStateProjection,
    CoordinationTaskClaim,
    build_artifact_published_payload,
    build_conflict_reported_payload,
    build_heartbeat_payload,
    build_path_released_payload,
    build_path_reserved_payload,
    build_projection_read_payload,
    build_reservation_refused_payload,
    build_session_registered_payload,
    build_task_claim_payload,
    build_task_released_payload,
    normalize_path,
    now_plus,
)
from vibe.core.telemetry.local import dump_canonical_json


@dataclass
class CoordinationStore:
    root: Path

    def __post_init__(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "sessions").mkdir(exist_ok=True)
        (self.root / "tasks").mkdir(exist_ok=True)
        (self.root / "leases" / "paths").mkdir(parents=True, exist_ok=True)
        (self.root / "artifacts").mkdir(exist_ok=True)
        (self.root / "conflicts").mkdir(exist_ok=True)
        self._events_path().parent.mkdir(parents=True, exist_ok=True)

    def _events_path(self) -> Path:
        return self.root / "events.jsonl"

    def _write_json(self, path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        text = dump_canonical_json(payload)
        temp = path.with_suffix(path.suffix + ".tmp")
        temp.write_text(text, encoding="utf-8")
        temp.replace(path)

    def _append_event(
        self, event_name: str, normalized_payload: dict[str, Any]
    ) -> None:
        event = CoordinationEvent(
            event_id=self._path_key(dump_canonical_json(normalized_payload)),
            sequence=self._event_sequence() + 1,
            event_name=event_name,
            session_id=normalized_payload.get("session_id"),
            task_id=normalized_payload.get("task_id"),
            payload=normalized_payload,
        )
        event.event_hash = "sha256:" + self._path_key(
            dump_canonical_json(
                event.model_dump(exclude_none=True, exclude={"event_hash"})
            )
        )
        self._events_path().parent.mkdir(parents=True, exist_ok=True)
        with self._events_path().open("a", encoding="utf-8") as f:
            f.write(dump_canonical_json(event.model_dump(exclude_none=True)))
            f.write("\n")

    def _event_sequence(self) -> int:
        if not self._events_path().is_file():
            return 0
        return sum(
            1
            for line in self._events_path().read_text(encoding="utf-8").splitlines()
            if line.strip()
        )

    @staticmethod
    def _path_key(path: str) -> str:
        return hashlib.sha256(path.encode("utf-8")).hexdigest()

    @staticmethod
    def _is_prefix(parent: str, child: str) -> bool:
        return parent == child or child.startswith(parent.rstrip("/") + "/")

    @staticmethod
    def _is_expired(expires_at: str | None) -> bool:
        if expires_at is None:
            return False
        return datetime.fromisoformat(expires_at) <= datetime.now(UTC)

    def _iter_reservations(self) -> list[CoordinationPathReservation]:
        reservations: list[CoordinationPathReservation] = []
        for path in sorted((self.root / "leases" / "paths").glob("*.json")):
            reservations.append(
                CoordinationPathReservation.model_validate_json(
                    path.read_text(encoding="utf-8")
                )
            )
        return reservations

    def _projection(self) -> CoordinationStateProjection:
        sessions: dict[str, CoordinationSession] = {}
        task_claims: dict[str, CoordinationTaskClaim] = {}
        reservations: dict[str, CoordinationPathReservation] = {}
        artifacts: list[CoordinationArtifactRef] = []
        conflicts: list[CoordinationConflict] = []

        for path in sorted((self.root / "sessions").glob("*.json")):
            session = CoordinationSession.model_validate_json(
                path.read_text(encoding="utf-8")
            )
            sessions[session.session_id] = session

        for path in sorted((self.root / "tasks").glob("*.json")):
            claim = CoordinationTaskClaim.model_validate_json(
                path.read_text(encoding="utf-8")
            )
            if self._is_expired(claim.expires_at) and claim.status == "active":
                claim.status = "stale"
            task_claims[claim.task_id] = claim

        for reservation in self._iter_reservations():
            if (
                self._is_expired(reservation.expires_at)
                and reservation.status == "active"
            ):
                reservation.status = "stale"
            if reservation.status == "active":
                for path in reservation.paths:
                    reservations[
                        f"{reservation.session_id}:{reservation.task_id}:{path}"
                    ] = reservation

        for path in sorted((self.root / "artifacts").glob("*.json")):
            artifacts.append(
                CoordinationArtifactRef.model_validate_json(
                    path.read_text(encoding="utf-8")
                )
            )

        for path in sorted((self.root / "conflicts").glob("*.json")):
            conflicts.append(
                CoordinationConflict.model_validate_json(
                    path.read_text(encoding="utf-8")
                )
            )

        return CoordinationStateProjection(
            active_sessions=sessions,
            active_task_claims=task_claims,
            active_path_reservations=reservations,
            recent_artifacts=artifacts,
            conflicts=conflicts,
        ).with_hash()

    def register_session(self, session: CoordinationSession) -> CoordinationSession:
        payload = session.model_dump(exclude_none=True)
        payload["state_sha256"] = self._projection().projection_sha256
        session = CoordinationSession.model_validate(payload)
        self._write_json(
            self.root / "sessions" / f"{session.session_id}.json",
            session.model_dump(exclude_none=True),
        )
        normalized = build_session_registered_payload(session)
        self._append_event("coord.session.registered", normalized)
        return session

    def heartbeat(
        self,
        *,
        session_id: str,
        task_id: str | None,
        status: str,
        reserved_paths: list[str],
    ) -> CoordinationHeartbeat:
        heartbeat = CoordinationHeartbeat(
            session_id=session_id,
            task_id=task_id,
            status=status,
            reserved_paths=[normalize_path(path) for path in reserved_paths],
        )
        payload = heartbeat.model_dump(exclude_none=True)
        payload["state_sha256"] = self._projection().projection_sha256
        heartbeat = CoordinationHeartbeat.model_validate(payload)
        session = self.read_state_projection().active_sessions.get(
            session_id
        ) or CoordinationSession(session_id=session_id, task_id=task_id, status=status)
        session.status = status
        session.task_id = task_id
        session.reserved_paths = heartbeat.reserved_paths
        session.updated_at = heartbeat.created_at
        session.state_sha256 = heartbeat.state_sha256
        self._write_json(
            self.root / "sessions" / f"{session_id}.json",
            session.model_dump(exclude_none=True),
        )
        normalized = build_heartbeat_payload(heartbeat)
        self._append_event("coord.session.heartbeat", normalized)
        return heartbeat

    def claim_task(
        self,
        *,
        session_id: str,
        task_id: str,
        claim_kind: str,
        ttl_seconds: int,
        scope: dict[str, Any],
    ) -> CoordinationClaimResult:
        claim = CoordinationTaskClaim(
            session_id=session_id,
            task_id=task_id,
            claim_kind=claim_kind,
            ttl_seconds=ttl_seconds,
            scope_allowed_paths=[
                normalize_path(path) for path in scope.get("allowed_paths", [])
            ],
            expires_at=now_plus(ttl_seconds),
        )
        payload = claim.model_dump(exclude_none=True)
        payload["state_sha256"] = self._projection().projection_sha256
        claim = CoordinationTaskClaim.model_validate(payload)
        self._write_json(
            self.root / "tasks" / f"{task_id}.json", claim.model_dump(exclude_none=True)
        )
        normalized = build_task_claim_payload(claim)
        self._append_event("coord.task.claimed", normalized)
        return CoordinationClaimResult(allowed=True, claim=claim)

    def reserve_paths(
        self,
        *,
        session_id: str,
        task_id: str,
        mode: Literal["read", "write"],
        paths: list[str],
        ttl_seconds: int,
    ) -> CoordinationReservationResult:
        normalized = [normalize_path(path) for path in paths]
        if mode == "write":
            for existing in self._iter_reservations():
                if existing.status != "active" or existing.mode != "write":
                    continue
                if existing.session_id == session_id and existing.task_id == task_id:
                    continue
                for existing_path in existing.paths:
                    for path in normalized:
                        if self._is_prefix(existing_path, path) or self._is_prefix(
                            path, existing_path
                        ):
                            conflict = CoordinationConflict(
                                conflict_id=self._path_key("|".join(normalized)),
                                kind="path_write_overlap",
                                session_id=session_id,
                                other_session_id=existing.session_id,
                                task_id=task_id,
                                paths=sorted({*normalized, *existing.paths}),
                                recommended_resolution="serialize_or_split_scope",
                            )
                            self.report_conflict(conflict)
                            refused_payload = build_reservation_refused_payload(
                                conflict
                            )
                            self._append_event(
                                "coord.path.reservation_refused", refused_payload
                            )
                            return CoordinationReservationResult(
                                allowed=False, conflict=conflict
                            )

        reservation = CoordinationPathReservation(
            session_id=session_id,
            task_id=task_id,
            mode=mode,
            paths=normalized,
            ttl_seconds=ttl_seconds,
            expires_at=now_plus(ttl_seconds),
        )
        payload = reservation.model_dump(exclude_none=True)
        payload["state_sha256"] = self._projection().projection_sha256
        reservation = CoordinationPathReservation.model_validate(payload)
        self._write_json(
            self.root
            / "leases"
            / "paths"
            / f"{self._path_key(session_id + task_id + '|'.join(normalized))}.json",
            reservation.model_dump(exclude_none=True),
        )
        reserved_payload = build_path_reserved_payload(reservation)
        self._append_event("coord.path.reserved", reserved_payload)
        return CoordinationReservationResult(allowed=True, reservation=reservation)

    def release_paths(self, *, session_id: str, task_id: str, paths: list[str]) -> None:
        normalized = {normalize_path(path) for path in paths}
        for path in sorted((self.root / "leases" / "paths").glob("*.json")):
            reservation = CoordinationPathReservation.model_validate_json(
                path.read_text(encoding="utf-8")
            )
            if (
                reservation.session_id == session_id
                and reservation.task_id == task_id
                and normalized.intersection(reservation.paths)
            ):
                reservation.status = "released"
                self._write_json(path, reservation.model_dump(exclude_none=True))
        released_payload = build_path_released_payload(
            session_id, task_id, sorted(normalized)
        )
        self._append_event("coord.path.released", released_payload)

    def publish_artifact(
        self,
        *,
        session_id: str,
        task_id: str | None,
        artifact_kind: str,
        artifact_uri: str,
        artifact_sha256: str,
        schema_id: str | None = None,
    ) -> CoordinationArtifactRef:
        artifact = CoordinationArtifactRef(
            session_id=session_id,
            task_id=task_id,
            artifact_kind=artifact_kind,
            artifact_uri=artifact_uri,
            artifact_sha256=artifact_sha256,
            schema_id=schema_id,
        )
        payload = artifact.model_dump(exclude_none=True)
        payload["state_sha256"] = self._projection().projection_sha256
        artifact = CoordinationArtifactRef.model_validate(payload)
        self._write_json(
            self.root / "artifacts" / f"{artifact_sha256.replace(':', '_')}.json",
            artifact.model_dump(exclude_none=True),
        )
        published_payload = build_artifact_published_payload(artifact)
        self._append_event("coord.artifact.published", published_payload)
        return artifact

    def report_conflict(self, conflict: CoordinationConflict) -> CoordinationConflict:
        payload = conflict.model_dump(exclude_none=True)
        payload["state_sha256"] = self._projection().projection_sha256
        conflict = CoordinationConflict.model_validate(payload)
        self._write_json(
            self.root / "conflicts" / f"{conflict.conflict_id}.json",
            conflict.model_dump(exclude_none=True),
        )
        reported_payload = build_conflict_reported_payload(conflict)
        self._append_event("coord.conflict.reported", reported_payload)
        return conflict

    def read_state_projection(
        self, *, session_id: str | None = None
    ) -> CoordinationStateProjection:
        projection = self._projection()
        read_payload = build_projection_read_payload(
            session_id, projection.projection_sha256
        )
        self._append_event("coord.projection.read", read_payload)
        return projection

    def release_task(self, *, session_id: str, task_id: str) -> None:
        task_path = self.root / "tasks" / f"{task_id}.json"
        if task_path.exists():
            claim = CoordinationTaskClaim.model_validate_json(
                task_path.read_text(encoding="utf-8")
            )
            claim.status = "released"
            self._write_json(task_path, claim.model_dump(exclude_none=True))
        released_payload = build_task_released_payload(session_id, task_id)
        self._append_event("coord.task.released", released_payload)

    def request_handoff(
        self,
        *,
        session_id: str,
        target_session_id: str,
        task_id: str | None = None,
        scope: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        from vibe.core.coordination._models import build_handoff_requested_payload

        handoff_payload = build_handoff_requested_payload(
            session_id, target_session_id, task_id, scope or {}
        )
        self._append_event("coord.handoff.requested", handoff_payload)
        return {"status": "requested", **handoff_payload}

    def mark_lease_stale(self, *, session_id: str, task_id: str, reason: str) -> None:
        from vibe.core.coordination._models import build_lease_marked_stale_payload

        for path in sorted((self.root / "leases" / "paths").glob("*.json")):
            reservation = CoordinationPathReservation.model_validate_json(
                path.read_text(encoding="utf-8")
            )
            if reservation.session_id == session_id and reservation.task_id == task_id:
                reservation.status = "stale"
                self._write_json(path, reservation.model_dump(exclude_none=True))
        stale_payload = build_lease_marked_stale_payload(session_id, task_id, reason)
        self._append_event("coord.lease.marked_stale", stale_payload)
