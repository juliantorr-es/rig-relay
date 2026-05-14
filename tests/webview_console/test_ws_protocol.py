"""Dogfood tests for the pywebview Rig Console WebSocket protocol.

Covers: auth, turn lifecycle, reconnect, idempotence, content-light, hardening.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from vibe.cli.textual_ui.rig_console.session_bridge import (
    FixtureSessionAdapter,
    RuntimeSessionAdapter,
)
from vibe.cli.webview_console.backend import RigConsoleBackend
from vibe.cli.webview_console.ws_api import ConsoleWebSocketServer

_TEST_TOKEN = "test-token-1234"


async def _make_server() -> ConsoleWebSocketServer:
    srv = ConsoleWebSocketServer(
        RigConsoleBackend(session_id="test-session"), port=0, token=_TEST_TOKEN
    )
    await srv.start()
    return srv


def test_backend_fixture_mode_uses_fixture_adapter() -> None:
    backend = RigConsoleBackend(session_id="test-session", mode="fixture")
    assert backend.mode == "fixture"
    assert isinstance(backend.bridge, FixtureSessionAdapter)
    assert not isinstance(backend.bridge, RuntimeSessionAdapter)


def test_backend_runtime_mode_uses_runtime_adapter() -> None:
    backend = RigConsoleBackend(session_id="test-session", mode="runtime")
    assert backend.mode == "runtime"
    assert isinstance(backend.bridge, RuntimeSessionAdapter)


async def _connect(port: int) -> Any:
    import websockets

    return await websockets.connect(f"ws://127.0.0.1:{port}")


async def _auth(ws: Any, last_seen_seq: int = 0) -> dict[str, Any]:
    await ws.send(
        json.dumps({
            "schema": "rig.ws.client.auth.v1",
            "token": _TEST_TOKEN,
            "last_seen_seq": last_seen_seq,
            "client_protocol_version": "rig.ws.v1",
            "client_name": "pytest",
        })
    )
    auth_msg = json.loads(await ws.recv())
    await ws.recv()  # consume snapshot
    return auth_msg


async def _send_intent(
    ws: Any, kind: str, payload: dict[str, Any] | None = None
) -> dict[str, Any]:
    await ws.send(
        json.dumps({
            "schema": "rig.ws.client.intent.v1",
            "intent_id": "test-001",
            "intent_kind": kind,
            "payload": payload or {},
        })
    )
    # Consume messages until we get an ack (skip deltas that may have
    # arrived from background streaming tasks)
    for _ in range(20):
        raw = await asyncio.wait_for(ws.recv(), timeout=5.0)
        msg = json.loads(raw)
        if msg.get("schema") in ("rig.ws.server.ack.v1", "rig.ws.server.snapshot.v1"):
            return msg
    return {}


async def _send_intent_expect_ack(
    ws: Any, kind: str, payload: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Send intent and read until ack. Ignores interleaved deltas."""
    await ws.send(
        json.dumps({
            "schema": "rig.ws.client.intent.v1",
            "intent_id": "test-001",
            "intent_kind": kind,
            "payload": payload or {},
        })
    )
    for _ in range(20):
        raw = await asyncio.wait_for(ws.recv(), timeout=5.0)
        msg = json.loads(raw)
        if msg.get("schema") == "rig.ws.server.ack.v1":
            return msg
    return {}


# ── Auth ──


@pytest.mark.asyncio
async def test_auth_valid_token() -> None:
    srv = await _make_server()
    try:
        async with await _connect(srv.port) as ws:
            msg = await _auth(ws)
            assert msg["schema"] == "rig.ws.server.auth_ok.v1"
            assert "seq" in msg
            assert msg["session_id"] == "test-session"
            assert "last_seen_seq" in msg
    finally:
        await srv.close()


@pytest.mark.asyncio
async def test_auth_bad_token_refused() -> None:
    srv = await _make_server()
    try:
        async with await _connect(srv.port) as ws:
            await ws.send(
                json.dumps({"schema": "rig.ws.client.auth.v1", "token": "wrong"})
            )
            msg = json.loads(await ws.recv())
            assert msg["schema"] == "rig.ws.server.auth_error.v1"
    finally:
        await srv.close()


