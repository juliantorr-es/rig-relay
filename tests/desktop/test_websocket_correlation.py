"""WebSocket correlation integration tests."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from rig_relay.desktop.correlation import DesktopCorrelation
from rig_relay.desktop.websocket_server import ProjectionWebSocketServer


class TestWebSocketServerCorrelation:
    def test_new_connection_correlation_creates_active_corr(self) -> None:
        recorder = MagicMock()
        recorder.event = MagicMock()

        server = ProjectionWebSocketServer(trace_recorder=recorder)
        corr = server._new_connection_correlation()
        assert corr.is_active is True

    def test_new_connection_correlation_inactive_without_recorder(self) -> None:
        server = ProjectionWebSocketServer()
        corr = server._new_connection_correlation()
        assert corr.is_active is False

    def test_safe_message_hash_is_deterministic(self) -> None:
        server = ProjectionWebSocketServer()
        msg = {"type": "ping", "seq": 1}
        assert server._safe_message_hash(msg) == server._safe_message_hash(msg)

    def test_safe_message_kind_classifies(self) -> None:
        server = ProjectionWebSocketServer()
        assert server._safe_message_kind({"type": "ping"}) == "ping"
        assert server._safe_message_kind({"type": "send_chat_message"}) == "chat"
        assert server._safe_message_kind({"type": "desktop_intent"}) == "intent"
        assert server._safe_message_kind({"type": "get_projection"}) == "projection"
        assert server._safe_message_kind({"type": "weird_unknown"}) == "unknown"

    def test_server_accepts_trace_recorder_param(self) -> None:
        recorder = MagicMock()
        server = ProjectionWebSocketServer(trace_recorder=recorder)
        assert server._trace_recorder is recorder

    def test_server_defaults_to_no_recorder(self) -> None:
        server = ProjectionWebSocketServer()
        assert server._trace_recorder is None

    def test_correlation_id_unique_per_call(self) -> None:
        c1 = ProjectionWebSocketServer._new_connection_correlation(
            ProjectionWebSocketServer()
        )
        c2 = ProjectionWebSocketServer._new_connection_correlation(
            ProjectionWebSocketServer()
        )
        assert c1.correlation_id != c2.correlation_id

    def test_auth_success_emits_handshake_trace(self) -> None:
        recorder = MagicMock()
        recorder.event = MagicMock()
        server = ProjectionWebSocketServer(token="secret", trace_recorder=recorder)

        class FakeWS:
            send = AsyncMock()
            close = AsyncMock()

        # Direct auth handler exercise.
        import asyncio

        async def _run() -> None:
            await server._handle_auth(
                FakeWS(),
                {"type": "auth", "token": "secret", "handshake_id": "corr_test"},
                DesktopCorrelation(trace_recorder=recorder),
                "ts_test",
            )

        asyncio.run(_run())
        names = [call.args[0] for call in recorder.event.call_args_list]
        assert "desktop.transport.auth_received" in names
        assert "desktop.transport.handshake_succeeded" in names
