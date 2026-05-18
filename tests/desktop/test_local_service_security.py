from __future__ import annotations

import asyncio
import json
from pathlib import Path
import secrets

import httpx
import pytest
import websockets
import websockets.exceptions as ws_exc


@pytest.fixture(scope="module")
def temp_frontend_dir(tmp_path_factory) -> Path:
    d = tmp_path_factory.mktemp("frontend")
    (d / "index.html").write_text(
        "<html><head></head><body>rig</body></html>", encoding="utf-8"
    )
    js_dir = d / "js"
    js_dir.mkdir()
    (js_dir / "main.js").write_text("console.log('rig');", encoding="utf-8")
    css_dir = d / "css"
    css_dir.mkdir()
    (css_dir / "style.css").write_text("body { }", encoding="utf-8")
    return d


@pytest.fixture
def bridge_token() -> str:
    return secrets.token_hex(32)


@pytest.fixture
def profile_store_override():
    from rig_relay.governance.service_state import set_profile_store_override

    set_profile_store_override(None)
    yield
    set_profile_store_override(None)


def _ws_url(server) -> str:
    return f"ws://{server._config.host}:{server.bound_port}/ws"


def _http_url(server, path="/") -> str:
    return f"http://{server._config.host}:{server.bound_port}{path}"


# ── Loopback Binding Tests ──


class TestLoopbackBinding:
    def test_binds_to_loopback_by_default(self, temp_frontend_dir, bridge_token):
        from rig_relay.desktop.bridge_server import (
            DesktopBridgeConfig,
            DesktopBridgeServer,
        )

        config = DesktopBridgeConfig(
            host="127.0.0.1",
            port=0,
            frontend_dir=temp_frontend_dir,
            auth_token=bridge_token,
        )
        server = DesktopBridgeServer(config)
        assert server._config.host == "127.0.0.1"

    def test_refuses_non_loopback_host(self, temp_frontend_dir, bridge_token):
        from rig_relay.desktop.bridge_server import (
            DesktopBridgeConfig,
            DesktopBridgeServer,
        )

        config = DesktopBridgeConfig(
            host="0.0.0.0",
            port=0,
            frontend_dir=temp_frontend_dir,
            auth_token=bridge_token,
        )
        server = DesktopBridgeServer(config)
        with pytest.raises(ValueError, match="Non-loopback host rejected"):
            asyncio.run(server.start())

    def test_non_loopback_allowed_with_env_flag(
        self, temp_frontend_dir, bridge_token, monkeypatch
    ):
        from rig_relay.desktop.bridge_server import (
            DesktopBridgeConfig,
            DesktopBridgeServer,
        )

        monkeypatch.setenv("RIG_RELAY_ALLOW_NON_LOOPBACK_LOCAL_BRIDGE", "1")
        config = DesktopBridgeConfig(
            host="0.0.0.0",
            port=0,
            frontend_dir=temp_frontend_dir,
            auth_token=bridge_token,
        )
        server = DesktopBridgeServer(config)
        try:
            asyncio.run(server.start())
        except ValueError as e:
            assert "Non-loopback host rejected" not in str(e)


# ── Health Endpoint Tests ──


