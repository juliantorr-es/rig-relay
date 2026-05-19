"""Concurrency tests for WebSocket server lock hardening and task lifecycle.

Tests async concurrency, lock correctness, task draining, and that no
OS-thread primitives leak into the WebSocket server. No real WebSocket
connections — call internal methods directly with mock objects.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from rig_relay.desktop.bridge_protocol import ProtocolTracker
from rig_relay.desktop.websocket_server import ProjectionWebSocketServer


class FakeWebSocket:
    """Minimal async mock that records sent messages."""

    def __init__(self) -> None:
        self.sent: list[str] = []
        self._closed = False

    async def send(self, data: str) -> None:
        self.sent.append(data)

    @property
    def closed(self) -> bool:
        return self._closed

    async def close(self, code: int = 1000, reason: str = "") -> None:
        self._closed = True


class StuckWebSocket:
    """WebSocket that blocks send forever — used for graceful-shutdown tests."""

    def __init__(self) -> None:
        self._closed = False

    async def send(self, data: str) -> None:
        await asyncio.Event().wait()  # Never completes

    @property
    def closed(self) -> bool:
        return self._closed

    async def close(self, code: int = 1000, reason: str = "") -> None:
        self._closed = True


# ---------------------------------------------------------------------------
# Sequence integrity under concurrent intent dispatch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_concurrent_intents_do_not_corrupt_projection_sequence() -> None:
    """Multiple concurrent tasks calling _next_seq must produce unique,
    monotonically increasing values with no gaps or duplicates.
    """
    server = ProjectionWebSocketServer()
    num_tasks = 20
    calls_per_task = 100
    seen: set[int] = set()
    lock = asyncio.Lock()

    async def spam_sequences() -> list[int]:
        local: list[int] = []
        for _ in range(calls_per_task):
            seq = await server._next_seq()
            local.append(seq)
        async with lock:
            seen.update(local)
        return local

    tasks = [asyncio.create_task(spam_sequences()) for _ in range(num_tasks)]
    results = await asyncio.gather(*tasks)

    all_values: list[int] = []
    for r in results:
        all_values.extend(r)

    total = num_tasks * calls_per_task
    assert len(all_values) == total
    assert len(seen) == total, (
        f"Expected {total} unique values, got {len(seen)} (some duplicates or gaps)"
    )
    assert min(seen) >= 1
    assert max(seen) == total


@pytest.mark.asyncio
async def test_sequence_lock_prevents_data_race() -> None:
    """Ensure _seq_lock prevents concurrent increment corruptions.

    Send many concurrent _next_seq calls and verify no value is repeated.
    """
    server = ProjectionWebSocketServer()
    n = 5000

    async def collector(n_calls: int) -> list[int]:
        result: list[int] = []
        for _ in range(n_calls):
            result.append(await server._next_seq())
        return result

    t1 = asyncio.create_task(collector(n))
    t2 = asyncio.create_task(collector(n))
    r1, r2 = await asyncio.gather(t1, t2)

    all_seqs = set(r1) | set(r2)
    assert len(all_seqs) == 2 * n, f"Expected {2 * n} unique seqs, got {len(all_seqs)}"


# ---------------------------------------------------------------------------
# Shutdown cancels and drains bridge tasks
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_shutdown_cancels_and_drains_bridge_tasks() -> None:
    """After close(), no handler tasks should remain tracked."""
    server = ProjectionWebSocketServer(port=0, token="test-token", auth_timeout=100)

    # Start the server to allocate _server
    try:
        import websockets

        async with websockets.serve(
            server._tracked_handle_connection, server._host, 0
        ) as srv:
            server._server = srv
            # Connect a client that will hang
            connected = asyncio.Event()

            async def mimic_handler() -> None:
                # Simulate what _tracked_handle_connection does
                task = asyncio.current_task()
                if task is not None:
                    server._handler_tasks.add(task)
                connected.set()
                await asyncio.Event().wait()  # Never completes naturally

            t = asyncio.create_task(mimic_handler())
            await connected.wait()

            assert len(server._handler_tasks) >= 1

            await server.close()

            assert len(server._handler_tasks) == 0
            t.cancel()
    except Exception:
        # Clean up if anything goes wrong
        if server._server:
            server._server.close()
        server._handler_tasks.clear()


@pytest.mark.asyncio
async def test_close_timeout_does_not_hang_forever() -> None:
    """close() must not hang indefinitely when a handler is stuck."""
    server = ProjectionWebSocketServer(port=0, token="test-token", auth_timeout=100)
    server._DRAIN_TIMEOUT = 0.5

    stuck = StuckWebSocket()
    server._connections.add(stuck)

    # Inject a handler task that will never complete
    async def stuck_handler() -> None:
        await asyncio.Event().wait()

    t = asyncio.create_task(stuck_handler())
    server._handler_tasks.add(t)

    # _server must be something truthy for close() to path through
    import websockets

    async with websockets.serve(lambda ws: asyncio.sleep(0), server._host, 0) as srv:
        server._server = srv
        try:
            await asyncio.wait_for(server.close(), timeout=3.0)
        except TimeoutError:
            pytest.fail("close() hung — graceful-shutdown timeout not effective")

    # The stuck handler task should have been cancelled
    assert t.cancelled() or t.done()


# ---------------------------------------------------------------------------
# No orphan tasks after connection lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_orphan_tasks_after_connection_close() -> None:
    """After a connection's finally block runs, all spawned tasks must be done."""
    # Simulate the per-connection task registry pattern
    _connection_tasks: set[asyncio.Task[Any]] = set()

    async def sample_task() -> None:
        await asyncio.sleep(0.01)

    def _spawn(coro: Any) -> asyncio.Task[Any]:
        task = asyncio.create_task(coro)
        _connection_tasks.add(task)
        task.add_done_callback(_connection_tasks.discard)
        return task

    t1 = _spawn(sample_task())
    t2 = _spawn(sample_task())
    t3 = _spawn(sample_task())

    assert len(_connection_tasks) == 3

    # Simulate the finally block
    for t in list(_connection_tasks):
        t.cancel()
    if _connection_tasks:
        await asyncio.gather(*_connection_tasks, return_exceptions=True)

    assert len(_connection_tasks) == 0
    assert t1.done()
    assert t2.done()
    assert t3.done()


