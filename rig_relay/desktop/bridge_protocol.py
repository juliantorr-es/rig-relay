from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
import secrets
import time
from typing import Any

from pydantic import BaseModel, Field, field_validator


class BridgeMessageDirection(StrEnum):
    FRONTEND_TO_BACKEND = "frontend_to_backend"
    BACKEND_TO_FRONTEND = "backend_to_frontend"


class BridgeMessageKind(StrEnum):
    PROJECTION = "projection"
    INTENT_REQUEST = "intent_request"
    INTENT_ACK = "intent_ack"
    INTENT_RESULT = "intent_result"
    LIFECYCLE_EVENT = "lifecycle_event"
    NOTIFICATION = "notification"
    ERROR = "error"
    HEARTBEAT = "heartbeat"
    FLOW_CONTROL = "flow_control"


class BridgeMessagePriority(StrEnum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


CRITICAL_KINDS: frozenset[str] = frozenset({"error"})
HIGH_KINDS: frozenset[str] = frozenset({
    "intent_request",
    "intent_ack",
    "intent_result",
})
LOW_KINDS: frozenset[str] = frozenset({"lifecycle_event", "notification", "heartbeat"})


def _default_priority(kind: BridgeMessageKind | str) -> BridgeMessagePriority:
    k = kind if isinstance(kind, str) else kind.value
    if k in CRITICAL_KINDS:
        return BridgeMessagePriority.CRITICAL
    if k in HIGH_KINDS:
        return BridgeMessagePriority.HIGH
    if k in LOW_KINDS:
        return BridgeMessagePriority.LOW
    return BridgeMessagePriority.NORMAL


class BridgeMessage(BaseModel):
    """Canonical bidirectional bridge protocol envelope."""

    model_config = {"extra": "forbid", "frozen": True}

    schema_version: str = "rig.relay.bridge_message.v1"
    message_id: str = Field(default_factory=lambda: f"msg_{secrets.token_hex(12)}")
    handshake_id: str = ""
    direction: BridgeMessageDirection
    kind: BridgeMessageKind
    sequence: int = Field(ge=0)
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    requires_ack: bool = False
    ack_for: str = ""
    idempotency_key: str = ""
    projection_sequence: int | None = None
    payload_schema: str = ""
    payload: dict = Field(default_factory=dict)
    safe_summary: dict = Field(default_factory=dict)
    redaction_status: str = "content_light"
    priority: BridgeMessagePriority = BridgeMessagePriority.NORMAL

    @field_validator("priority", mode="before")
    @classmethod
    def _ensure_priority(cls, v: object, info: Any) -> BridgeMessagePriority:
        if isinstance(v, BridgeMessagePriority):
            return v
        return _default_priority(info.data.get("kind", "projection"))


# ── Protocol helpers ────────────────────────────────────────────────


class ProtocolTracker:
    """Per-connection protocol state. Tracks sequence, dedup, etc."""

    def __init__(self, handshake_id: str) -> None:
        self.handshake_id = handshake_id
        self._outbound_seq: int = 0
        self._inbound_seq: int = -1
        self._seen_message_ids: set[str] = set()
        self._seen_idempotency_keys: set[str] = set()
        self._projection_seq: int = 0
        self._intent_ack_pending: dict[str, float] = {}
        self._started_at: float = time.monotonic()
        self._message_count_by_kind: dict[str, int] = {}
        self._duplicate_count: int = 0
        self._stale_projection_count: int = 0
        self._dropped_count: int = 0
        self._coalesced_count: int = 0
        self._max_queue_depth: int = 0
        self._protocol_error_count: int = 0
        self._last_heartbeat_at: float = time.monotonic()

    def next_outbound_seq(self) -> int:
        self._outbound_seq += 1
        return self._outbound_seq

    def check_inbound_seq(self, seq: int) -> bool:
        """Returns True if seq is newer than last seen. Tracks gap."""
        if seq > self._inbound_seq:
            self._inbound_seq = seq
            return True
        return False

    def is_duplicate_message(self, message_id: str) -> bool:
        """Returns True and counts duplicate if already seen."""
        if message_id in self._seen_message_ids:
            self._duplicate_count += 1
            return True
        self._seen_message_ids.add(message_id)
        return False

    def is_duplicate_idempotency(self, key: str) -> bool:
        """Returns True if idempotency_key already processed."""
        if not key:
            return False
        if key in self._seen_idempotency_keys:
            self._duplicate_count += 1
            return True
        self._seen_idempotency_keys.add(key)
        return False

    def record_ack_sent(self, intent_id: str) -> None:
        self._intent_ack_pending[intent_id] = time.monotonic()

    def record_ack_latency(self, intent_id: str) -> float | None:
        start = self._intent_ack_pending.pop(intent_id, None)
        if start is not None:
            return (time.monotonic() - start) * 1000
        return None

    def check_projection_sequence(self, seq: int) -> bool:
        """Returns True if this projection is newer than last rendered."""
        if seq > self._projection_seq:
            self._projection_seq = seq
            return True
        self._stale_projection_count += 1
        return False

    def record_kind(self, kind: str) -> None:
        self._message_count_by_kind[kind] = self._message_count_by_kind.get(kind, 0) + 1

    def record_dropped(self, count: int = 1) -> None:
        self._dropped_count += count

    def record_coalesced(self, count: int = 1) -> None:
        self._coalesced_count += count

    def record_queue_depth(self, depth: int) -> None:
        self._max_queue_depth = max(self._max_queue_depth, depth)

    def record_protocol_error(self) -> None:
        self._protocol_error_count += 1

    def record_heartbeat(self) -> None:
        self._last_heartbeat_at = time.monotonic()

    def heartbeat_age_sec(self) -> float:
        return time.monotonic() - self._last_heartbeat_at

    def snapshot(self) -> dict:
        return {
            "handshake_id": self.handshake_id,
            "outbound_seq": self._outbound_seq,
            "inbound_seq": self._inbound_seq,
            "projection_seq": self._projection_seq,
            "message_count_by_kind": dict(self._message_count_by_kind),
            "duplicate_count": self._duplicate_count,
            "stale_projection_count": self._stale_projection_count,
            "dropped_count": self._dropped_count,
            "coalesced_count": self._coalesced_count,
            "max_queue_depth": self._max_queue_depth,
            "protocol_error_count": self._protocol_error_count,
            "heartbeat_age_sec": self.heartbeat_age_sec(),
        }


# ── Evidence helpers ─────────────────────────────────────────────────


def create_protocol_evidence_event(
    tracker: ProtocolTracker, event_type: str, details: dict | None = None
) -> dict:
    return {
        "event_type": event_type,
        "handshake_id": tracker.handshake_id,
        "timestamp": datetime.now(UTC).isoformat(),
        "details": details or {},
        "snapshot": tracker.snapshot(),
    }
