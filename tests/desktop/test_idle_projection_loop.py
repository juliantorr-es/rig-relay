from __future__ import annotations

import asyncio
import json

import pytest

from rig_relay.desktop.websocket_server import ProjectionWebSocketServer
from rig_relay.tracing.recorder import TraceRecorder
from rig_relay.tracing.store import InMemoryTraceStore

DEFAULT_HOST = "127.0.0.1"
AUTH_TOKEN = "test-bridge-token-32chars-xxx"


async def _connect_and_auth(ws_port: int, token: str = AUTH_TOKEN):
    import websockets

    ws = await websockets.connect(f"ws://{DEFAULT_HOST}:{ws_port}")
    await ws.send(
        json.dumps({"type": "auth", "token": token, "handshake_id": "hs_test"})
    )
    response = json.loads(await ws.recv())
    assert response["type"] == "auth_ok"
    return ws


async def _recv_json(ws, timeout: float = 2.0) -> dict | None:
    try:
        raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
        return json.loads(raw)
    except TimeoutError:
        return None


def _is_bridge_status(msg: dict) -> bool:
    return (
        msg.get("schema_version") == "rig.relay.bridge_message.v1"
        and msg.get("kind") == "lifecycle_event"
        and msg.get("payload", {}).get("event_type") == "bridge.status"
    )


