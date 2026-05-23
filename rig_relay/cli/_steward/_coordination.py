"""Steward coordination bridge — writes authoritative runtime events.

Thin adapter over the canonical CoordinationStore. Maps steward lifecycle
transitions to coordination events using existing vocabulary where available
and steward-specific event names for transitions not yet in the canonical set.

Rules:
- CoordinationStore owns authoritative runtime events.
- Steward is the sole coordination writer in this slice — workers do not
  write claims, leases, or lifecycle transitions.
- Events carry correlation identifiers: trace_id, session_id, task_id,
  worker_id, cycle_id, artifact_sha256.
- Events are content-light: never store raw prompts, reasoning, source
  content, secrets, or raw worker transcripts.
- Artifact publication events reference artifact path + SHA256, never
  embed payload bodies.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any
import uuid

from rig_relay.coordination.models import CoordinationConflict, CoordinationSession
from rig_relay.coordination.store import CoordinationStore

COORDINATION_ROOT = ".build/rig-relay/coordination"

_ALLOWED_STEWARD_EVENT_NAMES: frozenset[str] = frozenset({
    "steward.cycle.started",
    "steward.cycle.finished",
    "steward.git.scanned",
    "steward.queue.read",
    "steward.task.considered",
    "steward.task.dispatched",
    "steward.task.completed",
    "steward.task.failed",
    "steward.task.claim_refused",
    "steward.task.reservation_refused",
    "steward.repair.proposed",
    "steward.repair.dispatched",
})


def _workspace_id(root: Path) -> str:
    repo_hash = hashlib.sha256(str(root.resolve()).encode()).hexdigest()[:12]
    return f"rig-{repo_hash}"


def _cycle_id() -> str:
    return uuid.uuid4().hex[:16]


def _worker_id(task_id: str) -> str:
    return f"opencode-{task_id}"


class StewardCoordinationBridge:
    """Writes steward lifecycle transitions into the coordination plane."""

    def __init__(self, root: Path) -> None:
        self._root = root
        self._store = CoordinationStore(root / COORDINATION_ROOT)
        self._trace_id: str | None = None

    @property
    def store(self) -> CoordinationStore:
        return self._store

    def set_trace_id(self, trace_id: str) -> None:
        self._trace_id = trace_id

    def _record(
        self,
        event_name: str,
        session_id: str,
        payload: dict[str, Any],
        *,
        task_id: str | None = None,
    ) -> None:
        if event_name not in _ALLOWED_STEWARD_EVENT_NAMES:
            raise ValueError(
                f"Rejected steward event name {event_name!r}. "
                f"Allowed: {sorted(_ALLOWED_STEWARD_EVENT_NAMES)}"
            )
        p: dict[str, Any] = {
            **payload,
            "event_kind": payload.get("event_kind", event_name),
        }
        if self._trace_id:
            p["trace_id"] = self._trace_id
        self._store.record_event(
            event_name=event_name, session_id=session_id, task_id=task_id, payload=p
        )

    def register_cycle(
        self, session_id: str, branch: str, head: str, lane_id: str = "default"
    ) -> CoordinationSession:
        session = CoordinationSession(
            session_id=session_id,
            task_id=None,
            agent_profile="steward",
            status="waking",
            reserved_paths=[],
        )
        self._store.register_session(session)
        self._record(
            "steward.cycle.started",
            session_id,
            {"branch": branch, "head": head, "lane_id": lane_id, "status": "waking"},
        )
        return session

    def heartbeat(
        self,
        session_id: str,
        task_id: str | None,
        status: str,
        *,
        current_step: str | None = None,
        reserved_paths: list[str] | None = None,
    ) -> None:
        self._store.heartbeat(
            session_id=session_id,
            task_id=task_id,
            status=status,
            current_step=current_step,
            reserved_paths=reserved_paths or [],
        )

    def record_git_scan(
        self,
        session_id: str,
        branch: str,
        head: str,
        dirty_modified: int,
        dirty_staged: int,
        dirty_untracked: int,
        dirty_file_hashes: list[str],
    ) -> None:
        self._record(
            "steward.git.scanned",
            session_id,
            {
                "branch": branch,
                "head": head,
                "dirty_modified_count": dirty_modified,
                "dirty_staged_count": dirty_staged,
                "dirty_untracked_count": dirty_untracked,
                "dirty_file_hashes": dirty_file_hashes,
                "dirty_file_count": len(dirty_file_hashes),
            },
        )

    def record_queue_read(
        self,
        session_id: str,
        queue_item_count: int,
        lane_count: int,
        *,
        issue_item_count: int = 0,
        work_item_count: int | None = None,
    ) -> None:
        if work_item_count is None:
            work_item_count = queue_item_count + issue_item_count
        payload = {"queue_item_count": queue_item_count, "lane_count": lane_count}
        if issue_item_count:
            payload["issue_item_count"] = issue_item_count
            payload["work_item_count"] = work_item_count
        self._record("steward.queue.read", session_id, payload)

    def record_task_considered(
        self,
        session_id: str,
        task_id: str,
        title: str,
        status: str,
        priority: int,
        eligible: bool,
        blocker_classes: list[str] | None = None,
    ) -> None:
        self._record(
            "steward.task.considered",
            session_id,
            {
                "task_title_sha256": hashlib.sha256(title.encode("utf-8")).hexdigest(),
                "queue_status": status,
                "priority": priority,
                "eligible": eligible,
                "blocker_classes": blocker_classes or [],
            },
            task_id=task_id,
        )

    def claim_task(
        self,
        session_id: str,
        task_id: str,
        allowed_paths: list[str],
        ttl_seconds: int = 1800,
    ) -> bool:
        result = self._store.claim_task(
            session_id=session_id,
            task_id=task_id,
            claim_kind="steward_dispatch",
            ttl_seconds=ttl_seconds,
            scope={"allowed_paths": allowed_paths},
        )
        if not result.allowed:
            self._record(
                "steward.task.claim_refused",
                session_id,
                {
                    "reason": "claim_refused",
                    "conflict_kind": result.conflict.kind
                    if result.conflict
                    else "unknown",
                },
                task_id=task_id,
            )
        return result.allowed

    def reserve_paths(
        self, session_id: str, task_id: str, paths: list[str], ttl_seconds: int = 1800
    ) -> bool:
        result = self._store.reserve_paths(
            session_id=session_id,
            task_id=task_id,
            mode="write",
            paths=paths,
            ttl_seconds=ttl_seconds,
        )
        if not result.allowed:
            self._record(
                "steward.task.reservation_refused",
                session_id,
                {
                    "reason": "reservation_refused",
                    "conflict_kind": result.conflict.kind
                    if result.conflict
                    else "unknown",
                },
                task_id=task_id,
            )
        return result.allowed

    def record_dispatch(
        self,
        session_id: str,
        task_id: str,
        worker_id: str,
        command_sha256: str,
        dry_run: bool,
        stream_mode: bool,
    ) -> None:
        self._record(
            "steward.task.dispatched",
            session_id,
            {
                "worker_id": worker_id,
                "command_sha256": command_sha256,
                "dry_run": dry_run,
                "stream_mode": stream_mode,
                "engine": "opencode",
            },
            task_id=task_id,
        )

    def record_completion(
        self,
        session_id: str,
        task_id: str,
        worker_id: str,
        exit_code: int,
        duration_ms: int | None = None,
    ) -> None:
        self._record(
            "steward.task.completed",
            session_id,
            {
                "worker_id": worker_id,
                "exit_code": exit_code,
                "duration_ms": duration_ms,
                "outcome": "completed" if exit_code == 0 else "failed",
            },
            task_id=task_id,
        )
        self._store.release_task(session_id=session_id, task_id=task_id)

    def record_failure(
        self,
        session_id: str,
        task_id: str,
        worker_id: str,
        exit_code: int,
        duration_ms: int | None = None,
    ) -> None:
        self._record(
            "steward.task.failed",
            session_id,
            {
                "worker_id": worker_id,
                "exit_code": exit_code,
                "duration_ms": duration_ms,
            },
            task_id=task_id,
        )
        self._store.release_task(session_id=session_id, task_id=task_id)

    def record_blocked(
        self, session_id: str, task_id: str, blocker_classes: list[str]
    ) -> None:
        for i, blocker_cls in enumerate(blocker_classes):
            conflict = CoordinationConflict(
                conflict_id=hashlib.sha256(
                    f"{task_id}:{blocker_cls}:{i}".encode()
                ).hexdigest()[:16],
                kind=blocker_cls,
                session_id=session_id,
                task_id=task_id,
                paths=[],
                recommended_resolution="human_review",
            )
            self._store.report_conflict(conflict)

    def publish_artifact_ref(
        self,
        session_id: str,
        task_id: str | None,
        artifact_kind: str,
        artifact_path: str,
        artifact_sha256: str,
        schema_version: str,
    ) -> None:
        self._store.publish_artifact(
            session_id=session_id,
            task_id=task_id,
            artifact_kind=artifact_kind,
            artifact_uri=artifact_path,
            artifact_sha256=artifact_sha256,
            schema_id=schema_version,
        )

    def record_repair_proposed(
        self,
        session_id: str,
        blocker_class: str,
        diagnosis_id: str,
        repairable: bool,
        repair_attempts: int,
    ) -> None:
        self._record(
            "steward.repair.proposed",
            session_id,
            {
                "blocker_class": blocker_class,
                "diagnosis_id": diagnosis_id,
                "repairable": repairable,
                "repair_attempts_so_far": repair_attempts,
            },
        )

    def record_repair_dispatched(
        self, session_id: str, repair_id: str, task_id: str, worker_id: str
    ) -> None:
        self._record(
            "steward.repair.dispatched",
            session_id,
            {"repair_id": repair_id, "worker_id": worker_id},
            task_id=task_id,
        )

    def record_cycle_finished(
        self, session_id: str, state: str, exit_code: int
    ) -> None:
        self._record(
            "steward.cycle.finished",
            session_id,
            {"final_state": state, "exit_code": exit_code},
        )

    def release_paths(self, session_id: str, task_id: str, paths: list[str]) -> None:
        self._store.release_paths(session_id=session_id, task_id=task_id, paths=paths)


__all__ = [
    "COORDINATION_ROOT",
    "StewardCoordinationBridge",
    "_cycle_id",
    "_worker_id",
    "_workspace_id",
]
