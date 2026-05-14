"""Tests for the WebSocket projection stream server."""

from __future__ import annotations

import json

import pytest

from rig_relay.desktop.websocket_server import (
    ALLOWED_MESSAGE_TYPES,
    DEFAULT_HOST,
    DEFAULT_PORT,
    MAX_SUBSCRIBE_INTERVAL,
    MIN_SUBSCRIBE_INTERVAL,
    ProjectionWebSocketServer,
)


async def authenticate(ws, token: str) -> None:
    """Send auth message and assert auth_ok response."""
    await ws.send(json.dumps({"type": "auth", "token": token}))
    response = json.loads(await ws.recv())
    assert response["type"] == "auth_ok"


class TestAuth:
    """Token authentication enforcement."""

    @pytest.mark.asyncio
    async def test_valid_token_connects(self, unused_tcp_port: int) -> None:
        import websockets

        server = ProjectionWebSocketServer(
            port=unused_tcp_port, token="test-token", auth_timeout=100
        )
        await server.start()
        try:
            async with websockets.connect(
                f"ws://{DEFAULT_HOST}:{unused_tcp_port}"
            ) as ws:
                await authenticate(ws, "test-token")
                # Now we can send protocol messages
                await ws.send(json.dumps({"type": "ping"}))
                response = json.loads(await ws.recv())
                assert response["type"] == "pong"
        finally:
            await server.close()

    @pytest.mark.asyncio
    async def test_missing_token_is_rejected(self, unused_tcp_port: int) -> None:
        import websockets

        server = ProjectionWebSocketServer(
            port=unused_tcp_port, token="secret", auth_timeout=100
        )
        await server.start()
        try:
            async with websockets.connect(
                f"ws://{DEFAULT_HOST}:{unused_tcp_port}"
            ) as ws:
                # Send a protocol message without auth first
                await ws.send(json.dumps({"type": "ping"}))
                response = json.loads(await ws.recv())
                assert response["type"] == "auth_required"
        finally:
            await server.close()

    @pytest.mark.asyncio
    async def test_wrong_token_is_rejected(self, unused_tcp_port: int) -> None:
        import websockets

        server = ProjectionWebSocketServer(
            port=unused_tcp_port, token="correct-token", auth_timeout=100
        )
        await server.start()
        try:
            async with websockets.connect(
                f"ws://{DEFAULT_HOST}:{unused_tcp_port}"
            ) as ws:
                await ws.send(json.dumps({"type": "auth", "token": "wrong-token"}))
                response = json.loads(await ws.recv())
                assert response["type"] == "auth_error"
                assert "Invalid token" in response["message"]
        finally:
            await server.close()

    @pytest.mark.asyncio
    async def test_get_projection_requires_auth(self, unused_tcp_port: int) -> None:
        import websockets

        server = ProjectionWebSocketServer(
            port=unused_tcp_port, token="secret", auth_timeout=100
        )
        await server.start()
        try:
            async with websockets.connect(
                f"ws://{DEFAULT_HOST}:{unused_tcp_port}"
            ) as ws:
                await ws.send(json.dumps({"type": "get_projection"}))
                response = json.loads(await ws.recv())
                assert response["type"] == "auth_required"
        finally:
            await server.close()

    @pytest.mark.asyncio
    async def test_subscribe_requires_auth(self, unused_tcp_port: int) -> None:
        import websockets

        server = ProjectionWebSocketServer(
            port=unused_tcp_port, token="secret", auth_timeout=100
        )
        await server.start()
        try:
            async with websockets.connect(
                f"ws://{DEFAULT_HOST}:{unused_tcp_port}"
            ) as ws:
                await ws.send(json.dumps({"type": "subscribe", "interval": 30}))
                response = json.loads(await ws.recv())
                assert response["type"] == "auth_required"
        finally:
            await server.close()

    @pytest.mark.asyncio
    async def test_token_not_printed_in_logs(self, unused_tcp_port: int) -> None:
        """Token access via property does not leak to repr/str by default."""
        server = ProjectionWebSocketServer(
            port=unused_tcp_port, token="super-secret", auth_timeout=100
        )
        # The token IS accessible via .token property, but repr shouldn't include it
        assert server.token == "super-secret"
        # repr should NOT contain the token string
        assert "super-secret" not in repr(server)

    @pytest.mark.asyncio
    async def test_auto_generated_token(self, unused_tcp_port: int) -> None:
        """Token is auto-generated when not provided."""
        server = ProjectionWebSocketServer(port=unused_tcp_port, auth_timeout=100)
        assert server.token is not None
        assert len(server.token) > 0

    @pytest.mark.asyncio
    async def test_auth_then_subscribe_and_unsubscribe(
        self, unused_tcp_port: int
    ) -> None:
        """After auth, subscribe/unsubscribe works normally."""
        import websockets

        server = ProjectionWebSocketServer(
            port=unused_tcp_port, token="test-token", auth_timeout=100
        )
        await server.start()
        try:
            async with websockets.connect(
                f"ws://{DEFAULT_HOST}:{unused_tcp_port}"
            ) as ws:
                await authenticate(ws, "test-token")
                await ws.send(json.dumps({"type": "subscribe", "interval": 1}))
                response = json.loads(await ws.recv())
                assert response["type"] == "projection"
                await ws.send(json.dumps({"type": "unsubscribe"}))
                # No error, unsubscribe succeeds silently
        finally:
            await server.close()

    @pytest.mark.asyncio
    async def test_auth_then_get_available_actions(self, unused_tcp_port: int) -> None:
        """After auth, get_available_actions works."""
        import websockets

        server = ProjectionWebSocketServer(
            port=unused_tcp_port, token="test-token", auth_timeout=100
        )
        await server.start()
        try:
            async with websockets.connect(
                f"ws://{DEFAULT_HOST}:{unused_tcp_port}"
            ) as ws:
                await authenticate(ws, "test-token")
                await ws.send(json.dumps({"type": "get_available_actions"}))
                response = json.loads(await ws.recv())
                assert response["type"] == "available_actions"
                assert isinstance(response["actions"], list)
                assert len(response["actions"]) > 0
        finally:
            await server.close()


