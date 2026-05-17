"""WebSocket security rejection tests — origin validation, message validation,
rejection trace events, token redaction, and connection abuse controls.
"""

from __future__ import annotations

import json

import pytest

from rig_relay.desktop.websocket_server import (
    DEFAULT_HOST,
    MAX_INVALID_WEBSOCKET_MESSAGES,
    ProjectionWebSocketServer,
)
from rig_relay.tracing.recorder import TraceRecorder
from rig_relay.tracing.store import InMemoryTraceStore


def _make_server(**kwargs) -> ProjectionWebSocketServer:
    defaults = {
        "auth_timeout": 100,
        "token": "test-secret-token-32chars!!",
        "missing_origin_allowed": True,
        "allow_null_origin": False,
    }
    defaults.update(kwargs)
    return ProjectionWebSocketServer(**defaults)


def _trace_store(server: ProjectionWebSocketServer) -> InMemoryTraceStore:
    store = InMemoryTraceStore()
    server._trace_recorder = TraceRecorder(store)
    return store


def _find_events(store: InMemoryTraceStore, event_type: str) -> list[dict]:
    return [e for e in store.events if e.get("event_type") == event_type]


def _rejection_reasons(store: InMemoryTraceStore) -> list[str]:
    reasons: list[str] = []
    for event in store.events:
        payload = event.get("payload", {})
        if isinstance(payload, dict):
            reason = payload.get("reason", "")
            if reason:
                reasons.append(str(reason))
    return reasons


class TestOriginValidation:
    @pytest.mark.asyncio
    async def test_loopback_origin_accepted(self, unused_tcp_port: int) -> None:
        import websockets

        server = _make_server(port=unused_tcp_port)
        store = _trace_store(server)
        await server.start()
        try:
            async with websockets.connect(
                f"ws://{DEFAULT_HOST}:{unused_tcp_port}",
                origin=f"http://{DEFAULT_HOST}:{unused_tcp_port}",  # pyright: ignore[reportArgumentType]
            ) as ws:
                await ws.send(json.dumps({"type": "auth", "token": server.token}))
                resp = json.loads(await ws.recv())
                assert resp["type"] == "auth_ok"
        finally:
            await server.close()
        origin_rejected = _find_events(store, "desktop.websocket.origin_rejected")
        assert len(origin_rejected) == 0, (
            f"Loopback origin was rejected: {origin_rejected}"
        )

    @pytest.mark.asyncio
    async def test_foreign_origin_rejected(self, unused_tcp_port: int) -> None:
        import websockets

        server = _make_server(port=unused_tcp_port)
        store = _trace_store(server)
        await server.start()
        try:
            with pytest.raises(websockets.InvalidStatus) as exc_info:
                async with websockets.connect(
                    f"ws://{DEFAULT_HOST}:{unused_tcp_port}",
                    origin="https://evil.example.com",  # pyright: ignore[reportArgumentType]
                ):
                    pass
            assert exc_info.value.response.status_code == 403
        finally:
            await server.close()
        origin_rejected = _find_events(store, "desktop.websocket.origin_rejected")
        assert len(origin_rejected) >= 1
        assert origin_rejected[0]["payload"]["reason"] == "foreign_origin_rejected"

    @pytest.mark.asyncio
    async def test_null_origin_rejected_when_disabled(
        self, unused_tcp_port: int
    ) -> None:
        import websockets

        server = _make_server(port=unused_tcp_port, allow_null_origin=False)
        store = _trace_store(server)
        await server.start()
        try:
            with pytest.raises(websockets.InvalidStatus) as exc_info:
                async with websockets.connect(
                    f"ws://{DEFAULT_HOST}:{unused_tcp_port}",
                    origin="null",  # pyright: ignore[reportArgumentType]
                ):
                    pass
            assert exc_info.value.response.status_code == 403
        finally:
            await server.close()
        reasons = _rejection_reasons(store)
        assert "null_origin_rejected" in reasons

    @pytest.mark.asyncio
    async def test_file_origin_always_rejected(self, unused_tcp_port: int) -> None:
        import websockets

        server = _make_server(port=unused_tcp_port)
        store = _trace_store(server)
        await server.start()
        try:
            with pytest.raises(websockets.InvalidStatus) as exc_info:
                async with websockets.connect(
                    f"ws://{DEFAULT_HOST}:{unused_tcp_port}",
                    origin="file:///tmp/evil.html",  # pyright: ignore[reportArgumentType]
                ):
                    pass
            assert exc_info.value.response.status_code == 403
        finally:
            await server.close()
        reasons = _rejection_reasons(store)
        assert "file_origin_rejected" in reasons

    @pytest.mark.asyncio
    async def test_missing_origin_accepted_when_allowed(
        self, unused_tcp_port: int
    ) -> None:
        import websockets

        server = _make_server(port=unused_tcp_port, missing_origin_allowed=True)
        store = _trace_store(server)
        await server.start()
        try:
            async with websockets.connect(
                f"ws://{DEFAULT_HOST}:{unused_tcp_port}"
            ) as ws:
                await ws.send(json.dumps({"type": "auth", "token": server.token}))
                resp = json.loads(await ws.recv())
                assert resp["type"] == "auth_ok"
        finally:
            await server.close()
        origin_rejected = _find_events(store, "desktop.websocket.origin_rejected")
        assert len(origin_rejected) == 0, "Missing origin rejected when allowed"

    @pytest.mark.asyncio
    async def test_missing_origin_rejected_when_disallowed(
        self, unused_tcp_port: int
    ) -> None:
        import websockets

        server = _make_server(port=unused_tcp_port, missing_origin_allowed=False)
        store = _trace_store(server)
        await server.start()
        try:
            with pytest.raises(websockets.InvalidStatus) as exc_info:
                async with websockets.connect(f"ws://{DEFAULT_HOST}:{unused_tcp_port}"):
                    pass
            assert exc_info.value.response.status_code == 403
        finally:
            await server.close()
        reasons = _rejection_reasons(store)
        assert "missing_origin" in reasons


