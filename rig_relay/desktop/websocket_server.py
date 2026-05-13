"""Rig Relay Desktop WebSocket Projection Stream.

Content-light projection stream over WebSocket. Localhost-only, token-gated.
No mutation authority.

Protocol:
  Client → Server:
    {"type": "auth", "token": "..."}        — authenticate (first message required)
    {"type": "get_projection"}              — request full projection
    {"type": "get_available_actions"}        — request available actions list
    {"type": "get_chat_state"}              — request current chat state
    {"type": "desktop_intent", ...}         — execute a governed intent (read-only/dry-run only)
    {"type": "subscribe", "interval": 30}   — periodic projection push (N seconds)
    {"type": "unsubscribe"}                 — stop periodic push
    {"type": "ping"}                        — keepalive

  Server → Client:
    {"type": "auth_ok"}                     — authentication succeeded
    {"type": "auth_error", "message": "..."} — authentication failed
    {"type": "auth_required"}               — first message was not auth
    {"type": "projection", "data": {...}, "seq": N}
    {"type": "available_actions", "actions": [...], "seq": N}
    {"type": "chat_state", "data": {...}, "seq": N}
    {"type": "desktop_intent_result", "data": {...}, "seq": N}
    {"type": "error", "message": "..."}
    {"type": "pong"}

Usage:
    from rig_relay.desktop.websocket_server import ProjectionWebSocketServer

    server = ProjectionWebSocketServer(token="my-secret-token")
    await server.start()

Pattern source: Rig's runtime_websocket.py (WebSocketStreamMessage pattern)
adapted for Rig Relay's content-light projection model with explicit
session-token security envelope.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
import secrets
from typing import Any

from rig_relay.desktop.intents import execute_desktop_intent, validate_intent_request
from rig_relay.desktop.projection import READ_ONLY_ACTIONS, build_projection

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 9876
MAX_SUBSCRIBE_INTERVAL = 300
MIN_SUBSCRIBE_INTERVAL = 5
DEFAULT_TOKEN_LENGTH = 32

ALLOWED_MESSAGE_TYPES = frozenset({
    "auth",
    "get_projection",
    "get_available_actions",
    "get_chat_state",
    "desktop_intent",
    "subscribe",
    "unsubscribe",
    "ping",
    "chat_state_updated",  # Push-only type
})

DEFAULT_AUTH_TIMEOUT = 5
DEFAULT_MAX_MESSAGE_BYTES = 65536
DEFAULT_RATE_LIMIT_PER_MINUTE = 60
_RATE_WINDOW_SECONDS = 60


class ProjectionWebSocketError(Exception):
    """Base error for projection WebSocket server."""


class ProjectionWebSocketServer:
    """Content-light projection stream over WebSocket.

    Binds to localhost by default. Token-gated. Each connection is an
    independent session. Supports polling-based subscription for periodic
    updates. Enforces auth timeout, message size limit, and per-connection
    rate limiting.

    Args:
        build_root: Path to .build/rig-relay directory.
        host: Bind address (default 127.0.0.1).
        port: Bind port (default 9876).
        token: Session token. Auto-generated if None.
        allow_non_localhost: Allow binding to non-localhost addresses.
        auth_timeout: Seconds to wait for auth before closing (default 5).
        max_message_bytes: Max incoming message size (default 64 KiB).
        rate_limit_per_minute: Max messages per minute per connection (default 60).
    """

    def __init__(
        self,
        build_root: Path | None = None,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        token: str | None = None,
        allow_non_localhost: bool = False,
        auth_timeout: int = DEFAULT_AUTH_TIMEOUT,
        max_message_bytes: int = DEFAULT_MAX_MESSAGE_BYTES,
        rate_limit_per_minute: int = DEFAULT_RATE_LIMIT_PER_MINUTE,
        chat_state_provider: Any | None = None,
    ) -> None:
        self._build_root = build_root
        self._host = host
        self._port = port
        self._token = (
            token if token is not None else secrets.token_hex(DEFAULT_TOKEN_LENGTH)
        )
        self._allow_non_localhost = allow_non_localhost
        self._auth_timeout = auth_timeout
        self._max_message_bytes = max_message_bytes
        self._rate_limit_per_minute = rate_limit_per_minute
        self._chat_state_provider = chat_state_provider
        self._seq = 0
        self._server: Any = None
        self._connections: set[Any] = set()
        self._connection_count = 0
        self._rejected_count = 0
        self._last_connection_at: str | None = None
        self._last_rejection_reason: str | None = None
        self._active_subscriptions = 0
        self._auth_timeout_count = 0
        self._oversized_message_count = 0
        self._rate_limited_count = 0
        self._lock = asyncio.Lock()

    @property
    def port(self) -> int:
        return self._port

    @property
    def host(self) -> str:
        return self._host

    @property
    def token(self) -> str:
        return self._token

    @property
    def connection_count(self) -> int:
        return self._connection_count

    @property
    def rejected_count(self) -> int:
        return self._rejected_count

    @property
    def last_connection_at(self) -> str | None:
        return self._last_connection_at

    @property
    def last_rejection_reason(self) -> str | None:
        return self._last_rejection_reason

    @property
    def active_subscriptions(self) -> int:
        return self._active_subscriptions

    async def get_connection_metadata(self) -> dict[str, Any]:
        """Return content-light connection metadata."""
        async with self._lock:
            return {
                "connection_count": self._connection_count,
                "rejected_connection_count": self._rejected_count,
                "last_connection_at": self._last_connection_at,
                "last_rejection_reason": self._last_rejection_reason,
                "active_subscriptions": self._active_subscriptions,
                "auth_timeout_count": self._auth_timeout_count,
                "oversized_message_count": self._oversized_message_count,
                "rate_limited_count": self._rate_limited_count,
            }

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

    async def _auth_timeout_guard(self, websocket: Any) -> None:
        """Background task: close connection if auth not received in time."""
        await asyncio.sleep(self._auth_timeout)
        async with self._lock:
            self._auth_timeout_count += 1
        try:
            await _send_json(
                websocket, {"type": "auth_timeout", "message": "Authentication timeout"}
            )
            await websocket.close()
        except Exception:
            pass

    async def _handle_connection(self, websocket: Any) -> None:
        """Handle a single WebSocket connection with token auth + abuse controls."""
        import websockets

        subscribe_task: asyncio.Task[None] | None = None
        authenticated = False
        message_count = 0
        rate_window_start = 0.0

        timeout_task = asyncio.create_task(self._auth_timeout_guard(websocket))

        try:
            async for raw_message in websocket:
                # Message size limit before parsing
                msg_bytes = _raw_bytes(raw_message)
                if len(msg_bytes) > self._max_message_bytes:
                    await self._reject_oversized(websocket)
                    break

                message = _parse_message(raw_message)
                if message is None:
                    await _send_json(
                        websocket, {"type": "error", "message": "Invalid JSON message"}
                    )
                    continue

                if not authenticated:
                    authenticated = await self._handle_auth(websocket, message)
                    if authenticated:
                        timeout_task.cancel()
                        message_count = 0
                        rate_window_start = 0.0
                    continue

                # Rate limit: sliding 60s window
                import time

                now = time.monotonic()
                if now - rate_window_start > _RATE_WINDOW_SECONDS:
                    message_count = 0
                    rate_window_start = now

                message_count += 1
                if message_count > self._rate_limit_per_minute:
                    await self._reject_rate_limited(websocket)
                    break

                subscribe_task = await self._handle_authenticated_message(
                    websocket, message, subscribe_task
                )

        except (asyncio.CancelledError, ConnectionResetError, BrokenPipeError):
            pass
        except websockets.ConnectionClosed:
            pass
        finally:
            timeout_task.cancel()
            if subscribe_task is not None:
                subscribe_task.cancel()
            async with self._lock:
                self._connections.discard(websocket)
                if subscribe_task is not None and self._active_subscriptions > 0:
                    self._active_subscriptions -= 1

    async def _reject_oversized(self, websocket: Any) -> None:
        """Reject an oversized message and close the connection."""
        async with self._lock:
            self._oversized_message_count += 1
        await _send_json(
            websocket,
            {
                "type": "message_too_large",
                "message": f"Message exceeds {self._max_message_bytes} byte limit",
            },
        )
        await websocket.close()

    async def _reject_rate_limited(self, websocket: Any) -> None:
        """Reject a rate-limited connection and close it."""
        async with self._lock:
            self._rate_limited_count += 1
        await _send_json(
            websocket,
            {"type": "rate_limited", "message": "Message rate limit exceeded"},
        )
        await websocket.close()

    async def _handle_auth(self, websocket: Any, message: dict[str, Any]) -> bool:
        """Handle authentication for a single message. Returns True if authenticated."""
        msg_type = message.get("type")

        if msg_type == "auth":
            provided = message.get("token", "")
            if provided == self._token:
                async with self._lock:
                    self._connection_count += 1
                    from datetime import UTC, datetime

                    self._last_connection_at = datetime.now(UTC).isoformat()
                await _send_json(websocket, {"type": "auth_ok"})
                async with self._lock:
                    self._connections.add(websocket)
                return True

            async with self._lock:
                self._rejected_count += 1
                self._last_rejection_reason = "invalid_token"
            await _send_json(
                websocket, {"type": "auth_error", "message": "Invalid token"}
            )
            return False

        async with self._lock:
            self._rejected_count += 1
            self._last_rejection_reason = "auth_required"
        await _send_json(websocket, {"type": "auth_required"})
        return False

    async def _handle_authenticated_message(  # noqa: PLR0912
        self,
        websocket: Any,
        message: dict[str, Any],
        subscribe_task: asyncio.Task[None] | None,
    ) -> asyncio.Task[None] | None:
        """Dispatch an authenticated protocol message. Returns updated subscribe_task."""
        msg_type = message.get("type")

        match msg_type:
            case "get_projection":
                projection = self._build_projection()
                await _send_json(
                    websocket,
                    {"type": "projection", "data": projection, "seq": self._next_seq()},
                )

            case "get_available_actions":
                await _send_json(
                    websocket,
                    {
                        "type": "available_actions",
                        "actions": list(READ_ONLY_ACTIONS),
                        "seq": self._next_seq(),
                    },
                )

            case "get_chat_state":
                if self._chat_state_provider:
                    chat_state = self._chat_state_provider()
                    await _send_json(
                        websocket,
                        {
                            "type": "chat_state",
                            "data": chat_state,
                            "seq": self._next_seq(),
                        },
                    )
                else:
                    await _send_json(
                        websocket,
                        {"type": "error", "message": "Chat state not available"},
                    )

            case "subscribe":
                if subscribe_task is not None:
                    subscribe_task.cancel()

                interval = message.get("interval", 30)
                if not isinstance(interval, (int, float)):
                    interval = 30
                interval = int(
                    max(MIN_SUBSCRIBE_INTERVAL, min(interval, MAX_SUBSCRIBE_INTERVAL))
                )

                async with self._lock:
                    self._active_subscriptions += 1
                subscribe_task = asyncio.create_task(
                    self._poll_and_push(websocket, interval)
                )

            case "unsubscribe":
                if subscribe_task is not None:
                    subscribe_task.cancel()
                    subscribe_task = None
                async with self._lock:
                    if self._active_subscriptions > 0:
                        self._active_subscriptions -= 1

            case "ping":
                await _send_json(websocket, {"type": "pong"})

            case "desktop_intent":
                # Strip WS envelope fields before schema validation
                intent_msg = {k: v for k, v in message.items() if k != "type"}
                validation_errors = validate_intent_request(intent_msg)
                if validation_errors:
                    await _send_json(
                        websocket,
                        {
                            "type": "desktop_intent_result",
                            "data": {
                                "schema_version": "rig.relay.desktop_intent_result.v1",
                                "intent_id": intent_msg.get("intent_id", "unknown"),
                                "created_at": __import__("datetime")
                                .datetime.now(__import__("datetime").timezone.utc)
                                .isoformat(),
                                "intent_name": intent_msg.get("intent_name", "unknown"),
                                "status": "refused",
                                "dry_run": True,
                                "result_kind": "validation_error",
                                "summary": f"Intent request validation failed: {'; '.join(validation_errors)}",
                                "output_refs": [],
                                "projection_refresh_recommended": False,
                                "authorization_required": False,
                                "warnings": [],
                                "error_code": "validation_failed",
                            },
                            "seq": self._next_seq(),
                        },
                    )
                else:
                    result = execute_desktop_intent(
                        request=intent_msg,
                        chat_state_provider=self._chat_state_provider,
                    )
                    await _send_json(
                        websocket,
                        {
                            "type": "desktop_intent_result",
                            "data": result,
                            "seq": self._next_seq(),
                        },
                    )

            case _:
                await _send_json(
                    websocket,
                    {"type": "error", "message": f"Unknown message type: {msg_type}"},
                )

        return subscribe_task

    async def broadcast_chat_state_updated(self) -> None:
        """Broadcast chat_state_updated event to all authenticated clients."""
        async with self._lock:
            if not self._connections:
                return

            message = {"type": "chat_state_updated", "seq": self._next_seq()}

            # Send to all active connections
            # We use list() to avoid mutation during iteration
            for ws in list(self._connections):
                try:
                    await _send_json(ws, message)
                except Exception:
                    self._connections.discard(ws)

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


def _raw_bytes(raw: Any) -> bytes:
    """Extract raw bytes from a WebSocket message for size checking."""
    if isinstance(raw, bytes):
        return raw
    return str(raw).encode("utf-8")


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
    "ALLOWED_MESSAGE_TYPES",
    "DEFAULT_AUTH_TIMEOUT",
    "DEFAULT_HOST",
    "DEFAULT_MAX_MESSAGE_BYTES",
    "DEFAULT_PORT",
    "DEFAULT_RATE_LIMIT_PER_MINUTE",
    "DEFAULT_TOKEN_LENGTH",
    "MAX_SUBSCRIBE_INTERVAL",
    "MIN_SUBSCRIBE_INTERVAL",
    "ProjectionWebSocketError",
    "ProjectionWebSocketServer",
]