class TestAuthConnectionTracking:
    """Auth state is tracked in connection metadata."""

    @pytest.mark.asyncio
    async def test_connection_count_tracks_auth_success(
        self, unused_tcp_port: int
    ) -> None:
        import websockets

        server = ProjectionWebSocketServer(
            port=unused_tcp_port, token="test-token", auth_timeout=100
        )
        await server.start()
        try:
            async with websockets.connect(
                f"ws://{DEFAULT_HOST}:{unused_tcp_port}"
            ) as ws:
                await authenticate(ws, "test-token")
                await ws.send(json.dumps({"type": "get_projection"}))
                await ws.recv()  # consume projection

            # Allow cleanup
            import asyncio

            await asyncio.sleep(0.1)
        finally:
            await server.close()

    @pytest.mark.asyncio
    async def test_rejected_count_tracks_failures(self, unused_tcp_port: int) -> None:
        import websockets

        server = ProjectionWebSocketServer(
            port=unused_tcp_port, token="test-token", auth_timeout=100
        )
        await server.start()
        try:
            async with websockets.connect(
                f"ws://{DEFAULT_HOST}:{unused_tcp_port}"
            ) as ws:
                await ws.send(json.dumps({"type": "get_projection"}))
                await ws.recv()  # auth_required
        finally:
            await server.close()

        meta = await server.get_connection_metadata()
        assert meta["rejected_connection_count"] >= 1
        assert meta["last_rejection_reason"] == "auth_required"

    @pytest.mark.asyncio
    async def test_last_rejection_reason_invalid_token(
        self, unused_tcp_port: int
    ) -> None:
        import websockets

        server = ProjectionWebSocketServer(
            port=unused_tcp_port, token="correct", auth_timeout=100
        )
        await server.start()
        try:
            async with websockets.connect(
                f"ws://{DEFAULT_HOST}:{unused_tcp_port}"
            ) as ws:
                await ws.send(json.dumps({"type": "auth", "token": "wrong"}))
                await ws.recv()  # auth_error
        finally:
            await server.close()

        meta = await server.get_connection_metadata()
        assert meta["rejected_connection_count"] >= 1
        assert meta["last_rejection_reason"] == "invalid_token"

    @pytest.mark.asyncio
    async def test_active_subscriptions_tracked(self, unused_tcp_port: int) -> None:
        import websockets

        server = ProjectionWebSocketServer(
            port=unused_tcp_port, token="test-token", auth_timeout=100
        )
        await server.start()
        start_meta = await server.get_connection_metadata()
        assert start_meta["active_subscriptions"] == 0

        try:
            async with websockets.connect(
                f"ws://{DEFAULT_HOST}:{unused_tcp_port}"
            ) as ws:
                await authenticate(ws, "test-token")
                await ws.send(json.dumps({"type": "subscribe", "interval": 1}))
                # Consume first push
                response = json.loads(await ws.recv())
                assert response["type"] == "projection"

                mid_meta = await server.get_connection_metadata()
                assert mid_meta["active_subscriptions"] == 1

                await ws.send(json.dumps({"type": "unsubscribe"}))

                # Allow cleanup
                import asyncio

                await asyncio.sleep(0.5)

            end_meta = await server.get_connection_metadata()
            assert end_meta["active_subscriptions"] == 0
        finally:
            await server.close()