class TestMessageValidation:
    @pytest.mark.asyncio
    async def test_non_json_rejected_with_trace(self, unused_tcp_port: int) -> None:
        import websockets

        server = _make_server(port=unused_tcp_port)
        store = _trace_store(server)
        await server.start()
        try:
            async with websockets.connect(
                f"ws://{DEFAULT_HOST}:{unused_tcp_port}"
            ) as ws:
                await ws.send(json.dumps({"type": "auth", "token": server.token}))
                resp = json.loads(await ws.recv())
                assert resp["type"] == "auth_ok"
                await ws.send("this is not json {{{")
                resp = json.loads(await ws.recv())
                assert resp["type"] == "error"
                assert resp["code"] == "invalid_json"
        finally:
            await server.close()
        rejected = _find_events(store, "desktop.websocket.message_rejected")
        reasons = [e["payload"].get("reason") for e in rejected]
        assert "invalid_json" in reasons

    @pytest.mark.asyncio
    async def test_json_array_rejected_with_trace(self, unused_tcp_port: int) -> None:
        import websockets

        server = _make_server(port=unused_tcp_port)
        store = _trace_store(server)
        await server.start()
        try:
            async with websockets.connect(
                f"ws://{DEFAULT_HOST}:{unused_tcp_port}"
            ) as ws:
                await ws.send(json.dumps({"type": "auth", "token": server.token}))
                resp = json.loads(await ws.recv())
                assert resp["type"] == "auth_ok"
                await ws.send(json.dumps([1, 2, 3]))
                resp = json.loads(await ws.recv())
                assert resp["type"] == "error"
                assert resp["code"] == "invalid_json"
        finally:
            await server.close()
        rejected = _find_events(store, "desktop.websocket.message_rejected")
        reasons = [e["payload"].get("reason") for e in rejected]
        assert "invalid_json" in reasons

    @pytest.mark.asyncio
    async def test_json_scalar_rejected_with_trace(self, unused_tcp_port: int) -> None:
        import websockets

        server = _make_server(port=unused_tcp_port)
        store = _trace_store(server)
        await server.start()
        try:
            async with websockets.connect(
                f"ws://{DEFAULT_HOST}:{unused_tcp_port}"
            ) as ws:
                await ws.send(json.dumps({"type": "auth", "token": server.token}))
                resp = json.loads(await ws.recv())
                assert resp["type"] == "auth_ok"
                await ws.send(json.dumps("just a string"))
                resp = json.loads(await ws.recv())
                assert resp["type"] == "error"
                assert resp["code"] == "invalid_json"
        finally:
            await server.close()
        rejected = _find_events(store, "desktop.websocket.message_rejected")
        reasons = [e["payload"].get("reason") for e in rejected]
        assert "invalid_json" in reasons

    @pytest.mark.asyncio
    async def test_missing_type_rejected_with_trace(self, unused_tcp_port: int) -> None:
        import websockets

        server = _make_server(port=unused_tcp_port)
        store = _trace_store(server)
        await server.start()
        try:
            async with websockets.connect(
                f"ws://{DEFAULT_HOST}:{unused_tcp_port}"
            ) as ws:
                await ws.send(json.dumps({"type": "auth", "token": server.token}))
                resp = json.loads(await ws.recv())
                assert resp["type"] == "auth_ok"
                await ws.send(json.dumps({"not_type": "something"}))
                resp = json.loads(await ws.recv())
                assert resp["type"] == "error"
        finally:
            await server.close()
        rejected = _find_events(store, "desktop.websocket.message_rejected")
        reasons = [e["payload"].get("reason") for e in rejected]
        assert "unknown_type" in reasons

    @pytest.mark.asyncio
    async def test_unknown_type_rejected_with_trace(self, unused_tcp_port: int) -> None:
        import websockets

        server = _make_server(port=unused_tcp_port)
        store = _trace_store(server)
        await server.start()
        try:
            async with websockets.connect(
                f"ws://{DEFAULT_HOST}:{unused_tcp_port}"
            ) as ws:
                await ws.send(json.dumps({"type": "auth", "token": server.token}))
                resp = json.loads(await ws.recv())
                assert resp["type"] == "auth_ok"
                await ws.send(json.dumps({"type": "launch_missiles"}))
                resp = json.loads(await ws.recv())
                assert resp["type"] == "error"
                assert resp["code"] == "unknown_message_type"
        finally:
            await server.close()
        rejected = _find_events(store, "desktop.websocket.message_rejected")
        reasons = [e["payload"].get("reason") for e in rejected]
        assert "unknown_type" in reasons


