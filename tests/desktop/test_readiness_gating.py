from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import websockets

from rig_relay.desktop.bridge_server import DesktopBridgeConfig, DesktopBridgeServer
from rig_relay.governance.service_state import ProfileStore, set_profile_store_override

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
FRONTEND_DIR = REPO_ROOT / "frontend" / "desktop"

READINESS_STATES = frozenset({
    "starting",
    "setup_required",
    "locked",
    "ready",
    "degraded",
    "failed",
})


def _make_temp_frontend(tmp_path: Path) -> Path:
    fe = tmp_path / "frontend"
    (fe / "js").mkdir(parents=True)
    (fe / "css").mkdir(parents=True)
    (fe / "index.html").write_text(
        "<!DOCTYPE html><html><head></head><body></body></html>"
    )
    (fe / "js" / "main.js").write_text("// main.js")
    return fe


def _make_config(
    frontend_dir: Path, auth_token: str = "test-token"
) -> DesktopBridgeConfig:
    return DesktopBridgeConfig(
        host="127.0.0.1", port=0, frontend_dir=frontend_dir, auth_token=auth_token
    )


# ── Test 1: healthz reports distinct readiness states ──────────────────


@pytest.mark.contract
class TestHealthzReadinessStates:
    def test_healthz_reports_distinct_readiness_states(self, tmp_path: Path) -> None:
        frontend_dir = _make_temp_frontend(tmp_path)
        config = _make_config(frontend_dir)
        bridge = DesktopBridgeServer(config)

        healthz = bridge._build_healthz()
        body = json.loads(healthz.body)

        assert "readiness_state" in body
        assert body["readiness_state"] in READINESS_STATES


@pytest.mark.integration
class TestHealthzReadinessStateSetupRequired:
    def test_healthz_readiness_state_setup_required_on_fresh_launch(
        self, tmp_path: Path
    ) -> None:
        empty_store = ProfileStore(root=tmp_path / "no_profile_here")
        set_profile_store_override(empty_store)
        try:
            frontend_dir = _make_temp_frontend(tmp_path)
            config = _make_config(frontend_dir)
            bridge = DesktopBridgeServer(config)

            healthz = bridge._build_healthz()
            body = json.loads(healthz.body)

            assert body["readiness_state"] == "setup_required"
        finally:
            set_profile_store_override(None)


# ── Test 3: bridge state machine reports starting before ready ─────────


@pytest.mark.contract
class TestBridgeStateMachineStarting:
    def test_bridge_state_machine_reports_starting_before_ready(self) -> None:
        from rig_relay.desktop.bridge_state_machine import (
            DesktopBridgeEvent,
            DesktopBridgeState,
            DesktopBridgeStateMachine,
        )

        sm = DesktopBridgeStateMachine()
        assert sm.current_state == DesktopBridgeState.UNINITIALIZED
        assert sm.current_state != "ready"

        sm.transition(DesktopBridgeEvent.RESOLVING_FRONTEND, reason="start")
        assert sm.current_state == DesktopBridgeState.TOKEN_GENERATING
        assert sm.current_state != DesktopBridgeState.UNINITIALIZED


# ── Test 4: frontend projection ready export ───────────────────────────


@pytest.mark.substrate
class TestFrontendProjectionReadyExport:
    def test_frontend_projection_ready_export(self) -> None:
        projection_js = (FRONTEND_DIR / "js" / "projection.js").read_text()

        assert "isProjectionReady" in projection_js or (
            "first projection" in projection_js.lower()
            and "_lastDigest" in projection_js
        )


# ── Test 5: frontend transport queues intents before ready ─────────────


@pytest.mark.substrate
class TestFrontendTransportQueuesIntents:
    def test_frontend_transport_queues_intents_before_ready(self) -> None:
        transport_js = (FRONTEND_DIR / "js" / "transport.js").read_text()

        assert "_outboundQueue" in transport_js or "outboundQueue" in transport_js


# ── Test 6: frontend does not report connected before projection ────────