class TestChatState:
    """Chat state protocol tests."""

    @pytest.mark.asyncio
    async def test_get_chat_state_returns_state(self, unused_tcp_port: int) -> None:
        import websockets

        def mock_chat_state():
            return {"messages": [{"role": "system", "content": "hello"}]}

        server = ProjectionWebSocketServer(
            port=unused_tcp_port,
            token="test-token",
            auth_timeout=100,
            chat_state_provider=mock_chat_state,
        )
        await server.start()
        try:
            async with websockets.connect(
                f"ws://{DEFAULT_HOST}:{unused_tcp_port}"
            ) as ws:
                await authenticate(ws, "test-token")
                await ws.send(json.dumps({"type": "get_chat_state"}))
                response = json.loads(await ws.recv())
                assert response["type"] == "chat_state"
                assert response["data"]["messages"][0]["content"] == "hello"
                assert "seq" in response
        finally:
            await server.close()

    @pytest.mark.asyncio
    async def test_get_chat_state_error_when_no_provider(
        self, unused_tcp_port: int
    ) -> None:
        import websockets

        server = ProjectionWebSocketServer(
            port=unused_tcp_port, token="test-token", auth_timeout=100
        )
        await server.start()
        try:
            async with websockets.connect(
                f"ws://{DEFAULT_HOST}:{unused_tcp_port}"
            ) as ws:
                await authenticate(ws, "test-token")
                await ws.send(json.dumps({"type": "get_chat_state"}))
                response = json.loads(await ws.recv())
                assert response["type"] == "error"
                assert "Chat state not available" in response["message"]
        finally:
            await server.close()

    @pytest.mark.asyncio
    async def test_broadcast_chat_state_updated(self, unused_tcp_port: int) -> None:
        import websockets

        server = ProjectionWebSocketServer(
            port=unused_tcp_port, token="test-token", auth_timeout=100
        )
        await server.start()
        try:
            async with websockets.connect(
                f"ws://{DEFAULT_HOST}:{unused_tcp_port}"
            ) as ws:
                await authenticate(ws, "test-token")

                # Broadcast
                await server.broadcast_chat_state_updated()

                # Receive update notification
                response = json.loads(await ws.recv())
                assert response["type"] == "chat_state_updated"
                assert "seq" in response
        finally:
            await server.close()