class TestAuthEnforcement:
    @pytest.mark.asyncio
    async def test_auth_without_token_rejected_with_trace(
        self, unused_tcp_port: int
    ) -> None:
        import websockets

        server = _make_server(port=unused_tcp_port)
        store = _trace_store(server)
        await server.start()
        try:
            async with websockets.connect(
                f"ws://{DEFAULT_HOST}:{unused_tcp_port}"
            ) as ws:
                await ws.send(json.dumps({"type": "auth"}))
                resp = json.loads(await ws.recv())
                assert resp["type"] == "auth_error"
        finally:
            await server.close()
        auth_failed = _find_events(store, "desktop.websocket.auth_failed")
        assert len(auth_failed) >= 1

    @pytest.mark.asyncio
    async def test_subscribe_before_auth_rejected_with_trace(
        self, unused_tcp_port: int
    ) -> None:
        import websockets

        server = _make_server(port=unused_tcp_port)
        store = _trace_store(server)
        await server.start()
        try:
            async with websockets.connect(
                f"ws://{DEFAULT_HOST}:{unused_tcp_port}"
            ) as ws:
                await ws.send(json.dumps({"type": "subscribe", "interval": 10}))
                resp = json.loads(await ws.recv())
                assert resp["type"] == "auth_required"
        finally:
            await server.close()
        rejected = _find_events(store, "desktop.websocket.message_rejected")
        reasons = [e["payload"].get("reason") for e in rejected]
        assert "unauthenticated" in reasons

    @pytest.mark.asyncio
    async def test_chat_before_auth_rejected_with_trace(
        self, unused_tcp_port: int
    ) -> None:
        import websockets

        server = _make_server(port=unused_tcp_port)
        store = _trace_store(server)
        await server.start()
        try:
            async with websockets.connect(
                f"ws://{DEFAULT_HOST}:{unused_tcp_port}"
            ) as ws:
                await ws.send(json.dumps({"type": "send_chat_message", "text": "hi"}))
                resp = json.loads(await ws.recv())
                assert resp["type"] == "auth_required"
        finally:
            await server.close()
        rejected = _find_events(store, "desktop.websocket.message_rejected")
        reasons = [e["payload"].get("reason") for e in rejected]
        assert "unauthenticated" in reasons


class TestAbuseControls:
    @pytest.mark.asyncio
    async def test_oversize_message_rejected_with_trace(
        self, unused_tcp_port: int
    ) -> None:
        import websockets

        server = _make_server(port=unused_tcp_port, max_message_bytes=100)
        store = _trace_store(server)
        await server.start()
        try:
            async with websockets.connect(
                f"ws://{DEFAULT_HOST}:{unused_tcp_port}"
            ) as ws:
                big = "x" * 200
                await ws.send(
                    json.dumps({"type": "auth", "token": server.token, "big": big})
                )
                resp = json.loads(await ws.recv())
                assert resp["type"] == "message_too_large"
        finally:
            await server.close()
        oversize = _find_events(store, "desktop.websocket.oversize_message")
        assert len(oversize) >= 1
        assert oversize[0]["payload"]["reason"] == "oversize_message"

    @pytest.mark.asyncio
    async def test_too_many_invalid_messages_closes_connection(
        self, unused_tcp_port: int
    ) -> None:
        import websockets

        server = _make_server(port=unused_tcp_port)
        store = _trace_store(server)
        await server.start()
        try:
            async with websockets.connect(
                f"ws://{DEFAULT_HOST}:{unused_tcp_port}"
            ) as ws:
                await ws.send(json.dumps({"type": "auth", "token": server.token}))
                resp = json.loads(await ws.recv())
                assert resp["type"] == "auth_ok"
                for _ in range(MAX_INVALID_WEBSOCKET_MESSAGES + 2):
                    await ws.send("not json {{{")
                resp = json.loads(await ws.recv())
                assert resp["type"] in ("error", "connection_closed")
                try:
                    async for _ in ws:
                        pass
                except websockets.ConnectionClosed:
                    pass
        finally:
            await server.close()
        closed = _find_events(store, "desktop.websocket.connection_closed")
        assert len(closed) >= 1
        assert closed[0]["payload"]["reason"] == "too_many_invalid_messages"


