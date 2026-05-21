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
from pathlib import Path
import time
from typing import Any

from websockets.asyncio.server import Server, ServerConnection, serve
from websockets.http11 import Request, Response

from rig_relay.core.logger import logger
from rig_relay.desktop._bridge_config import (
    DesktopBridgeConfig,
    DesktopBridgeRuntimeConfig,
    _is_loopback_host,
    _tls_trust_state,
    _unsafe_non_loopback_allowed,
)
from rig_relay.desktop._bridge_http import (
    _FRONTEND_EVENT_TO_TRANSITION,
    _empty_response,
    _extract_qs_value,
    _json_response,
    _WebSocketNoiseFilter,
    build_healthz_response,
    compute_readiness,
    gate_route_by_service_state,
    serve_file,
    serve_index_html,
    serve_static,
)
from rig_relay.desktop._bridge_probe import (
    apply_probe_transition,
    probe_healthz,
    probe_path,
)
from rig_relay.desktop._bridge_security import (
    validate_local_origin,
    validate_localhost_header,
)
from rig_relay.desktop.bridge_diagnostics import BridgeProbeReport
from rig_relay.desktop.bridge_state_machine import (
    DesktopBridgeEvent,
    DesktopBridgeStateMachine,
    InvalidBridgeTransitionError,
    TerminalBridgeStateError,
)
from rig_relay.desktop.correlation import DesktopCorrelation
from rig_relay.desktop.lifecycle_artifact import LifecycleArtifactWriter
from rig_relay.desktop.websocket_server import ProjectionWebSocketServer
from rig_relay.tracing.golden_path import TraceAuthorityKind, build_golden_path_event
from rig_relay.tracing.recorder import TraceRecorder
from rig_relay.tracing.store import get_default_trace_store
from scripts.rig_relay_trace_handshake import (
    _load_events,
    _select_handshake_id,
    format_handshake_trace,
)