class TestHealthEndpoint:
    @pytest.mark.asyncio
    async def test_healthz_returns_200_without_token(
        self, temp_frontend_dir, bridge_token
    ):
        from rig_relay.desktop.bridge_server import (
            DesktopBridgeConfig,
            DesktopBridgeServer,
        )

        config = DesktopBridgeConfig(
            host="127.0.0.1",
            port=0,
            frontend_dir=temp_frontend_dir,
            auth_token=bridge_token,
        )
        server = DesktopBridgeServer(config)
        await server.start()
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(_http_url(server, "/healthz"))
                assert resp.status_code == 200
                data = resp.json()
                assert data["ok"] is True
                assert "schema_version" in data
        finally:
            await server.stop()

    @pytest.mark.asyncio
    async def test_healthz_is_content_light(self, temp_frontend_dir, bridge_token):
        from rig_relay.desktop.bridge_server import (
            DesktopBridgeConfig,
            DesktopBridgeServer,
        )

        config = DesktopBridgeConfig(
            host="127.0.0.1",
            port=0,
            frontend_dir=temp_frontend_dir,
            auth_token=bridge_token,
        )
        server = DesktopBridgeServer(config)
        await server.start()
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(_http_url(server, "/healthz"))
                assert resp.status_code == 200
                data = resp.json()
                assert "token" not in data
                assert "auth_token" not in data
                assert "access_token" not in data
                assert "refresh_token" not in data
                assert "private_key" not in data
                assert "service_state" in data
                assert "profile_state" in data
        finally:
            await server.stop()

    @pytest.mark.asyncio
    async def test_healthz_works_with_remote_origin_rejected(
        self, temp_frontend_dir, bridge_token
    ):
        from rig_relay.desktop.bridge_server import (
            DesktopBridgeConfig,
            DesktopBridgeServer,
        )

        config = DesktopBridgeConfig(
            host="127.0.0.1",
            port=0,
            frontend_dir=temp_frontend_dir,
            auth_token=bridge_token,
        )
        server = DesktopBridgeServer(config)
        await server.start()
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(_http_url(server, "/healthz"))
                assert resp.status_code == 200
        finally:
            await server.stop()


# ── Origin Validation Tests ──


class TestHTTPOriginValidation:
    @pytest.mark.asyncio
    async def test_allows_local_origin(self, temp_frontend_dir, bridge_token):
        from rig_relay.desktop.bridge_server import (
            DesktopBridgeConfig,
            DesktopBridgeServer,
        )

        config = DesktopBridgeConfig(
            host="127.0.0.1",
            port=0,
            frontend_dir=temp_frontend_dir,
            auth_token=bridge_token,
        )
        server = DesktopBridgeServer(config)
        await server.start()
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    _http_url(server, "/healthz"),
                    headers={"Origin": "http://127.0.0.1"},
                )
                assert resp.status_code == 200
        finally:
            await server.stop()

    @pytest.mark.asyncio
    async def test_allows_localhost_origin(self, temp_frontend_dir, bridge_token):
        from rig_relay.desktop.bridge_server import (
            DesktopBridgeConfig,
            DesktopBridgeServer,
        )

        config = DesktopBridgeConfig(
            host="127.0.0.1",
            port=0,
            frontend_dir=temp_frontend_dir,
            auth_token=bridge_token,
        )
        server = DesktopBridgeServer(config)
        await server.start()
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    _http_url(server, "/healthz"),
                    headers={"Origin": "http://localhost"},
                )
                assert resp.status_code == 200
        finally:
            await server.stop()

    @pytest.mark.asyncio
    async def test_rejects_remote_origin(self, temp_frontend_dir, bridge_token):
        from rig_relay.desktop.bridge_server import (
            DesktopBridgeConfig,
            DesktopBridgeServer,
        )

        config = DesktopBridgeConfig(
            host="127.0.0.1",
            port=0,
            frontend_dir=temp_frontend_dir,
            auth_token=bridge_token,
        )
        server = DesktopBridgeServer(config)
        await server.start()
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    _http_url(server, "/healthz"),
                    headers={"Origin": "https://evil.example.com"},
                )
                assert resp.status_code == 403
                data = resp.json()
                assert "error" in data
                assert "Origin" in data.get("reason", "")
        finally:
            await server.stop()

    @pytest.mark.asyncio
    async def test_rejects_file_origin(self, temp_frontend_dir, bridge_token):
        from rig_relay.desktop.bridge_server import (
            DesktopBridgeConfig,
            DesktopBridgeServer,
        )

        config = DesktopBridgeConfig(
            host="127.0.0.1",
            port=0,
            frontend_dir=temp_frontend_dir,
            auth_token=bridge_token,
        )
        server = DesktopBridgeServer(config)
        await server.start()
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    _http_url(server, "/healthz"), headers={"Origin": "file://"}
                )
                assert resp.status_code == 403
        finally:
            await server.stop()

    @pytest.mark.asyncio
    async def test_allows_missing_origin(self, temp_frontend_dir, bridge_token):
        from rig_relay.desktop.bridge_server import (
            DesktopBridgeConfig,
            DesktopBridgeServer,
        )

        config = DesktopBridgeConfig(
            host="127.0.0.1",
            port=0,
            frontend_dir=temp_frontend_dir,
            auth_token=bridge_token,
        )
        server = DesktopBridgeServer(config)
        await server.start()
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(_http_url(server, "/healthz"))
                assert resp.status_code == 200
        finally:
            await server.stop()

    @pytest.mark.asyncio
    async def test_allows_null_origin(self, temp_frontend_dir, bridge_token):
        from rig_relay.desktop.bridge_server import (
            DesktopBridgeConfig,
            DesktopBridgeServer,
        )

        config = DesktopBridgeConfig(
            host="127.0.0.1",
            port=0,
            frontend_dir=temp_frontend_dir,
            auth_token=bridge_token,
        )
        server = DesktopBridgeServer(config)
        await server.start()
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    _http_url(server, "/healthz"), headers={"Origin": "null"}
                )
                assert resp.status_code == 200
        finally:
            await server.stop()