class TestIdleProjectionLoop:
    @pytest.mark.asyncio
    async def test_first_bridge_status_sent_after_auth(
        self, unused_tcp_port: int
    ) -> None:
        trace_store = InMemoryTraceStore()
        server = ProjectionWebSocketServer(
            port=unused_tcp_port,
            token=AUTH_TOKEN,
            auth_timeout=100,
            trace_recorder=TraceRecorder(trace_store),
        )
        server._bridge_status_interval = 0.5
        await server.start()
        try:
            ws = await _connect_and_auth(unused_tcp_port)

            frames = []
            deadline = asyncio.get_event_loop().time() + 3.0
            while asyncio.get_event_loop().time() < deadline:
                msg = await _recv_json(ws, timeout=0.3)
                if msg is None:
                    continue
                frames.append(msg)
                if any(_is_bridge_status(f) for f in frames):
                    break
            assert frames, "No post-auth frames received"
            status_msgs = [f for f in frames if _is_bridge_status(f)]
            assert status_msgs, (
                f"No bridge_status found in frames: "
                f"{json.dumps(frames, indent=2, sort_keys=True)}"
            )
            payload = status_msgs[0]["payload"]
            assert payload["bridge_runtime_state"] in ("idle", "ready")
            assert payload["backend_session_id"]
            assert payload["idle_sequence"] == 0
            assert isinstance(payload.get("capabilities"), list)

            await ws.close()
        finally:
            await server.close()

    @pytest.mark.asyncio
    async def test_periodic_bridge_status_without_active_work(
        self, unused_tcp_port: int
    ) -> None:
        trace_store = InMemoryTraceStore()
        server = ProjectionWebSocketServer(
            port=unused_tcp_port,
            token=AUTH_TOKEN,
            auth_timeout=100,
            trace_recorder=TraceRecorder(trace_store),
        )
        server._bridge_status_interval = 0.3
        await server.start()
        try:
            ws = await _connect_and_auth(unused_tcp_port)

            status_count = 0
            sequences = []
            for _ in range(40):
                msg = await _recv_json(ws, timeout=2.0)
                if msg is None:
                    break
                if _is_bridge_status(msg):
                    status_count += 1
                    seq = msg["payload"].get("idle_sequence", -1)
                    sequences.append(seq)
                if status_count >= 3:
                    break
            assert status_count >= 2, f"Expected >= 2 bridge_status, got {status_count}"
            assert sequences == sorted(sequences), (
                "Sequences must be monotonically increasing"
            )
            assert len(set(sequences)) == len(sequences), "Sequences must be unique"

            await ws.close()
        finally:
            await server.close()

    @pytest.mark.asyncio
    async def test_bridge_status_continues_during_idle_period(
        self, unused_tcp_port: int
    ) -> None:
        trace_store = InMemoryTraceStore()
        server = ProjectionWebSocketServer(
            port=unused_tcp_port,
            token=AUTH_TOKEN,
            auth_timeout=100,
            trace_recorder=TraceRecorder(trace_store),
        )
        server._bridge_status_interval = 0.4
        await server.start()
        try:
            ws = await _connect_and_auth(unused_tcp_port)

            statuses_before = 0
            for _ in range(30):
                msg = await _recv_json(ws, timeout=2.0)
                if msg is None:
                    break
                if _is_bridge_status(msg):
                    statuses_before += 1
                if statuses_before >= 2:
                    break
            assert statuses_before >= 2, (
                f"Expected >= 2 bridge_status, got {statuses_before}"
            )

            statuses_after = 0
            for _ in range(30):
                msg = await _recv_json(ws, timeout=2.0)
                if msg is None:
                    break
                if _is_bridge_status(msg):
                    statuses_after += 1
                if statuses_after >= 2:
                    break
            assert statuses_after >= 2, (
                f"Idle loop stopped early, got {statuses_after} more"
            )

            await ws.close()
        finally:
            await server.close()

    @pytest.mark.asyncio
    async def test_projection_loop_cancels_on_disconnect(
        self, unused_tcp_port: int
    ) -> None:
        trace_store = InMemoryTraceStore()
        server = ProjectionWebSocketServer(
            port=unused_tcp_port,
            token=AUTH_TOKEN,
            auth_timeout=100,
            trace_recorder=TraceRecorder(trace_store),
        )
        server._bridge_status_interval = 0.3
        await server.start()
        try:
            ws = await _connect_and_auth(unused_tcp_port)

            status_count = 0
            for _ in range(20):
                msg = await _recv_json(ws, timeout=2.0)
                if msg is None:
                    break
                if _is_bridge_status(msg):
                    status_count += 1
                if status_count >= 2:
                    break
            assert status_count >= 2, f"Expected >= 2 bridge_status, got {status_count}"

            handler_tasks_before = len(server._handler_tasks)
            await ws.close()
            await asyncio.sleep(0.5)

            handler_tasks_after = len(server._handler_tasks)
            assert handler_tasks_after <= handler_tasks_before, (
                f"Handler tasks should drain after disconnect: "
                f"before={handler_tasks_before} after={handler_tasks_after}"
            )

            disconnect_event = None
            for e in trace_store.events:
                if e.get("event_type") == "bridge.disconnect":
                    disconnect_event = e
                    break
            assert disconnect_event is not None, "bridge.disconnect event not emitted"
            pl = disconnect_event.get("payload", {})
            assert (
                isinstance(pl, dict)
                and pl.get("bridge_runtime_state") == "disconnected"
            )
        finally:
            await server.close()

    @pytest.mark.asyncio
    async def test_reconnect_creates_one_loop_not_two(
        self, unused_tcp_port: int
    ) -> None:
        trace_store = InMemoryTraceStore()
        server = ProjectionWebSocketServer(
            port=unused_tcp_port,
            token=AUTH_TOKEN,
            auth_timeout=100,
            trace_recorder=TraceRecorder(trace_store),
        )
        server._bridge_status_interval = 0.3
        await server.start()
        try:
            ws1 = await _connect_and_auth(unused_tcp_port)
            status_count_1 = 0
            for _ in range(15):
                msg = await _recv_json(ws1, timeout=2.0)
                if msg is None:
                    break
                if _is_bridge_status(msg):
                    status_count_1 += 1
                if status_count_1 >= 2:
                    break
            assert status_count_1 >= 2
            await ws1.close()
            await asyncio.sleep(0.3)

            ws2 = await _connect_and_auth(unused_tcp_port)
            status_count_2 = 0
            for _ in range(15):
                msg = await _recv_json(ws2, timeout=2.0)
                if msg is None:
                    break
                if _is_bridge_status(msg):
                    status_count_2 += 1
                if status_count_2 >= 2:
                    break
            assert status_count_2 >= 2, (
                f"Reconnect should get status, got {status_count_2}"
            )

            loop_started_events = [
                e
                for e in trace_store.events
                if str(e.get("event_type", "")) == "bridge.backend_loop_started"
            ]
            disconnect_events = [
                e
                for e in trace_store.events
                if str(e.get("event_type", "")) == "bridge.disconnect"
            ]
            assert len(loop_started_events) == 2, (
                f"Expected 2 loop-started events, got {len(loop_started_events)}"
            )
            assert len(disconnect_events) >= 1, (
                f"Expected >= 1 disconnect events, got {len(disconnect_events)}"
            )

            await ws2.close()
        finally:
            await server.close()

    @pytest.mark.asyncio
    async def test_bridge_lifecycle_events_emitted(self, unused_tcp_port: int) -> None:
        trace_store = InMemoryTraceStore()
        server = ProjectionWebSocketServer(
            port=unused_tcp_port,
            token=AUTH_TOKEN,
            auth_timeout=100,
            trace_recorder=TraceRecorder(trace_store),
        )
        server._bridge_status_interval = 0.5
        await server.start()
        try:
            ws = await _connect_and_auth(unused_tcp_port)
            await asyncio.sleep(1.5)
            await ws.close()
            await asyncio.sleep(0.3)

            event_names = {
                str(e.get("event_type", ""))
                for e in trace_store.events
                if str(e.get("event_type", "")).startswith("bridge.")
            }
            required = {
                "bridge.connection_begin",
                "bridge.first_projection_sent",
                "bridge.backend_loop_started",
                "bridge.heartbeat_sent",
            }
            found = required & event_names
            assert found == required, (
                f"Missing required lifecycle events: {required - found}. "
                f"Found events: {sorted(event_names)}"
            )

            disconnect_events = [
                e
                for e in trace_store.events
                if str(e.get("event_type", "")) == "bridge.disconnect"
            ]
            assert len(disconnect_events) >= 1, "bridge.disconnect event not emitted"
        finally:
            await server.close()

    @pytest.mark.asyncio
    async def test_bridge_status_payload_is_content_light(
        self, unused_tcp_port: int
    ) -> None:
        trace_store = InMemoryTraceStore()
        server = ProjectionWebSocketServer(
            port=unused_tcp_port,
            token=AUTH_TOKEN,
            auth_timeout=100,
            trace_recorder=TraceRecorder(trace_store),
        )
        server._bridge_status_interval = 0.3
        await server.start()
        try:
            ws = await _connect_and_auth(unused_tcp_port)

            status_payload = None
            for _ in range(15):
                msg = await _recv_json(ws, timeout=2.0)
                if msg is None:
                    break
                if _is_bridge_status(msg):
                    status_payload = msg["payload"]
                    break

            assert status_payload is not None, "bridge_status payload not found"
            sensitive_fields = {
                "token",
                "secret",
                "api_key",
                "password",
                "raw",
                "content",
            }
            for field in sensitive_fields:
                assert field not in json.dumps(status_payload).lower(), (
                    f"Sensitive field '{field}' found in bridge_status"
                )

            await ws.close()
        finally:
            await server.close()

    @pytest.mark.asyncio
    async def test_duplicate_connect_produces_separate_trackers(
        self, unused_tcp_port: int
    ) -> None:
        trace_store = InMemoryTraceStore()
        server = ProjectionWebSocketServer(
            port=unused_tcp_port,
            token=AUTH_TOKEN,
            auth_timeout=100,
            trace_recorder=TraceRecorder(trace_store),
            max_connections=10,
        )
        server._bridge_status_interval = 0.5
        await server.start()
        try:
            ws1 = await _connect_and_auth(unused_tcp_port)
            ws2 = await _connect_and_auth(unused_tcp_port)

            session_ids = set()
            for _ in range(40):
                msg1 = await _recv_json(ws1, timeout=2.0)
                if msg1 is not None and _is_bridge_status(msg1):
                    sid = msg1["payload"].get("backend_session_id")
                    if sid:
                        session_ids.add(sid)
                msg2 = await _recv_json(ws2, timeout=2.0)
                if msg2 is not None and _is_bridge_status(msg2):
                    sid = msg2["payload"].get("backend_session_id")
                    if sid:
                        session_ids.add(sid)
                if len(session_ids) >= 2:
                    break

            assert len(session_ids) >= 2, (
                f"Expected >= 2 distinct session IDs, got {len(session_ids)}"
            )

            loop_started = [
                e
                for e in trace_store.events
                if str(e.get("event_type", "")) == "bridge.backend_loop_started"
            ]
            assert len(loop_started) >= 2, (
                f"Expected >= 2 loop started events, got {len(loop_started)}"
            )

            await ws1.close()
            await ws2.close()
        finally:
            await server.close()