HTTP_OK = 200


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
        self._lifecycle_writer = LifecycleArtifactWriter()
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
        self._lifecycle_writer.write_event(
            step_id="bridge_frontend_dir_resolved",
            status="ok",
            source="backend",
            handshake_id=self._golden_handshake_id,
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
        self._lifecycle_writer.write_event(
            step_id="bridge_index_resolved",
            status="ok",
            source="backend",
            handshake_id=self._golden_handshake_id,
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
        self._lifecycle_writer.set_handshake_id(self._golden_handshake_id)
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
        self._lifecycle_writer.write_event(
            step_id="bridge_config_built",
            status="ok",
            source="backend",
            handshake_id=self._golden_handshake_id,
        )

        # ── bridge:05 create WS server ───────────────────────────────
        logging.getLogger("websockets.server").addFilter(_WebSocketNoiseFilter())

        def _on_ws_probe(step_id: str, label: str, details: dict[str, Any]) -> None:
            report.add_ok(step_id, label, details=details, message=label)
            self._on_ws_probe_transition(step_id, details)

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
            pywebview_loopback_mode=self._config.pywebview_loopback_mode,
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
        self._lifecycle_writer.write_event(
            step_id="bridge_server_bound",
            status="ok",
            source="backend",
            handshake_id=self._golden_handshake_id,
            duration_ms=bind_ms,
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
        await probe_healthz(report, self._build_healthz)
        self._emit_golden_event("desktop.bridge.health_probe_passed")
        self._lifecycle_writer.write_event(
            step_id="bridge_health_probed",
            status="ok",
            source="backend",
            handshake_id=self._golden_handshake_id,
        )
        self._transition_state(
            DesktopBridgeEvent.SELF_PROBED,
            reason="probe ladder complete",
            attributes={"step_id": "bridge:07-10"},
        )

        # ── bridge:08 probe /index.html ──────────────────────────────
        await probe_path(
            report,
            "/index.html",
            "bridge:08",
            "probe /index.html",
            "text/html",
            self._handle_http,
            frontend_dir,
        )
        self._emit_golden_event("desktop.bridge.index_probe_passed")

        # ── bridge:09 probe /js/main.js (compat module) ─────────
        await probe_path(
            report,
            "/js/main.js",
            "bridge:09",
            "probe /js/main.js",
            "javascript",
            self._handle_http,
            frontend_dir,
        )

        # ── bridge:09a probe active entrypoint ──────────────────────
        orchestrator_js = frontend_dir / "js" / "boot" / "orchestrator.js"
        if orchestrator_js.is_file():
            await probe_path(
                report,
                "/js/boot/orchestrator.js",
                "bridge:09a",
                "probe active entrypoint",
                "javascript",
                self._handle_http,
                frontend_dir,
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
            await probe_path(
                report,
                first_css,
                "bridge:10",
                f"probe {first_css}",
                "css",
                self._handle_http,
                frontend_dir,
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
        self.write_lifecycle_summary()
        self._emit_golden_event("desktop.bridge.shutdown")
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        self._print_handshake_trace()
        self._started = False

    def _handle_http(self, request: Request, frontend_dir: Path) -> Response | None:  # noqa: PLR0911 PLR0912 PLR0915
        raw_path = request.path or "/"
        path = raw_path.split("?", 1)[0] if "?" in raw_path else raw_path

        # Extract Host header for DNS-rebinding defense
        host_header = ""
        if hasattr(request, "headers") and request.headers:
            host_header = request.headers.get("Host", "")

        # Validate Host header (DNS-rebinding defense)
        host_ok, host_reason = validate_localhost_header(host_header, self._config.host)
        if not host_ok:
            logger.warning(
                "audit.host.rejected reason=%s host=%s", host_reason, host_header
            )
            return _json_response(
                {"error": "forbidden", "reason": host_reason}, status_code=403
            )

        # Extract and validate Origin header
        origin = ""
        if hasattr(request, "headers") and request.headers:
            origin = request.headers.get("Origin", "")

        origin_ok, origin_reason = validate_local_origin(
            origin, self._config.host, self._bound_port
        )
        if not origin_ok:
            logger.warning(
                "audit.origin.rejected reason=%s origin=%s", origin_reason, origin
            )
            return _json_response(
                {"error": "forbidden", "reason": origin_reason}, status_code=403
            )

        # Gate sensitive routes by service state
        gated_response = self._gate_route_by_service_state(path)
        if gated_response is not None:
            return gated_response

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
            self._lifecycle_writer.write_event(
                step_id="bridge_runtime_config_served",
                status="ok",
                source="backend",
                handshake_id=self._runtime_config.handshake_id
                if self._runtime_config
                else "",
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
            _match = _FRONTEND_EVENT_TO_TRANSITION.get(event_type)
            if _match is not None:
                self._apply_frontend_event_transition(_match, detail, event_type)
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
        return serve_file(file_path)

    def _serve_index_html(self, file_path: Path) -> Response | None:
        return serve_index_html(file_path, self._runtime_config)

    def _serve_static(self, path: str, frontend_dir: Path) -> Response | None:
        return serve_static(path, frontend_dir)

    def _gate_route_by_service_state(self, path: str) -> Response | None:
        return gate_route_by_service_state(path)

    def _build_healthz(self) -> Response:
        return build_healthz_response(
            self._config, self._bound_port, self._runtime_config, self._state_machine
        )

    def _compute_readiness(self, state_summary: dict[str, Any]) -> str:
        return compute_readiness(state_summary)

    def write_lifecycle_summary(self) -> dict[str, Any]:
        """Write and return the lifecycle summary artifact."""
        summary = self._lifecycle_writer.build_summary()
        summary.bridge_url = (
            self._runtime_config.frontend_url if self._runtime_config else ""
        )
        summary.websocket_url = (
            self._runtime_config.ws_url if self._runtime_config else ""
        )
        self._lifecycle_writer.evidence_dir.mkdir(parents=True, exist_ok=True)
        from pathlib import Path as _Path

        head_path = _Path(__file__).resolve().parent.parent.parent / ".git" / "HEAD"
        if head_path.exists():
            try:
                head_text = head_path.read_text(encoding="utf-8").strip()
                if head_text.startswith("ref:"):
                    ref_path = (
                        _Path(__file__).resolve().parent.parent.parent
                        / ".git"
                        / head_text[5:]
                    )
                    if ref_path.exists():
                        summary.head_sha = ref_path.read_text(encoding="utf-8").strip()[
                            :40
                        ]
                else:
                    summary.head_sha = head_text[:40]
            except OSError:
                pass
        self._lifecycle_writer.write_summary()
        return summary.model_dump(mode="json")

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
        self._lifecycle_writer.write_event(
            step_id="bridge_websocket_accepted",
            status="ok",
            source="backend",
            handshake_id=self._runtime_config.handshake_id
            if self._runtime_config
            else "",
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

    def _on_ws_probe_transition(
        self, step_id: str, details: dict[str, Any] | None = None
    ) -> None:
        apply_probe_transition(self._state_machine, step_id, details)

    def _apply_frontend_event_transition(
        self, event: DesktopBridgeEvent, detail: str, event_type: str
    ) -> None:
        self._transition_state(
            event,
            reason=f"frontend event: {event_type}",
            attributes={"detail": detail, "source": "frontend-event"},
        )

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