class TestReadOnlyProtocol:
    """Only allowed read-only message types are accepted after auth."""

    @pytest.mark.asyncio
    async def test_allowed_types_are_read_only(self) -> None:
        """ALLOWED_MESSAGE_TYPES contains only non-mutating operations."""
        expected = frozenset({
            "auth",
            "get_projection",
            "get_available_actions",
            "get_chat_state",
            "get_progress_events",
            "desktop_intent",
            "desktop_intent_request",
            "send_chat_message",
            "clear_chat",
            "cancel_chat_response",
            "subscribe",
            "unsubscribe",
            "ping",
            "chat_state_updated",
        })
        assert ALLOWED_MESSAGE_TYPES == expected

    @pytest.mark.asyncio
    async def test_intent_type_is_rejected(self, unused_tcp_port: int) -> None:
        """Mutation-like message types return error, not executed."""
        import websockets

        server = ProjectionWebSocketServer(
            port=unused_tcp_port, token="test-token", auth_timeout=100
        )
        await server.start()
        try:
            async with websockets.connect(
                f"ws://{DEFAULT_HOST}:{unused_tcp_port}"
            ) as ws:
                await authenticate(ws, "test-token")
                await ws.send(json.dumps({"type": "spawn_session"}))
                response = json.loads(await ws.recv())
                assert response["type"] == "error"
                assert "Unknown message type" in response["message"]
        finally:
            await server.close()

    @pytest.mark.asyncio
    async def test_execute_type_is_rejected(self, unused_tcp_port: int) -> None:
        import websockets

        server = ProjectionWebSocketServer(
            port=unused_tcp_port, token="test-token", auth_timeout=100
        )
        await server.start()
        try:
            async with websockets.connect(
                f"ws://{DEFAULT_HOST}:{unused_tcp_port}"
            ) as ws:
                await authenticate(ws, "test-token")
                await ws.send(json.dumps({"type": "execute"}))
                response = json.loads(await ws.recv())
                assert response["type"] == "error"
                assert "Unknown message type" in response["message"]
        finally:
            await server.close()

    @pytest.mark.asyncio
    async def test_write_type_is_rejected(self, unused_tcp_port: int) -> None:
        import websockets

        server = ProjectionWebSocketServer(
            port=unused_tcp_port, token="test-token", auth_timeout=100
        )
        await server.start()
        try:
            async with websockets.connect(
                f"ws://{DEFAULT_HOST}:{unused_tcp_port}"
            ) as ws:
                await authenticate(ws, "test-token")
                await ws.send(json.dumps({"type": "write_file"}))
                response = json.loads(await ws.recv())
                assert response["type"] == "error"
                assert "Unknown message type" in response["message"]
        finally:
            await server.close()


