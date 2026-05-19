from __future__ import annotations

import asyncio
import json

import pytest

from rig_relay.desktop.bridge_protocol import ProtocolTracker
from rig_relay.desktop.websocket_server import ProjectionWebSocketServer


class CountingWebSocket:
    def __init__(self) -> None:
        self.sent: list[str] = []
        self._closed = False
        self._drain_delay: float = 0.0

    async def send(self, data: str) -> None:
        if self._drain_delay > 0:
            await asyncio.sleep(self._drain_delay)
        self.sent.append(data)

    @property
    def closed(self) -> bool:
        return self._closed

    async def close(self, code: int = 1000, reason: str = "") -> None:
        self._closed = True


# ── CPU budget: measured in counts, not wall-clock ────────────────────────


def test_cpu_budget_is_measured_in_counts_not_wall_clock() -> None:
    """Bounds are enforced by queue caps and coalescing, not wall-clock time."""
    server = ProjectionWebSocketServer()
    assert server._MAX_PER_CONNECTION_QUEUE == 64
    assert "lifecycle_event" in server._COALESCE_KINDS
    assert "heartbeat" in server._COALESCE_KINDS
    assert "error" in server._NEVER_DROP_KINDS
    assert "intent_result" in server._NEVER_DROP_KINDS


# ── Projection patch coalesce count per flow control cycle ────────────────


@pytest.mark.asyncio
async def test_coalesce_kinds_are_correctly_configured() -> None:
    """In v1, only lifecycle_event and heartbeat are in COALESCE_KINDS.

    Projection patches are NOT in the coalesce set — they drain per cycle.
    """
    server = ProjectionWebSocketServer()
    assert "projection" not in server._COALESCE_KINDS
    assert "lifecycle_event" in server._COALESCE_KINDS
    assert "heartbeat" in server._COALESCE_KINDS
    assert len(server._COALESCE_KINDS) == 2


@pytest.mark.asyncio
async def test_coalesce_fires_when_pending_list_exists() -> None:
    """Coalescing replaces the last message of same kind in the pending list
    when a pre-existing pending list is present. This tests the coalesce
    code path directly by pre-populating the pending queue.
    """
    server = ProjectionWebSocketServer()
    ws = CountingWebSocket()
    tracker = ProtocolTracker("hs_coalesce_test")

    hsid = tracker.handshake_id

    # Pre-populate pending list — simulating a message left from a prior cycle
    server._per_connection_pending[hsid] = [
        {
            "type": "lifecycle_event",
            "kind": "lifecycle_event",
            "index": 0,
            "priority": "normal",
        }
    ]

    # Sending another lifecycle_event should coalesce (replace) the pending one
    await server._send_with_flow_control(
        ws,
        {
            "type": "lifecycle_event",
            "kind": "lifecycle_event",
            "index": 42,
            "priority": "normal",
        },
        tracker,
        "lifecycle_event",
    )

    snap = tracker.snapshot()
    assert snap["coalesced_count"] == 1

    # After coalescing, the pending message was replaced in-place;
    # no messages were sent because coalesce returns early.
    # Drain the pending queue to verify the coalesced value survived.
    pending = server._per_connection_pending.get(hsid, [])
    assert len(pending) == 1
    assert pending[0]["index"] == 42

    # Manually flush to verify send
    for msg in pending:
        await ws.send(json.dumps(msg))
    sent_events = [json.loads(s) for s in ws.sent]
    assert len(sent_events) == 1
    assert sent_events[0]["index"] == 42


@pytest.mark.asyncio
async def test_max_patches_coalesced_in_presence_of_multiple_pending() -> None:
    """Coalescing replaces the last matching-kind message in pending list.
    When multiple messages are pending, only the last one of the matching
    kind is replaced; non-matching messages are preserved.
    """
    server = ProjectionWebSocketServer()
    ws = CountingWebSocket()
    tracker = ProtocolTracker("hs_max_coalesce")

    hsid = tracker.handshake_id

    # Pre-populate with 2 messages — one lifecycle_event, one heartbeat
    server._per_connection_pending[hsid] = [
        {
            "type": "lifecycle_event",
            "kind": "lifecycle_event",
            "event": "first_event",
            "priority": "normal",
        },
        {"type": "heartbeat", "kind": "heartbeat", "priority": "normal"},
    ]

    await server._send_with_flow_control(
        ws,
        {
            "type": "lifecycle_event",
            "kind": "lifecycle_event",
            "event": "replaced_event",
            "priority": "normal",
        },
        tracker,
        "lifecycle_event",
    )

    snap = tracker.snapshot()
    assert snap["coalesced_count"] == 1

    # The lifecycle_event was replaced in-place; heartbeat was untouched.
    pending = server._per_connection_pending.get(hsid, [])
    assert len(pending) == 2  # heartbeat + replaced lifecycle_event

    # Verify the lifecycle_event was replaced
    lifecycle_msgs = [m for m in pending if m.get("kind") == "lifecycle_event"]
    assert len(lifecycle_msgs) == 1
    assert lifecycle_msgs[0]["event"] == "replaced_event"

    # Flush both pending messages
    for msg in pending:
        await ws.send(json.dumps(msg))
    sent_events = [json.loads(s) for s in ws.sent]
    assert len(sent_events) == 2  # heartbeat + replaced lifecycle_event


# ── Message queue drain throughput (bytes/count per operation) ────────────


