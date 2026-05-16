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

import pytest
import websockets

from rig_relay.cli.desktop_cockpit import CockpitAPI
from rig_relay.desktop.bridge_server import DesktopBridgeConfig, DesktopBridgeServer

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
            "transport_label": "Local Loopback Bridge",
            "tls_enabled": False,
            "local_mode": True,
        }
        api.set_runtime_config(config)
        result = api.get_runtime_config()
        assert result.get("token"), "Token missing — frontend will show token_missing"
        assert len(result["token"]) > 0
        assert result.get("ws_url", "").startswith("ws://")

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
