from __future__ import annotations

from datetime import UTC, datetime
import os
from pathlib import Path
import threading
from typing import Any

from pydantic import BaseModel, ConfigDict

LIFECYCLE_SCHEMA_VERSION = "rig.relay.bridge_lifecycle_event.v1"


class LifecycleEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = LIFECYCLE_SCHEMA_VERSION
    event_id: str = ""
    timestamp: str = ""
    source: str = ""
    step_id: str = ""
    lifecycle_phase: str = ""
    status: str = ""
    handshake_id: str = ""
    sequence: int = 0
    parent_step_id: str = ""
    safe_details: dict[str, Any] = {}
    error_code: str = ""
    error_message: str = ""
    duration_ms: int | None = None


class LifecycleSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "rig.relay.bridge_lifecycle_summary.v1"
    handshake_id: str = ""
    bridge_url: str = ""
    websocket_url: str = ""
    head_sha: str = ""
    generated_at: str = ""
    overall_status: str = "incomplete"
    total_steps: int = 0
    completed_steps: int = 0
    failed_steps: int = 0
    skipped_steps: int = 0
    ordered_steps: list[str] = []
    missing_steps: list[str] = []
    failed_steps_list: list[str] = []
    first_failure_step: str = ""
    first_failure_reason: str = ""
    widget_mount_status: str = "not_started"
    ready_status: str = "not_ready"
    frontend_events_received: int = 0
    backend_events_received: int = 0
    last_event_timestamp: str = ""
    last_step_id: str = ""


def _default_evidence_dir() -> Path:
    return (
        Path(__file__).resolve().parent.parent.parent
        / ".build"
        / "rig-relay"
        / "evidence"
    )


def _phase_from_step(step_id: str) -> str:
    if step_id.startswith("bridge_"):
        return "bridge_startup"
    if step_id.startswith("backend_ws_") or step_id.startswith("backend_projection_"):
        return "projection"
    if (
        step_id.startswith("frontend_boot_")
        or step_id.startswith("frontend_module_")
        or step_id.startswith("frontend_runtime_")
    ):
        return "frontend_boot"
    if (
        step_id.startswith("frontend_websocket_")
        or step_id.startswith("frontend_socket_")
        or step_id.startswith("frontend_auth_")
        or step_id.startswith("frontend_transport_")
    ):
        return "transport"
    if step_id.startswith("frontend_projection_"):
        return "projection"
    if step_id.startswith("frontend_widgets_"):
        return "widgets"
    if step_id.startswith("frontend_ready") or step_id.startswith("frontend_failed"):
        return "terminal"
    return "unknown"