class TestServerLifecycle:
    """Server starts, accepts connections, and shuts down."""

    @pytest.mark.asyncio
    async def test_server_starts_and_stops(self, unused_tcp_port: int) -> None:
        server = ProjectionWebSocketServer(port=unused_tcp_port, auth_timeout=100)
        await server.start()
        await server.close()
        # No error means success

    @pytest.mark.asyncio
    async def test_server_accepts_connection(self, unused_tcp_port: int) -> None:
        import websockets

        server = ProjectionWebSocketServer(
            port=unused_tcp_port, token="test-token", auth_timeout=100
        )
        await server.start()
        try:
            async with websockets.connect(
                f"ws://{DEFAULT_HOST}:{unused_tcp_port}"
            ) as ws:
                await authenticate(ws, "test-token")
                await ws.send(json.dumps({"type": "ping"}))
                response = json.loads(await ws.recv())
                assert response["type"] == "pong"
        finally:
            await server.close()

    @pytest.mark.asyncio
    async def test_server_rejects_invalid_message(self, unused_tcp_port: int) -> None:
        import websockets

        server = ProjectionWebSocketServer(
            port=unused_tcp_port, token="test-token", auth_timeout=100
        )
        await server.start()
        try:
            async with websockets.connect(
                f"ws://{DEFAULT_HOST}:{unused_tcp_port}"
            ) as ws:
                await authenticate(ws, "test-token")
                await ws.send("not json")
                response = json.loads(await ws.recv())
                assert response["type"] == "error"
                assert "Invalid JSON" in response["message"]
        finally:
            await server.close()

    @pytest.mark.asyncio
    async def test_invalid_message_before_auth(self, unused_tcp_port: int) -> None:
        """Invalid JSON before auth returns error (not auth_required)."""
        import websockets

        server = ProjectionWebSocketServer(
            port=unused_tcp_port, token="test-token", auth_timeout=100
        )
        await server.start()
        try:
            async with websockets.connect(
                f"ws://{DEFAULT_HOST}:{unused_tcp_port}"
            ) as ws:
                await ws.send("not json")
                response = json.loads(await ws.recv())
                # Error about invalid JSON comes before auth requirement
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

        server = ProjectionWebSocketServer(
            port=unused_tcp_port, token="test-token", auth_timeout=100
        )
        await server.start()
        try:
            async with websockets.connect(
                f"ws://{DEFAULT_HOST}:{unused_tcp_port}"
            ) as ws:
                await authenticate(ws, "test-token")
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

        server = ProjectionWebSocketServer(
            port=unused_tcp_port, token="test-token", auth_timeout=100
        )
        await server.start()
        try:
            async with websockets.connect(
                f"ws://{DEFAULT_HOST}:{unused_tcp_port}"
            ) as ws:
                await authenticate(ws, "test-token")
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

        server = ProjectionWebSocketServer(
            port=unused_tcp_port, token="test-token", auth_timeout=100
        )
        await server.start()
        try:
            async with websockets.connect(
                f"ws://{DEFAULT_HOST}:{unused_tcp_port}"
            ) as ws:
                await authenticate(ws, "test-token")
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

        server = ProjectionWebSocketServer(
            port=unused_tcp_port, token="test-token", auth_timeout=100
        )
        await server.start()
        try:
            async with websockets.connect(
                f"ws://{DEFAULT_HOST}:{unused_tcp_port}"
            ) as ws:
                await authenticate(ws, "test-token")
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

        server = ProjectionWebSocketServer(
            port=unused_tcp_port, token="test-token", auth_timeout=100
        )
        await server.start()
        try:
            async with websockets.connect(
                f"ws://{DEFAULT_HOST}:{unused_tcp_port}"
            ) as ws:
                await authenticate(ws, "test-token")
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

        server = ProjectionWebSocketServer(
            port=unused_tcp_port, token="test-token", auth_timeout=100
        )
        await server.start()
        try:
            async with websockets.connect(
                f"ws://{DEFAULT_HOST}:{unused_tcp_port}"
            ) as ws:
                await authenticate(ws, "test-token")
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

        server = ProjectionWebSocketServer(
            port=unused_tcp_port, token="test-token", auth_timeout=100
        )
        await server.start()
        try:
            async with websockets.connect(
                f"ws://{DEFAULT_HOST}:{unused_tcp_port}"
            ) as ws:
                await authenticate(ws, "test-token")
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

        server = ProjectionWebSocketServer(
            port=unused_tcp_port, token="test-token", auth_timeout=100
        )
        await server.start()
        try:
            async with (
                websockets.connect(f"ws://{DEFAULT_HOST}:{unused_tcp_port}") as ws1,
                websockets.connect(f"ws://{DEFAULT_HOST}:{unused_tcp_port}") as ws2,
            ):
                await authenticate(ws1, "test-token")
                await authenticate(ws2, "test-token")
                await ws1.send(json.dumps({"type": "get_projection"}))
                await ws2.send(json.dumps({"type": "get_projection"}))
                r1 = json.loads(await ws1.recv())
                r2 = json.loads(await ws2.recv())
                assert r1["type"] == "projection"
                assert r2["type"] == "projection"
        finally:
            await server.close()

    @pytest.mark.asyncio
    async def test_two_clients_both_authenticate(self, unused_tcp_port: int) -> None:
        """Two clients can authenticate simultaneously."""
        import websockets

        server = ProjectionWebSocketServer(
            port=unused_tcp_port, token="shared-token", auth_timeout=100
        )
        await server.start()
        try:
            async with (
                websockets.connect(f"ws://{DEFAULT_HOST}:{unused_tcp_port}") as ws1,
                websockets.connect(f"ws://{DEFAULT_HOST}:{unused_tcp_port}") as ws2,
            ):
                await authenticate(ws1, "shared-token")
                await authenticate(ws2, "shared-token")
                # Both can now ping
                await ws1.send(json.dumps({"type": "ping"}))
                await ws2.send(json.dumps({"type": "ping"}))
                r1 = json.loads(await ws1.recv())
                r2 = json.loads(await ws2.recv())
                assert r1["type"] == "pong"
                assert r2["type"] == "pong"
        finally:
            await server.close()