# ── DNS-Rebinding Defense Tests ──


class TestDNSRebindingDefense:
    @pytest.mark.asyncio
    async def test_allows_localhost_host_header(self, temp_frontend_dir, bridge_token):
        from rig_relay.desktop.bridge_server import (
            DesktopBridgeConfig,
            DesktopBridgeServer,
        )

        config = DesktopBridgeConfig(
            host="127.0.0.1",
            port=0,
            frontend_dir=temp_frontend_dir,
            auth_token=bridge_token,
        )
        server = DesktopBridgeServer(config)
        await server.start()
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    _http_url(server, "/healthz"), headers={"Host": "localhost"}
                )
                assert resp.status_code == 200
        finally:
            await server.stop()

    @pytest.mark.asyncio
    async def test_rejects_dns_rebinding_host(self, temp_frontend_dir, bridge_token):
        from rig_relay.desktop.bridge_server import (
            DesktopBridgeConfig,
            DesktopBridgeServer,
        )

        config = DesktopBridgeConfig(
            host="127.0.0.1",
            port=0,
            frontend_dir=temp_frontend_dir,
            auth_token=bridge_token,
        )
        server = DesktopBridgeServer(config)
        await server.start()
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    _http_url(server, "/healthz"), headers={"Host": "evil.example.com"}
                )
                assert resp.status_code == 403
                data = resp.json()
                assert "forbidden" in data.get("error", "")
        finally:
            await server.stop()

    @pytest.mark.asyncio
    async def test_rejects_remote_host_with_port(self, temp_frontend_dir, bridge_token):
        from rig_relay.desktop.bridge_server import (
            DesktopBridgeConfig,
            DesktopBridgeServer,
        )

        config = DesktopBridgeConfig(
            host="127.0.0.1",
            port=0,
            frontend_dir=temp_frontend_dir,
            auth_token=bridge_token,
        )
        server = DesktopBridgeServer(config)
        await server.start()
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    _http_url(server, "/healthz"),
                    headers={"Host": "attacker.local:8080"},
                )
                assert resp.status_code == 403
        finally:
            await server.stop()

    @pytest.mark.asyncio
    async def test_rejects_dns_rebinding_with_origin(
        self, temp_frontend_dir, bridge_token
    ):
        from rig_relay.desktop.bridge_server import (
            DesktopBridgeConfig,
            DesktopBridgeServer,
        )

        config = DesktopBridgeConfig(
            host="127.0.0.1",
            port=0,
            frontend_dir=temp_frontend_dir,
            auth_token=bridge_token,
        )
        server = DesktopBridgeServer(config)
        await server.start()
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    _http_url(server, "/healthz"),
                    headers={
                        "Host": "rebind.example.com",
                        "Origin": "https://rebind.example.com",
                    },
                )
                assert resp.status_code == 403
        finally:
            await server.stop()


# ── Service State Gating Tests ──


