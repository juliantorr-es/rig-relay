from __future__ import annotations

import json
import logging
import mimetypes
from pathlib import Path
from typing import TYPE_CHECKING, Any
import urllib.parse

from websockets.http11 import Headers, Response

from rig_relay.core.logger import logger
from rig_relay.desktop.bridge_state_machine import DesktopBridgeEvent

if TYPE_CHECKING:
    from rig_relay.desktop._bridge_config import (
        DesktopBridgeConfig,
        DesktopBridgeRuntimeConfig,
    )
    from rig_relay.desktop.bridge_state_machine import DesktopBridgeStateMachine

mimetypes.init()

HTTP_OK = 200

_JSON_HEADERS = Headers({"Content-Type": "application/json"})


class _WebSocketNoiseFilter(logging.Filter):
    """Downgrade non-WebSocket HTTP request errors to warnings.

    The websockets library's Request.parse() validates GET method before
    process_request() runs. Non-GET requests (POST, OPTIONS, etc.) trigger
    ValueError with full traceback. This filter downgrades those specific
    errors to WARNING level — they are expected noise from browser
    breadcrumbs / pywebview preflight, not real WebSocket failures.
    """

    _SUPPRESS_PATTERNS = (
        "unsupported HTTP method",
        "unsupported protocol",
        "invalid HTTP request line",
    )

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        if any(pattern in msg for pattern in self._SUPPRESS_PATTERNS):
            record.levelno = logging.WARNING
            record.levelname = "WARNING"
            record.exc_info = None
        return True


def _extract_qs_token(path: str) -> str:
    """Extract ?token=... from a raw request path."""
    if "?" not in path:
        return ""
    qs = path.split("?", 1)[1]
    return urllib.parse.parse_qs(qs).get("token", [""])[0]


def _extract_qs_value(path: str, key: str) -> str:
    if "?" not in path:
        return ""
    qs = path.split("?", 1)[1]
    return urllib.parse.parse_qs(qs).get(key, [""])[0]


def _json_response(data: dict[str, Any], status_code: int = 200) -> Response:
    return Response(
        status_code=status_code,
        reason_phrase="OK" if status_code == HTTP_OK else "Error",
        headers=_JSON_HEADERS,
        body=json.dumps(data).encode(),
    )


def _empty_response(status_code: int, reason_phrase: str) -> Response:
    return Response(
        status_code=status_code,
        reason_phrase=reason_phrase,
        headers=Headers({}),
        body=b"",
    )


def _bytes_response(body: bytes, content_type: str, status_code: int = 200) -> Response:
    return Response(
        status_code=status_code,
        reason_phrase="OK" if status_code == HTTP_OK else "Error",
        headers=Headers({"Content-Type": content_type}),
        body=body,
    )


def serve_file(file_path: Path) -> Response | None:
    if not file_path.is_file():
        return _empty_response(404, "Not Found")

    mime_type, _ = mimetypes.guess_type(str(file_path))
    content_type = mime_type or "application/octet-stream"

    try:
        body = file_path.read_bytes()
        return _bytes_response(body, content_type)
    except OSError:
        return _empty_response(500, "Internal Server Error")


def serve_index_html(
    file_path: Path, runtime_config: DesktopBridgeRuntimeConfig | None
) -> Response | None:
    response = serve_file(file_path)
    if (
        response is None
        or runtime_config is None
        or not isinstance(response.body, bytes)
    ):
        return response
    try:
        html = response.body.decode("utf-8")
    except UnicodeDecodeError:
        return response
    bootstrap = {
        "schema_version": "rig.desktop.runtime_config.v1",
        "frontend_url": runtime_config.frontend_url,
        "ws_url": runtime_config.ws_url,
        "ws_protocol": "wss" if runtime_config.tls_enabled else "ws",
        "static_protocol": "https" if runtime_config.tls_enabled else "http",
        "tls_enabled": runtime_config.tls_enabled,
        "tls_mode": runtime_config.tls_mode,
        "tls_trust_state": runtime_config.tls_trust_state,
        "transport_label": runtime_config.transport_label,
        "handshake_id": runtime_config.handshake_id,
        "local_mode": True,
        "token_present": bool(runtime_config.auth_token),
        "token": runtime_config.auth_token,
    }
    script = (
        "<script>window.__RIG_RELAY_RUNTIME_CONFIG__ = "
        + json.dumps(bootstrap)
        + ";</script>"
    )
    if "</head>" in html:
        html = html.replace("</head>", f"{script}</head>", 1)
    else:
        html = script + html
    return _bytes_response(html.encode("utf-8"), "text/html")


def serve_static(path: str, frontend_dir: Path) -> Response | None:
    """Serve static assets from frontend_dir. Prevents path traversal."""
    normalized = (
        Path(path).resolve() if path.startswith("/") else Path("/" + path).resolve()
    )
    requested = frontend_dir / normalized.relative_to("/")

    try:
        requested.resolve().relative_to(frontend_dir.resolve())
    except ValueError:
        return _empty_response(403, "Forbidden")

    if not requested.is_file():
        return _empty_response(404, "Not Found")

    return serve_file(requested)