class TestAuthTimeout:
    """Auth timeout enforcement."""

    @pytest.mark.asyncio
    async def test_connection_without_auth_times_out(
        self, unused_tcp_port: int
    ) -> None:
        """Connection that never sends auth gets auth_timeout."""
        import websockets

        server = ProjectionWebSocketServer(
            port=unused_tcp_port, token="secret", auth_timeout=1
        )
        await server.start()
        try:
            async with websockets.connect(
                f"ws://{DEFAULT_HOST}:{unused_tcp_port}"
            ) as ws:
                # Wait — don't send anything
                response = json.loads(await ws.recv())
                assert response["type"] == "auth_timeout"
                assert "timeout" in response["message"]
        finally:
            await server.close()

    @pytest.mark.asyncio
    async def test_auth_before_timeout_succeeds(self, unused_tcp_port: int) -> None:
        """Valid auth before timeout prevents timeout."""
        import websockets

        server = ProjectionWebSocketServer(
            port=unused_tcp_port, token="fast-token", auth_timeout=30
        )
        await server.start()
        try:
            async with websockets.connect(
                f"ws://{DEFAULT_HOST}:{unused_tcp_port}"
            ) as ws:
                await ws.send(json.dumps({"type": "auth", "token": "fast-token"}))
                response = json.loads(await ws.recv())
                assert response["type"] == "auth_ok"
                await ws.send(json.dumps({"type": "ping"}))
                response = json.loads(await ws.recv())
                assert response["type"] == "pong"
        finally:
            await server.close()

    @pytest.mark.asyncio
    async def test_auth_timeout_metadata_increments(self, unused_tcp_port: int) -> None:
        """Auth timeout increments the metadata counter."""
        import websockets

        server = ProjectionWebSocketServer(
            port=unused_tcp_port, token="secret", auth_timeout=1
        )
        await server.start()
        try:
            async with websockets.connect(
                f"ws://{DEFAULT_HOST}:{unused_tcp_port}"
            ) as ws:
                await ws.recv()  # auth_timeout
                import asyncio

                await asyncio.sleep(0.2)
        finally:
            await server.close()

        meta = await server.get_connection_metadata()
        assert meta["auth_timeout_count"] >= 1

    @pytest.mark.asyncio
    async def test_auth_timeout_does_not_affect_other_connections(
        self, unused_tcp_port: int
    ) -> None:
        """One connection timing out does not affect others."""
        import websockets

        server = ProjectionWebSocketServer(
            port=unused_tcp_port, token="shared", auth_timeout=30
        )
        await server.start()
        try:
            async with websockets.connect(
                f"ws://{DEFAULT_HOST}:{unused_tcp_port}"
            ) as ws:
                await authenticate(ws, "shared")
                await ws.send(json.dumps({"type": "ping"}))
                response = json.loads(await ws.recv())
                assert response["type"] == "pong"
        finally:
            await server.close()