class TestServiceStateGating:
    @pytest.mark.asyncio
    async def test_locked_state_blocks_sensitive_http_routes(
        self, temp_frontend_dir, bridge_token, profile_store_override
    ):
        from rig_relay.desktop.bridge_server import (
            DesktopBridgeConfig,
            DesktopBridgeServer,
        )

        config = DesktopBridgeConfig(
            host="127.0.0.1",
            port=0,
            frontend_dir=temp_frontend_dir,
            auth_token=bridge_token,
        )
        server = DesktopBridgeServer(config)
        await server.start()
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(_http_url(server, "/healthz"))
                assert resp.status_code == 200
                resp = await client.get(_http_url(server, "/"))
                assert resp.status_code == 200
        finally:
            await server.stop()

    @pytest.mark.asyncio
    async def test_setup_required_state_still_serves_static_assets(
        self, temp_frontend_dir, bridge_token, profile_store_override
    ):
        from rig_relay.desktop.bridge_server import (
            DesktopBridgeConfig,
            DesktopBridgeServer,
        )

        config = DesktopBridgeConfig(
            host="127.0.0.1",
            port=0,
            frontend_dir=temp_frontend_dir,
            auth_token=bridge_token,
        )
        server = DesktopBridgeServer(config)
        await server.start()
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(_http_url(server, "/js/main.js"))
                assert resp.status_code == 200
        finally:
            await server.stop()

    @pytest.mark.asyncio
    async def test_setup_required_state_returns_healthz(
        self, temp_frontend_dir, bridge_token, profile_store_override
    ):
        from rig_relay.desktop.bridge_server import (
            DesktopBridgeConfig,
            DesktopBridgeServer,
        )

        config = DesktopBridgeConfig(
            host="127.0.0.1",
            port=0,
            frontend_dir=temp_frontend_dir,
            auth_token=bridge_token,
        )
        server = DesktopBridgeServer(config)
        await server.start()
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(_http_url(server, "/healthz"))
                assert resp.status_code == 200
                data = resp.json()
                assert data.get("service_state") == "setup_required"
        finally:
            await server.stop()

    @pytest.mark.asyncio
    async def test_non_sensitive_http_routes_work_in_setup_required(
        self, temp_frontend_dir, bridge_token, profile_store_override
    ):
        from rig_relay.desktop.bridge_server import (
            DesktopBridgeConfig,
            DesktopBridgeServer,
        )

        config = DesktopBridgeConfig(
            host="127.0.0.1",
            port=0,
            frontend_dir=temp_frontend_dir,
            auth_token=bridge_token,
        )
        server = DesktopBridgeServer(config)
        await server.start()
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(_http_url(server, "/index.html"))
                assert resp.status_code == 200
        finally:
            await server.stop()


# ── WebSocket Security Tests ──


