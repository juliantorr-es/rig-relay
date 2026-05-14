"""WebSocket API for the pywebview Rig Console.

All runtime communication goes through WebSocket. Every server event
carries seq, session_id, turn_id, event_id, and created_at for
idempotent replay-safe frontend consumption.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
import json
import secrets
from typing import Any

from vibe.cli.webview_console.backend import RigConsoleBackend

_DEFAULT_HOST = "127.0.0.1"
_DEFAULT_PORT = 0
_DEFAULT_TOKEN_BYTES = 32


class ConsoleWebSocketServer:
    """Local WebSocket server for Rig Console frontend communication.

    Binds to 127.0.0.1, token-gated. Every server event carries envelope
    metadata (seq, session_id, turn_id, created_at) for idempotent replay.
    """

    def __init__(
        self,
        backend: RigConsoleBackend,
        host: str = _DEFAULT_HOST,
        port: int = _DEFAULT_PORT,
        token: str | None = None,
    ) -> None:
        self._backend = backend
        self._host = host
        self._port = port
        self._token = token or secrets.token_hex(_DEFAULT_TOKEN_BYTES)
        self._server: Any = None
        self._seq = 0
        self._session_id = backend._session_id

    @property
    def port(self) -> int:
        return self._port

    @property
    def host(self) -> str:
        return self._host

    @property
    def token(self) -> str:
        return self._token

    def _envelope(self, schema: str, **extra: Any) -> dict[str, Any]:
        """Build a server event with identity metadata."""
        self._seq += 1
        result: dict[str, Any] = {
            "schema": schema,
            "seq": self._seq,
            "session_id": self._session_id,
            "created_at": datetime.now(UTC).isoformat(),
        }
        result.update(extra)
        return result

    async def start(self) -> None:
        import websockets

        self._server = await websockets.serve(
            self._handle,
            self._host,
            self._port,
            ping_interval=30,
            ping_timeout=10,
        )
        if self._port == 0:
            self._port = self._server.sockets[0].getsockname()[1]

    async def wait_closed(self) -> None:
        if self._server:
            await self._server.wait_closed()

    async def close(self) -> None:
        if self._server:
            self._server.close()
            await self._server.wait_closed()

    async def _handle(self, websocket: Any) -> None:
        authenticated = False
        try:
            async for raw in websocket:
                msg = _parse(raw)
                if msg is None:
                    continue
                if not authenticated:
                    authenticated = await self._handle_auth(websocket, msg)
                    continue
                await self._handle_message(websocket, msg)
        except (asyncio.CancelledError, ConnectionResetError):
            pass
        except Exception:
            pass

    async def _handle_auth(self, websocket: Any, msg: dict[str, Any]) -> bool:
        if msg.get("schema") != "rig.ws.client.auth.v1":
            await _send(websocket, self._envelope("rig.ws.server.auth_error.v1"))
            return False
        if msg.get("token") != self._token:
            await _send(websocket, self._envelope("rig.ws.server.auth_error.v1"))
            return False
        await _send(websocket, self._envelope("rig.ws.server.auth_ok.v1"))
        snap = await self._backend.projection.snapshot()
        await _send(websocket, self._envelope("rig.ws.server.snapshot.v1", data=snap))
        return True

    async def _handle_message(self, websocket: Any, msg: dict[str, Any]) -> None:
        schema = msg.get("schema", "")

        if schema == "rig.ws.client.ping.v1":
            await _send(websocket, self._envelope("rig.ws.server.pong.v1"))
            return

        if schema != "rig.ws.client.intent.v1":
            return

        intent_kind = msg.get("intent_kind", "")
        intent_id = msg.get("intent_id", "unknown")
        payload = msg.get("payload", {})

        match intent_kind:
            case "start_turn":
                text = payload.get("text", "")
                if not text.strip():
                    await _send(websocket, self._envelope(
                        "rig.ws.server.ack.v1", intent_id=intent_id,
                        status="refused", reason="Empty prompt",
                    ))
                    return
                result = await self._backend.session.start_turn(text, self._backend._workspace_root)
                await _send(websocket, self._envelope(
                    "rig.ws.server.ack.v1", intent_id=intent_id,
                    status="accepted" if result["accepted"] else "refused",
                    reason=result.get("refusal_reason", ""),
                    turn_id=result.get("turn_id", ""),
                ))
                if result["accepted"]:
                    await self._stream_turn_events(websocket, result.get("turn_id", ""))

            case "cancel_turn":
                await self._backend.session.cancel()
                await _send(websocket, self._envelope(
                    "rig.ws.server.ack.v1", intent_id=intent_id,
                    status="accepted", reason="cancelling",
                ))

            case "get_snapshot":
                snap = await self._backend.projection.snapshot()
                await _send(websocket, self._envelope("rig.ws.server.snapshot.v1", data=snap))

    async def _stream_turn_events(self, websocket: Any, turn_id: str) -> None:
        try:
            async for item in self._backend.bridge.stream_events(turn_id):
                value = {
                    "item_id": item.item_id,
                    "turn_id": item.turn_id,
                    "kind": item.kind,
                    "title": item.title,
                    "body_text": item.body_text,
                    "tool_name": item.tool_name,
                    "status": item.status,
                    "error_kind": item.error_kind,
                    "event_id": item.item_id,
                }
                await _send(websocket, self._envelope(
                    "rig.ws.server.delta.v1", op="append", path="/transcript", value=value,
                    turn_id=turn_id, event_id=item.item_id,
                ))
                if item.kind == "turn_status":
                    snap = await self._backend.projection.snapshot()
                    await _send(websocket, self._envelope("rig.ws.server.snapshot.v1", data=snap))
        except Exception:
            pass


def _parse(raw: Any) -> dict[str, Any] | None:
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    try:
        return json.loads(str(raw))
    except (json.JSONDecodeError, ValueError):
        return None


async def _send(websocket: Any, data: dict[str, Any]) -> None:
    import websockets

    try:
        await websocket.send(json.dumps(data, sort_keys=True, ensure_ascii=False))
    except websockets.ConnectionClosed:
        pass


__all__ = ["ConsoleWebSocketServer"]