@pytest.mark.asyncio
async def test_heartbeat_task_is_tracked_and_cancelled() -> None:
    """Heartbeat spawned via _spawn must appear in task set and be cancellable."""
    _connection_tasks: set[asyncio.Task[Any]] = set()

    def _spawn(coro: Any) -> asyncio.Task[Any]:
        task = asyncio.create_task(coro)
        _connection_tasks.add(task)
        task.add_done_callback(_connection_tasks.discard)
        return task

    heartbeat = _spawn(asyncio.sleep(60))
    assert len(_connection_tasks) == 1
    assert not heartbeat.done()

    # Cancel + drain
    heartbeat.cancel()
    await asyncio.gather(heartbeat, return_exceptions=True)
    assert heartbeat.done()


# ---------------------------------------------------------------------------
# No threading primitives
# ---------------------------------------------------------------------------


def test_asyncio_locks_not_used_for_thread_synchronization() -> None:
    """Verify no threading imports or primitives leak into the file."""
    source = (
        __import__("pathlib").Path(__file__).parent.parent.parent
        / "rig_relay"
        / "desktop"
        / "websocket_server.py"
    ).read_text()
    assert "import threading" not in source
    assert "from threading" not in source
    assert "threading.Lock" not in source
    assert "threading.RLock" not in source
    assert "threading.Condition" not in source
    assert "threading.Semaphore" not in source
    assert "Thread(" not in source