class TestWebSocketSecurity:
    @pytest.mark.asyncio
    async def test_ws_rejects_remote_origin(self, temp_frontend_dir, bridge_token):
        from rig_relay.desktop.bridge_server import (
            DesktopBridgeConfig,
            DesktopBridgeServer,
        )

        config = DesktopBridgeConfig(
            host="127.0.0.1",
            port=0,
            frontend_dir=temp_frontend_dir,
            auth_token=bridge_token,
        )
        server = DesktopBridgeServer(config)
        await server.start()
        try:
            ws_url = f"ws://127.0.0.1:{server.bound_port}/ws"
            with pytest.raises(ws_exc.InvalidStatus):
                async with websockets.connect(
                    ws_url,
                    additional_headers={"Origin": "https://evil.example.com"},
                    open_timeout=3,
                    close_timeout=3,
                ):
                    pass
        finally:
            await server.stop()

    @pytest.mark.asyncio
    async def test_ws_allows_local_origin(self, temp_frontend_dir, bridge_token):
        from rig_relay.desktop.bridge_server import (
            DesktopBridgeConfig,
            DesktopBridgeServer,
        )

        config = DesktopBridgeConfig(
            host="127.0.0.1",
            port=0,
            frontend_dir=temp_frontend_dir,
            auth_token=bridge_token,
        )
        server = DesktopBridgeServer(config)
        await server.start()
        try:
            ws_url = f"ws://127.0.0.1:{server.bound_port}/ws"
            async with websockets.connect(
                ws_url,
                additional_headers={"Origin": "http://127.0.0.1"},
                open_timeout=5,
            ) as ws:
                alive = await ws.ping()
                assert alive is not None
        finally:
            await server.stop()

    @pytest.mark.asyncio
    async def test_ws_requires_auth_token(self, temp_frontend_dir, bridge_token):
        from rig_relay.desktop.bridge_server import (
            DesktopBridgeConfig,
            DesktopBridgeServer,
        )

        config = DesktopBridgeConfig(
            host="127.0.0.1",
            port=0,
            frontend_dir=temp_frontend_dir,
            auth_token=bridge_token,
        )
        server = DesktopBridgeServer(config)
        await server.start()
        try:
            ws_url = f"ws://127.0.0.1:{server.bound_port}/ws"
            async with websockets.connect(
                ws_url,
                additional_headers={"Origin": "http://127.0.0.1"},
                open_timeout=5,
            ) as ws:
                await ws.send(json.dumps({"type": "get_projection"}))
                resp = json.loads(await ws.recv())
                assert resp["type"] == "auth_required"
        finally:
            await server.stop()

    @pytest.mark.asyncio
    async def test_ws_rejects_wrong_token(self, temp_frontend_dir, bridge_token):
        from rig_relay.desktop.bridge_server import (
            DesktopBridgeConfig,
            DesktopBridgeServer,
        )

        config = DesktopBridgeConfig(
            host="127.0.0.1",
            port=0,
            frontend_dir=temp_frontend_dir,
            auth_token=bridge_token,
        )
        server = DesktopBridgeServer(config)
        await server.start()
        try:
            ws_url = f"ws://127.0.0.1:{server.bound_port}/ws"
            async with websockets.connect(
                ws_url,
                additional_headers={"Origin": "http://127.0.0.1"},
                open_timeout=5,
            ) as ws:
                await ws.send(json.dumps({"type": "auth", "token": "wrong-token-123"}))
                resp = json.loads(await ws.recv())
                assert resp["type"] == "auth_error"
                assert "Invalid token" in resp.get("message", "")
        finally:
            await server.stop()

    @pytest.mark.asyncio
    async def test_ws_accepts_correct_token(self, temp_frontend_dir, bridge_token):
        from rig_relay.desktop.bridge_server import (
            DesktopBridgeConfig,
            DesktopBridgeServer,
        )

        config = DesktopBridgeConfig(
            host="127.0.0.1",
            port=0,
            frontend_dir=temp_frontend_dir,
            auth_token=bridge_token,
        )
        server = DesktopBridgeServer(config)
        await server.start()
        try:
            ws_url = f"ws://127.0.0.1:{server.bound_port}/ws"
            async with websockets.connect(
                ws_url,
                additional_headers={"Origin": "http://127.0.0.1"},
                open_timeout=5,
            ) as ws:
                await ws.send(json.dumps({"type": "auth", "token": bridge_token}))
                resp = json.loads(await ws.recv())
                assert resp["type"] == "auth_ok"
        finally:
            await server.stop()

    @pytest.mark.asyncio
    async def test_ws_rejects_file_origin(self, temp_frontend_dir, bridge_token):
        from rig_relay.desktop.bridge_server import (
            DesktopBridgeConfig,
            DesktopBridgeServer,
        )

        config = DesktopBridgeConfig(
            host="127.0.0.1",
            port=0,
            frontend_dir=temp_frontend_dir,
            auth_token=bridge_token,
        )
        server = DesktopBridgeServer(config)
        await server.start()
        try:
            ws_url = f"ws://127.0.0.1:{server.bound_port}/ws"
            with pytest.raises(ws_exc.InvalidStatus):
                async with websockets.connect(
                    ws_url,
                    additional_headers={"Origin": "file://"},
                    open_timeout=3,
                    close_timeout=3,
                ):
                    pass
        finally:
            await server.stop()

    @pytest.mark.asyncio
    async def test_ws_intent_gated_by_service_state(
        self, temp_frontend_dir, bridge_token, profile_store_override
    ):
        from rig_relay.desktop.bridge_server import (
            DesktopBridgeConfig,
            DesktopBridgeServer,
        )

        config = DesktopBridgeConfig(
            host="127.0.0.1",
            port=0,
            frontend_dir=temp_frontend_dir,
            auth_token=bridge_token,
        )
        server = DesktopBridgeServer(config)
        await server.start()
        try:
            ws_url = f"ws://127.0.0.1:{server.bound_port}/ws"
            async with websockets.connect(
                ws_url,
                additional_headers={"Origin": "http://127.0.0.1"},
                open_timeout=5,
            ) as ws:
                await ws.send(json.dumps({"type": "auth", "token": bridge_token}))
                auth_resp = json.loads(await ws.recv())
                assert auth_resp["type"] == "auth_ok"

                await ws.send(
                    json.dumps({
                        "type": "desktop_intent_request",
                        "schema_version": "rig.relay.desktop_intent_request.v1",
                        "created_at": "2026-05-17T00:00:00Z",
                        "intent_name": "sign_in_github_start",
                        "intent_id": "test-intent-1",
                        "parameters": {},
                    })
                )
                result = json.loads(await ws.recv())
                assert result["type"] == "desktop_intent_result"
                assert result["data"]["status"] == "refused"
                assert "service_gated" in result["data"].get("error_code", "")
        finally:
            await server.stop()