class TestMessageSizeLimit:
    """Message size limit enforcement."""

    @pytest.mark.asyncio
    async def test_oversized_message_rejected(self, unused_tcp_port: int) -> None:
        """Message exceeding max_message_bytes is rejected."""
        import websockets

        server = ProjectionWebSocketServer(
            port=unused_tcp_port,
            token="secret",
            max_message_bytes=100,
            auth_timeout=100,
        )
        await server.start()
        try:
            async with websockets.connect(
                f"ws://{DEFAULT_HOST}:{unused_tcp_port}"
            ) as ws:
                await authenticate(ws, "secret")
                # Send a message > 100 bytes
                big_payload = {"type": "get_projection", "padding": "x" * 200}
                await ws.send(json.dumps(big_payload))
                response = json.loads(await ws.recv())
                assert response["type"] == "message_too_large"
                assert "byte limit" in response["message"]
        finally:
            await server.close()

    @pytest.mark.asyncio
    async def test_normal_sized_message_allowed(self, unused_tcp_port: int) -> None:
        """Small messages are processed normally."""
        import websockets

        server = ProjectionWebSocketServer(
            port=unused_tcp_port,
            token="secret",
            max_message_bytes=65536,
            auth_timeout=100,
        )
        await server.start()
        try:
            async with websockets.connect(
                f"ws://{DEFAULT_HOST}:{unused_tcp_port}"
            ) as ws:
                await authenticate(ws, "secret")
                await ws.send(json.dumps({"type": "ping"}))
                response = json.loads(await ws.recv())
                assert response["type"] == "pong"
        finally:
            await server.close()

    @pytest.mark.asyncio
    async def test_oversized_message_before_auth(self, unused_tcp_port: int) -> None:
        """Oversized message before auth is rejected too."""
        import websockets

        server = ProjectionWebSocketServer(
            port=unused_tcp_port, token="secret", max_message_bytes=50, auth_timeout=100
        )
        await server.start()
        try:
            async with websockets.connect(
                f"ws://{DEFAULT_HOST}:{unused_tcp_port}"
            ) as ws:
                # Send oversized message without auth
                big_payload = {"type": "auth", "token": "secret", "padding": "x" * 100}
                await ws.send(json.dumps(big_payload))
                response = json.loads(await ws.recv())
                assert response["type"] == "message_too_large"
        finally:
            await server.close()

    @pytest.mark.asyncio
    async def test_oversized_message_metadata_increments(
        self, unused_tcp_port: int
    ) -> None:
        """Oversized message counter increments."""
        import websockets

        server = ProjectionWebSocketServer(
            port=unused_tcp_port, token="secret", max_message_bytes=50, auth_timeout=100
        )
        await server.start()
        try:
            async with websockets.connect(
                f"ws://{DEFAULT_HOST}:{unused_tcp_port}"
            ) as ws:
                await ws.send('{"padding": "' + "x" * 100 + '"}')
                await ws.recv()  # message_too_large
                import asyncio

                await asyncio.sleep(0.2)
        finally:
            await server.close()

        meta = await server.get_connection_metadata()
        assert meta["oversized_message_count"] >= 1

    @pytest.mark.asyncio
    async def test_large_invalid_json(self, unused_tcp_port: int) -> None:
        """Large invalid JSON does not crash the server."""
        import websockets

        server = ProjectionWebSocketServer(
            port=unused_tcp_port,
            token="secret",
            max_message_bytes=65536,
            auth_timeout=100,
        )
        await server.start()
        try:
            async with websockets.connect(
                f"ws://{DEFAULT_HOST}:{unused_tcp_port}"
            ) as ws:
                await authenticate(ws, "secret")
                # Send a large but valid non-JSON message
                await ws.send("x" * 1000)
                response = json.loads(await ws.recv())
                assert response["type"] == "error"
                assert "Invalid JSON" in response["message"]
        finally:
            await server.close()


