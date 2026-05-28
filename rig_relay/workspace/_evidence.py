from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path
from typing import Any

from rig_relay.workspace._digest import compute_event_digest
from rig_relay.workspace.models import WorkspaceLifecycleEvent


class WorkspaceLifecycleLedger:
    def __init__(self, ledger_path: str | Path) -> None:
        self._ledger_path = Path(ledger_path)
        self._ledger_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock_path = self._ledger_path.with_suffix(".jsonl.lock")

    def _last_event(self, workspace_id: str) -> WorkspaceLifecycleEvent | None:
        events = self.load_events(workspace_id)
        return events[-1] if events else None

    def append(self, event: WorkspaceLifecycleEvent) -> str:
        if not event.event_digest:
            event.event_digest = compute_event_digest(event)

        self._ledger_path.touch(exist_ok=True)

        lock_fd: int | None = None
        try:
            lock_fd = os.open(str(self._lock_path), os.O_RDWR | os.O_CREAT, 0o644)
            fcntl.flock(lock_fd, fcntl.LOCK_EX)

            prior = self._last_event(event.workspace_id)
            event.prior_event_digest = prior.event_digest if prior else None

            line_bytes = (event.model_dump_json() + "\n").encode("utf-8")
            with open(self._ledger_path, "ab") as f:
                f.write(line_bytes)
                f.flush()
                os.fsync(f.fileno())
        finally:
            if lock_fd is not None:
                try:
                    fcntl.flock(lock_fd, fcntl.LOCK_UN)
                    os.close(lock_fd)
                except OSError:
                    pass

        return event.event_digest

    def load_events(self, workspace_id: str) -> list[WorkspaceLifecycleEvent]:
        if not self._ledger_path.exists():
            return []

        events: list[WorkspaceLifecycleEvent] = []
        try:
            with open(self._ledger_path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj: dict[str, Any] = json.loads(line)
                    except (json.JSONDecodeError, TypeError):
                        continue
                    if obj.get("workspace_id") != workspace_id:
                        continue
                    try:
                        event = WorkspaceLifecycleEvent.model_validate(obj)
                    except Exception:
                        continue
                    events.append(event)
        except OSError:
            return []

        return events

    def verify_chain(self, workspace_id: str) -> tuple[bool, str]:
        events = self.load_events(workspace_id)
        if not events:
            return (True, "empty chain")

        for i, event in enumerate(events):
            expected = compute_event_digest(event)
            if event.event_digest != expected:
                return (False, f"content tampered at event {event.event_id}")
            if i > 0 and event.prior_event_digest != events[i - 1].event_digest:
                return (False, f"chain broken at event {event.event_id}")

        return (True, "")


__all__ = ["WorkspaceLifecycleLedger"]
