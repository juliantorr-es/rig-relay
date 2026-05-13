"""Tests for the WebSocket projection stream server."""

from __future__ import annotations

import json

import pytest

from rig_relay.desktop.websocket_server import (
    DEFAULT_HOST,
    DEFAULT_PORT,
    MAX_SUBSCRIBE_INTERVAL,
    MIN_SUBSCRIBE_INTERVAL,
    ProjectionWebSocketServer,
)


class TestServerLifecycle:
    """Server starts, accepts connections, and shuts down."""

    @pytest.mark.asyncio
    async def test_server_starts_and_stops(self, unused_tcp_port: int) -> None:
        server = ProjectionWebSocketServer(port=unused_tcp_port)
        await server.start()
        await server.close()
        # No error means success

    @pytest.mark.asyncio
    async def test_server_accepts_connection(self, unused_tcp_port: int) -> None:
        import websockets

        server = ProjectionWebSocketServer(port=unused_tcp_port)
        await server.start()
        try:
            async with websockets.connect(
                f"ws://{DEFAULT_HOST}:{unused_tcp_port}"
            ) as ws:
                await ws.send(json.dumps({"type": "ping"}))
                response = json.loads(await ws.recv())
                assert response["type"] == "pong"
        finally:
            await server.close()

    @pytest.mark.asyncio
    async def test_server_rejects_invalid_message(self, unused_tcp_port: int) -> None:
        import websockets

        server = ProjectionWebSocketServer(port=unused_tcp_port)
        await server.start()
        try:
            async with websockets.connect(
                f"ws://{DEFAULT_HOST}:{unused_tcp_port}"
            ) as ws:
                await ws.send("not json")
                response = json.loads(await ws.recv())
                assert response["type"] == "error"
                assert "Invalid JSON" in response["message"]
        finally:
            await server.close()


class TestProjectionMessages:
    """Server responds correctly to projection requests."""

    @pytest.mark.asyncio
    async def test_get_projection_returns_valid_projection(
        self, unused_tcp_port: int
    ) -> None:
        import websockets

        server = ProjectionWebSocketServer(port=unused_tcp_port)
        await server.start()
        try:
            async with websockets.connect(
                f"ws://{DEFAULT_HOST}:{unused_tcp_port}"
            ) as ws:
                await ws.send(json.dumps({"type": "get_projection"}))
                response = json.loads(await ws.recv())
                assert response["type"] == "projection"
                assert "data" in response
                assert (
                    response["data"]["schema_version"]
                    == "rig.relay.desktop_projection.v1"
                )
                assert "source_status" in response["data"]
                assert "seq" in response
        finally:
            await server.close()

    @pytest.mark.asyncio
    async def test_get_available_actions(self, unused_tcp_port: int) -> None:
        import websockets

        server = ProjectionWebSocketServer(port=unused_tcp_port)
        await server.start()
        try:
            async with websockets.connect(
                f"ws://{DEFAULT_HOST}:{unused_tcp_port}"
            ) as ws:
                await ws.send(json.dumps({"type": "get_available_actions"}))
                response = json.loads(await ws.recv())
                assert response["type"] == "available_actions"
                assert isinstance(response["actions"], list)
                assert len(response["actions"]) > 0
                assert "seq" in response
        finally:
            await server.close()

    @pytest.mark.asyncio
    async def test_projection_has_seq_incrementing(self, unused_tcp_port: int) -> None:
        import websockets

        server = ProjectionWebSocketServer(port=unused_tcp_port)
        await server.start()
        try:
            async with websockets.connect(
                f"ws://{DEFAULT_HOST}:{unused_tcp_port}"
            ) as ws:
                await ws.send(json.dumps({"type": "get_projection"}))
                r1 = json.loads(await ws.recv())
                await ws.send(json.dumps({"type": "get_projection"}))
                r2 = json.loads(await ws.recv())
                assert r2["seq"] > r1["seq"]
        finally:
            await server.close()


