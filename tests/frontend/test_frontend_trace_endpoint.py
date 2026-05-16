"""Tests proving frontend trace sink boundaries and bridge /frontend-event routing."""

from __future__ import annotations

from pathlib import Path

FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend" / "desktop"


def _read(name: str) -> str:
    return (FRONTEND_DIR / "js" / name).read_text(encoding="utf-8")


class TestFrontendTraceEndpoint:
    def test_frontend_trace_uses_slash_frontend_event(self):
        """frontendTrace.js must send breadcrumbs to /frontend-event, never /ws."""
        source = (FRONTEND_DIR / "js" / "telemetry" / "frontendTrace.js").read_text(
            encoding="utf-8"
        )
        # Only check code lines, not comments
        code_lines = [l for l in source.split("\n") if not l.strip().startswith("//")]
        code = "\n".join(code_lines)
        assert "/frontend-event" in code, (
            "frontendTrace.js must use /frontend-event endpoint"
        )
        assert "/ws" not in code, "frontendTrace.js must never reference /ws in code"

    def test_frontend_trace_does_not_use_ws_url(self):
        """frontendTrace.js must never derive trace endpoint from ws_url or websocket_url."""
        source = (FRONTEND_DIR / "js" / "telemetry" / "frontendTrace.js").read_text(
            encoding="utf-8"
        )
        assert "ws_url" not in source, "frontendTrace.js must not reference ws_url"
        assert "websocket_url" not in source, (
            "frontendTrace.js must not reference websocket_url"
        )
        assert "wsUrl" not in source, "frontendTrace.js must not reference wsUrl"

    def test_frontend_trace_payload_uses_type_field(self):
        """frontendTrace.js must send type field in payload, not event."""
        source = (FRONTEND_DIR / "js" / "telemetry" / "frontendTrace.js").read_text(
            encoding="utf-8"
        )
        assert "type:" in source or "type," in source or "type=" in source, (
            "frontendTrace.js payload must include type field"
        )

    def test_frontend_trace_includes_handshake_id(self):
        """frontendTrace.js must include handshake_id in payload when set."""
        source = (FRONTEND_DIR / "js" / "telemetry" / "frontendTrace.js").read_text(
            encoding="utf-8"
        )
        assert "handshake_id" in source, (
            "frontendTrace.js payload must include handshake_id"
        )

    def test_frontend_trace_no_token_values(self):
        """frontendTrace.js must never include token value in payload."""
        source = (FRONTEND_DIR / "js" / "telemetry" / "frontendTrace.js").read_text(
            encoding="utf-8"
        )
        # no raw token in strings or identifiers
        assert "auth_token" not in source, "frontendTrace.js must not leak auth_token"
        assert "token:" not in source, "frontendTrace.js must not include token field"

    def test_frontend_trace_uses_get_method(self):
        """frontendTrace.js browser fallback must use GET, not POST."""
        source = (FRONTEND_DIR / "js" / "telemetry" / "frontendTrace.js").read_text(
            encoding="utf-8"
        )
        # Should use GET for query-param approach
        code_lines = [
            l.strip()
            for l in source.split("\n")
            if l.strip() and not l.strip().startswith("//")
        ]
        code = "\n".join(code_lines)
        assert "method: 'GET'" in code or 'method: "GET"' in code, (
            "frontendTrace.js browser fallback must use GET method"
        )


class TestEmitBreadcrumbEndpoint:
    def test_emit_breadcrumb_uses_slash_frontend_event(self):
        """emitBreadcrumb in transportState.js sends to /frontend-event, never /ws."""
        source = (FRONTEND_DIR / "js" / "transportState.js").read_text(encoding="utf-8")
        emit_start = source.index("emitBreadcrumb")
        emit_end = (
            source.index("\n}", emit_start + 200)
            if "\n}" in source[emit_start:]
            else len(source)
        )
        emit_section = source[emit_start : emit_end + 1]
        # Only check code lines
        code_lines = [
            l for l in emit_section.split("\n") if not l.strip().startswith("//")
        ]
        code = "\n".join(code_lines)
        assert "/frontend-event" in code, "emitBreadcrumb must use /frontend-event"
        assert "/ws" not in code, "emitBreadcrumb must never send to /ws"

    def test_emit_breadcrumb_does_not_use_ws_url(self):
        """emitBreadcrumb must never derive URL from ws_url or websocket_url."""
        source = (FRONTEND_DIR / "js" / "transportState.js").read_text(encoding="utf-8")
        emit_start = source.index("emitBreadcrumb")
        emit_section = source[emit_start:]
        assert "ws_url" not in emit_section, "emitBreadcrumb must not reference ws_url"
        assert "websocket_url" not in emit_section, (
            "emitBreadcrumb must not reference websocket_url"
        )


class TestStatusUsesCanonicalTrace:
    def test_status_js_imports_from_canonical_frontend_trace(self):
        """status.js must import recordFrontendEvent from telemetry/frontendTrace.js."""
        source = (FRONTEND_DIR / "js" / "status.js").read_text(encoding="utf-8")
        assert "telemetry/frontendTrace.js" in source, (
            "status.js must import from canonical telemetry/frontendTrace.js"
        )


class TestBridgeFrontendEventHandling:
    def test_bridge_handles_post_frontend_event(self):
        """Bridge server's _handle_http must parse POST JSON body for /frontend-event."""
        source = (
            Path(__file__).resolve().parents[2]
            / "rig_relay"
            / "desktop"
            / "bridge_server.py"
        )
        content = source.read_text()
        assert 'path == "/frontend-event"' in content, (
            "Bridge must route /frontend-event"
        )
        assert 'getattr(request, "method"' in content or 'request.method' in content, (
            "Bridge must check HTTP method on /frontend-event"
        )
        assert 'getattr(request, "body"' in content or 'request.body' in content, (
            "Bridge must read request body for POST /frontend-event"
        )

    def test_bridge_has_method_guard_on_ws(self):
        """Bridge server must guard against non-WebSocket requests reaching Request.parse."""
        source = (
            Path(__file__).resolve().parents[2]
            / "rig_relay"
            / "desktop"
            / "bridge_server.py"
        )
        content = source.read_text()
        assert "_WebSocketNoiseFilter" in content, (
            "Bridge must have WebSocket noise filter for non-GET requests"
        )
        assert "unsupported HTTP method" in content, (
            "Noise filter must suppress unsupported HTTP method errors"
        )


class TestStartupProbesEntrypoint:
    def test_startup_probes_orchestrator(self):
        """Bridge startup must probe the active orchestrator entrypoint."""
        source = (
            Path(__file__).resolve().parents[2]
            / "rig_relay"
            / "desktop"
            / "bridge_server.py"
        )
        content = source.read_text()
        assert "/js/boot/orchestrator.js" in content, (
            "Bridge startup must probe /js/boot/orchestrator.js"
        )
        assert "active_entrypoint" in content, (
            "Bridge diagnostics must report active_entrypoint"
        )