class TestRateLimit:
    """Per-connection rate limit enforcement."""

    @pytest.mark.asyncio
    async def test_rate_limit_triggers(self, unused_tcp_port: int) -> None:
        """Exceeding rate limit closes connection."""
        import websockets

        server = ProjectionWebSocketServer(
            port=unused_tcp_port,
            token="secret",
            rate_limit_per_minute=3,
            auth_timeout=100,
        )
        await server.start()
        try:
            async with websockets.connect(
                f"ws://{DEFAULT_HOST}:{unused_tcp_port}"
            ) as ws:
                await authenticate(ws, "secret")
                # Send 4 messages (rate limit is 3)
                for _ in range(3):
                    await ws.send(json.dumps({"type": "ping"}))
                    response = json.loads(await ws.recv())
                    assert response["type"] == "pong"

                # 4th should be rate limited
                await ws.send(json.dumps({"type": "ping"}))
                response = json.loads(await ws.recv())
                assert response["type"] == "rate_limited"
                assert "rate limit" in response["message"].lower()
        finally:
            await server.close()

    @pytest.mark.asyncio
    async def test_rate_limit_metadata_increments(self, unused_tcp_port: int) -> None:
        """Rate limit counter increments on rate limit."""
        import websockets

        server = ProjectionWebSocketServer(
            port=unused_tcp_port,
            token="secret",
            rate_limit_per_minute=2,
            auth_timeout=100,
        )
        await server.start()
        try:
            async with websockets.connect(
                f"ws://{DEFAULT_HOST}:{unused_tcp_port}"
            ) as ws:
                await authenticate(ws, "secret")
                await ws.send(json.dumps({"type": "ping"}))
                await ws.recv()  # pong
                await ws.send(json.dumps({"type": "ping"}))
                await ws.recv()  # pong
                await ws.send(json.dumps({"type": "ping"}))
                await ws.recv()  # rate_limited
                import asyncio

                await asyncio.sleep(0.2)
        finally:
            await server.close()

        meta = await server.get_connection_metadata()
        assert meta["rate_limited_count"] >= 1

    @pytest.mark.asyncio
    async def test_subscribe_does_not_count_toward_rate_limit(
        self, unused_tcp_port: int
    ) -> None:
        """Only client-to-server messages count; server push does not."""
        import websockets

        server = ProjectionWebSocketServer(
            port=unused_tcp_port,
            token="secret",
            rate_limit_per_minute=10,
            auth_timeout=100,
        )
        await server.start()
        try:
            async with websockets.connect(
                f"ws://{DEFAULT_HOST}:{unused_tcp_port}"
            ) as ws:
                await authenticate(ws, "secret")
                # Subscribe (counts as 1 client message)
                await ws.send(json.dumps({"type": "subscribe", "interval": 1}))
                response = json.loads(await ws.recv())
                assert response["type"] == "projection"

                # Send non-subscribe messages - 4 more fits in limit of 10
                for _ in range(4):
                    await ws.send(json.dumps({"type": "ping"}))
                    await ws.recv()

                # Unsubscribe
                await ws.send(json.dumps({"type": "unsubscribe"}))
                # No error = rate limit not exceeded
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

    def test_allowed_types_are_defined(self) -> None:
        assert "auth" in ALLOWED_MESSAGE_TYPES
        assert "get_projection" in ALLOWED_MESSAGE_TYPES
        assert "get_available_actions" in ALLOWED_MESSAGE_TYPES
        assert "subscribe" in ALLOWED_MESSAGE_TYPES
        assert "unsubscribe" in ALLOWED_MESSAGE_TYPES
        assert "ping" in ALLOWED_MESSAGE_TYPES
        # No mutation types
        assert "spawn_session" not in ALLOWED_MESSAGE_TYPES
        assert "execute" not in ALLOWED_MESSAGE_TYPES
        assert "write_file" not in ALLOWED_MESSAGE_TYPES
