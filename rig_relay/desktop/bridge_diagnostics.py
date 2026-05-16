"""Bridge diagnostics — startup probe ladder for DesktopBridgeServer.

Produces a step-by-step startup report showing every gate needed for
pywebview to load the frontend and connect to the backend.

Every critical startup step emits a stable step id, human label,
status (ok/warn/fail/skipped), details, and a remediation hint on failure.
"""

from __future__ import annotations

import json
import time
from enum import Enum
from pathlib import Path
from typing import Any

BRIDGE_PROBE_SCHEMA = "rig.desktop.bridge_probe.v1"


class BridgeProbeStatus(str, Enum):
    ok = "ok"
    warn = "warn"
    fail = "fail"
    skipped = "skipped"


class BridgeProbeStep:
    __slots__ = (
        "step_id", "label", "status", "details",
        "message", "remediation", "duration_ms",
    )

    def __init__(
        self,
        step_id: str,
        label: str,
        status: BridgeProbeStatus,
        details: dict[str, Any] | None = None,
        message: str = "",
        remediation: str | None = None,
        duration_ms: int | None = None,
    ) -> None:
        self.step_id = step_id
        self.label = label
        self.status = status
        self.details = details or {}
        self.message = message
        self.remediation = remediation
        self.duration_ms = duration_ms

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "step_id": self.step_id,
            "label": self.label,
            "status": self.status.value,
            "message": self.message,
        }
        if self.details:
            d["details"] = self.details
        if self.remediation:
            d["remediation"] = self.remediation
        if self.duration_ms is not None:
            d["duration_ms"] = self.duration_ms
        return d


class BridgeProbeReport:
    __slots__ = (
        "schema_version", "started_at", "mode", "tls_enabled",
        "frontend_url", "ws_url", "steps", "_failed_ids", "_warning_ids",
    )

    def __init__(
        self,
        *,
        mode: str = "unknown",
        tls_enabled: bool = False,
        frontend_url: str = "",
        ws_url: str = "",
    ) -> None:
        self.schema_version = BRIDGE_PROBE_SCHEMA
        self.started_at = time.time()
        self.mode = mode
        self.tls_enabled = tls_enabled
        self.frontend_url = frontend_url
        self.ws_url = ws_url
        self.steps: list[BridgeProbeStep] = []
        self._failed_ids: list[str] = []
        self._warning_ids: list[str] = []

    @property
    def ok(self) -> bool:
        return len(self._failed_ids) == 0

    @property
    def failed_step_ids(self) -> list[str]:
        return list(self._failed_ids)

    @property
    def warning_step_ids(self) -> list[str]:
        return list(self._warning_ids)

    def add_step(self, step: BridgeProbeStep) -> None:
        self.steps.append(step)
        if step.status == BridgeProbeStatus.fail:
            self._failed_ids.append(step.step_id)
        elif step.status == BridgeProbeStatus.warn:
            self._warning_ids.append(step.step_id)

    def add_ok(
        self,
        step_id: str,
        label: str,
        details: dict[str, Any] | None = None,
        message: str = "",
        duration_ms: int | None = None,
    ) -> BridgeProbeStep:
        step = BridgeProbeStep(
            step_id=step_id,
            label=label,
            status=BridgeProbeStatus.ok,
            details=details,
            message=message,
            duration_ms=duration_ms,
        )
        self.add_step(step)
        return step

    def add_warn(
        self,
        step_id: str,
        label: str,
        details: dict[str, Any] | None = None,
        message: str = "",
        remediation: str | None = None,
        duration_ms: int | None = None,
    ) -> BridgeProbeStep:
        step = BridgeProbeStep(
            step_id=step_id,
            label=label,
            status=BridgeProbeStatus.warn,
            details=details,
            message=message,
            remediation=remediation,
            duration_ms=duration_ms,
        )
        self.add_step(step)
        return step

    def add_fail(
        self,
        step_id: str,
        label: str,
        details: dict[str, Any] | None = None,
        message: str = "",
        remediation: str | None = None,
        duration_ms: int | None = None,
    ) -> BridgeProbeStep:
        step = BridgeProbeStep(
            step_id=step_id,
            label=label,
            status=BridgeProbeStatus.fail,
            details=details,
            message=message,
            remediation=remediation,
            duration_ms=duration_ms,
        )
        self.add_step(step)
        return step

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "started_at": self.started_at,
            "mode": self.mode,
            "tls_enabled": self.tls_enabled,
            "frontend_url": self.frontend_url,
            "ws_url": self.ws_url,
            "ok": self.ok,
            "failed_step_ids": self.failed_step_ids,
            "warning_step_ids": self.warning_step_ids,
            "steps": [s.to_dict() for s in self.steps],
        }

    def print_terminal(self, verbose: bool = False) -> None:
        for step in self.steps:
            icon = _status_icon(step.status)
            line = f"  {icon} [{step.step_id}] {step.label}"
            if step.message:
                line += f": {step.message}"
            if verbose and step.details:
                for k, v in step.details.items():
                    line += f"\n       {k}={v}"
            if step.remediation and step.status != BridgeProbeStatus.ok:
                line += f"\n       ↳ {step.remediation}"
            print(line)

    def write_json(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2) + "\n")

    def write_text_log(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        lines: list[str] = []
        lines.append(f"=== Bridge Probe Report ({self.schema_version}) ===")
        lines.append(f"  mode={self.mode} tls_enabled={self.tls_enabled}")
        lines.append(f"  frontend_url={self.frontend_url}")
        lines.append(f"  ws_url={self.ws_url}")
        lines.append(f"  ok={self.ok}")
        lines.append("")
        for step in self.steps:
            icon = _terminal_icon(step.status)
            lines.append(f"  {icon} [{step.step_id}] {step.label}")
            if step.message:
                lines.append(f"       {step.message}")
            if step.details:
                for k, v in step.details.items():
                    lines.append(f"       {k}={v}")
            if step.remediation and step.status != BridgeProbeStatus.ok:
                lines.append(f"       ↳ {step.remediation}")
            if step.duration_ms:
                lines.append(f"       duration={step.duration_ms}ms")
            lines.append("")
        path.write_text("\n".join(lines) + "\n")


def _status_icon(status: BridgeProbeStatus) -> str:
    match status:
        case BridgeProbeStatus.ok:
            return "✅"
        case BridgeProbeStatus.warn:
            return "⚠️"
        case BridgeProbeStatus.fail:
            return "❌"
        case BridgeProbeStatus.skipped:
            return "⬜"


def _terminal_icon(status: BridgeProbeStatus) -> str:
    match status:
        case BridgeProbeStatus.ok:
            return "[OK]"
        case BridgeProbeStatus.warn:
            return "[WARN]"
        case BridgeProbeStatus.fail:
            return "[FAIL]"
        case BridgeProbeStatus.skipped:
            return "[SKIP]"


def _redact_token(token: str) -> str:
    if not token:
        return "(empty)"
    if len(token) <= 8:
        return "*" * len(token)
    return token[:4] + "…" + token[-4:]


__all__ = [
    "BRIDGE_PROBE_SCHEMA",
    "BridgeProbeStatus",
    "BridgeProbeStep",
    "BridgeProbeReport",
]
