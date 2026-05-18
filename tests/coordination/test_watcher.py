from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from rig_relay.coordination.models import (
    CoordinationSession,
    reset_path_salt_for_testing,
)
from rig_relay.coordination.store import CoordinationStore
from rig_relay.coordination.watcher import CoordinationWatcher, CoordinationWatchEvent

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


def _make_store(tmp_path: Path) -> CoordinationStore:
    return CoordinationStore(tmp_path / ".build" / "rig-relay" / "coordination")


async def _collect_until(
    watcher: CoordinationWatcher, max_events: int, timeout: float = 5.0
) -> list[CoordinationWatchEvent]:
    collected: list[CoordinationWatchEvent] = []

    async def _collect() -> None:
        async for event in watcher.events():
            collected.append(event)
            if len(collected) >= max_events:
                break

    task = asyncio.create_task(_collect())
    try:
        await asyncio.wait_for(task, timeout=timeout)
    except TimeoutError:
        await watcher.stop()
        try:
            await task
        except asyncio.CancelledError:
            pass
    return collected


async def test_watcher_detects_ledger_append(tmp_path: Path) -> None:
    reset_path_salt_for_testing()
    store = _make_store(tmp_path)
    watcher = CoordinationWatcher(store.root, poll_interval_s=0.05)
    await watcher.start()
    await asyncio.sleep(0.1)

    collection_task = asyncio.create_task(
        _collect_until(watcher, max_events=1, timeout=5.0)
    )

    store.register_session(CoordinationSession(session_id="s1", status="running"))

    collected = await collection_task
    assert len(collected) >= 1
    assert collected[0].event_type == "events_appended"
    assert collected[0].event_count >= 1

    event_names = [e["event_name"] for e in collected[0].events]
    assert "coord.session.registered" in event_names


async def test_watcher_stops_cleanly(tmp_path: Path) -> None:
    reset_path_salt_for_testing()
    store = _make_store(tmp_path)
    watcher = CoordinationWatcher(store.root, poll_interval_s=0.05)
    await watcher.start()

    async def _stop_after_delay() -> None:
        await asyncio.sleep(0.15)
        await watcher.stop()

    stop_task = asyncio.create_task(_stop_after_delay())
    collected: list[CoordinationWatchEvent] = []
    async for event in watcher.events():
        collected.append(event)

    await stop_task
    assert not watcher._running


async def test_watcher_no_events_when_no_change(tmp_path: Path) -> None:
    reset_path_salt_for_testing()
    store = _make_store(tmp_path)
    watcher = CoordinationWatcher(store.root, poll_interval_s=0.05)
    await watcher.start()

    async def _stop_after_delay() -> None:
        await asyncio.sleep(0.3)
        await watcher.stop()

    stop_task = asyncio.create_task(_stop_after_delay())
    collected: list[CoordinationWatchEvent] = []
    async for event in watcher.events():
        collected.append(event)

    await stop_task
    assert len(collected) == 0


async def test_watcher_does_not_corrupt_ledger(tmp_path: Path) -> None:
    reset_path_salt_for_testing()
    store = _make_store(tmp_path)
    watcher = CoordinationWatcher(store.root, poll_interval_s=0.05)
    await watcher.start()
    await asyncio.sleep(0.1)

    collection_task = asyncio.create_task(
        _collect_until(watcher, max_events=1, timeout=5.0)
    )

    store.register_session(
        CoordinationSession(session_id="s1", status="running")
    )

    collected = await collection_task
    assert len(collected) >= 1

    events_path = store.root / "events.jsonl"
    lines = events_path.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) >= 1
    for line in lines:
        parsed = json.loads(line)
        assert parsed["schema_version"] == "rig.relay.coordination.event.v1"
        assert parsed["event_name"].startswith("coord.")
        assert parsed["event_id"]
        assert parsed["sequence"] >= 1
        assert parsed["event_hash"].startswith("sha256:")

    projection = store.read_state_projection()
    assert "s1" in projection.active_sessions
    assert projection.active_sessions["s1"].status == "running"


async def test_watcher_handles_missing_ledger(tmp_path: Path) -> None:
    reset_path_salt_for_testing()
    store = _make_store(tmp_path)
    watcher = CoordinationWatcher(store.root, poll_interval_s=0.05)

    await watcher.start()
    assert not watcher._events_path.exists()

    async def _stop_after_delay() -> None:
        await asyncio.sleep(0.2)
        await watcher.stop()

    stop_task = asyncio.create_task(_stop_after_delay())
    collected: list[CoordinationWatchEvent] = []
    async for event in watcher.events():
        collected.append(event)

    await stop_task
    assert len(collected) == 0


async def test_watcher_idempotent_stop(tmp_path: Path) -> None:
    reset_path_salt_for_testing()
    store = _make_store(tmp_path)
    watcher = CoordinationWatcher(store.root, poll_interval_s=0.05)
    await watcher.start()

    await watcher.stop()
    await watcher.stop()

    assert not watcher._running