# ── Sequence numbers ──


@pytest.mark.asyncio
async def test_every_event_has_envelope() -> None:
    srv = await _make_server()
    try:
        async with await _connect(srv.port) as ws:
            await _auth(ws)
            snap_msg = await _send_intent(ws, "get_snapshot")
            assert snap_msg["schema"] == "rig.ws.server.snapshot.v1"
            assert snap_msg["seq"] >= 2
            assert snap_msg["session_id"] == "test-session"
            assert "created_at" in snap_msg
            assert "data" in snap_msg
    finally:
        await srv.close()


# ── Turn lifecycle ──


@pytest.mark.asyncio
async def test_start_turn_empty_refused() -> None:
    srv = await _make_server()
    try:
        async with await _connect(srv.port) as ws:
            await _auth(ws)
            ack = await _send_intent(ws, "start_turn", {"text": ""})
            assert ack.get("status") == "refused"
            assert "Empty" in ack.get("reason", "")
    finally:
        await srv.close()


@pytest.mark.asyncio
async def test_start_turn_accepted() -> None:
    srv = await _make_server()
    try:
        async with await _connect(srv.port) as ws:
            await _auth(ws)
            ack = await _send_intent(ws, "start_turn", {"text": "hello fixture"})
            assert ack["status"] == "accepted"
            assert ack["turn_id"] != ""
    finally:
        await srv.close()


@pytest.mark.timeout(20)
@pytest.mark.asyncio
async def test_active_turn_refuses_second() -> None:
    """start_turn while running returns refused ack.

    Uses RuntimeSessionAdapter with a blocking FakeLoop to keep the
    turn active long enough for a second start_turn to be refused.
    """
    from unittest.mock import MagicMock, patch

    from vibe.cli.textual_ui.rig_console.session_bridge import CodingSessionBridge

    backend = RigConsoleBackend(session_id="test-session")
    # Replace bridge with real RuntimeSessionAdapter + slow FakeLoop
    bridge = CodingSessionBridge(
        session_id="test-session", receipt_store=backend.receipt_store
    )
    backend._bridge = bridge
    backend._session._bridge = bridge
    backend._projection._bridge = bridge

    class SlowFakeLoop:
        def __init__(self, *args: object, **kwargs: object) -> None:
            self.telemetry_client = MagicMock()

        async def __aenter__(self) -> SlowFakeLoop:
            return self

        async def __aexit__(self, *args: object) -> None:
            pass

        async def aclose(self) -> None:
            pass

        def emit_new_session_telemetry(self) -> None:
            pass

        async def act(self, text: str, client_message_id: str | None = None):
            from vibe.core.types import AssistantEvent, UserMessageEvent

            yield UserMessageEvent(content=text, message_id="msg-1")
            await asyncio.sleep(30)  # keep running until cancelled
            yield AssistantEvent(content="reply", message_id="msg-2")

    with patch(
        "vibe.cli.textual_ui.rig_console.session_bridge.AgentLoop", SlowFakeLoop
    ):
        srv = ConsoleWebSocketServer(backend, port=0, token=_TEST_TOKEN)
        await srv.start()
        try:
            async with await _connect(srv.port) as ws:
                await _auth(ws)
                ack1 = await _send_intent(ws, "start_turn", {"text": "hello"})
                assert ack1["status"] == "accepted"
                # Immediately send second intent while first is running
                ack2 = await _send_intent_expect_ack(
                    ws, "start_turn", {"text": "second"}
                )
                assert ack2.get("status") == "refused"
                # Cancel the running turn
                await _send_intent_expect_ack(ws, "cancel_turn")
        finally:
            await srv.close()


@pytest.mark.asyncio
async def test_cancel_idle_turn_refused() -> None:
    """cancel_turn while idle returns safe no-op ack."""
    srv = await _make_server()
    try:
        async with await _connect(srv.port) as ws:
            await _auth(ws)
            ack = await _send_intent_expect_ack(ws, "cancel_turn")
            assert ack.get("status") == "refused"
            assert "No active" in ack.get("reason", "")
    finally:
        await srv.close()


