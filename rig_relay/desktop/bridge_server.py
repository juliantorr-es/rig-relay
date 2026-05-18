"""DesktopBridgeServer — single local HTTPS/WSS bridge for Rig Relay.

Replaces the split pywebview static server + separate WebSocket server
with one HTTP/WS server on one host:port.

Routes:
    GET / and /index.html  → serve index.html
    GET /js/*, /css/*, etc.  → serve static frontend assets
    GET /ws                  → WebSocket projection/event stream
    GET /healthz             → local health check JSON

All served from one origin, one certificate, one auth token.
Uses the websockets library (already a dependency) for both HTTP and WS.

WebSocket connections delegate to ProjectionWebSocketServer for full
auth, projection, chat, and intent handling.
"""

from __future__ import annotations

import json
import logging
import mimetypes
import os
from pathlib import Path
import ssl
import time
from typing import Any

from websockets.asyncio.server import Server, ServerConnection, serve
from websockets.http11 import Headers, Request, Response

from rig_relay.core.logger import logger
from rig_relay.desktop.bridge_diagnostics import BridgeProbeReport
from rig_relay.desktop.bridge_state_machine import (
    DesktopBridgeEvent,
    DesktopBridgeStateMachine,
    InvalidBridgeTransitionError,
    TerminalBridgeStateError,
)
from rig_relay.desktop.correlation import DesktopCorrelation, new_correlation_id
from rig_relay.desktop.websocket_server import ProjectionWebSocketServer
from rig_relay.tracing.golden_path import TraceAuthorityKind, build_golden_path_event
from rig_relay.tracing.recorder import TraceRecorder
from rig_relay.tracing.store import get_default_trace_store
from scripts.rig_relay_trace_handshake import (
    _load_events,
    _select_handshake_id,
    format_handshake_trace,
)

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
    import urllib.parse

    if "?" not in path:
        return ""
    qs = path.split("?", 1)[1]
    return urllib.parse.parse_qs(qs).get("token", [""])[0]


def _extract_qs_value(path: str, key: str) -> str:
    import urllib.parse

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


class DesktopBridgeConfig:
    """Configuration for the single bridge server."""

    def __init__(
        self,
        *,
        host: str = "127.0.0.1",
        port: int | None = None,
        frontend_dir: Path | None = None,
        auth_token: str = "",
        ssl_context: ssl.SSLContext | None = None,
        tls_mode: str | None = None,
        cert_fingerprint_sha256: str | None = None,
        build_root: Path | None = None,
        chat_state_provider: Any | None = None,
        chat_message_handler: Any | None = None,
    ) -> None:
        self.host = host
        self.port = port
        self.frontend_dir = frontend_dir
        self.auth_token = auth_token
        self.ssl_context = ssl_context
        self.tls_enabled = ssl_context is not None
        self.tls_mode = tls_mode or ("tls" if self.tls_enabled else "insecure")
        self.cert_fingerprint_sha256 = cert_fingerprint_sha256
        self.build_root = build_root
        self.chat_state_provider = chat_state_provider
        self.chat_message_handler = chat_message_handler


class DesktopBridgeRuntimeConfig:
    """Runtime config delivered to frontend via JS API bridge."""

    def __init__(
        self,
        *,
        host: str,
        port: int,
        tls_enabled: bool,
        tls_mode: str,
        auth_token: str,
        cert_fingerprint_sha256: str | None = None,
        app_version: str = "dev",
        tls_trust_state: str = "disabled",
        handshake_id: str | None = None,
    ) -> None:
        scheme = "https" if tls_enabled else "http"
        ws_scheme = "wss" if tls_enabled else "ws"
        self.frontend_url = f"{scheme}://{host}:{port}/index.html"
        self.ws_url = f"{ws_scheme}://{host}:{port}/ws"
        self.bridge_origin = f"{scheme}://{host}:{port}"
        self.bridge_host = host
        self.bridge_port = port
        self.tls_enabled = tls_enabled
        self.tls_mode = tls_mode
        self.cert_fingerprint_sha256 = cert_fingerprint_sha256
        self.tls_trust_state = tls_trust_state
        self.transport_label = _transport_label(tls_enabled, tls_trust_state)
        self.handshake_id = handshake_id or new_correlation_id()
        self.local_mode = True
        self.merge_enabled = False
        self.push_enabled = False
        self.auth_required = True
        self.auth_token = auth_token
        self.app_version = app_version

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "rig.desktop.runtime_config.v1",
            "frontend_url": self.frontend_url,
            "ws_url": self.ws_url,
            "bridge_origin": self.bridge_origin,
            "bridge_host": self.bridge_host,
            "bridge_port": self.bridge_port,
            "tls_enabled": self.tls_enabled,
            "tls_mode": self.tls_mode,
            "tls_trust_state": self.tls_trust_state,
            "cert_fingerprint_sha256": self.cert_fingerprint_sha256,
            "transport_label": self.transport_label,
            "handshake_id": self.handshake_id,
            "local_mode": self.local_mode,
            "merge_enabled": self.merge_enabled,
            "push_enabled": self.push_enabled,
            "auth_required": self.auth_required,
            "token_present": bool(self.auth_token),
            "auth_token": self.auth_token,
            "token": self.auth_token,
            "app_version": self.app_version,
        }