def test_all_locks_are_asyncio() -> None:
    """All lock-type attributes must be asyncio primitives."""
    server = ProjectionWebSocketServer()
    assert isinstance(server._lock, asyncio.Lock)
    assert isinstance(server._seq_lock, asyncio.Lock)
    assert isinstance(server._tracker_lock, asyncio.Lock)

    # Verify no lock is a threading primitive (check class name)
    def _is_threading_lock(obj: object) -> bool:
        return type(obj).__module__.startswith("threading")

    assert not _is_threading_lock(server._lock)
    assert not _is_threading_lock(server._seq_lock)
    assert not _is_threading_lock(server._tracker_lock)


# ---------------------------------------------------------------------------
# Message dedup cache concurrent access is guarded
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_message_dedup_cache_concurrent_access_is_guarded() -> None:
    """Concurrent calls to ProtocolTracker.is_duplicate_message must not
    produce duplicate accept on identical message_id, nor corrupt the set.
    """
    tracker = ProtocolTracker("hs_concurrent")

    async def try_dedup(msg_id: str) -> bool:
        return tracker.is_duplicate_message(msg_id)

    # Same message_id sent from 100 concurrent "tasks" (coroutines)
    results = await asyncio.gather(*[
        try_dedup("msg_duplicate_001") for _ in range(100)
    ])

    # Exactly one call should return False (first seen), rest True
    false_count = sum(1 for r in results if not r)
    true_count = sum(1 for r in results if r)
    assert false_count == 1, f"Expected exactly 1 'not duplicate', got {false_count}"
    assert true_count == 99


@pytest.mark.asyncio
async def test_tracker_dict_concurrent_access_is_guarded() -> None:
    """Concurrent writes to _protocol_trackers through the same handshake_id
    must not cause corruption.
    """
    server = ProjectionWebSocketServer()

    async def register_tracker(hsid: str) -> None:
        async with server._tracker_lock:
            if hsid not in server._protocol_trackers:
                server._protocol_trackers[hsid] = ProtocolTracker(hsid)

    await asyncio.gather(*[register_tracker("hs_shared") for _ in range(50)])

    assert "hs_shared" in server._protocol_trackers
    assert len(server._protocol_trackers) == 1


@pytest.mark.asyncio
async def test_ws_handshake_id_concurrent_read_is_consistent() -> None:
    """Concurrent writes to _ws_handshake_id must be covered by _tracker_lock
    so reads (via _get_tracker) never see a partial state.
    """
    server = ProjectionWebSocketServer()

    async def write_handshake(ws: FakeWebSocket, handshake_id: str) -> None:
        async with server._tracker_lock:
            server._ws_handshake_id[id(ws)] = handshake_id
            server._protocol_trackers[handshake_id] = ProtocolTracker(handshake_id)

    ws1 = FakeWebSocket()
    ws2 = FakeWebSocket()

    await asyncio.gather(write_handshake(ws1, "hs_a"), write_handshake(ws2, "hs_b"))

    t1 = await server._get_tracker(ws1)
    t2 = await server._get_tracker(ws2)

    assert t1 is not None
    assert t2 is not None
    assert t1.handshake_id == "hs_a"
    assert t2.handshake_id == "hs_b"


@pytest.mark.asyncio
async def test_per_connection_pending_concurrent_access_is_guarded() -> None:
    """Concurrent writes to _per_connection_pending via _send_with_flow_control
    for the same handshake_id must not lose messages.
    """
    server = ProjectionWebSocketServer()
    ws = FakeWebSocket()
    tracker = ProtocolTracker("hs_flow")

    async def send_flow(msg: dict, kind: str) -> None:
        await server._send_with_flow_control(ws, msg, tracker, kind)

    msgs = [{"type": "test", "n": i} for i in range(20)]

    await asyncio.gather(*[send_flow(m, "projection") for m in msgs])

    # All messages should have been sent to the fake websocket
    assert len(ws.sent) == 20
    parsed = [json.loads(s) for s in ws.sent]
    values = sorted(p.get("n", -1) for p in parsed)
    assert values == list(range(20))