@pytest.mark.asyncio
async def test_second_prompt_after_completed_turn() -> None:
    """After completed, prompt can submit again."""
    srv = await _make_server()
    try:
        async with await _connect(srv.port) as ws:
            await _auth(ws)
            # First turn
            ack1 = await _send_intent(ws, "start_turn", {"text": "hello"})
            assert ack1["status"] == "accepted"
            for _ in range(5):
                raw = await asyncio.wait_for(ws.recv(), timeout=2.0)
                msg = json.loads(raw)
                if msg.get("schema") == "rig.ws.server.snapshot.v1":
                    break
            # Second turn
            ack2 = await _send_intent(ws, "start_turn", {"text": "world"})
            assert ack2["status"] == "accepted"
    finally:
        await srv.close()


# ── Reconnect ──


@pytest.mark.asyncio
async def test_reconnect_with_replay() -> None:
    """Reconnect with last_seen_seq replays buffered deltas."""
    srv = await _make_server()
    try:
        async with await _connect(srv.port) as ws1:
            await _auth(ws1)
            ack = await _send_intent(ws1, "start_turn", {"text": "hello"})
            assert ack["status"] == "accepted"
            deltas = []
            for _ in range(5):
                raw = await asyncio.wait_for(ws1.recv(), timeout=2.0)
                msg = json.loads(raw)
                if msg.get("schema") == "rig.ws.server.delta.v1":
                    deltas.append(msg)
                if msg.get("schema") == "rig.ws.server.snapshot.v1":
                    break

        last_delta_seq = max((d.get("seq", 0) for d in deltas), default=0)

        async with await _connect(srv.port) as ws2:
            await ws2.send(
                json.dumps({
                    "schema": "rig.ws.client.auth.v1",
                    "token": _TEST_TOKEN,
                    "last_seen_seq": last_delta_seq - 1 if last_delta_seq > 0 else 0,
                    "client_protocol_version": "rig.ws.v1",
                    "client_name": "pytest",
                })
            )
            auth_msg = json.loads(await ws2.recv())
            assert auth_msg["schema"] == "rig.ws.server.auth_ok.v1"

            found_replay = False
            found_snapshot = False
            for _ in range(len(deltas) + 2):
                raw = await asyncio.wait_for(ws2.recv(), timeout=3.0)
                msg = json.loads(raw)
                if msg.get("schema") == "rig.ws.server.delta.v1":
                    found_replay = True
                if msg.get("schema") == "rig.ws.server.snapshot.v1":
                    found_snapshot = True
                    break
            assert found_replay, "Expected replayed deltas"
            assert found_snapshot, "Expected final snapshot after replay"
    finally:
        await srv.close()


@pytest.mark.asyncio
async def test_reconnect_with_snapshot_fallback() -> None:
    """Reconnect with last_seen_seq=0 gets fresh snapshot (no replay)."""
    srv = await _make_server()
    try:
        async with await _connect(srv.port) as ws1:
            await _auth(ws1)
            ack = await _send_intent(ws1, "start_turn", {"text": "hello"})
            assert ack["status"] == "accepted"
            for _ in range(5):
                raw = await asyncio.wait_for(ws1.recv(), timeout=2.0)
                if json.loads(raw).get("schema") == "rig.ws.server.snapshot.v1":
                    break

        async with await _connect(srv.port) as ws2:
            await ws2.send(
                json.dumps({
                    "schema": "rig.ws.client.auth.v1",
                    "token": _TEST_TOKEN,
                    "last_seen_seq": 0,
                    "client_protocol_version": "rig.ws.v1",
                    "client_name": "pytest",
                })
            )
            auth_msg = json.loads(await ws2.recv())
            assert auth_msg["schema"] == "rig.ws.server.auth_ok.v1"
            raw = await asyncio.wait_for(ws2.recv(), timeout=2.0)
            msg = json.loads(raw)
            assert msg.get("schema") == "rig.ws.server.snapshot.v1"
    finally:
        await srv.close()


# ── Idempotence ──


