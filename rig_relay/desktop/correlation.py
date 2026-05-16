"""Desktop lifecycle correlation — traceable bridge, transport, and intent events.

Creates correlation IDs that connect UI actions, bridge probe ladder steps,
WebSocket transport events, intent dispatch, and backend validation/supervisor
spans into one evidence trace.
"""

from __future__ import annotations

import hashlib
import secrets
import time
from typing import Any


def new_correlation_id() -> str:
    """Generate a short, safe, local-only correlation id."""
    return f"corr_{secrets.token_hex(6)}"


def new_transport_session_id() -> str:
    """Generate a stable transport session id."""
    return f"ts_{secrets.token_hex(8)}"


def hash_message_payload(data: str) -> str:
    """Content-safe hash of a message payload."""
    return hashlib.sha256(data.encode()).hexdigest()[:16]


def hash_dict_payload(data: dict[str, Any]) -> str:
    """Content-safe hash of a dict payload."""
    import json

    canonical = json.dumps(
        data, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


class DesktopCorrelation:
    """Correlation state for a desktop lifecycle.

    Carries a correlation_id, optional trace_recorder, and emits
    safe lifecycle events across bridge, transport, and intent boundaries.

    Usage:
        corr = DesktopCorrelation(trace_recorder=recorder)
        corr.emit_bridge_step("bridge:01", "assets verified", status="ok")
        corr.emit_transport_event("desktop.transport.connecting", attributes={...})
        corr.emit_intent_dispatched("ralph_scan", intent_id="...", payload_hash="...")

    All attributes are content-safe: no raw paths, command text, secrets, or
    message payloads.
    """

    __slots__ = ("correlation_id", "_recorder", "_started_at")

    def __init__(
        self, *, correlation_id: str | None = None, trace_recorder: Any | None = None
    ) -> None:
        self.correlation_id = correlation_id or new_correlation_id()
        self._recorder = trace_recorder
        self._started_at = time.time()

    @property
    def is_active(self) -> bool:
        return self._recorder is not None

    def emit_event(
        self, name: str, attributes: dict[str, object] | None = None
    ) -> None:
        if self._recorder is None:
            return
        attrs = dict(attributes or {})
        attrs["correlation_id"] = self.correlation_id
        self._recorder.event(name, attributes=attrs)

    def emit_span(self, name: str, attributes: dict[str, object] | None = None) -> Any:
        if self._recorder is None:
            return None
        attrs = dict(attributes or {})
        attrs["correlation_id"] = self.correlation_id
        return self._recorder.start_span(name, attributes=attrs)

    def end_span(
        self, span: Any, status: str = "ok", attributes: dict[str, object] | None = None
    ) -> None:
        if self._recorder is None:
            return
        attrs = dict(attributes or {})
        attrs["correlation_id"] = self.correlation_id
        from rig_relay.tracing.models import TraceStatus

        self._recorder.end_span(
            span, status=getattr(TraceStatus, status, TraceStatus.ok), attributes=attrs
        )

    def emit_bridge_step(
        self,
        step_id: str,
        label: str,
        status: str = "ok",
        details: dict[str, Any] | None = None,
        duration_ms: int | None = None,
    ) -> None:
        self.emit_event(
            "desktop.bridge.probe",
            attributes={
                "bridge.step_id": step_id,
                "bridge.step_label": label,
                "bridge.step_status": status,
                **(_safe_details(details)),
                **(dict(duration_ms=duration_ms) if duration_ms is not None else {}),
            },
        )

    def emit_transport_event(
        self,
        event_name: str,
        transport_session_id: str | None = None,
        attributes: dict[str, object] | None = None,
    ) -> None:
        attrs = dict(attributes or {})
        if transport_session_id:
            attrs["transport.session_id"] = transport_session_id
        self.emit_event(event_name, attributes=attrs)

    def emit_intent_dispatched(
        self,
        intent_name: str,
        intent_id: str = "",
        payload_hash: str = "",
        payload_kind: str = "",
    ) -> None:
        self.emit_event(
            "desktop.intent.dispatched",
            attributes={
                "intent.name": intent_name,
                "intent.id": intent_id or new_correlation_id(),
                "intent.payload_hash": payload_hash,
                "intent.payload_kind": payload_kind,
            },
        )

    def emit_intent_result(
        self,
        intent_name: str,
        intent_id: str,
        result_status: str,
        result_refusal_code: str = "",
        duration_ms: int | None = None,
    ) -> None:
        attrs: dict[str, object] = {
            "intent.name": intent_name,
            "intent.id": intent_id,
            "intent.result_status": result_status,
        }
        if result_refusal_code:
            attrs["intent.refusal_code"] = result_refusal_code
        if duration_ms is not None:
            attrs["duration_ms"] = duration_ms
        self.emit_event("desktop.intent.completed", attributes=attrs)


def _safe_details(details: dict[str, Any] | None) -> dict[str, object]:
    """Filter details to only safe keys."""
    if not details:
        return {}
    safe_keys = {
        "port",
        "host",
        "tls_enabled",
        "transport_label",
        "token_length",
        "token_present",
        "cert_mode",
        "cert_fingerprint",
        "projection_digest",
        "widget_count",
        "frontend_dir_hash",
        "frontend_dir_kind",
        "ws_scheme",
        "frontend_scheme",
    }
    result: dict[str, object] = {}
    for k, v in details.items():
        if k in safe_keys:
            result[k] = v
        elif k == "frontend_dir" and isinstance(v, str):
            import hashlib

            result["frontend_dir_hash"] = hashlib.sha256(v.encode()).hexdigest()[:16]
            result["frontend_dir_kind"] = _classify_path_kind(v)
        elif k == "ws_url" and isinstance(v, str):
            result["ws_scheme"] = "wss" if v.startswith("wss") else "ws"
        elif k == "frontend_url" and isinstance(v, str):
            result["frontend_scheme"] = "https" if v.startswith("https") else "http"
    return result


def _classify_path_kind(path: str) -> str:
    """Classify a path for trace safety."""
    p = str(path).lower()
    if "/tmp" in p or "/var/folders" in p:
        return "temp"
    if "worktree" in p:
        return "worktree"
    if "application support" in p:
        return "app_support"
    return "repo"


__all__ = [
    "DesktopCorrelation",
    "_classify_path_kind",
    "hash_dict_payload",
    "hash_message_payload",
    "new_correlation_id",
    "new_transport_session_id",
]
