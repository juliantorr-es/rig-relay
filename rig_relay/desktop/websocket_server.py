"""Rig Relay Desktop WebSocket Projection Stream.

Content-light projection stream over WebSocket. Localhost-only, token-gated.
No mutation authority for filesystem — chat messages are ephemeral.

Protocol:
  Client → Server:
    {"type": "auth", "token": "..."}        — authenticate (first message required)
    {"type": "get_projection"}              — request full projection
    {"type": "get_available_actions"}        — request available actions list
    {"type": "get_chat_state"}              — request current chat state
    {"type": "get_progress_events"}         — request recent progress events (up to N)
    {"type": "desktop_intent", ...}         — execute a governed intent (read-only/dry-run only)
    {"type": "send_chat_message", ...}       — send a chat message (ephemeral state only)
    {"type": "clear_chat"}                   — clear chat transcript
    {"type": "cancel_chat_response"}         — cancel active agent turn
    {"type": "subscribe", "interval": 30}   — periodic projection push (N seconds)
    {"type": "unsubscribe"}                 — stop periodic push
    {"type": "ping"}                        — keepalive

  Server → Client:
    {"type": "auth_ok"}                     — authentication succeeded
    {"type": "auth_error", "message": "..."} — authentication failed
    {"type": "auth_required"}               — first message was not auth
    {"type": "auth_timeout", "message": "..."} — auth timeout
    {"type": "projection", "data": {...}, "seq": N}
    {"type": "available_actions", "actions": [...], "seq": N}
    {"type": "chat_state", "data": {...}, "seq": N}
    {"type": "chat_state_updated", "seq": N}  — broadcast push
    {"type": "chat_message_accepted", "chat_state": {...}, "seq": N}
    {"type": "chat_cleared", "chat_state": {...}, "seq": N}
    {"type": "chat_cancelled", "result": {...}, "seq": N}
    {"type": "progress_events", "events": [...], "seq": N}
    {"type": "progress_event", "data": {...}, "seq": N}
    {"type": "desktop_intent_result", "data": {...}, "seq": N}
    {"type": "error", "code": "...", "message": "..."}
    {"type": "pong"}
    {"type": "message_too_large", "message": "..."}
    {"type": "rate_limited", "message": "..."}
    {"type": "server_full", "message": "..."}

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
from collections.abc import Callable
import hashlib
import json
from pathlib import Path
import secrets
import ssl
from typing import Any

from rig_relay.core.logger import logger
from rig_relay.desktop.bridge_protocol import (
    BridgeMessage,
    BridgeMessageDirection,
    BridgeMessageKind,
    ProtocolTracker,
)
from rig_relay.desktop.bridge_refusals import (
    build_bridge_refusal_envelope,
    enforce_intent,
)
from rig_relay.desktop.correlation import (
    DesktopCorrelation,
    hash_dict_payload,
    new_transport_session_id,
)
from rig_relay.desktop.intents import execute_desktop_intent, validate_intent_request
from rig_relay.desktop.progress_events import ProgressEventBuffer
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
    "get_progress_events",
    "desktop_intent",
    "desktop_intent_request",
    "send_chat_message",
    "clear_chat",
    "cancel_chat_response",
    "subscribe",
    "unsubscribe",
    "ping",
    "chat_state_updated",  # Push-only type
})

DEFAULT_AUTH_TIMEOUT = 5
DEFAULT_MAX_MESSAGE_BYTES = 65536
DEFAULT_RATE_LIMIT_PER_MINUTE = 60
DEFAULT_MAX_CONNECTIONS = 10
DEFAULT_WS_ORIGINS: frozenset[str] = frozenset({
    "http://127.0.0.1",
    "https://127.0.0.1",
    "http://localhost",
    "https://localhost",
})
MAX_INVALID_WEBSOCKET_MESSAGES = 3
_RATE_WINDOW_SECONDS = 60

# Per-message-type rate limit multipliers.
# Values > 1.0 mean stricter (fewer allowed), < 1.0 mean looser.
# The base rate limit is _rate_limit_per_minute. The effective limit
# for a message type is floor(base / multiplier).
_RATE_LIMIT_BY_TYPE: dict[str, float] = {
    "auth": 3.0,  # Strict: 20/min at base 60
    "send_chat_message": 4.0,  # Very strict: 15/min at base 60
    "desktop_intent": 4.0,
    "desktop_intent_request": 4.0,
    "subscribe": 6.0,  # Most strict: 10/min
    "get_projection": 0.5,  # Loose: 120/min
}

# JSON schema: required fields and types per message type.
_MESSAGE_SCHEMA: dict[str, dict[str, Any]] = {
    "auth": {"token": str},
    "send_chat_message": {"text": str},
    "clear_chat": {},
    "cancel_chat_response": {},
    "get_projection": {},
    "get_available_actions": {},
    "get_chat_state": {},
    "get_progress_events": {},
    "subscribe": {"interval": (int, float)},
    "unsubscribe": {},
    "ping": {},
}


def _validate_message_shape(msg_type: str, message: dict[str, Any]) -> list[str]:
    """Validate that required fields exist and have correct types.

    Returns a list of error strings, empty if valid.
    """
    schema = _MESSAGE_SCHEMA.get(msg_type)
    if schema is None:
        return []  # Unknown types are handled by the dispatch switch

    errors = []
    for field, expected in schema.items():
        if field not in message:
            errors.append(f"missing required field '{field}'")
        elif expected is not None and not isinstance(message[field], expected):
            type_name = (
                " | ".join(t.__name__ for t in expected)
                if isinstance(expected, tuple)
                else expected.__name__
            )
            errors.append(
                f"field '{field}' must be {type_name}, got {type(message[field]).__name__}"
            )
    return errors


class ProjectionWebSocketError(Exception):
    """Base error for projection WebSocket server."""


class ProjectionWebSocketServer:
    """Content-light projection stream over WebSocket.

    Binds to localhost by default. Token-gated. Each connection is an
    independent session. Supports polling-based subscription for periodic
    updates. Enforces auth timeout, message size limit, per-connection
    rate limiting, and connection cap. Graceful shutdown closes all
    active connections cleanly.

    Structured error codes (``type``: ``error``, ``code``: one of below):
        ``no_chat_handler``      — chat_message_handler not configured
        ``empty_message``        — text missing or empty
        ``chat_handler_failed``  — handler raised an exception
        ``projection_failed``    — projection build failed
        ``chat_unavailable``     — no chat_state_provider set
        ``unknown_message_type`` — message type not in ALLOWED_MESSAGE_TYPES
        ``invalid_json``         — message is not valid JSON

    Args:
        build_root: Path to .build/rig-relay directory.
        host: Bind address (default 127.0.0.1).
        port: Bind port (default 9876).
        token: Session token. Auto-generated if None.
        allow_non_localhost: Allow binding to non-localhost addresses.
        auth_timeout: Seconds to wait for auth before closing (default 5).
        max_message_bytes: Max incoming message size (default 64 KiB).
        rate_limit_per_minute: Max messages per minute per connection (default 60).
        max_connections: Max concurrent connections (default 10).
        allowed_origins: Allowed Origin header values (default localhost-only).
        max_connections: Maximum concurrent authenticated connections (default 10).
        allowed_origins: Set of allowed Origin header values for defense-in-depth.
        chat_state_provider: Callable returning current chat state dict.
        chat_message_handler: Callable for chat mutations (send/clear/cancel).
    """

    ERR_NO_CHAT_HANDLER = "no_chat_handler"
    ERR_EMPTY_MESSAGE = "empty_message"
    ERR_CHAT_HANDLER_FAILED = "chat_handler_failed"
    ERR_PROJECTION_FAILED = "projection_failed"
    ERR_CHAT_UNAVAILABLE = "chat_unavailable"
    ERR_UNKNOWN_TYPE = "unknown_message_type"
    ERR_INVALID_JSON = "invalid_json"

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
        max_connections: int = DEFAULT_MAX_CONNECTIONS,
        allowed_origins: frozenset[str] | None = DEFAULT_WS_ORIGINS,
        chat_state_provider: Any | None = None,
        chat_message_handler: Any | None = None,
        ssl_context: ssl.SSLContext | None = None,
        probe_callback: Callable[[str, str, dict[str, Any]], None] | None = None,
        trace_recorder: Any | None = None,
        golden_trace_id: str = "",
        golden_handshake_id: str = "",
        missing_origin_allowed: bool = True,
        allow_null_origin: bool = False,
        pywebview_loopback_mode: bool = False,
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
        self._max_connections = max_connections
        self._allowed_origins = allowed_origins
        self._chat_state_provider = chat_state_provider
        self._chat_message_handler = chat_message_handler
        self._ssl_context = ssl_context
        self._probe_callback = probe_callback
        self._trace_recorder = trace_recorder
        self._golden_trace_id = golden_trace_id
        self._golden_handshake_id = golden_handshake_id
        self._missing_origin_allowed = missing_origin_allowed
        self._allow_null_origin = allow_null_origin
        self._pywebview_loopback_mode = pywebview_loopback_mode
        self._protocol_trackers: dict[str, ProtocolTracker] = {}
        self._ws_handshake_id: dict[int, str] = {}
        self._first_projection_sent = False
        self._progress_buffer = ProgressEventBuffer()
        self._seq = 0
        self._server: Any = None
        self._connections: set[Any] = set()
        self._connection_count = 0
        self._connection_seq = 0
        self._rejected_count = 0
        self._last_connection_at: str | None = None
        self._last_rejection_reason: str | None = None
        self._active_subscriptions = 0
        self._auth_timeout_count = 0
        self._oversized_message_count = 0
        self._rate_limited_count = 0
        self._origin_rejected_count = 0
        self._invalid_message_closed_count = 0
        self._lock = asyncio.Lock()
        self._current_connection_id = ""
        self._evidence_recorder: Any | None = None
        self._per_connection_pending: dict[str, list[dict]] = {}
        self._MAX_PER_CONNECTION_QUEUE = 64
        self._NEVER_DROP_KINDS: frozenset[str] = frozenset({"error", "intent_result"})
        self._COALESCE_KINDS: frozenset[str] = frozenset({
            "lifecycle_event",
            "heartbeat",
        })

    def _emit_probe(self, step_id: str, label: str, details: dict[str, Any]) -> None:
        if self._probe_callback is not None:
            try:
                self._probe_callback(step_id, label, details)
            except Exception:
                pass

    def _new_connection_correlation(self) -> DesktopCorrelation:
        """Create a DesktopCorrelation for a new WebSocket connection."""
        return DesktopCorrelation(trace_recorder=self._trace_recorder)

    def _emit_golden_event(
        self,
        event_type: str,
        *,
        status: str | None = None,
        payload: dict[str, Any] | None = None,
        handshake_id: str = "",
        connection_id: str = "",
        duration_ms: int | None = None,
        error_message: str | None = None,
    ) -> None:
        from rig_relay.tracing.golden_path import (
            TraceAuthorityKind,
            build_correlation,
            build_golden_path_event,
        )
        from rig_relay.tracing.models import TraceStatus

        if self._trace_recorder is None:
            return
        corr_payload = build_correlation(
            handshake_id=handshake_id or self._golden_handshake_id,
            connection_id=connection_id,
        )
        event = build_golden_path_event(
            event_type=event_type,
            trace_id=self._golden_trace_id or None,
            handshake_id=handshake_id or self._golden_handshake_id,
            parent_span_id=None,
            correlation=corr_payload,
            status=TraceStatus(status) if status else None,
            authority={
                "authority_kind": TraceAuthorityKind.websocket_server.value,
                "trusted": True,
                "source_path": "rig_relay/desktop/websocket_server.py",
            },
            payload=payload,
            duration_ms=duration_ms,
            error_message=error_message,
            host=self._host,
            port=self._port,
            token_present=bool(self._token),
        )
        self._trace_recorder.store.write(event)

    @staticmethod
    def _safe_message_hash(message: dict[str, Any]) -> str:
        """Return a content-safe hash of an incoming/outgoing message."""
        return hash_dict_payload(message)

    @staticmethod
    def _safe_message_kind(message: dict[str, Any]) -> str:
        """Return the message kind for trace safety."""
        kind = message.get("type", "unknown")
        if kind in {"auth", "ping", "pong", "subscribe", "unsubscribe"}:
            return kind
        if kind in {
            "send_chat_message",
            "get_chat_state",
            "clear_chat",
            "cancel_chat_response",
            "chat_state_updated",
        }:
            return "chat"
        if kind in {
            "desktop_intent",
            "desktop_intent_request",
            "desktop_intent_result",
        }:
            return "intent"
        if kind in {"get_projection", "get_available_actions", "get_progress_events"}:
            return "projection"
        return "unknown"

    def _get_tracker(self, websocket: Any) -> ProtocolTracker | None:
        ws_id = id(websocket)
        handshake_id = self._ws_handshake_id.get(ws_id)
        if handshake_id:
            return self._protocol_trackers.get(handshake_id)
        return None

    def _wrap_envelope(
        self,
        kind: str,
        payload: dict,
        tracker: ProtocolTracker,
        requires_ack: bool = False,
        ack_for: str = "",
        idempotency_key: str = "",
        projection_sequence: int | None = None,
        safe_summary: dict | None = None,
    ) -> dict:
        msg = BridgeMessage(
            message_id=f"msg_{secrets.token_hex(12)}",
            handshake_id=tracker.handshake_id,
            direction=BridgeMessageDirection.BACKEND_TO_FRONTEND,
            kind=BridgeMessageKind(kind),
            sequence=tracker.next_outbound_seq(),
            requires_ack=requires_ack,
            ack_for=ack_for,
            idempotency_key=idempotency_key,
            projection_sequence=projection_sequence,
            payload=payload,
            safe_summary=safe_summary or {},
        )
        tracker.record_kind(kind)
        return msg.model_dump()

    @staticmethod
    def _is_v1_envelope(message: dict[str, Any]) -> bool:
        return message.get("schema_version") == "rig.relay.bridge_message.v1" and bool(
            message.get("message_id")
        )

    async def _handle_envelope_message(self, websocket: Any, envelope: dict) -> None:
        try:
            msg = BridgeMessage.model_validate(envelope)
        except Exception:
            await _send_json(
                websocket, {"type": "protocol_error", "message": "Invalid envelope"}
            )
            return

        tracker = self._protocol_trackers.get(msg.handshake_id)
        if not tracker:
            tracker = ProtocolTracker(msg.handshake_id)
            self._protocol_trackers[msg.handshake_id] = tracker
            self._ws_handshake_id[id(websocket)] = msg.handshake_id

        if tracker.is_duplicate_message(msg.message_id):
            return

        tracker.check_inbound_seq(msg.sequence)
        tracker.record_kind(msg.kind.value)

        match msg.kind:
            case BridgeMessageKind.HEARTBEAT:
                tracker.record_heartbeat()
                ack = self._wrap_envelope(
                    "heartbeat", {}, tracker, ack_for=msg.message_id
                )
                await self._send_with_flow_control(websocket, ack, tracker, "heartbeat")

            case BridgeMessageKind.INTENT_REQUEST:
                idem_key = msg.idempotency_key or msg.payload.get("intent_id", "")
                if tracker.is_duplicate_idempotency(idem_key):
                    result = self._wrap_envelope(
                        "intent_result",
                        {"status": "duplicate", "message": "Intent already processed"},
                        tracker,
                        ack_for=msg.message_id,
                    )
                    await _send_json(websocket, result)
                    return

                refusal = self._enforce_intent_bridge(msg)
                if refusal:
                    refusal_envelope = self._wrap_envelope(
                        "error", refusal, tracker, ack_for=msg.message_id
                    )
                    await _send_json(websocket, refusal_envelope)
                    return

                ack = self._wrap_envelope(
                    "intent_ack", {}, tracker, ack_for=msg.message_id
                )
                tracker.record_ack_sent(idem_key)
                await _send_json(websocket, ack)

                await self._handle_desktop_intent(websocket, msg.payload, None, tracker)

            case BridgeMessageKind.LIFECYCLE_EVENT:
                pass

            case _:
                pass

    async def _send_with_flow_control(
        self,
        websocket: Any,
        envelope: dict[str, Any],
        tracker: ProtocolTracker,
        kind: str,
    ) -> None:
        hsid = tracker.handshake_id

        if kind in self._COALESCE_KINDS and hsid in self._per_connection_pending:
            pending = self._per_connection_pending[hsid]
            for i in range(len(pending) - 1, -1, -1):
                pm = pending[i]
                if isinstance(pm, dict) and pm.get("kind") == kind:
                    pending[i] = envelope
                    tracker.record_coalesced(1)
                    tc = self._get_tracker(websocket) or tracker
                    if tc:
                        await self._emit_protocol_evidence(
                            tc, "flow_control", {"action": "coalesced", "kind": kind}
                        )
                    return

        pending_list = self._per_connection_pending.setdefault(hsid, [])
        tracker.record_queue_depth(len(pending_list) + 1)

        if len(pending_list) >= self._MAX_PER_CONNECTION_QUEUE:
            if kind in self._NEVER_DROP_KINDS:
                self._drop_lowest_priority(hsid, kind, tracker)
            else:
                priority = envelope.get("priority", "normal")
                if priority in ("low", "normal"):
                    tracker.record_dropped(1)
                    await self._emit_protocol_evidence(
                        tracker,
                        "flow_control",
                        {
                            "action": "dropped_incoming",
                            "kind": kind,
                            "priority": priority,
                        },
                    )
                    return

        pending_list.append(envelope)
        await self._flush_connection_queue(websocket, tracker)

    def _drop_lowest_priority(
        self, handshake_id: str, incoming_kind: str, tracker: ProtocolTracker
    ) -> None:
        pending = self._per_connection_pending.get(handshake_id)
        if not pending:
            return
        _priority_order = {"critical": 0, "high": 1, "normal": 2, "low": 3}
        worst_idx = -1
        worst_priority = -1
        for i, msg in enumerate(pending):
            if not isinstance(msg, dict):
                continue
            k = msg.get("kind", "")
            if k in self._NEVER_DROP_KINDS:
                continue
            p = _priority_order.get(msg.get("priority", "normal"), 2)
            if p > worst_priority:
                worst_priority = p
                worst_idx = i
        if worst_idx >= 0:
            pending.pop(worst_idx)
            tracker.record_dropped(1)

    async def _flush_connection_queue(
        self, websocket: Any, tracker: ProtocolTracker
    ) -> None:
        pending = self._per_connection_pending.get(tracker.handshake_id)
        if not pending:
            return
        while pending:
            msg = pending.pop(0)
            await _send_json(websocket, msg)
        if tracker.handshake_id in self._per_connection_pending:
            del self._per_connection_pending[tracker.handshake_id]

    async def _emit_protocol_evidence(
        self, tracker: ProtocolTracker, event_type: str, details: dict[str, Any]
    ) -> None:
        try:
            from rig_relay.desktop.bridge_protocol import create_protocol_evidence_event

            event = create_protocol_evidence_event(tracker, event_type, details)
            if self._evidence_recorder is not None:
                self._evidence_recorder.record(event_type, event)
        except ImportError:
            pass

    async def _start_heartbeat(self, websocket: Any, tracker: ProtocolTracker) -> None:
        try:
            while True:
                await asyncio.sleep(15)
                if not tracker or websocket.closed:
                    break
                tracker.record_heartbeat()
                envelope = self._wrap_envelope(
                    kind="heartbeat", payload={}, tracker=tracker
                )
                await self._send_with_flow_control(
                    websocket, envelope, tracker, "heartbeat"
                )
        except asyncio.CancelledError:
            pass
        except Exception:
            pass

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

    @property
    def max_connections(self) -> int:
        return self._max_connections

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
                "origin_rejected_count": self._origin_rejected_count,
                "invalid_message_closed_count": self._invalid_message_closed_count,
                "max_connections": self._max_connections,
            }

    async def start(self) -> None:
        """Start the WebSocket server. Runs until cancelled."""
        import websockets

        async def _inspect_origin(conn: Any, request: Any) -> Any | None:
            origin = request.headers.get("Origin", "")
            if not origin:
                if self._pywebview_loopback_mode or self._missing_origin_allowed:
                    if self._pywebview_loopback_mode:
                        self._emit_golden_event(
                            "desktop.websocket.pywebview_origin_exception_allowed",
                            payload={"origin": "(missing)"},
                        )
                    return None
                return await self._reject_origin(
                    origin="(missing)",
                    reason="missing_origin",
                    detail="Origin header missing and missing_origin_allowed is False",
                )
            if origin.lower() == "null":
                if self._pywebview_loopback_mode or self._allow_null_origin:
                    if self._pywebview_loopback_mode:
                        self._emit_golden_event(
                            "desktop.websocket.pywebview_origin_exception_allowed",
                            payload={"origin": "null"},
                        )
                    return None
                return await self._reject_origin(
                    origin=origin,
                    reason="null_origin_rejected",
                    detail="null origin not allowed",
                )
            if origin.lower().startswith("file://"):
                return await self._reject_origin(
                    origin=origin,
                    reason="file_origin_rejected",
                    detail="file:// origins are never allowed",
                )
            if self._allow_non_localhost:
                return None
            if origin not in self._allowed_origins and not any(
                loopback in origin for loopback in {"127.0.0.1", "localhost", "::1"}
            ):
                return await self._reject_origin(
                    origin=origin,
                    reason="foreign_origin_rejected",
                    detail=f"Origin '{origin}' not in allowed set",
                )
            return None

        self._server = await websockets.serve(
            self._handle_connection,
            self._host,
            self._port,
            ping_interval=30,
            ping_timeout=10,
            process_request=_inspect_origin,
            ssl=self._ssl_context,
        )

    @property
    def scheme(self) -> str:
        return "wss" if self._ssl_context is not None else "ws"

    async def wait_closed(self) -> None:
        """Wait until the server is closed."""
        if self._server:
            await self._server.wait_closed()

    async def close(self) -> None:
        """Gracefully shut down the server and all active connections."""
        async with self._lock:
            stale = set(self._connections)
        for ws in stale:
            try:
                await ws.close(1012, "Server shutting down")
            except Exception:
                pass
        async with self._lock:
            self._connections.clear()
            self._active_subscriptions = 0
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

    @staticmethod
    def _make_error(code: str, message: str) -> dict[str, Any]:
        return {"type": "error", "code": code, "message": message}

    async def _reject_origin(self, *, origin: str, reason: str, detail: str) -> Any:
        from websockets.datastructures import Headers
        from websockets.http11 import Response

        async with self._lock:
            self._origin_rejected_count += 1
        logger.warning(
            "audit.origin.rejected reason=%s detail=%s origin_present=%s",
            reason,
            detail,
            bool(origin),
        )
        self._emit_golden_event(
            "desktop.websocket.origin_rejected",
            handshake_id=self._golden_handshake_id,
            payload={
                "reason": reason,
                "origin_present": bool(origin and origin != "(missing)"),
                "detail": detail,
            },
        )
        return Response(
            status_code=403,
            reason_phrase="Forbidden",
            headers=Headers([("Content-Type", "text/plain")]),
            body=f"Origin rejected: {detail}\n".encode(),
        )

    async def _auth_timeout_guard(self, websocket: Any) -> None:
        """Background task: close connection if auth not received in time."""
        await asyncio.sleep(self._auth_timeout)
        async with self._lock:
            self._auth_timeout_count += 1
        logger.warning("audit.auth.timeout")
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

        corr = self._new_connection_correlation()
        transport_id = new_transport_session_id()
        connection_id = f"conn_{secrets.token_hex(6)}"
        self._current_connection_id = connection_id
        self._emit_golden_event(
            "desktop.websocket.accepted", payload={"connection_id": connection_id}
        )
        corr.emit_transport_event(
            "desktop.transport.connection_begin",
            transport_session_id=transport_id,
            attributes={
                "transport.session_id": transport_id,
                "transport.host": self._host,
                "transport.port": self._port,
            },
        )

        async with self._lock:
            self._connection_seq += 1

        # Enforce global connection cap
        async with self._lock:
            if len(self._connections) >= self._max_connections:
                self._rejected_count += 1
                self._last_rejection_reason = "max_connections"
                logger.warning(
                    "audit.connection.server_full max=%s", self._max_connections
                )
                await _send_json(
                    websocket,
                    {
                        "type": "server_full",
                        "message": f"Server at maximum connections ({self._max_connections})",
                    },
                )
                await websocket.close()
                return

        subscribe_task: asyncio.Task[None] | None = None
        heartbeat_task: asyncio.Task[None] | None = None
        authenticated = False
        message_count = 0
        invalid_count = 0
        rate_window_start = 0.0

        timeout_task = asyncio.create_task(self._auth_timeout_guard(websocket))

        try:
            async for raw_message in websocket:
                msg_bytes = _raw_bytes(raw_message)
                if len(msg_bytes) > self._max_message_bytes:
                    await self._reject_oversized(websocket)
                    break

                message = _parse_message(raw_message)
                if message is None:
                    invalid_count += 1
                    self._emit_golden_event(
                        "desktop.websocket.message_rejected",
                        handshake_id=self._golden_handshake_id,
                        connection_id=connection_id,
                        payload={"reason": "invalid_json"},
                    )
                    await _send_json(
                        websocket,
                        self._make_error(self.ERR_INVALID_JSON, "Invalid JSON message"),
                    )
                    if invalid_count >= MAX_INVALID_WEBSOCKET_MESSAGES:
                        await self._reject_too_many_invalid(websocket)
                        break
                    continue

                if not authenticated:
                    authenticated = await self._handle_auth(
                        websocket, message, corr, transport_id
                    )
                    if authenticated:
                        timeout_task.cancel()
                        message_count = 0
                        rate_window_start = 0.0
                        corr.emit_transport_event(
                            "desktop.transport.auth_ok",
                            transport_session_id=transport_id,
                            attributes={"transport.session_id": transport_id},
                        )
                        handshake_id = message.get("handshake_id", "")
                        tracker = self._protocol_trackers.get(handshake_id)
                        if not tracker and handshake_id:
                            tracker = ProtocolTracker(handshake_id)
                            self._protocol_trackers[handshake_id] = tracker
                            self._ws_handshake_id[id(websocket)] = handshake_id
                        if tracker:
                            heartbeat_task = asyncio.ensure_future(
                                self._start_heartbeat(websocket, tracker)
                            )
                    continue

                # Check for v1 bridge protocol envelope
                if self._is_v1_envelope(message):
                    await self._handle_envelope_message(websocket, message)
                    continue

                # Validate message shape before dispatch
                msg_type = message.get("type", "")
                shape_errors = _validate_message_shape(msg_type, message)
                if shape_errors:
                    invalid_count += 1
                    logger.warning(
                        "audit.message.invalid_shape msg_type=%s errors=%s",
                        msg_type,
                        shape_errors,
                    )
                    self._emit_golden_event(
                        "desktop.websocket.message_rejected",
                        handshake_id=self._golden_handshake_id,
                        connection_id=connection_id,
                        payload={
                            "reason": "invalid_message_shape",
                            "msg_type": msg_type,
                        },
                    )
                    await _send_json(
                        websocket,
                        self._make_error(
                            "invalid_message_shape", "; ".join(shape_errors)
                        ),
                    )
                    if invalid_count >= MAX_INVALID_WEBSOCKET_MESSAGES:
                        await self._reject_too_many_invalid(websocket)
                        break
                    continue

                if msg_type != "auth" and "token" in message:
                    invalid_count += 1
                    logger.warning(
                        "audit.message.unexpected_token_field msg_type=%s", msg_type
                    )
                    self._emit_golden_event(
                        "desktop.websocket.message_rejected",
                        handshake_id=self._golden_handshake_id,
                        connection_id=connection_id,
                        payload={
                            "reason": "unexpected_token_field",
                            "msg_type": msg_type,
                        },
                    )
                    await _send_json(
                        websocket,
                        self._make_error(
                            "unexpected_token_field",
                            "token field not allowed on non-auth messages",
                        ),
                    )
                    if invalid_count >= MAX_INVALID_WEBSOCKET_MESSAGES:
                        await self._reject_too_many_invalid(websocket)
                        break
                    continue

                import time

                now = time.monotonic()
                if now - rate_window_start > _RATE_WINDOW_SECONDS:
                    message_count = 0
                    rate_window_start = now

                # Per-type rate limit multiplier
                msg_multiplier = _RATE_LIMIT_BY_TYPE.get(msg_type, 1.0)
                effective_limit = max(
                    1, int(self._rate_limit_per_minute / msg_multiplier)
                )

                message_count += 1
                if message_count > effective_limit:
                    await self._reject_rate_limited(websocket)
                    break

                subscribe_task = await self._handle_authenticated_message(
                    websocket, message, subscribe_task
                )
                # Emit safe message receipt evidence
                corr.emit_transport_event(
                    "desktop.transport.message_received",
                    transport_session_id=transport_id,
                    attributes={
                        "transport.session_id": transport_id,
                        "message.kind": self._safe_message_kind(message),
                        "message.payload_hash": self._safe_message_hash(message),
                        "message.payload_bytes": len(json.dumps(message)),
                    },
                )

        except (asyncio.CancelledError, ConnectionResetError, BrokenPipeError):
            corr.emit_transport_event(
                "desktop.transport.error",
                transport_session_id=transport_id,
                attributes={
                    "transport.session_id": transport_id,
                    "transport.error_kind": "connection_reset",
                },
            )
        except websockets.ConnectionClosed:
            pass
        finally:
            timeout_task.cancel()
            if heartbeat_task is not None:
                heartbeat_task.cancel()
            if subscribe_task is not None:
                subscribe_task.cancel()
            ws_id = id(websocket)
            handshake_id = self._ws_handshake_id.pop(ws_id, None)
            if handshake_id:
                self._protocol_trackers.pop(handshake_id, None)
                self._per_connection_pending.pop(handshake_id, None)
            async with self._lock:
                self._connections.discard(websocket)
                if subscribe_task is not None and self._active_subscriptions > 0:
                    self._active_subscriptions -= 1
            self._emit_golden_event("desktop.websocket.closed")
            corr.emit_transport_event(
                "desktop.transport.connection_close",
                transport_session_id=transport_id,
                attributes={
                    "transport.session_id": transport_id,
                    "transport.was_clean": True,
                },
            )

    async def _reject_oversized(self, websocket: Any) -> None:
        async with self._lock:
            self._oversized_message_count += 1
        logger.warning("audit.rate.oversized max_bytes=%s", self._max_message_bytes)
        self._emit_golden_event(
            "desktop.websocket.oversize_message",
            handshake_id=self._golden_handshake_id,
            connection_id=self._current_connection_id,
            payload={
                "reason": "oversize_message",
                "message_bytes": self._max_message_bytes,
            },
        )
        await _send_json(
            websocket,
            {
                "type": "message_too_large",
                "message": f"Message exceeds {self._max_message_bytes} byte limit",
            },
        )
        await websocket.close()

    async def _reject_rate_limited(self, websocket: Any) -> None:
        async with self._lock:
            self._rate_limited_count += 1
        logger.warning("audit.rate.limited")
        self._emit_golden_event(
            "desktop.websocket.rate_limited",
            handshake_id=self._golden_handshake_id,
            connection_id=self._current_connection_id,
            payload={"reason": "rate_limited"},
        )
        await _send_json(
            websocket,
            {"type": "rate_limited", "message": "Message rate limit exceeded"},
        )
        await websocket.close()

    async def _reject_too_many_invalid(self, websocket: Any) -> None:
        async with self._lock:
            self._invalid_message_closed_count += 1
        logger.warning(
            "audit.connection.too_many_invalid max=%s", MAX_INVALID_WEBSOCKET_MESSAGES
        )
        self._emit_golden_event(
            "desktop.websocket.connection_closed",
            handshake_id=self._golden_handshake_id,
            connection_id=self._current_connection_id,
            payload={
                "reason": "too_many_invalid_messages",
                "threshold": MAX_INVALID_WEBSOCKET_MESSAGES,
            },
        )
        await _send_json(
            websocket,
            {
                "type": "connection_closed",
                "message": f"Too many invalid messages ({MAX_INVALID_WEBSOCKET_MESSAGES} limit)",
            },
        )
        await websocket.close()

    async def _handle_auth(
        self,
        websocket: Any,
        message: dict[str, Any],
        corr: DesktopCorrelation,
        transport_id: str,
    ) -> bool:
        msg_type = message.get("type")
        if msg_type == "auth":
            provided = message.get("token", "")
            handshake_id = message.get("handshake_id", "")
            self._emit_golden_event(
                "desktop.websocket.auth_received",
                handshake_id=handshake_id,
                payload={"token_present": bool(provided)},
            )
            corr.emit_transport_event(
                "desktop.transport.auth_received",
                transport_session_id=transport_id,
                attributes={
                    "transport.session_id": transport_id,
                    "handshake_id": handshake_id,
                    "token_present": bool(provided),
                },
            )
            self._emit_probe(
                "bridge:15",
                "websocket auth message received",
                {"token_present": bool(provided), "handshake_id": handshake_id},
            )
            if provided == self._token:
                async with self._lock:
                    self._connection_count += 1
                    from datetime import UTC, datetime

                    self._last_connection_at = datetime.now(UTC).isoformat()
                await _send_json(websocket, {"type": "auth_ok"})
                async with self._lock:
                    self._connections.add(websocket)
                self._emit_golden_event(
                    "desktop.websocket.auth_ok", handshake_id=handshake_id
                )
                corr.emit_transport_event(
                    "desktop.transport.handshake_succeeded",
                    transport_session_id=transport_id,
                    attributes={
                        "transport.session_id": transport_id,
                        "handshake_id": handshake_id,
                        "token_present": True,
                    },
                )
                self._emit_probe(
                    "bridge:16",
                    "websocket auth accepted",
                    {"token_present": True, "handshake_id": handshake_id},
                )
                return True
            async with self._lock:
                self._rejected_count += 1
                self._last_rejection_reason = "invalid_token"
            self._emit_golden_event(
                "desktop.websocket.auth_failed",
                handshake_id=handshake_id,
                status="error",
                error_message="invalid_token",
            )
            logger.warning("audit.auth.invalid_token")
            self._emit_probe(
                "bridge:16",
                "websocket auth refused",
                {
                    "reason": "invalid_token",
                    "token_present": bool(provided),
                    "handshake_id": handshake_id,
                },
            )
            await _send_json(
                websocket, {"type": "auth_error", "message": "Invalid token"}
            )
            return False
        async with self._lock:
            self._rejected_count += 1
            self._last_rejection_reason = "auth_required"
        msg_type = message.get("type", "")
        logger.warning("audit.auth.required attempted_type=%s", msg_type)
        self._emit_golden_event(
            "desktop.websocket.message_rejected",
            handshake_id=self._golden_handshake_id,
            connection_id=self._current_connection_id,
            payload={"reason": "unauthenticated", "msg_type": msg_type or "missing"},
        )
        await _send_json(websocket, {"type": "auth_required"})
        return False

    async def _handle_authenticated_message(
        self,
        websocket: Any,
        message: dict[str, Any],
        subscribe_task: asyncio.Task[None] | None,
    ) -> asyncio.Task[None] | None:
        msg_type = message.get("type")

        match msg_type:
            case "heartbeat":
                tracker = self._get_tracker(websocket)
                if tracker:
                    tracker.record_heartbeat()
                await _send_json(websocket, {"type": "heartbeat_ack"})

            case "get_projection":
                self._emit_golden_event("desktop.projection.build_started")
                loop = asyncio.get_running_loop()
                try:
                    projection = await loop.run_in_executor(
                        None, self._build_projection
                    )
                    self._emit_golden_event(
                        "desktop.projection.build_ok",
                        payload={
                            "schema_version": projection.get("schema_version", "")
                        },
                    )
                except Exception as exc:
                    self._emit_golden_event(
                        "desktop.projection.send_failed",
                        status="error",
                        error_message=str(exc)[:500],
                    )
                    raise
                digest_src = {
                    k: v
                    for k, v in projection.items()
                    if k not in {"generated_at", "_schema_validation_errors"}
                }
                raw = json.dumps(digest_src, sort_keys=True, ensure_ascii=False).encode(
                    "utf-8"
                )
                digest = hashlib.sha256(raw).hexdigest()
                projection["digest"] = digest
                self._emit_golden_event(
                    "desktop.projection.sent",
                    payload={
                        "schema_version": projection.get("schema_version", ""),
                        "size_bytes": len(json.dumps(projection)),
                    },
                )
                tracker = self._get_tracker(websocket)
                if tracker:
                    envelope = self._wrap_envelope(
                        "projection",
                        {"data": projection, "digest": digest},
                        tracker,
                        projection_sequence=tracker._projection_seq + 1,
                    )
                    await self._send_with_flow_control(
                        websocket, envelope, tracker, "projection"
                    )
                else:
                    await _send_json(
                        websocket,
                        {
                            "type": "projection",
                            "data": projection,
                            "seq": self._next_seq(),
                        },
                    )
                if not self._first_projection_sent:
                    self._first_projection_sent = True
                    self._emit_probe(
                        "bridge:17",
                        "first projection sent",
                        {
                            "schema_version": projection.get(
                                "schema_version", "unknown"
                            ),
                            "size_bytes": len(json.dumps(projection)),
                        },
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
                        self._make_error(
                            self.ERR_CHAT_UNAVAILABLE, "Chat state not available"
                        ),
                    )

            case "get_progress_events":
                count = message.get("count", 20)
                if not isinstance(count, int):
                    count = 20
                events = self._progress_buffer.recent(max(1, min(count, 100)))
                await _send_json(
                    websocket,
                    {
                        "type": "progress_events",
                        "events": events,
                        "seq": self._next_seq(),
                    },
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

            case "send_chat_message":
                await self._handle_chat_message(websocket, message)

            case "clear_chat":
                await self._handle_clear_chat(websocket, message)

            case "cancel_chat_response":
                await self._handle_cancel_chat(websocket, message)

            case "desktop_intent" | "desktop_intent_request":
                subscribe_task = await self._handle_desktop_intent(
                    websocket,
                    message,
                    subscribe_task,
                    tracker=self._get_tracker(websocket),
                )

            case _:
                self._emit_golden_event(
                    "desktop.websocket.message_rejected",
                    handshake_id=self._golden_handshake_id,
                    connection_id=self._current_connection_id,
                    payload={"reason": "unknown_type", "msg_type": msg_type},
                )
                await _send_json(
                    websocket,
                    self._make_error(
                        self.ERR_UNKNOWN_TYPE, f"Unknown message type: {msg_type}"
                    ),
                )

        return subscribe_task

    async def _handle_chat_message(self, websocket: Any, message: dict) -> None:
        if self._chat_message_handler is None:
            await _send_json(
                websocket,
                self._make_error(
                    self.ERR_NO_CHAT_HANDLER, "Chat message handler not configured"
                ),
            )
            return

        text = message.get("text", "")
        client_message_id = message.get("client_message_id")

        if not isinstance(text, str) or not text.strip():
            await _send_json(
                websocket,
                self._make_error(
                    self.ERR_EMPTY_MESSAGE, "Empty or invalid message text"
                ),
            )
            return

        text = text[:4000]

        try:
            result = self._chat_message_handler(
                "send_chat_message", text=text, client_message_id=client_message_id
            )
            await _send_json(
                websocket,
                {
                    "type": "chat_message_accepted",
                    "seq": self._next_seq(),
                    "chat_state": result,
                },
            )
        except Exception as e:
            await _send_json(
                websocket, self._make_error(self.ERR_CHAT_HANDLER_FAILED, str(e))
            )

    async def _handle_clear_chat(self, websocket: Any, message: dict) -> None:
        if self._chat_message_handler is None:
            await _send_json(
                websocket,
                self._make_error(
                    self.ERR_NO_CHAT_HANDLER, "Chat message handler not configured"
                ),
            )
            return
        try:
            result = self._chat_message_handler("clear_chat")
            await _send_json(
                websocket,
                {"type": "chat_cleared", "seq": self._next_seq(), "chat_state": result},
            )
        except Exception as e:
            await _send_json(
                websocket, self._make_error(self.ERR_CHAT_HANDLER_FAILED, str(e))
            )

    async def _handle_cancel_chat(self, websocket: Any, message: dict) -> None:
        if self._chat_message_handler is None:
            await _send_json(
                websocket,
                self._make_error(
                    self.ERR_NO_CHAT_HANDLER, "Chat message handler not configured"
                ),
            )
            return
        try:
            result = self._chat_message_handler("cancel_chat_response")
            await _send_json(
                websocket,
                {"type": "chat_cancelled", "seq": self._next_seq(), "result": result},
            )
        except Exception as e:
            await _send_json(
                websocket, self._make_error(self.ERR_CHAT_HANDLER_FAILED, str(e))
            )

    def _enforce_intent_bridge(self, msg: BridgeMessage) -> dict[str, Any] | None:
        from rig_relay.desktop.intents import ALLOWED_INTENTS

        payload = msg.payload or {}
        intent_kind = str(payload.get("intent_kind") or payload.get("intent_name", ""))
        schema_version = str(
            payload.get("schema_version") or payload.get("_schema_version", "")
        )
        mutation_class = str(payload.get("mutation_class", ""))
        capability_required = payload.get("capability_required")
        if isinstance(capability_required, list):
            capability_required = [str(c) for c in capability_required]
        else:
            capability_required = []

        allowed = frozenset(ALLOWED_INTENTS.keys())

        result = enforce_intent(
            intent_kind=intent_kind,
            schema_version=schema_version,
            mutation_class=mutation_class,
            capability_required=capability_required,
            trace_id=msg.trace_id,
            payload=payload,
            allowed_intents=allowed,
        )

        if result.allowed:
            return None

        return build_bridge_refusal_envelope(
            refusal_kind=result.refusal_kind,
            reason_code=result.reason_code,
            human_safe_message=result.message,
            trace_id=msg.trace_id,
            frontend_session_id=msg.frontend_session_id,
            backend_session_id=msg.backend_session_id,
            parent_message_id=msg.message_id,
            refused_intent_kind=intent_kind,
            mutation_class=mutation_class,
            capability_required=capability_required,
        )

    async def _handle_desktop_intent(
        self,
        websocket: Any,
        message: dict[str, Any],
        subscribe_task: asyncio.Task[None] | None = None,
        tracker: ProtocolTracker | None = None,
    ) -> asyncio.Task[None] | None:
        intent_msg = {k: v for k, v in message.items() if k != "type"}
        validation_errors = validate_intent_request(intent_msg)
        if validation_errors:
            result_data = {
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
            }
            if tracker:
                envelope = self._wrap_envelope(
                    "intent_result", result_data, tracker, ack_for=tracker.handshake_id
                )
                await _send_json(websocket, envelope)
            else:
                await _send_json(
                    websocket,
                    {
                        "type": "desktop_intent_result",
                        "data": result_data,
                        "seq": self._next_seq(),
                    },
                )
        else:
            # Gate sensitive intent capabilities by service state
            from rig_relay.governance.service_state import get_capability_gate

            gate = get_capability_gate()
            intent_name = intent_msg.get("intent_name", "")
            allowed, reason = gate.is_allowed(intent_name)
            if not allowed:
                gated_data = {
                    "schema_version": "rig.relay.desktop_intent_result.v1",
                    "intent_id": intent_msg.get("intent_id", "unknown"),
                    "created_at": __import__("datetime")
                    .datetime.now(__import__("datetime").timezone.utc)
                    .isoformat(),
                    "intent_name": intent_name,
                    "status": "refused",
                    "dry_run": True,
                    "result_kind": "service_gated",
                    "summary": f"Intent '{intent_name}' is gated: {reason}",
                    "output_refs": [],
                    "projection_refresh_recommended": False,
                    "authorization_required": False,
                    "warnings": [],
                    "error_code": "service_gated",
                }
                if tracker:
                    envelope = self._wrap_envelope(
                        "intent_result",
                        gated_data,
                        tracker,
                        ack_for=tracker.handshake_id,
                    )
                    await _send_json(websocket, envelope)
                else:
                    await _send_json(
                        websocket,
                        {
                            "type": "desktop_intent_result",
                            "data": gated_data,
                            "seq": self._next_seq(),
                        },
                    )
                return subscribe_task

            async def _progress_emitter(event_data: dict[str, Any]) -> None:
                await self.broadcast_progress_event(event_data)

            result = execute_desktop_intent(
                request=intent_msg,
                chat_state_provider=self._chat_state_provider,
                progress_emitter=_progress_emitter,
            )
            if tracker:
                envelope = self._wrap_envelope(
                    "intent_result", result, tracker, ack_for=tracker.handshake_id
                )
                await _send_json(websocket, envelope)
            else:
                await _send_json(
                    websocket,
                    {
                        "type": "desktop_intent_result",
                        "data": result,
                        "seq": self._next_seq(),
                    },
                )
        return subscribe_task

    async def broadcast_chat_state_updated(self) -> None:
        async with self._lock:
            if not self._connections:
                return
            message = {"type": "chat_state_updated", "seq": self._next_seq()}
            for ws in list(self._connections):
                try:
                    await _send_json(ws, message)
                except Exception:
                    self._connections.discard(ws)

    async def broadcast_progress_event(self, event_data: dict[str, Any]) -> None:
        self._progress_buffer.push_dict(event_data)
        async with self._lock:
            if not self._connections:
                return
            message = {
                "type": "progress_event",
                "data": event_data,
                "seq": self._next_seq(),
            }
            for ws in list(self._connections):
                try:
                    await _send_json(ws, message)
                except Exception:
                    self._connections.discard(ws)

    def _build_projection(self) -> dict[str, Any]:
        try:
            return build_projection(build_root=self._build_root)
        except Exception:
            return {
                "schema_version": "rig.relay.desktop_projection.v1",
                "generated_at": "",
                "app_version": "unknown",
                "source_status": {},
                "warnings": ["Projection build failed"],
                "read_only_actions": [],
            }

    async def _poll_and_push(self, websocket: Any, interval: int) -> None:
        """Periodically rebuild projection and push to client.

        Runs ``build_projection`` in a thread executor to avoid blocking
        the async event loop (projection build can take 2+ seconds due
        to subprocess calls and disk I/O). Skips the push when the
        projection content hasn't changed since the last push
        (digest-based dedup). The digest is embedded in the projection
        data so the frontend can also skip redundant re-renders.
        """
        loop = asyncio.get_running_loop()
        last_digest: str | None = None
        try:
            while True:
                await asyncio.sleep(interval)
                projection = await loop.run_in_executor(None, self._build_projection)

                # Compute digest on a copy that excludes volatile fields
                digest_src = {
                    k: v
                    for k, v in projection.items()
                    if k not in {"generated_at", "_schema_validation_errors"}
                }
                raw = json.dumps(digest_src, sort_keys=True, ensure_ascii=False).encode(
                    "utf-8"
                )
                digest = hashlib.sha256(raw).hexdigest()

                # Skip push when content hasn't changed
                if last_digest is not None and digest == last_digest:
                    continue
                last_digest = digest
                projection["digest"] = digest

                tracker = self._get_tracker(websocket)
                if tracker:
                    envelope = self._wrap_envelope(
                        "projection",
                        {"data": projection, "digest": digest},
                        tracker,
                        projection_sequence=tracker._projection_seq + 1,
                    )
                    await self._send_with_flow_control(
                        websocket, envelope, tracker, "projection"
                    )
                else:
                    await _send_json(
                        websocket,
                        {
                            "type": "projection",
                            "data": projection,
                            "seq": self._next_seq(),
                        },
                    )
        except (asyncio.CancelledError, ConnectionError, BrokenPipeError):
            pass
        finally:
            ws_id = id(websocket)
            handshake_id = self._ws_handshake_id.pop(ws_id, None)
            if handshake_id:
                self._protocol_trackers.pop(handshake_id, None)
            async with self._lock:
                if self._active_subscriptions > 0:
                    self._active_subscriptions -= 1
                self._connections.discard(websocket)

    def _next_seq(self) -> int:
        self._seq += 1
        return self._seq


def _raw_bytes(raw: Any) -> bytes:
    if isinstance(raw, bytes):
        return raw
    return str(raw).encode("utf-8")


def _parse_message(raw: Any) -> dict[str, Any] | None:
    """Parse a raw WebSocket message into a dict, or return None for invalid.

    Rejects: non-JSON, JSON arrays, JSON scalars (non-dict).
    Returns None for invalid messages.
    """
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    try:
        parsed = json.loads(str(raw))
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(parsed, dict):
        return None
    return parsed


async def _send_json(websocket: Any, data: dict[str, Any]) -> None:
    import websockets

    try:
        await websocket.send(json.dumps(data, sort_keys=True, ensure_ascii=False))
    except websockets.ConnectionClosed:
        pass


def _get_default_build_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent / ".build" / "rig-relay"


__all__ = [
    "ALLOWED_MESSAGE_TYPES",
    "DEFAULT_AUTH_TIMEOUT",
    "DEFAULT_HOST",
    "DEFAULT_MAX_CONNECTIONS",
    "DEFAULT_MAX_MESSAGE_BYTES",
    "DEFAULT_PORT",
    "DEFAULT_RATE_LIMIT_PER_MINUTE",
    "DEFAULT_TOKEN_LENGTH",
    "DEFAULT_WS_ORIGINS",
    "MAX_INVALID_WEBSOCKET_MESSAGES",
    "MAX_SUBSCRIBE_INTERVAL",
    "MIN_SUBSCRIBE_INTERVAL",
    "ProjectionWebSocketError",
    "ProjectionWebSocketServer",
]