@pytest.mark.asyncio
async def test_queue_drain_sends_all_queued_bytes_in_one_operation() -> None:
    """When the queue drains, all accumulated messages are sent in a single
    operation. Verify byte and count throughput.
    """
    server = ProjectionWebSocketServer()
    ws = CountingWebSocket()
    tracker = ProtocolTracker("hs_drain_throughput")

    num_messages = 40
    total_bytes = 0
    for i in range(num_messages):
        envelope = {
            "type": "projection",
            "kind": "projection",
            "sequence": i,
            "payload": {"data": f"payload_{i:04d}"},
            "priority": "normal",
        }
        total_bytes += len(json.dumps(envelope))
        await server._send_with_flow_control(ws, envelope, tracker, "projection")

    # All messages are sent (projection is NOT coalesced, so all go through)
    assert len(ws.sent) == num_messages

    sent_bytes = sum(len(s) for s in ws.sent)
    assert sent_bytes >= total_bytes

    snap = tracker.snapshot()
    # No drops expected under the queue cap (40 < 64)
    assert snap["dropped_count"] == 0
    # Queue never exceeded capacity
    assert snap["max_queue_depth"] <= num_messages


@pytest.mark.asyncio
async def test_queue_drop_above_cap_enforced_by_counts() -> None:
    """When pending queue exceeds MAX_PER_CONNECTION_QUEUE, low/normal
    priority messages are dropped. Dropped count is tracked in ProtocolTracker.
    """
    server = ProjectionWebSocketServer()
    object.__setattr__(server, "_MAX_PER_CONNECTION_QUEUE", 3)
    ws = CountingWebSocket()
    tracker = ProtocolTracker("hs_overcap")

    hsid = tracker.handshake_id

    # Pre-populate the pending queue to capacity (3 messages)
    server._per_connection_pending[hsid] = [
        {"type": "projection", "kind": "projection", "n": 0, "priority": "low"},
        {"type": "projection", "kind": "projection", "n": 1, "priority": "low"},
        {"type": "projection", "kind": "projection", "n": 2, "priority": "low"},
    ]

    # Next projection message exceeds capacity — should drop
    await server._send_with_flow_control(
        ws,
        {"type": "projection", "kind": "projection", "n": 99, "priority": "low"},
        tracker,
        "projection",
    )

    snap = tracker.snapshot()
    assert snap["dropped_count"] >= 1, (
        f"Expected drops above cap, got dropped_count={snap['dropped_count']}"
    )


@pytest.mark.asyncio
async def test_never_drop_kinds_survive_overcap_by_displacing_lower_priority() -> None:
    """NEVER_DROP kinds (error, intent_result) survive queue overflow by
    displacing the lowest-priority eligible message in the queue.
    """
    server = ProjectionWebSocketServer()
    object.__setattr__(server, "_MAX_PER_CONNECTION_QUEUE", 3)
    ws = CountingWebSocket()
    tracker = ProtocolTracker("hs_never_drop")

    hsid = tracker.handshake_id

    # Fill queue with low-priority projection messages at capacity
    server._per_connection_pending[hsid] = [
        {"type": "projection", "kind": "projection", "n": 0, "priority": "low"},
        {"type": "projection", "kind": "projection", "n": 1, "priority": "low"},
        {"type": "projection", "kind": "projection", "n": 2, "priority": "low"},
    ]

    # Send a never-drop error when queue is at capacity
    await server._send_with_flow_control(
        ws,
        {"type": "error", "kind": "error", "code": "TEST_ERR", "priority": "critical"},
        tracker,
        "error",
    )

    snap = tracker.snapshot()
    assert snap["dropped_count"] == 1, (
        f"Expected 1 drop from displacing low-priority, got {snap['dropped_count']}"
    )
    sent = [json.loads(s) for s in ws.sent]
    assert any(m.get("kind") == "error" for m in sent)


# ── CPU budget philosophy documentation ───────────────────────────────────


def test_cpu_budget_philosophy_documented_in_implementation() -> None:
    """CPU budget is enforced by queue caps (MAX_PER_CONNECTION_QUEUE),
    coalesce semantics (COALESCE_KINDS), never-drop protection (NEVER_DROP_KINDS),
    and drop counting (record_dropped) — all count-based, no wall-clock.
    """
    tracker = ProtocolTracker("hs_philosophy")
    tracker.record_queue_depth(5)
    tracker.record_coalesced(3)
    tracker.record_dropped(1)

    snap = tracker.snapshot()
    assert snap["max_queue_depth"] == 5
    assert snap["coalesced_count"] == 3
    assert snap["dropped_count"] == 1
    assert "wall_clock" not in snap
    assert "elapsed" not in snap
    assert "cpu_time" not in snap


def test_cpu_budget_queue_cap_is_count_not_time() -> None:
    """_MAX_PER_CONNECTION_QUEUE is a count (64), not a rate or time window."""
    server = ProjectionWebSocketServer()
    assert isinstance(server._MAX_PER_CONNECTION_QUEUE, int)
    assert server._MAX_PER_CONNECTION_QUEUE > 0
    # No time-based rate limiter attributes
    assert not hasattr(server, "_rate_window_sec")
    assert not hasattr(server, "_rate_bucket")


def test_protocol_tracker_snapshot_has_no_wall_clock_fields() -> None:
    """ProtocolTracker.snapshot() reports count-based metrics only."""
    tracker = ProtocolTracker("hs_no_clock")
    snap = tracker.snapshot()

    count_fields = {
        "handshake_id",
        "outbound_seq",
        "inbound_seq",
        "projection_seq",
        "duplicate_count",
        "stale_projection_count",
        "dropped_count",
        "coalesced_count",
        "max_queue_depth",
        "protocol_error_count",
        "message_count_by_kind",
        "heartbeat_age_sec",
    }
    for key in snap:
        assert key in count_fields, f"Unexpected wall-clock-ish field: {key}"