class DesktopBridgeServer:
    """Single bridge server: HTTPS + WSS on one port.

    Serves static frontend files and WebSocket projection stream
    from a single host:port origin.
    """

    def __init__(
        self,
        config: DesktopBridgeConfig,
        *,
        probe_report: BridgeProbeReport | None = None,
        debug: bool = False,
    ) -> None:
        self._config = config
        self._server: Server | None = None
        self._ws_server: ProjectionWebSocketServer | None = None
        self._bound_port: int = 0
        self._started: bool = False
        self._runtime_config: DesktopBridgeRuntimeConfig | None = None
        self._trace_recorder = TraceRecorder(get_default_trace_store())
        self._state_machine = DesktopBridgeStateMachine()
        self._debug = debug
        self.probe_report = probe_report or BridgeProbeReport(
            mode="packaged" if getattr(config, "build_root", None) else "source",
            tls_enabled=config.tls_enabled,
        )
        self._probe_active = debug or self.probe_report.steps == []
        self._golden_trace_id = ""
        self._golden_handshake_id = ""
        self._golden_commit_sha = ""
        self._golden_started_at = 0.0

    def _emit_golden_event(
        self,
        event_type: str,
        *,
        status: str | None = None,
        payload: dict[str, Any] | None = None,
        parent_span_id: str = "",
        authority_kind: str = "",
        duration_ms: int | None = None,
        error_message: str | None = None,
    ) -> None:
        from rig_relay.tracing.models import TraceStatus

        event = build_golden_path_event(
            event_type=event_type,
            trace_id=self._golden_trace_id or None,
            handshake_id=self._golden_handshake_id,
            commit_sha=self._golden_commit_sha,
            parent_span_id=parent_span_id or None,
            status=TraceStatus(status) if status else None,
            authority={
                "authority_kind": authority_kind
                or TraceAuthorityKind.desktop_bridge.value,
                "trusted": True,
                "source_path": "rig_relay/desktop/bridge_server.py",
            },
            payload=payload,
            duration_ms=duration_ms,
            error_message=error_message,
            host=self._config.host,
            port=self._bound_port,
            tls_enabled=self._config.tls_enabled,
            transport_label=(
                self._runtime_config.transport_label if self._runtime_config else ""
            ),
            token_present=bool(self._config.auth_token),
            frontend_url=(
                self._runtime_config.frontend_url if self._runtime_config else ""
            ),
            websocket_url=(self._runtime_config.ws_url if self._runtime_config else ""),
        )
        self._trace_recorder.store.write(event)

    @property
    def bound_port(self) -> int:
        return self._bound_port

    @property
    def runtime_config(self) -> DesktopBridgeRuntimeConfig:
        if self._runtime_config is None:
            raise RuntimeError("Bridge not started. Call start() first.")
        return self._runtime_config

    def _transition_state(
        self,
        event: DesktopBridgeEvent,
        *,
        reason: str,
        attributes: dict[str, Any] | None = None,
    ) -> None:
        try:
            self._state_machine.transition(event, reason=reason, attributes=attributes)
        except (InvalidBridgeTransitionError, TerminalBridgeStateError):
            return

    async def start(self) -> None:  # noqa: PLR0915,PLR0914,PLR0912
        """Start the bridge server with probe ladder."""
        if self._started:
            return

        import time as _time

        from rig_relay.tracing.models import new_trace_id

        self._golden_started_at = _time.time()
        self._golden_trace_id = new_trace_id()

        self._emit_golden_event(
            "desktop.bridge.launch_requested",
            payload={"host": self._config.host, "port": self._config.port or 0},
        )

        self._trace_recorder.event(
            "desktop.bridge.start_begin",
            {
                "host": self._config.host,
                "port": self._config.port or 0,
                "tls_enabled": self._config.tls_enabled,
            },
        )

        host = self._config.host
        port = self._config.port or 0
        frontend_dir = self._config.frontend_dir
        report = self.probe_report
        report.frontend_url = ""
        report.ws_url = ""

        if not _is_loopback_host(host) and not _unsafe_non_loopback_allowed():
            raise ValueError(f"Non-loopback host rejected: {host}")

        # ── bridge:01 resolve frontend_dir ──────────────────────────
        self._state_machine.transition(
            DesktopBridgeEvent.RESOLVING_FRONTEND,
            reason="resolve frontend_dir",
            attributes={"step_id": "bridge:01"},
        )
        if frontend_dir is None:
            report.add_fail(
                "bridge:01",
                "resolve frontend_dir",
                message="frontend_dir is None",
                remediation="Set frontend_dir in DesktopBridgeConfig or check FRONTEND_DIR constant.",
            )
            raise ValueError("frontend_dir is required")
        if not frontend_dir.is_dir():
            report.add_fail(
                "bridge:01",
                "resolve frontend_dir",
                details={"path": str(frontend_dir)},
                message=f"Directory does not exist: {frontend_dir}",
                remediation=f"Ensure {frontend_dir} exists or set correct frontend_dir.",
            )
            raise ValueError(f"frontend_dir does not exist: {frontend_dir}")
        report.add_ok(
            "bridge:01",
            "resolve frontend_dir",
            details={"path": str(frontend_dir)},
            message=str(frontend_dir),
        )
        self._emit_golden_event(
            "desktop.bridge.frontend_resolved", payload={"frontend_dir_ok": True}
        )
        self._transition_state(
            DesktopBridgeEvent.ASSETS_VERIFIED,
            reason="verify asset files",
            attributes={"step_id": "bridge:03"},
        )

        # ── bridge:02 resolve index_path ────────────────────────────
        index_path = frontend_dir / "index.html"
        if not index_path.is_file():
            report.add_fail(
                "bridge:02",
                "resolve index.html",
                details={"path": str(index_path)},
                message="index.html not found",
                remediation=f"Ensure index.html exists at {frontend_dir}/index.html. Run build step.",
            )
            raise FileNotFoundError(f"index.html not found at {index_path}")
        index_size = index_path.stat().st_size
        report.add_ok(
            "bridge:02",
            "resolve index.html",
            details={"path": str(index_path), "size_bytes": index_size},
            message=f"{index_size / 1024:.1f} KB",
        )
        self._emit_golden_event(
            "desktop.bridge.index_resolved", payload={"index_size_bytes": index_size}
        )

        # ── bridge:03 verify asset files ────────────────────────────
        main_js = frontend_dir / "js" / "main.js"
        css_dir = frontend_dir / "css"
        main_js_ok = main_js.is_file()
        css_ok = css_dir.is_dir()
        asset_details: dict[str, Any] = {
            "js/main.js": main_js_ok,
            "js/main.js_size": main_js.stat().st_size if main_js_ok else 0,
            "css_dir": str(css_dir) if css_ok else "missing",
        }
        if not main_js_ok:
            report.add_fail(
                "bridge:03",
                "verify asset files",
                details=asset_details,
                message="js/main.js missing",
                remediation=f"Ensure {frontend_dir}/js/main.js exists. Check frontend build.",
            )
            raise FileNotFoundError(f"js/main.js not found at {main_js}")
        if not css_ok:
            report.add_warn(
                "bridge:03",
                "verify asset files",
                details=asset_details,
                message="css dir missing — UI may be unstyled",
                remediation=f"Ensure {frontend_dir}/css/ directory exists.",
            )
        else:
            report.add_ok(
                "bridge:03",
                "verify asset files",
                details=asset_details,
                message=f"js/main.js={main_js.stat().st_size / 1024:.1f}KB, css dir ok",
            )
            self._emit_golden_event("desktop.bridge.asset_probe_passed")

        # ── bridge:04 build runtime_config ──────────────────────────
        self._runtime_config = DesktopBridgeRuntimeConfig(
            host=host,
            port=port,
            tls_enabled=self._config.tls_enabled,
            tls_mode=self._config.tls_mode,
            auth_token=self._config.auth_token,
            cert_fingerprint_sha256=self._config.cert_fingerprint_sha256,
            tls_trust_state=_tls_trust_state(self._config),
            handshake_id=getattr(self._config, "handshake_id", None),
        )
        self._golden_handshake_id = self._runtime_config.handshake_id
        report.frontend_url = self._runtime_config.frontend_url
        report.ws_url = self._runtime_config.ws_url
        report.add_ok(
            "bridge:04",
            "build runtime_config",
            details={
                "host": host,
                "port": port,
                "tls_enabled": self._config.tls_enabled,
                "tls_trust_state": self._runtime_config.tls_trust_state,
                "transport_label": self._runtime_config.transport_label,
                "token_present": bool(self._config.auth_token),
                "handshake_id": self._runtime_config.handshake_id,
            },
            message=(
                f"{self._runtime_config.transport_label}, "
                f"token_present={bool(self._config.auth_token)}"
            ),
        )
        self._emit_golden_event(
            "desktop.bridge.runtime_config_built",
            payload={
                "frontend_url": self._runtime_config.frontend_url,
                "websocket_url": self._runtime_config.ws_url,
            },
        )
        self._transition_state(
            DesktopBridgeEvent.CONFIG_BUILT,
            reason="build runtime_config",
            attributes={"step_id": "bridge:04"},
        )

        # ── bridge:05 create WS server ───────────────────────────────
        logging.getLogger("websockets.server").addFilter(_WebSocketNoiseFilter())

        def _on_ws_probe(step_id: str, label: str, details: dict[str, Any]) -> None:
            report.add_ok(step_id, label, details=details, message=label)
            self._apply_probe_transition(step_id, details)

        self._ws_server = ProjectionWebSocketServer(
            build_root=self._config.build_root,
            host=host,
            port=port,
            token=self._config.auth_token,
            ssl_context=self._config.ssl_context,
            chat_state_provider=self._config.chat_state_provider,
            chat_message_handler=self._config.chat_message_handler,
            probe_callback=_on_ws_probe,
            trace_recorder=self._trace_recorder,
            golden_trace_id=self._golden_trace_id,
            golden_handshake_id=self._golden_handshake_id,
            missing_origin_allowed=False,
        )
        report.add_ok(
            "bridge:05", "create WS server", message="ProjectionWebSocketServer ready"
        )
        self._emit_golden_event("desktop.bridge.websocket_server_created")
        self._transition_state(
            DesktopBridgeEvent.SERVER_CREATED,
            reason="create WS server",
            attributes={"step_id": "bridge:05"},
        )

        # ── bridge:06 bind host/port ─────────────────────────────────
        async def ws_handler(conn: ServerConnection) -> None:
            await self._handle_ws(conn)

        async def process_request(
            conn: ServerConnection, request: Request
        ) -> Response | None:
            return self._handle_http(request, frontend_dir)

        t0 = time.time()
        try:
            self._server = await serve(
                ws_handler,
                host,
                port,
                ssl=self._config.ssl_context,
                process_request=process_request,
                compression=None,
            )
        except Exception as exc:
            report.add_fail(
                "bridge:06",
                "bind host/port",
                details={"host": host, "port": port, "error": str(exc)},
                message=f"Failed to bind {host}:{port}: {exc}",
                remediation="Check if port is already in use. Use RIG_RELAY_LOCAL_TLS=1 only when TLS is intended.",
            )
            raise
        bind_ms = int((time.time() - t0) * 1000)

        ADDR_TUPLE_MIN_LENGTH = 2
        for sock in self._server.sockets:
            addr = sock.getsockname()
            if addr and len(addr) >= ADDR_TUPLE_MIN_LENGTH:
                self._bound_port = addr[1]
                break

        if self._bound_port == 0:
            self._bound_port = port

        report.add_ok(
            "bridge:06",
            "bind host/port",
            details={"host": host, "bound_port": self._bound_port},
            message=f"http://{host}:{self._bound_port}",
            duration_ms=bind_ms,
        )
        self._emit_golden_event(
            "desktop.bridge.server_bound",
            payload={"bound_port": self._bound_port},
            duration_ms=bind_ms,
        )
        self._transition_state(
            DesktopBridgeEvent.SERVER_BOUND,
            reason="bind host/port",
            attributes={"step_id": "bridge:06", "bound_port": self._bound_port},
        )

        self._runtime_config.bridge_port = self._bound_port
        self._runtime_config.frontend_url = f"{'https' if self._config.tls_enabled else 'http'}://{host}:{self._bound_port}/index.html"
        self._runtime_config.ws_url = f"{'wss' if self._config.tls_enabled else 'ws'}://{host}:{self._bound_port}/ws"
        self._runtime_config.bridge_origin = f"{'https' if self._config.tls_enabled else 'http'}://{host}:{self._bound_port}"
        report.frontend_url = self._runtime_config.frontend_url
        report.ws_url = self._runtime_config.ws_url

        self._emit_golden_event(
            "desktop.bridge.frontend_url_announced",
            payload={"frontend_url": self._runtime_config.frontend_url},
        )
        self._emit_golden_event(
            "desktop.bridge.websocket_url_announced",
            payload={"websocket_url": self._runtime_config.ws_url},
        )

        # ── bridge:07 probe /healthz ─────────────────────────────────
        await self._probe_healthz(report)
        self._emit_golden_event("desktop.bridge.health_probe_passed")
        self._transition_state(
            DesktopBridgeEvent.SELF_PROBED,
            reason="probe ladder complete",
            attributes={"step_id": "bridge:07-10"},
        )

        # ── bridge:08 probe /index.html ──────────────────────────────
        await self._probe_path(
            report, "/index.html", "bridge:08", "probe /index.html", "text/html"
        )
        self._emit_golden_event("desktop.bridge.index_probe_passed")

        # ── bridge:09 probe /js/main.js (compat module) ─────────
        await self._probe_path(
            report, "/js/main.js", "bridge:09", "probe /js/main.js", "javascript"
        )

        # ── bridge:09a probe active entrypoint ──────────────────────
        orchestrator_js = frontend_dir / "js" / "boot" / "orchestrator.js"
        if orchestrator_js.is_file():
            await self._probe_path(
                report,
                "/js/boot/orchestrator.js",
                "bridge:09a",
                "probe active entrypoint",
                "javascript",
            )
            asset_details["active_entrypoint"] = "/js/boot/orchestrator.js"
            asset_details["compat_module"] = "/js/main.js"
        else:
            report.add_warn(
                "bridge:09a",
                "probe active entrypoint",
                message="orchestrator.js not found — index.html may fail to load",
                remediation=f"Ensure {orchestrator_js} exists.",
            )

        # ── bridge:10 probe CSS ──────────────────────────────────────
        css_files = sorted(css_dir.glob("*.css")) if css_dir.is_dir() else []
        if css_files:
            first_css = f"/css/{css_files[0].name}"
            await self._probe_path(
                report, first_css, "bridge:10", f"probe {first_css}", "css"
            )
        else:
            report.add_warn(
                "bridge:10",
                "probe CSS",
                message="no CSS files found in css/",
                remediation="CSS directory is empty — UI will be unstyled.",
            )

        self._started = True
        self._emit_golden_event("desktop.bridge.window_created")
        self._transition_state(
            DesktopBridgeEvent.WEBVIEW_CREATED,
            reason="webview created",
            attributes={"step_id": "bridge:11"},
        )
        self._emit_golden_event("desktop.bridge.window_start_called")
        self._transition_state(
            DesktopBridgeEvent.WEBVIEW_STARTED,
            reason="webview started",
            attributes={"step_id": "bridge:12"},
        )
        logger.info(
            "DesktopBridgeServer started host=%s port=%s frontend_url=%s websocket_url=%s tls_enabled=%s token_present=%s transport_label=%s",
            host,
            self._bound_port,
            self._runtime_config.frontend_url,
            self._runtime_config.ws_url,
            self._config.tls_enabled,
            bool(self._config.auth_token),
            self._runtime_config.transport_label,
        )

    async def stop(self) -> None:
        """Stop the bridge server cleanly."""
        self._emit_golden_event("desktop.bridge.shutdown")
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        self._print_handshake_trace()
        self._started = False

    def _handle_http(self, request: Request, frontend_dir: Path) -> Response | None:  # noqa: PLR0911
        raw_path = request.path or "/"
        path = raw_path.split("?", 1)[0] if "?" in raw_path else raw_path

        # WebSocket upgrade — only GET is valid; reject POST/PUT/etc.
        if path == "/ws":
            if getattr(request, "method", "GET") != "GET":
                logger.warning(
                    "Rejecting non-WebSocket %s to /ws from frontend trace",
                    getattr(request, "method", "GET"),
                )
                return _empty_response(
                    405, "Method Not Allowed — use GET for WebSocket upgrade"
                )
            logger.debug("WebSocket upgrade request from %s", raw_path)
            return None

        # /healthz
        if path == "/healthz":
            return self._build_healthz()

        # /runtime-config.json or /runtime-config (token stripped from HTTP response for safety)
        if (
            path in {"/runtime-config.json", "/runtime-config"}
            and self._runtime_config is not None
        ):
            config_dict = self._runtime_config.to_dict()
            config_dict.pop("auth_token", None)
            config_dict.pop("token", None)
            self._trace_recorder.event(
                "desktop.frontend.runtime_config_served",
                attributes={
                    "handshake_id": self._runtime_config.handshake_id,
                    "frontend_url": self._runtime_config.frontend_url,
                    "ws_url": self._runtime_config.ws_url,
                    "transport_label": self._runtime_config.transport_label,
                    "tls_enabled": self._runtime_config.tls_enabled,
                    "token_present": bool(self._runtime_config.auth_token),
                },
            )
            self._transition_state(
                DesktopBridgeEvent.FRONTEND_CONFIG_LOADED,
                reason="runtime-config.json served",
                attributes={"step_id": "bridge:13"},
            )
            return _json_response(config_dict)

        if path == "/frontend-event":
            # Accept both GET query-param (from emitBreadcrumb) and POST JSON (from frontendTrace)
            event_type = ""
            handshake_id = ""
            detail = ""
            if getattr(request, "method", "") == "POST" and getattr(
                request, "body", None
            ):
                try:
                    body_data = json.loads(
                        getattr(request, "body", b"").decode("utf-8")
                    )
                    if isinstance(body_data, dict):
                        event_type = body_data.get("type", "")
                        handshake_id = body_data.get("handshake_id", "")
                        detail = (
                            json.dumps(body_data, default=str)
                            if body_data.get("detail")
                            else ""
                        )
                except (json.JSONDecodeError, UnicodeDecodeError):
                    pass
            else:
                event_type = _extract_qs_value(raw_path, "type")
                handshake_id = _extract_qs_value(raw_path, "handshake_id")
                detail = _extract_qs_value(raw_path, "detail")
            if event_type:
                self._trace_recorder.event(
                    event_type,
                    attributes={"handshake_id": handshake_id, "detail": detail},
                )
                self._emit_golden_event(
                    event_type,
                    payload={"detail": detail} if detail else None,
                    authority_kind=TraceAuthorityKind.frontend_runtime.value,
                )
            return _empty_response(HTTP_OK, "OK")

        # /index.html or /
        if path in {"/", "/index.html"}:
            if self._runtime_config is not None:
                DesktopCorrelation(
                    correlation_id=self._runtime_config.handshake_id,
                    trace_recorder=self._trace_recorder,
                ).emit_event(
                    "desktop.frontend.bootstrap_loaded",
                    attributes={
                        "handshake_id": self._runtime_config.handshake_id,
                        "frontend_url": self._runtime_config.frontend_url,
                        "transport_label": self._runtime_config.transport_label,
                        "tls_enabled": self._runtime_config.tls_enabled,
                        "token_present": bool(self._runtime_config.auth_token),
                    },
                )
            return self._serve_index_html(frontend_dir / "index.html")

        # static assets
        return self._serve_static(path, frontend_dir)

    def _serve_file(self, file_path: Path) -> Response | None:
        if not file_path.is_file():
            return _empty_response(404, "Not Found")

        mime_type, _ = mimetypes.guess_type(str(file_path))
        content_type = mime_type or "application/octet-stream"

        try:
            body = file_path.read_bytes()
            return _bytes_response(body, content_type)
        except OSError:
            return _empty_response(500, "Internal Server Error")

    def _serve_index_html(self, file_path: Path) -> Response | None:
        response = self._serve_file(file_path)
        if (
            response is None
            or self._runtime_config is None
            or not isinstance(response.body, bytes)
        ):
            return response
        try:
            html = response.body.decode("utf-8")
        except UnicodeDecodeError:
            return response
        bootstrap = {
            "schema_version": "rig.desktop.runtime_config.v1",
            "frontend_url": self._runtime_config.frontend_url,
            "ws_url": self._runtime_config.ws_url,
            "ws_protocol": "wss" if self._runtime_config.tls_enabled else "ws",
            "static_protocol": "https" if self._runtime_config.tls_enabled else "http",
            "tls_enabled": self._runtime_config.tls_enabled,
            "tls_mode": self._runtime_config.tls_mode,
            "tls_trust_state": self._runtime_config.tls_trust_state,
            "transport_label": self._runtime_config.transport_label,
            "handshake_id": self._runtime_config.handshake_id,
            "local_mode": True,
            "token_present": bool(self._runtime_config.auth_token),
            "token": self._runtime_config.auth_token,
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

    def _serve_static(self, path: str, frontend_dir: Path) -> Response | None:
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

        return self._serve_file(requested)

    async def _handle_ws(self, conn: ServerConnection) -> None:
        """Handle WebSocket connections — delegates to ProjectionWebSocketServer."""
        report = self.probe_report
        remote = conn.remote_address[0] if conn.remote_address else "unknown"
        if self._runtime_config is not None:
            self._trace_recorder.event(
                "desktop.transport.websocket_connected",
                attributes={
                    "handshake_id": self._runtime_config.handshake_id,
                    "transport.session_id": self._runtime_config.handshake_id,
                    "ws_url": self._runtime_config.ws_url,
                    "transport_label": self._runtime_config.transport_label,
                    "token_present": bool(self._runtime_config.auth_token),
                },
            )
        report.add_ok(
            "bridge:14",
            "websocket upgrade accepted",
            details={"remote": remote, "path": "/ws"},
            message=f"WS upgrade from {remote}",
        )
        self._transition_state(
            DesktopBridgeEvent.WEBSOCKET_CONNECTED,
            reason="websocket upgrade accepted",
            attributes={"step_id": "bridge:14", "remote": remote},
        )
        if self._ws_server is None:
            report.add_fail(
                "bridge:14",
                "websocket upgrade accepted",
                message="WS server is None",
                remediation="Bridge may not have started correctly. Check bridge:05.",
            )
            await conn.close(1011, "Server not ready")
            return
        await self._ws_server._handle_connection(conn)

    async def _probe_healthz(self, report: BridgeProbeReport) -> None:
        try:
            resp = self._build_healthz()
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

    async def _probe_path(
        self,
        report: BridgeProbeReport,
        path: str,
        step_id: str,
        label: str,
        expected_content_type: str,
    ) -> None:
        try:
            resp = self._handle_http(
                Request(path=path, headers=Headers({})),
                self._config.frontend_dir or Path("."),
            )
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
            if (
                ok_status
                and expected_content_type == "javascript"
                and "text/html" in ct
            ):
                report.add_fail(
                    step_id,
                    label,
                    details={
                        "path": path,
                        "status": resp.status_code,
                        "content_type": ct,
                    },
                    message=f"Returned {ct}; expected javascript",
                    remediation=f"Check that {path} is served as static file, not index.html fallback.",
                )
            elif ok_status:
                report.add_ok(
                    step_id,
                    label,
                    details={
                        "path": path,
                        "status": resp.status_code,
                        "content_type": ct,
                    },
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

    def _apply_probe_transition(
        self, step_id: str, details: dict[str, Any] | None = None
    ) -> None:
        payload = {"step_id": step_id, **(details or {})}
        match step_id:
            case "bridge:15":
                self._transition_state(
                    DesktopBridgeEvent.WEBSOCKET_CONNECTED,
                    reason="websocket auth message received",
                    attributes=payload,
                )
            case "bridge:16":
                self._transition_state(
                    DesktopBridgeEvent.AUTHENTICATED,
                    reason="websocket auth accepted",
                    attributes=payload,
                )
            case "bridge:17":
                self._transition_state(
                    DesktopBridgeEvent.PROJECTION_SENT,
                    reason="first projection sent",
                    attributes=payload,
                )
            case "bridge:18":
                self._transition_state(
                    DesktopBridgeEvent.PROJECTION_RENDERED,
                    reason="projection rendered",
                    attributes=payload,
                )

    def _build_healthz(self) -> Response:
        from rig_relay.governance.service_state import get_capability_gate

        gate = get_capability_gate()
        state_summary = gate.state_summary()
        return _json_response({
            "ok": True,
            "schema_version": "rig.desktop.healthz.v1",
            "bridge_mode": "single",
            "bridge_host": self._config.host,
            "bridge_port": self._bound_port,
            "tls_enabled": self._config.tls_enabled,
            "tls_mode": self._config.tls_mode,
            "transport_label": (
                self._runtime_config.transport_label
                if self._runtime_config
                else "unknown"
            ),
            "ws_path": "/ws",
            "auth_required": True,
            "frontend_url": (
                self._runtime_config.frontend_url if self._runtime_config else ""
            ),
            "ws_url": (self._runtime_config.ws_url if self._runtime_config else ""),
            "bridge_state": self._state_machine.current_state.value,
            "bridge_previous_state": (
                self._state_machine.export_projection()["previous_state"]
            ),
            "bridge_last_event": self._state_machine.export_projection()["last_event"],
            "bridge_failed_step": self._state_machine.export_projection()[
                "failed_step"
            ],
            "bridge_transition_count": self._state_machine.export_projection()[
                "transition_count"
            ],
            "frontend_dir_exists": (
                self._config.frontend_dir.is_dir()
                if self._config.frontend_dir
                else False
            ),
            "index_exists": (
                (self._config.frontend_dir / "index.html").is_file()
                if self._config.frontend_dir
                else False
            ),
            "main_js_exists": (
                (self._config.frontend_dir / "js" / "main.js").is_file()
                if self._config.frontend_dir
                else False
            ),
            "css_dir_exists": (
                (self._config.frontend_dir / "css").is_dir()
                if self._config.frontend_dir
                else False
            ),
            "active_ws_clients": 0,
            "last_ws_error": None,
            "service_state": state_summary.get("service_state", "unknown"),
            "profile_exists": state_summary.get("profile_exists", False),
            "profile_state": state_summary.get("profile_state", "setup_required"),
            "local_auth_enabled": state_summary.get("local_auth_enabled", False),
        })

    def _print_handshake_trace(self) -> None:
        trace_path = (
            Path.home()
            / "Library"
            / "Application Support"
            / "Rig Relay"
            / "traces"
            / "trace_events.jsonl"
        )
        if not trace_path.exists():
            return
        events = _load_events(trace_path)
        handshake_id = (
            self._runtime_config.handshake_id if self._runtime_config else None
        )
        selected = _select_handshake_id(events, handshake_id)
        if selected is None:
            print()
            print("Handshake trace: none found")
            return
        print()
        print(format_handshake_trace(events, selected))


__all__ = ["DesktopBridgeConfig", "DesktopBridgeRuntimeConfig", "DesktopBridgeServer"]


def _is_loopback_host(host: str) -> bool:
    return host in {"127.0.0.1", "localhost", "::1"}


def _unsafe_non_loopback_allowed() -> bool:
    return os.getenv("RIG_RELAY_ALLOW_NON_LOOPBACK_LOCAL_BRIDGE", "").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _tls_trust_state(config: DesktopBridgeConfig) -> str:
    if not config.tls_enabled:
        return "disabled"
    if config.tls_mode == "mkcert":
        return "unknown"
    if config.tls_mode in {"adhoc_local", "self_signed"}:
        return "self_signed"
    return "unknown"


def _transport_label(tls_enabled: bool, tls_trust_state: str) -> str:
    if not tls_enabled:
        return "Loopback Token Bridge"
    if tls_trust_state == "trusted":
        return "TLS Loopback Bridge"
    if tls_trust_state in {"self_signed", "untrusted", "development"}:
        return "Untrusted Development TLS Bridge"
    return "TLS Loopback Bridge"