@pytest.mark.substrate
class TestFrontendConnectedBeforeProjection:
    def test_frontend_does_not_report_connected_before_projection(self) -> None:
        transport_js = (FRONTEND_DIR / "js" / "transport.js").read_text()

        assert "_wsAuthenticated" in transport_js
        assert "_firstProjectionReceived" in transport_js


# ── Test 7: WebSocket auth and projection roundtrip readiness ──────────


@pytest.mark.integration
@pytest.mark.asyncio
class TestWebSocketReadinessRoundtrip:
    async def test_websocket_auth_and_projection_roundtrip_readiness(self) -> None:
        config = _make_config(FRONTEND_DIR)
        bridge = DesktopBridgeServer(config)
        await bridge.start()
        try:
            ws_url = bridge.runtime_config.ws_url
            async with websockets.connect(ws_url) as ws:
                await ws.send(json.dumps({"type": "auth", "token": "test-token"}))
                auth_resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
                assert auth_resp["type"] == "auth_ok"

                await ws.send(json.dumps({"type": "get_projection"}))
                proj_resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
                assert proj_resp["type"] == "projection"
                assert "data" in proj_resp
                data = proj_resp["data"]
                assert "schema_version" in data
                assert "service_state" in data
        finally:
            await bridge.stop()


# ── Test 8: unauthorized message before auth refused ───────────────────


@pytest.mark.integration
@pytest.mark.asyncio
class TestUnauthorizedBeforeAuth:
    async def test_unauthorized_message_before_auth_refused(self) -> None:
        config = _make_config(FRONTEND_DIR)
        bridge = DesktopBridgeServer(config)
        await bridge.start()
        try:
            ws_url = bridge.runtime_config.ws_url
            async with websockets.connect(ws_url) as ws:
                await ws.send(json.dumps({"type": "get_projection"}))
                resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
                assert resp["type"] in {"auth_required", "error"}
        finally:
            await bridge.stop()


# ── Test 9: double terminate idempotent ────────────────────────────────


@pytest.mark.adversarial
class TestDoubleTerminateIdempotent:
    @pytest.mark.asyncio
    async def test_double_terminate_idempotent(self) -> None:
        from rig_relay.runtime.supervisor import _finalize_subprocess

        proc = await asyncio.create_subprocess_exec(
            "sleep",
            "60",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            await _finalize_subprocess(proc, timeout_seconds=2.0)
            await _finalize_subprocess(proc, timeout_seconds=2.0)
        finally:
            try:
                proc.kill()
                await proc.wait()
            except ProcessLookupError:
                pass


# ── Test 10: auth double listen refused ────────────────────────────────


@pytest.mark.contract
class TestAuthDoubleListenRefused:
    def test_auth_double_listen_refused(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from rig_relay.identity.auth_session_manager import (
            AuthSession,
            AuthSessionManager,
        )
        from rig_relay.identity.models import IdentityProviderKind

        manager = AuthSessionManager()

        def _fake_run_loopback(self: AuthSessionManager, session: AuthSession) -> None:
            session.started.set()

        monkeypatch.setattr(AuthSessionManager, "_run_loopback", _fake_run_loopback)
        monkeypatch.setattr(
            "rig_relay.identity.auth_session_manager.find_free_loopback_port",
            lambda: 19999,
        )

        provider_impl = MagicMock()
        provider_impl.default_scopes.return_value = ["read:user"]
        provider_impl.build_auth_url.return_value = "https://example.com/auth"

        manager.start_session(
            provider_kind=IdentityProviderKind.GITHUB, provider_impl=provider_impl
        )

        provider_impl2 = MagicMock()
        provider_impl2.default_scopes.return_value = ["read:user"]
        provider_impl2.build_auth_url.return_value = "https://example.com/auth"

        with pytest.raises(RuntimeError, match="already pending"):
            manager.start_session(
                provider_kind=IdentityProviderKind.GITHUB, provider_impl=provider_impl2
            )
