"""Rig Relay Desktop WebSocket Projection Stream.

Content-light projection stream over WebSocket. Runs on localhost only.
Serves projection data built from disk artifacts. No mutation authority.

Protocol:
  Client → Server:
    {"type": "get_projection"}            — request full projection
    {"type": "get_available_actions"}     — request available actions list
    {"type": "subscribe", "interval": 30} — periodic projection push (N seconds)
    {"type": "unsubscribe"}               — stop periodic push
    {"type": "ping"}                      — keepalive

  Server → Client:
    {"type": "projection", "data": {...}, "seq": N}
    {"type": "available_actions", "actions": [...], "seq": N}
    {"type": "error", "message": "..."}
    {"type": "pong"}

Usage:
    from rig_relay.desktop.websocket_server import ProjectionWebSocketServer

    server = ProjectionWebSocketServer()
    await server.start()

Pattern source: Rig's runtime_websocket.py (WebSocketStreamMessage pattern)
adapted for Rig Relay's content-light projection model.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from rig_relay.desktop.projection import READ_ONLY_ACTIONS, build_projection

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 9876
MAX_SUBSCRIBE_INTERVAL = 300
MIN_SUBSCRIBE_INTERVAL = 5


class ProjectionWebSocketError(Exception):
    """Base error for projection WebSocket server."""


class ProjectionWebSocketServer:
    """Content-light projection stream over WebSocket.

    Binds to localhost only. Each connection is an independent session.
    Supports polling-based subscription for periodic updates.

    Args:
        build_root: Path to .build/rig-relay directory.
        host: Bind address (default 127.0.0.1).
        port: Bind port (default 9876).
    """

    def __init__(
        self,
        build_root: Path | None = None,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
    ) -> None:
        self._build_root = build_root
        self._host = host
        self._port = port
        self._seq = 0
        self._server: Any = None

    @property
    def port(self) -> int:
        return self._port

    @property
    def host(self) -> str:
        return self._host

    async def start(self) -> None:
        """Start the WebSocket server. Runs until cancelled."""
        import websockets

        self._server = await websockets.serve(
            self._handle_connection,
            self._host,
            self._port,
            ping_interval=30,
            ping_timeout=10,
        )

    async def wait_closed(self) -> None:
        """Wait until the server is closed."""
        if self._server:
            await self._server.wait_closed()

    async def close(self) -> None:
        """Gracefully shut down the server."""
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

    async def _handle_connection(self, websocket: Any) -> None:
        """Handle a single WebSocket connection."""
        subscribe_task: asyncio.Task[None] | None = None

        try:
            async for raw_message in websocket:
                message = _parse_message(raw_message)
                if message is None:
                    await _send_json(
                        websocket, {"type": "error", "message": "Invalid JSON message"}
                    )
                    continue

                msg_type = message.get("type")

                if msg_type == "get_projection":
                    projection = self._build_projection()
                    await _send_json(
                        websocket,
                        {
                            "type": "projection",
                            "data": projection,
                            "seq": self._next_seq(),
                        },
                    )

                elif msg_type == "get_available_actions":
                    await _send_json(
                        websocket,
                        {
                            "type": "available_actions",
                            "actions": list(READ_ONLY_ACTIONS),
                            "seq": self._next_seq(),
                        },
                    )

                elif msg_type == "subscribe":
                    if subscribe_task is not None:
                        subscribe_task.cancel()
                        subscribe_task = None

                    interval = message.get("interval", 30)
                    if not isinstance(interval, (int, float)):
                        interval = 30
                    interval = int(
                        max(
                            MIN_SUBSCRIBE_INTERVAL,
                            min(interval, MAX_SUBSCRIBE_INTERVAL),
                        )
                    )

                    subscribe_task = asyncio.create_task(
                        self._poll_and_push(websocket, interval)
                    )

                elif msg_type == "unsubscribe":
                    if subscribe_task is not None:
                        subscribe_task.cancel()
                        subscribe_task = None

                elif msg_type == "ping":
                    await _send_json(websocket, {"type": "pong"})

                else:
                    await _send_json(
                        websocket,
                        {
                            "type": "error",
                            "message": f"Unknown message type: {msg_type}",
                        },
                    )

        except (asyncio.CancelledError, ConnectionResetError, BrokenPipeError):
            pass
        finally:
            if subscribe_task is not None:
                subscribe_task.cancel()

    def _build_projection(self) -> dict[str, Any]:
        """Build a content-light projection from available artifacts."""
        return build_projection(build_root=self._build_root)

    async def _poll_and_push(self, websocket: Any, interval: int) -> None:
        """Periodically rebuild projection and push to client."""
        try:
            while True:
                await asyncio.sleep(interval)
                projection = self._build_projection()
                await _send_json(
                    websocket,
                    {"type": "projection", "data": projection, "seq": self._next_seq()},
                )
        except asyncio.CancelledError:
            pass

    def _next_seq(self) -> int:
        self._seq += 1
        return self._seq


def _parse_message(raw: Any) -> dict[str, Any] | None:
    """Parse a raw WebSocket message into a dict."""
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    try:
        return json.loads(str(raw))
    except (json.JSONDecodeError, ValueError):
        return None


async def _send_json(websocket: Any, data: dict[str, Any]) -> None:
    """Send a JSON message over WebSocket."""
    import websockets

    try:
        await websocket.send(json.dumps(data, sort_keys=True, ensure_ascii=False))
    except websockets.ConnectionClosed:
        pass


def _get_default_build_root() -> Path:
    """Resolve default build root from repo structure."""
    return Path(__file__).resolve().parent.parent.parent / ".build" / "rig-relay"


__all__ = [
    "DEFAULT_HOST",
    "DEFAULT_PORT",
    "MAX_SUBSCRIBE_INTERVAL",
    "MIN_SUBSCRIBE_INTERVAL",
    "ProjectionWebSocketError",
    "ProjectionWebSocketServer",
]