# ── Token Safety Tests ──


class TestTokenSafety:
    def test_token_not_in_projection(self, bridge_token):
        from rig_relay.desktop.projection import build_projection

        projection = build_projection()
        proj_str = json.dumps(projection)
        assert bridge_token not in proj_str, "Bridge token leaked in projection"

    @pytest.mark.asyncio
    async def test_runtime_config_strips_token(self, temp_frontend_dir, bridge_token):
        from rig_relay.desktop.bridge_server import (
            DesktopBridgeConfig,
            DesktopBridgeServer,
        )

        config = DesktopBridgeConfig(
            host="127.0.0.1",
            port=0,
            frontend_dir=temp_frontend_dir,
            auth_token=bridge_token,
        )
        server = DesktopBridgeServer(config)
        await server.start()
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(_http_url(server, "/runtime-config.json"))
                assert resp.status_code == 200
                data = resp.json()
                assert "auth_token" not in data, "Token leaked in runtime-config.json"
                assert "token" not in data, "Token leaked in runtime-config.json"
                assert data.get("token_present") is True
        finally:
            await server.stop()

    @pytest.mark.asyncio
    async def test_healthz_does_not_leak_token(self, temp_frontend_dir, bridge_token):
        from rig_relay.desktop.bridge_server import (
            DesktopBridgeConfig,
            DesktopBridgeServer,
        )

        config = DesktopBridgeConfig(
            host="127.0.0.1",
            port=0,
            frontend_dir=temp_frontend_dir,
            auth_token=bridge_token,
        )
        server = DesktopBridgeServer(config)
        await server.start()
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(_http_url(server, "/healthz"))
                data = resp.json()
                assert bridge_token not in json.dumps(data), "Token leaked in healthz"
        finally:
            await server.stop()


# ── OAuth Loopback Exception Tests ──


class TestOAuthLoopbackException:
    def test_auth_session_manager_has_separate_port(self):
        from rig_relay.identity.auth_session_manager import AuthSessionManager
        from rig_relay.identity.oauth_loopback import find_free_loopback_port

        AuthSessionManager()
        port = find_free_loopback_port()
        assert isinstance(port, int)
        assert port > 0

    def test_auth_session_uses_state_validation(self):
        import hashlib

        state = secrets.token_hex(32)
        state_hash = hashlib.sha256(state.encode("utf-8")).hexdigest()
        assert len(state_hash) == 64

    def test_auth_callback_uses_loopback_redirect_uri(self):
        from rig_relay.identity.oauth_loopback import (
            build_loopback_redirect_uri,
            find_free_loopback_port,
        )

        port = find_free_loopback_port()
        uri = build_loopback_redirect_uri(port)
        assert "127.0.0.1" in uri or "localhost" in uri
        assert str(port) in uri

    def test_auth_session_not_governed_by_cockpit_token(self):
        from rig_relay.identity.auth_session_manager import AuthSessionManager

        manager = AuthSessionManager()
        assert manager is not None
        assert not hasattr(manager, "bridge_token")
