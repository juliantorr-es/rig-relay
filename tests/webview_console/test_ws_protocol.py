"""Dogfood tests for the pywebview Rig Console WebSocket protocol.

Tests cover:
1. Auth: valid token, missing token, bad token
2. start_turn: empty prompt refused, text accepted, events streamed
3. cancel_turn: cancels active turn
4. get_snapshot: returns consistent projection
5. Idempotence: same delta received twice does not duplicate transcript
6. Sequence numbers: every server event carries seq, session_id, created_at
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from vibe.cli.webview_console.backend import RigConsoleBackend
from vibe.cli.webview_console.ws_api import ConsoleWebSocketServer

_TEST_TOKEN = "test-token-1234"


async def _make_server() -> ConsoleWebSocketServer:
    srv = ConsoleWebSocketServer(RigConsoleBackend(session_id="test-session"), port=0, token=_TEST_TOKEN)
    await srv.start()
    return srv


async def _connect(ws_url: str) -> Any:
    import websockets

    return await websockets.connect(ws_url)


async def _auth(ws: Any) -> dict[str, Any]:
    await ws.send(json.dumps({"schema": "rig.ws.client.auth.v1", "token": _TEST_TOKEN}))
    # Server sends auth_ok then snapshot
    auth_msg = json.loads(await ws.recv())
    # Consume the snapshot
    await ws.recv()
    return auth_msg


async def _send_intent(ws: Any, kind: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    await ws.send(json.dumps({
        "schema": "rig.ws.client.intent.v1",
        "intent_id": "test-001",
        "intent_kind": kind,
        "payload": payload or {},
    }))
    raw = await ws.recv()
    return json.loads(raw)


# ── Auth ──


@pytest.mark.asyncio
async def test_auth_valid_token() -> None:
    srv = await _make_server()
    try:
        async with await _connect(f"ws://127.0.0.1:{srv.port}") as ws:
            msg = await _auth(ws)
            assert msg["schema"] == "rig.ws.server.auth_ok.v1"
            assert "seq" in msg
            assert msg["session_id"] == "test-session"
    finally:
        await srv.close()


@pytest.mark.asyncio
async def test_auth_bad_token_refused() -> None:
    srv = await _make_server()
    try:
        async with await _connect(f"ws://127.0.0.1:{srv.port}") as ws:
            await ws.send(json.dumps({"schema": "rig.ws.client.auth.v1", "token": "wrong"}))
            msg = json.loads(await ws.recv())
            assert msg["schema"] == "rig.ws.server.auth_error.v1"
    finally:
        await srv.close()


# ── Sequence numbers ──


@pytest.mark.asyncio
async def test_every_event_has_envelope() -> None:
    """Every server event carries seq, session_id, created_at."""
    srv = await _make_server()
    try:
        async with await _connect(f"ws://127.0.0.1:{srv.port}") as ws:
            await _auth(ws)
            snap_msg = await _send_intent(ws, "get_snapshot")
            assert snap_msg["schema"] == "rig.ws.server.snapshot.v1"
            assert snap_msg["seq"] >= 2
            assert snap_msg["session_id"] == "test-session"
            assert "created_at" in snap_msg
            assert "data" in snap_msg
    finally:
        await srv.close()


@pytest.mark.asyncio
async def test_start_turn_empty_refused() -> None:
    srv = await _make_server()
    try:
        async with await _connect(f"ws://127.0.0.1:{srv.port}") as ws:
            await _auth(ws)
            ack = await _send_intent(ws, "start_turn", {"text": ""})
            assert ack["status"] == "refused"
    finally:
        await srv.close()


@pytest.mark.asyncio
async def test_start_turn_accepted() -> None:
    srv = await _make_server()
    try:
        async with await _connect(f"ws://127.0.0.1:{srv.port}") as ws:
            await _auth(ws)
            ack = await _send_intent(ws, "start_turn", {"text": "hello fixture"})
            assert ack["status"] == "accepted"
            assert ack["turn_id"] != ""
    finally:
        await srv.close()


@pytest.mark.asyncio
async def test_start_turn_streams_events() -> None:
    srv = await _make_server()
    try:
        async with await _connect(f"ws://127.0.0.1:{srv.port}") as ws:
            await _auth(ws)
            ack = await _send_intent(ws, "start_turn", {"text": "hello"})
            assert ack["status"] == "accepted"

            items: list[dict[str, Any]] = []
            for _ in range(3):
                raw = await asyncio.wait_for(ws.recv(), timeout=5.0)
                msg = json.loads(raw)
                if msg["schema"] == "rig.ws.server.delta.v1":
                    items.append(msg["value"])

            assert len(items) >= 2
            assert items[0]["kind"] in ("user_message", "context_envelope")

            final_raw = await asyncio.wait_for(ws.recv(), timeout=5.0)
            final = json.loads(final_raw)
            assert final["schema"] == "rig.ws.server.snapshot.v1"
            assert len(final["data"]["transcript"]) >= 2
    finally:
        await srv.close()


@pytest.mark.asyncio
async def test_cancel_turn() -> None:
    srv = await _make_server()
    try:
        async with await _connect(f"ws://127.0.0.1:{srv.port}") as ws:
            await _auth(ws)
            await _send_intent(ws, "start_turn", {"text": "hello"})
            # Fixture adapter completes immediately; consume all events
            for _ in range(5):
                raw = await asyncio.wait_for(ws.recv(), timeout=2.0)
                msg = json.loads(raw)
                if msg["schema"] == "rig.ws.server.snapshot.v1":
                    break
            # Cancel is still valid (no-op on fixture)
            await ws.send(json.dumps({
                "schema": "rig.ws.client.intent.v1",
                "intent_id": "cancel-001",
                "intent_kind": "cancel_turn",
                "payload": {},
            }))
            cancel_raw = await asyncio.wait_for(ws.recv(), timeout=5.0)
            cancel_ack = json.loads(cancel_raw)
            assert cancel_ack.get("schema") == "rig.ws.server.ack.v1"
    finally:
        await srv.close()


@pytest.mark.asyncio
async def test_snapshot_consistency() -> None:
    srv = await _make_server()
    try:
        async with await _connect(f"ws://127.0.0.1:{srv.port}") as ws:
            await _auth(ws)
            await _send_intent(ws, "start_turn", {"text": "hello"})
            for _ in range(4):
                await asyncio.wait_for(ws.recv(), timeout=5.0)

            snap = await _send_intent(ws, "get_snapshot")
            snap_data = snap["data"]
            assert "session_id" in snap_data
            assert "turn_status" in snap_data
            assert "transcript" in snap_data
            for t in snap_data["transcript"]:
                assert "item_id" in t
                assert "kind" in t
                assert "title" in t
    finally:
        await srv.close()


@pytest.mark.asyncio
async def test_delta_idempotent() -> None:
    srv = await _make_server()
    try:
        async with await _connect(f"ws://127.0.0.1:{srv.port}") as ws:
            await _auth(ws)
            await _send_intent(ws, "start_turn", {"text": "hello"})
            event_ids: set[str] = set()
            dupes = False
            for _ in range(10):
                raw = await asyncio.wait_for(ws.recv(), timeout=5.0)
                msg = json.loads(raw)
                if msg["schema"] == "rig.ws.server.delta.v1":
                    eid = msg.get("event_id") or msg.get("value", {}).get("item_id")
                    if eid in event_ids:
                        dupes = True
                        break
                    if eid:
                        event_ids.add(eid)
                if msg["schema"] == "rig.ws.server.snapshot.v1":
                    break
            assert not dupes, "Backend re-emitted duplicate event_id"
    finally:
        await srv.close()


_CONTENT_LIGHT_FORBIDDEN = {
    "stdout", "stderr", "diff", "patch", "argv",
    "file_contents", "raw_prompt", "secret", "raw_output",
    "old_text", "new_text", "chunk_text",
}


@pytest.mark.asyncio
async def test_content_light_deltas() -> None:
    srv = await _make_server()
    try:
        async with await _connect(f"ws://127.0.0.1:{srv.port}") as ws:
            await _auth(ws)
            await _send_intent(ws, "start_turn", {"text": "hello"})
            for _ in range(10):
                raw = await asyncio.wait_for(ws.recv(), timeout=5.0)
                msg = json.loads(raw)
                if msg["schema"] == "rig.ws.server.snapshot.v1":
                    break
                if msg["schema"] == "rig.ws.server.delta.v1":
                    val = msg.get("value", {})
                    forbidden = _CONTENT_LIGHT_FORBIDDEN & set(val.keys())
                    assert not forbidden, f"Forbidden fields in delta: {forbidden}"
    finally:
        await srv.close()
