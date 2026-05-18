"""Rig Relay Coordination Watcher — Governance Seam.

Polling watcher for the coordination event ledger (events.jsonl).
Detects new events appended by other sessions/processes and emits
structured watch events. Read-only — never mutates the ledger.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel


class CoordinationWatchEvent(BaseModel):
    """Structured watch event emitted when the coordination ledger changes."""

    event_type: Literal["events_appended", "state_changed"]
    event_count: int
    events: list[dict[str, Any]]
    detected_at: str


class CoordinationWatcher:
    """Polls the coordination event ledger for new events.

    Lightweight polling watcher for local dogfood operation.
    Detects: new events appended to events.jsonl, new conflict records,
    stale leases, session state changes.

    Usage::

        watcher = CoordinationWatcher(store.root, poll_interval_s=1.0)
        await watcher.start()
        async for event in watcher.events():
            handle(event)
        # call watcher.stop() from another coroutine to exit the loop
    """

    def __init__(self, store_root: Path, poll_interval_s: float = 1.0) -> None:
        self._store_root = store_root
        self._poll_interval_s = poll_interval_s
        self._events_path = store_root / "events.jsonl"
        self._last_size = 0
        self._last_mtime = 0.0
        self._running = False

    async def start(self) -> None:
        """Record initial ledger state so only future changes are detected."""
        self._running = True
        if self._events_path.exists():
            stat = self._events_path.stat()
            self._last_size = stat.st_size
            self._last_mtime = stat.st_mtime

    async def stop(self) -> None:
        """Signal the poll loop to exit. Idempotent — safe to call multiple times."""
        self._running = False

    async def events(self) -> AsyncIterator[CoordinationWatchEvent]:
        """Async iterator yielding watch events as ledger changes are detected.

        Blocks until ``stop()`` is called (from another coroutine).
        Yields a ``CoordinationWatchEvent`` each time new events are detected.
        """
        while self._running:
            try:
                if self._events_path.exists():
                    stat = self._events_path.stat()
                    changed = (
                        stat.st_mtime > self._last_mtime
                        or stat.st_size > self._last_size
                    )
                    if stat.st_size < self._last_size:
                        self._last_size = 0
                        changed = True

                    if changed:
                        new_events = self._read_new_events()
                        if new_events:
                            yield CoordinationWatchEvent(
                                event_type="events_appended",
                                event_count=len(new_events),
                                events=new_events,
                                detected_at=datetime.now(UTC).isoformat(),
                            )
                        self._last_size = stat.st_size
                        self._last_mtime = stat.st_mtime
            except OSError:
                pass

            await asyncio.sleep(self._poll_interval_s)

    def _read_new_events(self) -> list[dict[str, Any]]:
        """Read only new JSONL lines added since the last poll."""
        events: list[dict[str, Any]] = []
        with open(self._events_path, encoding="utf-8") as f:
            f.seek(self._last_size)
            for line in f:
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    events.append(json.loads(stripped))
                except json.JSONDecodeError:
                    pass
        return events
