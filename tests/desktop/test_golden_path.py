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
from types import SimpleNamespace
from pathlib import Path

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
        host="127.0.0.1",
        port=0,
        frontend_dir=frontend,
        auth_token="test-token",
    )
    bridge = DesktopBridgeServer(config)
    await bridge.start()
    try:
        response = bridge._handle_http(type("Req", (), {"path": "/index.html"})(), frontend)
        assert response is not None
        body = response.body.decode("utf-8")
        assert "window.__RIG_RELAY_RUNTIME_CONFIG__" in body
        assert '"token_present": true' in body
        assert '"token": "test-token"' in body
        assert '"handshake_id":' in body
    finally:
        await bridge.stop()


@pytest.mark.asyncio
async def test_runtime_config_and_index_emit_frontend_breadcrumbs(tmp_path: Path) -> None:
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (frontend / "index.html").write_text("<html><head></head><body></body></html>")
    (frontend / "js").mkdir()
    (frontend / "js" / "main.js").write_text("console.log(1)")
    (frontend / "css").mkdir()
    (frontend / "css" / "styles.css").write_text("body{}")

    config = DesktopBridgeConfig(
        host="127.0.0.1",
        port=0,
        frontend_dir=frontend,
        auth_token="test-token",
    )
    bridge = DesktopBridgeServer(config)
    await bridge.start()
    try:
        bridge._trace_recorder = TraceRecorder(InMemoryTraceStore())
        bridge._handle_http(type("Req", (), {"path": "/index.html"})(), frontend)
        bridge._handle_http(type("Req", (), {"path": "/runtime-config.json"})(), frontend)
        names = [event["name"] for event in bridge._trace_recorder.store.events]
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
        host="127.0.0.1",
        port=0,
        frontend_dir=frontend,
        auth_token="test-token",
    )
    bridge = DesktopBridgeServer(config)
    await bridge.start()
    try:
        response = bridge._handle_http(
            SimpleNamespace(path="/frontend-event?type=frontend_status_rendered&handshake_id=corr_test&detail=%7B%22x%22%3A1%7D"),
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