class LifecycleArtifactWriter:
    def __init__(self, evidence_dir: Path | None = None) -> None:
        self.evidence_dir = evidence_dir or _default_evidence_dir()
        self._lock = threading.RLock()
        self._seq = 0
        self._events: list[LifecycleEvent] = []
        self._handshake_id = ""

    @property
    def artifact_path(self) -> Path:
        return self.evidence_dir / "bridge_lifecycle_trace.v1.jsonl"

    @property
    def summary_path(self) -> Path:
        return self.evidence_dir / "bridge_lifecycle_summary.v1.json"

    def set_handshake_id(self, handshake_id: str) -> None:
        self._handshake_id = handshake_id

    def write_event(
        self,
        *,
        step_id: str,
        status: str,
        source: str,
        handshake_id: str = "",
        lifecycle_phase: str = "",
        parent_step_id: str = "",
        safe_details: dict[str, Any] | None = None,
        error_message: str = "",
        duration_ms: int | None = None,
    ) -> LifecycleEvent:
        from uuid import uuid4

        with self._lock:
            self._seq += 1
        hsid = handshake_id or self._handshake_id
        event = LifecycleEvent(
            event_id=uuid4().hex[:12],
            timestamp=datetime.now(UTC).isoformat(),
            source=source,
            step_id=step_id,
            lifecycle_phase=lifecycle_phase or _phase_from_step(step_id),
            status=status,
            handshake_id=hsid,
            sequence=self._seq,
            parent_step_id=parent_step_id,
            safe_details=safe_details or {},
            error_message=error_message,
            duration_ms=duration_ms,
        )
        with self._lock:
            self._events.append(event)
            self._write_line(event)
        return event

    def _write_line(self, event: LifecycleEvent) -> None:
        self.evidence_dir.mkdir(parents=True, exist_ok=True)
        line = event.model_dump_json(exclude_none=True) + "\n"
        try:
            with open(self.artifact_path, "a", encoding="utf-8") as f:
                f.write(line)
                f.flush()
                os.fsync(f.fileno())
        except OSError:
            pass

    def build_summary(self) -> LifecycleSummary:
        from rig_relay.desktop.lifecycle_steps import (
            LifecycleStep,
            validate_lifecycle_completeness,
        )

        with self._lock:
            events = list(self._events)

        completed: set[LifecycleStep] = set()
        failed: list[str] = []
        ordered: list[str] = []
        first_failure = ""
        first_failure_reason = ""
        frontend_count = 0
        backend_count = 0
        last_ts = ""
        last_step = ""
        widget_status = "not_started"
        ready_step_found = False

        for e in sorted(events, key=lambda e: e.sequence):
            ordered.append(e.step_id)
            last_ts = e.timestamp
            last_step = e.step_id
            if e.source == "frontend":
                frontend_count += 1
            elif e.source in ("backend", "websocket"):
                backend_count += 1

            try:
                step = LifecycleStep(e.step_id)
            except ValueError:
                continue

            if e.status in ("ok", "started"):
                completed.add(step)

            if e.status == "failed" and not first_failure:
                failed.append(e.step_id)
                first_failure = e.step_id
                first_failure_reason = e.error_message

            if step == LifecycleStep.FRONTEND_WIDGETS_MOUNT_OK:
                widget_status = "mounted"
            elif step == LifecycleStep.FRONTEND_WIDGETS_MOUNT_STARTED:
                widget_status = "mounting"
            elif step == LifecycleStep.FRONTEND_READY:
                ready_step_found = True

        is_ready, missing = validate_lifecycle_completeness(completed)
        missing_strs = [s.value for s in missing]
        failed_strs = list(failed)

        overall = "incomplete"
        if ready_step_found and is_ready:
            overall = "ready"
        elif LifecycleStep.FRONTEND_FAILED in completed:
            overall = "failed"
        elif len(failed) > 0:
            overall = "failed"
        elif ready_step_found and not is_ready:
            overall = "incomplete"

        return LifecycleSummary(
            handshake_id=self._handshake_id,
            generated_at=datetime.now(UTC).isoformat(),
            overall_status=overall,
            total_steps=len(events),
            completed_steps=len(completed),
            failed_steps=len(failed),
            skipped_steps=len(events) - len(completed) - len(failed),
            ordered_steps=ordered,
            missing_steps=missing_strs,
            failed_steps_list=failed_strs,
            first_failure_step=first_failure,
            first_failure_reason=first_failure_reason,
            widget_mount_status=widget_status,
            ready_status="ready" if ready_step_found else "not_ready",
            frontend_events_received=frontend_count,
            backend_events_received=backend_count,
            last_event_timestamp=last_ts,
            last_step_id=last_step,
        )

    def write_summary(self) -> LifecycleSummary:
        summary = self.build_summary()
        self.evidence_dir.mkdir(parents=True, exist_ok=True)
        self.summary_path.write_text(
            summary.model_dump_json(indent=2) + "\n", encoding="utf-8"
        )
        return summary

    def get_events(self) -> list[LifecycleEvent]:
        with self._lock:
            return list(self._events)

    def clear_for_new_handshake(self) -> None:
        with self._lock:
            self._events.clear()
            self._seq = 0


__all__ = [
    "LIFECYCLE_SCHEMA_VERSION",
    "LifecycleArtifactWriter",
    "LifecycleEvent",
    "LifecycleSummary",
]