def gate_route_by_service_state(path: str) -> Response | None:
    """Gate sensitive HTTP routes by service state.

    Returns None if the route is allowed, or a 403 JSON response if gated.
    When the profile is setup_required or locked, sensitive routes are
    blocked even with valid token/origin.
    """
    from rig_relay.governance.service_state import get_capability_gate

    gate = get_capability_gate()
    state_summary = gate.state_summary()
    service_state = state_summary.get("service_state", "")
    profile_state = state_summary.get("profile_state", "")

    # Always allowed routes (never gated)
    if path in {
        "/",
        "/index.html",
        "/healthz",
        "/runtime-config.json",
        "/runtime-config",
        "/ws",
        "/websocket.js",
    }:
        return None
    if (
        path.startswith("/js/")
        or path.startswith("/css/")
        or path.startswith("/assets/")
    ):
        return None
    if path == "/frontend-event":
        return None

    # In ready/degraded state, all routes are allowed
    if service_state in {"ready", "degraded"}:
        return None

    # In setup_required or locked state, block sensitive routes
    if service_state in {"setup_required", "locked"}:
        message = f"Service is {service_state}. Route '{path}' is not available until profile is unlocked."
        logger.warning(
            "audit.route.gated service_state=%s path=%s", service_state, path
        )
        return _json_response(
            {
                "error": "service_gated",
                "service_state": service_state,
                "profile_state": profile_state,
                "message": message,
            },
            status_code=403,
        )

    return None


def compute_readiness(state_summary: dict[str, Any]) -> str:  # noqa: PLR0911
    """Map service state to readiness state for frontend consumption."""
    service_state = state_summary.get("service_state", "setup_required")
    if service_state in {"starting"}:
        return "starting"
    if service_state == "setup_required":
        return "setup_required"
    if service_state == "locked":
        return "locked"
    if service_state == "ready":
        return "ready"
    if service_state == "degraded":
        return "degraded"
    if service_state == "failed":
        return "failed"
    return service_state


def build_healthz_response(
    config: DesktopBridgeConfig,
    bound_port: int,
    runtime_config: DesktopBridgeRuntimeConfig | None,
    state_machine: DesktopBridgeStateMachine,
) -> Response:
    from rig_relay.governance.service_state import get_capability_gate

    gate = get_capability_gate()
    state_summary = gate.state_summary()
    projection = state_machine.export_projection()
    return _json_response({
        "ok": True,
        "schema_version": "rig.desktop.healthz.v1",
        "bridge_mode": "single",
        "bridge_host": config.host,
        "bridge_port": bound_port,
        "tls_enabled": config.tls_enabled,
        "tls_mode": config.tls_mode,
        "transport_label": (
            runtime_config.transport_label if runtime_config else "unknown"
        ),
        "ws_path": "/ws",
        "auth_required": True,
        "frontend_url": (runtime_config.frontend_url if runtime_config else ""),
        "ws_url": (runtime_config.ws_url if runtime_config else ""),
        "bridge_state": state_machine.current_state.value,
        "bridge_previous_state": projection["previous_state"],
        "bridge_last_event": projection["last_event"],
        "bridge_failed_step": projection["failed_step"],
        "bridge_transition_count": projection["transition_count"],
        "frontend_dir_exists": (
            config.frontend_dir.is_dir() if config.frontend_dir else False
        ),
        "index_exists": (
            (config.frontend_dir / "index.html").is_file()
            if config.frontend_dir
            else False
        ),
        "main_js_exists": (
            (config.frontend_dir / "js" / "main.js").is_file()
            if config.frontend_dir
            else False
        ),
        "css_dir_exists": (
            (config.frontend_dir / "css").is_dir() if config.frontend_dir else False
        ),
        "active_ws_clients": 0,
        "last_ws_error": None,
        "service_state": state_summary.get("service_state", "unknown"),
        "readiness_state": compute_readiness(state_summary),
        "profile_exists": state_summary.get("profile_exists", False),
        "profile_state": state_summary.get("profile_state", "setup_required"),
        "local_auth_enabled": state_summary.get("local_auth_enabled", False),
    })


_FRONTEND_EVENT_TO_TRANSITION: dict[str, DesktopBridgeEvent] = {
    "frontend_boot_started": DesktopBridgeEvent.WEBVIEW_CREATED,
    "frontend_runtime_config_loaded": DesktopBridgeEvent.FRONTEND_CONFIG_LOADED,
    "frontend_first_projection_rendered": DesktopBridgeEvent.PROJECTION_RENDERED,
}

__all__ = [
    "build_healthz_response",
    "compute_readiness",
    "gate_route_by_service_state",
    "serve_file",
    "serve_index_html",
    "serve_static",
]
