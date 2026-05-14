"""Rig Relay Coordination Store — Governance Seam.

Owned by ``rig_relay.coordination``. Legacy adapter at ``vibe.core.coordination``.

File-backed coordination store for task claims, path reservations,
session management, artifact references, conflicts, and events.

Usage:
    from rig_relay.coordination.store import CoordinationStore
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
from typing import Any, Literal

from rig_relay.coordination._canonical_json import dump_canonical_json
from rig_relay.coordination.models import (
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

    def _session_path(self, session_id: str) -> Path:
        return self.root / "sessions" / f"{session_id}.json"

    def _task_path(self, task_id: str) -> Path:
        return self.root / "tasks" / f"{task_id}.json"

    def _lease_path(self, path_hash: str) -> Path:
        return self.root / "leases" / "paths" / f"{path_hash}.json"

    def _artifact_path(self, artifact_sha256: str) -> Path:
        safe = artifact_sha256.replace(":", "_")
        return self.root / "artifacts" / f"{safe}.json"

    def _conflict_path(self, conflict_id: str) -> Path:
        return self.root / "conflicts" / f"{conflict_id}.json"

    @staticmethod
    def _is_prefix(parent: str, child: str) -> bool:
        return parent == child or child.startswith(parent.rstrip("/") + "/")

    def _iter_reservations(self) -> list[CoordinationPathReservation]:
        reservations: list[CoordinationPathReservation] = []
        for lease_path in sorted((self.root / "leases" / "paths").glob("*.json")):
            reservations.append(
                CoordinationPathReservation.model_validate_json(
                    lease_path.read_text(encoding="utf-8")
                )
            )
        return reservations

    def _path_key(self, canonical_json: str) -> str:
        return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()[:24]

    def _append_event(
        self, event_name: str, normalized_payload: dict[str, Any]
    ) -> None:
        event = CoordinationEvent(
            event_id=self._path_key(dump_canonical_json(normalized_payload)),
            session_id=normalized_payload.get("session_id"),
            task_id=normalized_payload.get("task_id"),
            sequence=self._next_sequence(),
            event_name=event_name,
            payload=normalized_payload,
            event_hash="sha256:"
            + hashlib.sha256(
                dump_canonical_json(dump_canonical_json(normalized_payload)).encode(
                    "utf-8"
                )
            ).hexdigest(),
        )
        events_path = self._events_path()
        with events_path.open("a", encoding="utf-8") as f:
            f.write(dump_canonical_json(event.model_dump(exclude_none=True)) + "\n")

    def _next_sequence(self) -> int:
        events_path = self._events_path()
        if not events_path.is_file():
            return 1
        try:
            with events_path.open("r", encoding="utf-8") as f:
                last_line = ""
                for line in f:
                    if line.strip():
                        last_line = line
            if last_line:
                last = json.loads(last_line)
                return (last.get("sequence", 0) or 0) + 1
        except (json.JSONDecodeError, OSError):
            pass
        return 1

    def register_session(self, session: CoordinationSession) -> CoordinationSession:
        session_path = self._session_path(session.session_id)
        self._write_json(session_path, session.model_dump(exclude_none=True))
        reg_payload = build_session_registered_payload(session)
        self._append_event("coord.session.registered", reg_payload)
        return session

    def heartbeat(
        self,
        *,
        session_id: str,
        task_id: str | None = None,
        status: str,
        reserved_paths: list[str] | None = None,
        current_step: str | None = None,
    ) -> CoordinationHeartbeat:
        heartbeat = CoordinationHeartbeat(
            session_id=session_id,
            task_id=task_id,
            status=status,
            current_step=current_step,
            reserved_paths=reserved_paths or [],
        )
        session_path = self._session_path(session_id)
        if session_path.is_file():
            session = CoordinationSession.model_validate_json(
                session_path.read_text(encoding="utf-8")
            )
            session.status = status
            session.updated_at = heartbeat.created_at
            session.reserved_paths = reserved_paths or []
            self._write_json(session_path, session.model_dump(exclude_none=True))
        hb_payload = build_heartbeat_payload(heartbeat)
        self._append_event("coord.session.heartbeat", hb_payload)
        return heartbeat

    def claim_task(
        self,
        *,
        session_id: str,
        task_id: str,
        claim_kind: str,
        ttl_seconds: int,
        scope: dict[str, Any] | None = None,
    ) -> CoordinationClaimResult:
        task_path = self._task_path(task_id)
        now = datetime.now(UTC)
        expires = now_plus(ttl_seconds)

        if task_path.exists():
            existing = CoordinationTaskClaim.model_validate_json(
                task_path.read_text(encoding="utf-8")
            )
            if existing.status == "active":
                expires_dt = datetime.fromisoformat(
                    existing.expires_at.replace("Z", "+00:00")
                    if existing.expires_at
                    else "1970-01-01T00:00:00+00:00"
                )
                if expires_dt > now:
                    # Same-owner renewal: refresh claim, don't block
                    same_owner = (
                        existing.session_id == session_id
                        and existing.task_id == task_id
                    )
                    if not same_owner:
                        conflict = CoordinationConflict(
                            conflict_id=str(hash(task_id + session_id) & 0xFFFFFFFF),
                            kind="task_already_claimed",
                            session_id=session_id,
                            other_session_id=existing.session_id,
                            task_id=task_id,
                            paths=[],
                            recommended_resolution="serialize_or_split_scope",
                        )
                        self._write_json(
                            self._conflict_path(conflict.conflict_id),
                            conflict.model_dump(exclude_none=True),
                        )
                        return CoordinationClaimResult(
                            allowed=False,
                            claim=None,
                            conflict=conflict,
                            warnings=[
                                f"Task '{task_id}' already claimed by {existing.session_id}"
                            ],
                        )

        scope_paths = list(scope.get("allowed_paths", [])) if scope else []
        claim = CoordinationTaskClaim(
            session_id=session_id,
            task_id=task_id,
            claim_kind=claim_kind,
            ttl_seconds=ttl_seconds,
            scope_allowed_paths=scope_paths,
            status="active",
            created_at=now.isoformat(),
            expires_at=expires,
        )
        self._write_json(task_path, claim.model_dump(exclude_none=True))
        claim_payload = build_task_claim_payload(claim)
        self._append_event("coord.task.claimed", claim_payload)
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
        expires = now_plus(ttl_seconds)
        normalized = [normalize_path(path) for path in paths]

        # ── Conflict detection ────────────────────────────────────
        # exclusive_write (mode="write") conflicts with both read and write.
        # shared_read (mode="read") conflicts only with existing write.
        for existing in self._iter_reservations():
            if existing.status != "active":
                continue
            # Same-owner renewal is allowed
            if existing.session_id == session_id and existing.task_id == task_id:
                continue
            # Read/read coexistence: no conflict
            if mode == "read" and existing.mode == "read":
                continue
            # Check for path overlap
            for existing_path in existing.paths:
                for raw_path in paths:
                    if self._is_prefix(existing_path, raw_path) or self._is_prefix(
                        raw_path, existing_path
                    ):
                        conflict_kind = (
                            "path_write_overlap"
                            if mode == "write"
                            else "read_blocked_by_write"
                        )
                        conflict = CoordinationConflict(
                            conflict_id=self._path_key("|".join(normalized)),
                            kind=conflict_kind,
                            session_id=session_id,
                            other_session_id=existing.session_id,
                            task_id=task_id,
                            paths=[raw_path],
                            recommended_resolution="serialize_or_split_scope",
                        )
                        self._write_json(
                            self._conflict_path(conflict.conflict_id),
                            conflict.model_dump(exclude_none=True),
                        )
                        refusal_payload = build_reservation_refused_payload(conflict)
                        self._append_event(
                            "coord.path.reservation_refused", refusal_payload
                        )
                        return CoordinationReservationResult(
                            allowed=False,
                            reservation=None,
                            conflict=conflict,
                            warnings=[
                                f"Path '{raw_path}' already reserved by {existing.session_id}"
                            ],
                        )

        reservation = CoordinationPathReservation(
            session_id=session_id,
            task_id=task_id,
            mode=mode,
            paths=normalized,
            ttl_seconds=ttl_seconds,
            expires_at=expires,
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
        released: list[str] = []
        normalized = [normalize_path(path) for path in paths]
        lease_key = self._path_key(session_id + task_id + "|".join(normalized))
        lease_path = self.root / "leases" / "paths" / f"{lease_key}.json"
        if lease_path.exists():
            reservation = CoordinationPathReservation.model_validate_json(
                lease_path.read_text(encoding="utf-8")
            )
            if reservation.session_id == session_id:
                reservation.status = "released"
                self._write_json(lease_path, reservation.model_dump(exclude_none=True))
                released.extend(normalized)
        if released:
            release_payload = build_path_released_payload(session_id, task_id, released)
            self._append_event("coord.path.released", release_payload)

    def publish_artifact(
        self,
        *,
        session_id: str,
        task_id: str | None = None,
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
        self._write_json(
            self._artifact_path(artifact_sha256), artifact.model_dump(exclude_none=True)
        )
        art_payload = build_artifact_published_payload(artifact)
        self._append_event("coord.artifact.published", art_payload)
        return artifact

    def report_conflict(self, conflict: CoordinationConflict) -> CoordinationConflict:
        self._write_json(
            self._conflict_path(conflict.conflict_id),
            conflict.model_dump(exclude_none=True),
        )
        conflict_payload = build_conflict_reported_payload(conflict)
        self._append_event("coord.conflict.reported", conflict_payload)
        return conflict

    @staticmethod
    def _is_expired(expires_at: str | None) -> bool:
        if expires_at is None:
            return False
        return datetime.fromisoformat(expires_at) <= datetime.now(UTC)

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
                for rpath in reservation.paths:
                    reservations[
                        f"{reservation.session_id}:{reservation.task_id}:{rpath}"
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

    def read_state_projection(self) -> CoordinationStateProjection:
        sessions: dict[str, CoordinationSession] = {}
        tasks: dict[str, CoordinationTaskClaim] = {}
        leases: dict[str, CoordinationPathReservation] = {}
        artifacts: list[CoordinationArtifactRef] = []
        conflicts: list[CoordinationConflict] = []

        for session_path in sorted((self.root / "sessions").glob("*.json")):
            session = CoordinationSession.model_validate_json(
                session_path.read_text(encoding="utf-8")
            )
            sessions[session.session_id] = session

        for task_path in sorted((self.root / "tasks").glob("*.json")):
            task = CoordinationTaskClaim.model_validate_json(
                task_path.read_text(encoding="utf-8")
            )
            if task.status == "active":
                tasks[task.task_id] = task

        for lease_path in sorted((self.root / "leases" / "paths").glob("*.json")):
            lease = CoordinationPathReservation.model_validate_json(
                lease_path.read_text(encoding="utf-8")
            )
            if lease.status == "active":
                expires_at = lease.expires_at
                if expires_at is not None and datetime.fromisoformat(
                    expires_at.replace("Z", "+00:00")
                ) <= datetime.now(UTC):
                    continue
                leases[lease_path.stem] = lease

        recent_artifacts = sorted(
            (self.root / "artifacts").glob("*.json"), reverse=True
        )[:50]
        for art_path in recent_artifacts:
            artifact = CoordinationArtifactRef.model_validate_json(
                art_path.read_text(encoding="utf-8")
            )
            artifacts.append(artifact)

        for conflict_path in sorted((self.root / "conflicts").glob("*.json")):
            conflict = CoordinationConflict.model_validate_json(
                conflict_path.read_text(encoding="utf-8")
            )
            conflicts.append(conflict)

        projection = CoordinationStateProjection(
            active_sessions=sessions,
            active_task_claims=tasks,
            active_path_reservations=leases,
            recent_artifacts=artifacts,
            conflicts=conflicts,
        )

        projection = projection.with_hash()
        read_payload = build_projection_read_payload(None, projection.projection_sha256)
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
        from rig_relay.coordination.models import build_handoff_requested_payload

        handoff_payload = build_handoff_requested_payload(
            session_id, target_session_id, task_id, scope or {}
        )
        self._append_event("coord.handoff.requested", handoff_payload)
        return {"status": "requested", **handoff_payload}

    def mark_lease_stale(self, *, session_id: str, task_id: str, reason: str) -> None:
        from rig_relay.coordination.models import build_lease_marked_stale_payload

        for path in sorted((self.root / "leases" / "paths").glob("*.json")):
            reservation = CoordinationPathReservation.model_validate_json(
                path.read_text(encoding="utf-8")
            )
            if reservation.session_id == session_id and reservation.task_id == task_id:
                reservation.status = "stale"
                self._write_json(path, reservation.model_dump(exclude_none=True))
        stale_payload = build_lease_marked_stale_payload(session_id, task_id, reason)
        self._append_event("coord.lease.marked_stale", stale_payload)


# ── alias ────────────────────────────────────────────────────

FileCoordinationStore = CoordinationStore

__all__ = ["CoordinationStore", "FileCoordinationStore"]
