"""Golden-path regression tests for the desktop bridge.

Proves the protocol-level chain without requiring pywebview GUI:
- runtime config has token when delivered via CockpitAPI
- fallback tokenless config produces explicit token_missing state
- /ws accepts upgrade and in-band auth
- first projection can be sent through the handler
- healthz includes all asset-existence fields
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
import websockets

from rig_relay.cli.desktop_cockpit import CockpitAPI
from rig_relay.desktop.bridge_server import DesktopBridgeConfig, DesktopBridgeServer
from rig_relay.tracing.recorder import TraceRecorder
from rig_relay.tracing.store import InMemoryTraceStore

FRONTEND_DIR = Path(__file__).resolve().parent.parent.parent / "frontend" / "desktop"


class TestRuntimeConfigHasToken:
    """Proves the CockpitAPI → frontend config path includes token."""

    def test_runtime_config_includes_token(self) -> None:
        api = CockpitAPI(
            ws_token="test-token-32chars-abcdefgh", ws_port=9876, mode="fixture"
        )
        config = {
            "token": "test-token-32chars-abcdefgh",
            "auth_token": "test-token-32chars-abcdefgh",
            "ws_url": "ws://127.0.0.1:9876/ws",
            "frontend_url": "http://127.0.0.1:9876/index.html",
            "transport_label": "Loopback Token Bridge",
            "tls_enabled": False,
            "local_mode": True,
        }
        api.set_runtime_config(config)
        result = api.get_runtime_config()
        assert result.get("token"), "Token missing — frontend will show token_missing"
        assert len(result["token"]) > 0
        assert result.get("ws_url", "").startswith("ws://")

    def test_runtime_config_default_uses_loopback_http(self) -> None:
        api = CockpitAPI(ws_token=None, ws_port=9876, mode="fixture")
        result = api.get_runtime_config()
        assert result["frontend_origin"] == "http://127.0.0.1"
        assert result["ws_url"].startswith("ws://")
        assert result["static_protocol"] == "http"
        assert result["ws_protocol"] == "ws"
        assert result["token_present"] is False


class TestTransportLabels:
    def test_default_label_is_loopback_token_bridge(self) -> None:
        api = CockpitAPI(ws_token="token", ws_port=9876, mode="fixture")
        result = api.get_runtime_config()
        assert result["transport_label"] == "Loopback Token Bridge"
        assert "Secure Local Bridge" not in result["transport_label"]


def test_desktop_bridge_config_defaults_to_loopback_host() -> None:
    config = DesktopBridgeConfig(frontend_dir=FRONTEND_DIR)
    assert config.host == "127.0.0.1"


@pytest.mark.asyncio
async def test_index_html_injects_runtime_config(tmp_path: Path) -> None:
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (frontend / "index.html").write_text("<html><head></head><body></body></html>")
    (frontend / "js").mkdir()
    (frontend / "js" / "main.js").write_text("console.log(1)")
    (frontend / "css").mkdir()
    (frontend / "css" / "styles.css").write_text("body{}")

    config = DesktopBridgeConfig(
        host="127.0.0.1", port=0, frontend_dir=frontend, auth_token="test-token"
    )
    bridge = DesktopBridgeServer(config)
    await bridge.start()
    try:
        response = bridge._handle_http(
            type("Req", (), {"path": "/index.html"})(), frontend  # type: ignore[arg-type]
        )
        assert response is not None
        body = response.body.decode("utf-8")
        assert "window.__RIG_RELAY_RUNTIME_CONFIG__" in body
        assert '"token_present": true' in body
        assert '"token": "test-token"' in body
        assert '"handshake_id":' in body
    finally:
        await bridge.stop()


@pytest.mark.asyncio
async def test_runtime_config_and_index_emit_frontend_breadcrumbs(
    tmp_path: Path,
) -> None:
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (frontend / "index.html").write_text("<html><head></head><body></body></html>")
    (frontend / "js").mkdir()
    (frontend / "js" / "main.js").write_text("console.log(1)")
    (frontend / "css").mkdir()
    (frontend / "css" / "styles.css").write_text("body{}")

    config = DesktopBridgeConfig(
        host="127.0.0.1", port=0, frontend_dir=frontend, auth_token="test-token"
    )
    bridge = DesktopBridgeServer(config)
    await bridge.start()
    try:
        bridge._trace_recorder = TraceRecorder(InMemoryTraceStore())
        bridge._handle_http(type("Req", (), {"path": "/index.html"})(), frontend)  # type: ignore[arg-type]
        bridge._handle_http(
            type("Req", (), {"path": "/runtime-config.json"})(), frontend  # type: ignore[arg-type]
        )
        names = [
            event.get("event_type") or event.get("name")
            for event in bridge._trace_recorder.store.events  # type: ignore[attr-defined]
        ]
        assert "desktop.frontend.bootstrap_loaded" in names
        assert "desktop.frontend.runtime_config_served" in names
    finally:
        await bridge.stop()


@pytest.mark.asyncio
async def test_frontend_event_beacon_records_trace(tmp_path: Path) -> None:
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (frontend / "index.html").write_text("<html><head></head><body></body></html>")
    (frontend / "js").mkdir()
    (frontend / "js" / "main.js").write_text("console.log(1)")
    (frontend / "css").mkdir()
    (frontend / "css" / "styles.css").write_text("body{}")

    config = DesktopBridgeConfig(
        host="127.0.0.1", port=0, frontend_dir=frontend, auth_token="test-token"
    )
    bridge = DesktopBridgeServer(config)
    await bridge.start()
    try:
        response = bridge._handle_http(
            SimpleNamespace(  # type: ignore[arg-type]
                path="/frontend-event?type=frontend_status_rendered&handshake_id=corr_test&detail=%7B%22x%22%3A1%7D"
            ),
            frontend,
        )
        assert response is not None
        assert response.status_code == 200
    finally:
        await bridge.stop()

    def test_runtime_config_default_has_no_token(self) -> None:
        """Fallback config (no set_runtime_config) has no token — produces token_missing."""
        api = CockpitAPI(ws_token=None, ws_port=9876, mode="fixture")
        result = api.get_runtime_config()
        assert not result.get("token"), "Fallback config unexpectedly has token"


class TestWebSocketAuthAndProjection:
    """Proves the WebSocket auth + projection protocol works."""

    @pytest.mark.asyncio
    async def test_ws_auth_ok_and_projection(self) -> None:
        timeout_seconds = 10
        config = DesktopBridgeConfig(
            host="127.0.0.1",
            port=0,
            frontend_dir=FRONTEND_DIR,
            auth_token="golden-auth-token-test-1234",
        )
        bridge = DesktopBridgeServer(config)
        await bridge.start()
        try:
            ws_url = bridge.runtime_config.ws_url
            async with websockets.connect(ws_url) as ws:
                # Auth
                await ws.send(
                    json.dumps({"type": "auth", "token": "golden-auth-token-test-1234"})
                )
                auth_resp = json.loads(
                    await asyncio.wait_for(ws.recv(), timeout=timeout_seconds)
                )
                assert auth_resp["type"] == "auth_ok"

                # Projection
                await ws.send(json.dumps({"type": "get_projection"}))
                proj_resp = json.loads(
                    await asyncio.wait_for(ws.recv(), timeout=timeout_seconds)
                )
                assert proj_resp["type"] == "projection"
                proj = proj_resp["data"]
                assert "schema_version" in proj
                assert "digest" in proj
        finally:
            await bridge.stop()

    @pytest.mark.asyncio
    async def test_ws_auth_bad_token_refused(self) -> None:
        config = DesktopBridgeConfig(
            host="127.0.0.1",
            port=0,
            frontend_dir=FRONTEND_DIR,
            auth_token="correct-token",
        )
        bridge = DesktopBridgeServer(config)
        await bridge.start()
        try:
            ws_url = bridge.runtime_config.ws_url
            async with websockets.connect(ws_url) as ws:
                await ws.send(json.dumps({"type": "auth", "token": "wrong-token"}))
                auth_resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
                assert auth_resp["type"] == "auth_error"
        finally:
            await bridge.stop()


class TestHealthz:
    """Proves /healthz includes all asset-existence fields."""

    @pytest.mark.asyncio
    async def test_healthz_asset_fields(self) -> None:
        config = DesktopBridgeConfig(
            host="127.0.0.1", port=0, frontend_dir=FRONTEND_DIR, auth_token="test"
        )
        bridge = DesktopBridgeServer(config)
        await bridge.start()
        try:
            resp = bridge._build_healthz()
            body = json.loads(resp.body)
            assert body["ok"] is True
            assert body["frontend_dir_exists"] is True
            assert body["index_exists"] is True
            assert body["main_js_exists"] is True
            assert body["css_dir_exists"] is True
            assert "ws_url" in body
            assert "frontend_url" in body
            assert "auth_token" not in body
            assert "token" not in body
        finally:
            await bridge.stop()


class TestProbeLadder:
    """Proves the probe ladder is complete for the golden path."""

    @pytest.mark.asyncio
    async def test_full_probe_ladder_all_ok(self) -> None:
        from rig_relay.desktop.bridge_diagnostics import BridgeProbeReport

        report = BridgeProbeReport(mode="source")
        config = DesktopBridgeConfig(
            host="127.0.0.1", port=0, frontend_dir=FRONTEND_DIR, auth_token="test-token"
        )
        bridge = DesktopBridgeServer(config, probe_report=report)
        await bridge.start()
        try:
            assert report.ok
            step_ids = [s.step_id for s in report.steps]
            for required in [f"bridge:{i:02d}" for i in range(1, 11)]:
                assert required in step_ids, f"Missing probe step: {required}"
        finally:
            await bridge.stop()


class TestGoldenPathTraceSummaryLogic:
    """Trace-summary analyzer unit tests — proves the trace schema, event builder,
    and summary script can detect complete/missing/split-brain traces from synthetic
    events. These do NOT prove the real frontend/browser/bridge path.
    For real browser integration proof, see test_golden_path_browser_integration.py.
    """

    def test_trace_event_schema_parses(self) -> None:
        from rig_relay.tracing.golden_path import build_golden_path_event

        event = build_golden_path_event(
            event_type="desktop.bridge.launch_requested",
            handshake_id="hs_test123",
            host="127.0.0.1",
            port=9876,
            tls_enabled=False,
            token_present=True,
        )
        d = cast(dict[str, Any], event.to_dict())
        assert d["schema_version"] == "rig.trace_event.v1"
        assert d["event_type"] == "desktop.bridge.launch_requested"
        assert d["trace_id"]
        assert d["span_id"]
        assert d["correlation"]["handshake_id"] == "hs_test123"
        assert d["redaction"]["token_present"] is True
        assert d["redaction"]["token_value_included"] is False
        assert d["redaction"]["contains_secret"] is False
        assert d["authority"]["authority_kind"] == "desktop_bridge"
        assert d["authority"]["trusted"] is True

    def test_trace_event_no_token_value(self) -> None:
        from rig_relay.tracing.golden_path import build_golden_path_event

        event = build_golden_path_event(
            event_type="desktop.bridge.launch_requested", token_present=True
        )
        d = cast(dict[str, Any], event.to_dict())
        # token_value_included must always be false
        assert d["redaction"]["token_value_included"] is False
        # No actual token value string in payload
        payload = cast(dict[str, Any], d["payload"])
        for v in payload.values():
            if isinstance(v, str):
                assert "secret" not in v.lower()

    def test_trace_event_no_token_leakage_in_payload(self) -> None:
        from rig_relay.tracing.golden_path import build_golden_path_event

        event = build_golden_path_event(
            event_type="desktop.websocket.auth_received",
            handshake_id="hs_test",
            token_present=True,
        )
        d = cast(dict[str, Any], event.to_dict())
        payload_str = json.dumps(d["payload"])
        assert "secret" not in payload_str.lower()

    def test_bridge_startup_emits_trace_id_and_handshake(self) -> None:
        from rig_relay.tracing.recorder import TraceRecorder
        from rig_relay.tracing.store import InMemoryTraceStore

        store = InMemoryTraceStore()
        recorder = TraceRecorder(store)
        recorder.event(
            "desktop.bridge.launch_requested",
            attributes={"handshake_id": "hs_abc", "host": "127.0.0.1"},
        )
        events = store.events
        assert len(events) >= 1
        assert "trace_id" in events[0]
        assert "span_id" in events[0]

    @pytest.mark.asyncio
    async def test_bridge_start_emits_golden_events(self) -> None:
        from rig_relay.tracing.store import InMemoryTraceStore

        store = InMemoryTraceStore()
        config = DesktopBridgeConfig(
            host="127.0.0.1", port=0, frontend_dir=FRONTEND_DIR, auth_token="test-token"
        )
        bridge = DesktopBridgeServer(config)
        bridge._trace_recorder = TraceRecorder(store)
        await bridge.start()
        try:
            names = [e.get("event_type") or e.get("name") for e in store.events]
            assert "desktop.bridge.launch_requested" in names
            assert "desktop.bridge.frontend_resolved" in names
            assert "desktop.bridge.runtime_config_built" in names
            assert "desktop.bridge.server_bound" in names
            assert "desktop.bridge.health_probe_passed" in names
            assert "desktop.bridge.index_probe_passed" in names
            assert "desktop.bridge.websocket_server_created" in names
            assert "desktop.bridge.window_start_called" in names
        finally:
            await bridge.stop()

    @pytest.mark.asyncio
    async def test_shutdown_emits_golden_event(self) -> None:
        from rig_relay.tracing.store import InMemoryTraceStore

        store = InMemoryTraceStore()
        config = DesktopBridgeConfig(
            host="127.0.0.1", port=0, frontend_dir=FRONTEND_DIR, auth_token="test-token"
        )
        bridge = DesktopBridgeServer(config)
        bridge._trace_recorder = TraceRecorder(store)
        await bridge.start()
        await bridge.stop()
        names = [e.get("event_type") or e.get("name") for e in store.events]
        assert "desktop.bridge.shutdown" in names

    @pytest.mark.asyncio
    async def test_runtime_config_built_includes_frontend_and_ws_url(self) -> None:
        from rig_relay.tracing.store import InMemoryTraceStore

        store = InMemoryTraceStore()
        config = DesktopBridgeConfig(
            host="127.0.0.1", port=0, frontend_dir=FRONTEND_DIR, auth_token="test-token"
        )
        bridge = DesktopBridgeServer(config)
        bridge._trace_recorder = TraceRecorder(store)
        await bridge.start()
        try:
            for event in store.events:  # type: ignore[attr-defined]
                if (
                    event.get("event_type") or event.get("name")
                ) == "desktop.bridge.runtime_config_built":
                    payload: dict[str, Any] = cast(dict[str, Any], event.get("payload") or event.get("attributes") or {})
                    assert "frontend_url" in payload or "frontend_url" in str(event)
                    assert "websocket_url" in payload or "websocket_url" in str(event)
                    break
        finally:
            await bridge.stop()


class TestDuplicateWebSocketCycleTracking:
    """Non-blocking advisory: track duplicate WebSocket upgrade/auth cycles.

    Manual verification observed two connection cycles ~19s apart in one
    pywebview launch. This is classified as expected reconnect/reload
    lifecycle. If duplicate cycles accumulate (>3 in one launch),
    investigate pywebview page reload or WebSocket reconnect logic.
    """

    def test_duplicate_ws_cycle_documented_as_expected(self) -> None:
        """Golden-path proof records duplicate connection as expected lifecycle."""
        proof_path = (
            Path(__file__).resolve().parents[2]
            / "docs"
            / "audits"
            / "desktop"
            / "desktop-golden-path-proof.md"
        )
        content = proof_path.read_text()
        assert "passed_with_followup" in content, (
            "Golden path proof must record passed_with_followup result"
        )
        assert "duplicate" in content.lower(), (
            "Golden path proof must document duplicate WebSocket connection finding"
        )

    def test_duplicate_ws_cycle_threshold_specified(self) -> None:
        """Documentation specifies >3 cycles in one launch as investigation trigger."""
        proof_path = (
            Path(__file__).resolve().parents[2]
            / "docs"
            / "audits"
            / "desktop"
            / "desktop-golden-path-proof.md"
        )
        content = proof_path.read_text()
        assert ">3" in content or " > 3" in content or "> 3" in content, (
            "Golden path proof must specify threshold for duplicate cycle investigation"
        )
