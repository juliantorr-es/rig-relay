from __future__ import annotations

from collections.abc import Callable
import json
from pathlib import Path
from typing import Any

from websockets.http11 import Headers, Request, Response

from rig_relay.desktop.bridge_diagnostics import BridgeProbeReport
from rig_relay.desktop.bridge_state_machine import (
    DesktopBridgeEvent,
    DesktopBridgeStateMachine,
    InvalidBridgeTransitionError,
    TerminalBridgeStateError,
)

HTTP_OK = 200

__all__ = ["apply_probe_transition", "probe_healthz", "probe_path"]


def apply_probe_transition(
    state_machine: DesktopBridgeStateMachine,
    step_id: str,
    details: dict[str, Any] | None = None,
) -> None:
    payload = {"step_id": step_id, **(details or {})}
    match step_id:
        case "bridge:15":
            event = DesktopBridgeEvent.WEBSOCKET_CONNECTED
            reason = "websocket auth message received"
        case "bridge:16":
            event = DesktopBridgeEvent.AUTHENTICATED
            reason = "websocket auth accepted"
        case "bridge:17":
            event = DesktopBridgeEvent.PROJECTION_SENT
            reason = "first projection sent"
        case "bridge:18":
            event = DesktopBridgeEvent.PROJECTION_RENDERED
            reason = "projection rendered"
        case _:
            return
    try:
        state_machine.transition(event, reason=reason, attributes=payload)
    except (InvalidBridgeTransitionError, TerminalBridgeStateError):
        return


async def probe_healthz(
    report: BridgeProbeReport, build_healthz_fn: Callable[[], Response]
) -> None:
    try:
        resp = build_healthz_fn()
        body = json.loads(resp.body) if isinstance(resp.body, bytes) else {}
        report.add_ok(
            "bridge:07",
            "probe /healthz",
            details={"status": resp.status_code, "ok": body.get("ok")},
            message=f"HTTP {resp.status_code}, ok={body.get('ok')}",
        )
    except Exception as exc:
        report.add_warn(
            "bridge:07",
            "probe /healthz",
            message=f"Self-probe failed: {exc}",
            remediation="Bridge is running but /healthz is not responding.",
        )


async def probe_path(
    report: BridgeProbeReport,
    path: str,
    step_id: str,
    label: str,
    expected_content_type: str,
    http_handler: Callable[[Request, Path], Response | None],
    frontend_dir: Path,
) -> None:
    try:
        resp = http_handler(Request(path=path, headers=Headers({})), frontend_dir)
        if resp is None:
            report.add_fail(
                step_id,
                label,
                details={"path": path},
                message="No response (WebSocket upgrade intercepted?)",
                remediation=f"Check route for {path}.",
            )
            return
        ct = resp.headers.get("Content-Type", "")
        ok_status = resp.status_code == HTTP_OK
        if ok_status and expected_content_type == "javascript" and "text/html" in ct:
            report.add_fail(
                step_id,
                label,
                details={"path": path, "status": resp.status_code, "content_type": ct},
                message=f"Returned {ct}; expected javascript",
                remediation=f"Check that {path} is served as static file, not index.html fallback.",
            )
        elif ok_status:
            report.add_ok(
                step_id,
                label,
                details={"path": path, "status": resp.status_code, "content_type": ct},
                message=f"HTTP {resp.status_code}, {ct}",
            )
        else:
            report.add_fail(
                step_id,
                label,
                details={"path": path, "status": resp.status_code},
                message=f"HTTP {resp.status_code}",
                remediation=f"Check that {path} exists under frontend_dir.",
            )
    except Exception as exc:
        report.add_fail(
            step_id,
            label,
            message=f"Probe failed: {exc}",
            remediation=f"Check server is running and {path} is accessible.",
        )