class TestSubscribe:
    """Subscription mechanism works correctly."""

    @pytest.mark.asyncio
    async def test_subscribe_triggers_periodic_push(self, unused_tcp_port: int) -> None:
        import websockets

        server = ProjectionWebSocketServer(port=unused_tcp_port)
        await server.start()
        try:
            async with websockets.connect(
                f"ws://{DEFAULT_HOST}:{unused_tcp_port}"
            ) as ws:
                # Subscribe with short interval
                await ws.send(json.dumps({"type": "subscribe", "interval": 1}))
                # Wait for push
                response = json.loads(await ws.recv())
                assert response["type"] == "projection"
                # Unsubscribe
                await ws.send(json.dumps({"type": "unsubscribe"}))
        finally:
            await server.close()

    @pytest.mark.asyncio
    async def test_subscribe_replaces_prior_subscription(
        self, unused_tcp_port: int
    ) -> None:
        """A second subscribe replaces the prior subscription task."""
        import websockets

        server = ProjectionWebSocketServer(port=unused_tcp_port)
        await server.start()
        try:
            async with websockets.connect(
                f"ws://{DEFAULT_HOST}:{unused_tcp_port}"
            ) as ws:
                await ws.send(json.dumps({"type": "subscribe", "interval": 5}))
                # Don't wait for first push; second subscribe replaces it
                await ws.send(json.dumps({"type": "subscribe", "interval": 10}))
                await ws.send(json.dumps({"type": "unsubscribe"}))
                # No error means success
        finally:
            await server.close()


class TestPing:
    """Ping/pong works correctly."""

    @pytest.mark.asyncio
    async def test_ping_returns_pong(self, unused_tcp_port: int) -> None:
        import websockets

        server = ProjectionWebSocketServer(port=unused_tcp_port)
        await server.start()
        try:
            async with websockets.connect(
                f"ws://{DEFAULT_HOST}:{unused_tcp_port}"
            ) as ws:
                await ws.send(json.dumps({"type": "ping"}))
                response = json.loads(await ws.recv())
                assert response["type"] == "pong"
        finally:
            await server.close()


class TestUnknownMessageType:
    """Unknown message types are rejected."""

    @pytest.mark.asyncio
    async def test_unknown_type_returns_error(self, unused_tcp_port: int) -> None:
        import websockets

        server = ProjectionWebSocketServer(port=unused_tcp_port)
        await server.start()
        try:
            async with websockets.connect(
                f"ws://{DEFAULT_HOST}:{unused_tcp_port}"
            ) as ws:
                await ws.send(json.dumps({"type": "nonexistent_command"}))
                response = json.loads(await ws.recv())
                assert response["type"] == "error"
                assert "Unknown message type" in response["message"]
        finally:
            await server.close()


class TestMultipleClients:
    """Server handles multiple simultaneous connections."""

    @pytest.mark.asyncio
    async def test_two_clients_receive_separate_responses(
        self, unused_tcp_port: int
    ) -> None:
        import websockets

        server = ProjectionWebSocketServer(port=unused_tcp_port)
        await server.start()
        try:
            async with (
                websockets.connect(f"ws://{DEFAULT_HOST}:{unused_tcp_port}") as ws1,
                websockets.connect(f"ws://{DEFAULT_HOST}:{unused_tcp_port}") as ws2,
            ):
                await ws1.send(json.dumps({"type": "get_projection"}))
                await ws2.send(json.dumps({"type": "get_projection"}))
                r1 = json.loads(await ws1.recv())
                r2 = json.loads(await ws2.recv())
                assert r1["type"] == "projection"
                assert r2["type"] == "projection"
        finally:
            await server.close()


class TestConstants:
    """Constants are sensible."""

    def test_default_host_is_localhost(self) -> None:
        assert DEFAULT_HOST == "127.0.0.1"

    def test_default_port(self) -> None:
        assert DEFAULT_PORT == 9876

    def test_interval_bounds(self) -> None:
        assert MIN_SUBSCRIBE_INTERVAL <= MAX_SUBSCRIBE_INTERVAL
        assert MIN_SUBSCRIBE_INTERVAL == 5
        assert MAX_SUBSCRIBE_INTERVAL == 300