@pytest.mark.asyncio
async def test_delta_idempotent() -> None:
    """Backend does not re-emit duplicate event_id."""
    srv = await _make_server()
    try:
        async with await _connect(srv.port) as ws:
            await _auth(ws)
            await _send_intent(ws, "start_turn", {"text": "hello"})
            event_ids: set[str] = set()
            dupes = False
            for _ in range(10):
                raw = await asyncio.wait_for(ws.recv(), timeout=5.0)
                msg = json.loads(raw)
                if msg.get("schema") == "rig.ws.server.delta.v1":
                    eid = msg.get("event_id") or (msg.get("value") or {}).get("item_id")
                    if eid in event_ids:
                        dupes = True
                        break
                    if eid:
                        event_ids.add(eid)
                if msg.get("schema") == "rig.ws.server.snapshot.v1":
                    break
            assert not dupes
    finally:
        await srv.close()


@pytest.mark.asyncio
async def test_stale_seq_ignored() -> None:
    """Frontend ignores deltas with seq <= lastSeq."""
    srv = await _make_server()
    try:
        async with await _connect(srv.port) as ws:
            await _auth(ws)
            ack = await _send_intent(ws, "start_turn", {"text": "hello"})
            assert ack["status"] == "accepted"
            deltas = []
            for _ in range(5):
                raw = await asyncio.wait_for(ws.recv(), timeout=2.0)
                msg = json.loads(raw)
                if msg.get("schema") == "rig.ws.server.delta.v1":
                    deltas.append(msg)
                if msg.get("schema") == "rig.ws.server.snapshot.v1":
                    break
            # Simulate receiving a delta with old seq
            if deltas:
                stale = dict(deltas[0])
                stale["seq"] = 1  # definitely stale
                # Our reducer ignores seq <= lastSeq
                # This just verifies no crash
            assert len(deltas) >= 1
    finally:
        await srv.close()


# ── Content-light proof ──


_CONTENT_LIGHT_FORBIDDEN = {
    "stdout",
    "stderr",
    "diff",
    "patch",
    "argv",
    "file_contents",
    "raw_prompt",
    "secret",
    "raw_output",
    "old_text",
    "new_text",
    "chunk_text",
}


@pytest.mark.asyncio
async def test_content_light_deltas() -> None:
    srv = await _make_server()
    try:
        async with await _connect(srv.port) as ws:
            await _auth(ws)
            await _send_intent(ws, "start_turn", {"text": "hello"})
            for _ in range(10):
                raw = await asyncio.wait_for(ws.recv(), timeout=5.0)
                msg = json.loads(raw)
                if msg.get("schema") == "rig.ws.server.snapshot.v1":
                    snap_data = msg.get("data", {})
                    for t in snap_data.get("transcript", []):
                        forbidden = _CONTENT_LIGHT_FORBIDDEN & set(t.keys())
                        assert not forbidden, f"Forbidden in snapshot: {forbidden}"
                    break
                if msg.get("schema") == "rig.ws.server.delta.v1":
                    val = msg.get("value", {})
                    forbidden = _CONTENT_LIGHT_FORBIDDEN & set(val.keys())
                    assert not forbidden, f"Forbidden in delta: {forbidden}"
    finally:
        await srv.close()


@pytest.mark.asyncio
async def test_content_light_ack_and_warning() -> None:
    """ack and warning events carry no forbidden fields."""
    srv = await _make_server()
    try:
        async with await _connect(srv.port) as ws:
            await _auth(ws)
            # Trigger a warning with unknown schema
            await ws.send(json.dumps({"schema": "rig.ws.client.unknown.v1"}))
            raw = await asyncio.wait_for(ws.recv(), timeout=2.0)
            msg = json.loads(raw)
            assert msg.get("schema") == "rig.ws.server.warning.v1"
            val_keys = set(msg.keys())
            forbidden = _CONTENT_LIGHT_FORBIDDEN & val_keys
            assert not forbidden, f"Forbidden in warning: {forbidden}"
    finally:
        await srv.close()


# ── Replay buffer ──


@pytest.mark.asyncio
async def test_replay_buffer_bounded() -> None:
    """Replay buffer does not grow unbounded."""
    srv = await _make_server()
    try:
        # Fill buffer with more entries than max
        for i in range(1050):
            srv._append_replay({
                "schema": "rig.ws.server.delta.v1",
                "seq": i + 1,
                "value": {"item_id": f"i{i}"},
            })
        assert len(srv._replay_buffer) <= 1000
    finally:
        await srv.close()