class TestCorrelationAndRedaction:
    @pytest.mark.asyncio
    async def test_rejection_trace_includes_connection_id(
        self, unused_tcp_port: int
    ) -> None:
        import websockets

        server = _make_server(port=unused_tcp_port)
        store = _trace_store(server)
        await server.start()
        try:
            async with websockets.connect(
                f"ws://{DEFAULT_HOST}:{unused_tcp_port}"
            ) as ws:
                await ws.send(json.dumps({"type": "auth", "token": server.token}))
                resp = json.loads(await ws.recv())
                assert resp["type"] == "auth_ok"
                await ws.send("not json {{{")
                resp = json.loads(await ws.recv())
                assert resp["type"] == "error"
        finally:
            await server.close()
        rejected = _find_events(store, "desktop.websocket.message_rejected")
        assert len(rejected) >= 1
        correlation = rejected[0].get("correlation", {})
        assert "connection_id" in correlation, f"No connection_id in: {correlation}"

    @pytest.mark.asyncio
    async def test_rejection_trace_excludes_token_values(
        self, unused_tcp_port: int
    ) -> None:
        import websockets

        server = _make_server(port=unused_tcp_port)
        store = _trace_store(server)
        await server.start()
        try:
            async with websockets.connect(
                f"ws://{DEFAULT_HOST}:{unused_tcp_port}"
            ) as ws:
                await ws.send(
                    json.dumps({"type": "auth", "token": "wrong-token-value"})
                )
                resp = json.loads(await ws.recv())
                assert resp["type"] == "auth_error"
        finally:
            await server.close()
        for event in store.events:
            event_str = json.dumps(event)
            assert "wrong-token-value" not in event_str, (
                f"Token value leaked in: {event.get('event_type')}"
            )
            assert server.token not in event_str, (
                f"Server token leaked in: {event.get('event_type')}"
            )

    @pytest.mark.asyncio
    async def test_handshake_id_in_correlation(self, unused_tcp_port: int) -> None:
        import websockets

        server = _make_server(port=unused_tcp_port)
        store = _trace_store(server)
        server._golden_handshake_id = "corr_test_handshake"
        await server.start()
        try:
            async with websockets.connect(
                f"ws://{DEFAULT_HOST}:{unused_tcp_port}"
            ) as ws:
                await ws.send(json.dumps({"type": "auth", "token": server.token}))
                resp = json.loads(await ws.recv())
                assert resp["type"] == "auth_ok"
        finally:
            await server.close()
        for event in store.events:
            correlation = event.get("correlation", {})
            payload = event.get("payload", {})
            if event.get("event_type") in {
                "desktop.websocket.accepted",
                "desktop.websocket.auth_ok",
                "desktop.websocket.auth_received",
            }:
                has_corr = (
                    isinstance(correlation, dict) and "handshake_id" in correlation
                ) or (
                    isinstance(payload, dict)
                    and payload.get("token_present") is not None
                )
                assert has_corr, f"No correlation in: {event.get('event_type')}"


class TestGoldenPathRegression:
    @pytest.mark.asyncio
    async def test_valid_auth_then_projection_works(self, unused_tcp_port: int) -> None:
        import websockets

        server = _make_server(port=unused_tcp_port)
        store = _trace_store(server)
        await server.start()
        try:
            async with websockets.connect(
                f"ws://{DEFAULT_HOST}:{unused_tcp_port}"
            ) as ws:
                await ws.send(json.dumps({"type": "auth", "token": server.token}))
                resp = json.loads(await ws.recv())
                assert resp["type"] == "auth_ok"

                await ws.send(json.dumps({"type": "ping"}))
                resp = json.loads(await ws.recv())
                assert resp["type"] == "pong"

                await ws.send(json.dumps({"type": "get_projection"}))
                resp = json.loads(await ws.recv())
                assert resp["type"] == "projection"
                assert "data" in resp
        finally:
            await server.close()
        auth_ok = _find_events(store, "desktop.websocket.auth_ok")
        assert len(auth_ok) >= 1
