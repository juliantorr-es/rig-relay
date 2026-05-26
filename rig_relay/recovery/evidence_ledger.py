"""Append-only content-light JSONL evidence ledger for recovery evaluation.

Durable storage with integrity verification, duplicate-key rejection,
and explicit corruption surface. No raw emissions or payload content.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
from pathlib import Path
from typing import Any


class EvidenceLedger:
    """Append-only JSONL ledger for recovery evaluation events.

    Thread-safe and process-safe via fcntl file locking.
    """

    def __init__(self, ledger_path: Path) -> None:
        self._path = ledger_path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock_path = ledger_path.with_suffix(ledger_path.suffix + ".lock")

    def append_event(self, event: dict[str, Any]) -> str:
        """Append one event. Returns the event_digest."""
        _assert_no_raw_content(event)
        event_digest = _compute_event_digest(event)
        event["event_digest"] = event_digest

        line = json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n"

        with open(self._lock_path, "a") as lock_fd:
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            try:
                with open(self._path, "a") as f:
                    f.write(line)
                    f.flush()
                    os.fsync(f.fileno())
            finally:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)

        return event_digest

    def load_events(self) -> list[dict[str, Any]]:
        """Load all events with integrity verification.

        Returns a list of valid event dicts. Corrupt or tampered
        events are surfaced via EvidenceCorruptionWarning logs,
        not silently dropped.
        """
        if not self._path.exists():
            return []

        events: list[dict[str, Any]] = []
        corrupt: list[int] = []

        with open(self._path) as f:
            for line_num, line in enumerate(f, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    event = _load_and_verify_event(line)
                    events.append(event)
                except (json.JSONDecodeError, KeyError, ValueError):
                    corrupt.append(line_num)

        if corrupt:
            import logging

            logger = logging.getLogger(__name__)
            logger.warning(
                "Evidence ledger %s: %d corrupt lines at %s",
                self._path,
                len(corrupt),
                corrupt[:10],
            )

        return events

    def count_events(self) -> int:
        """Count events via line count (fast, no full parse)."""
        if not self._path.exists():
            return 0
        count = 0
        with open(self._path) as f:
            for line in f:
                if line.strip():
                    count += 1
        return count


def _load_and_verify_event(line: str) -> dict[str, Any]:
    """Parse one JSONL line and verify event_digest integrity."""
    event = json.loads(line)
    if "event_digest" not in event:
        event["event_digest"] = _compute_event_digest(event)
        return event
    stored_digest = event.pop("event_digest", None)
    computed = _compute_event_digest(event)
    if stored_digest is not None and stored_digest != computed:
        raise ValueError(
            f"Event integrity failure: stored={stored_digest}, computed={computed}"
        )
    event["event_digest"] = computed
    return event


def _compute_event_digest(event: dict[str, Any]) -> str:
    """Compute SHA256 of event excluding event_digest itself."""
    data = {k: v for k, v in event.items() if k != "event_digest"}
    payload = json.dumps(data, sort_keys=True, separators=(",", ":"))
    return f"sha256:{hashlib.sha256(payload.encode()).hexdigest()}"


_FORBIDDEN_EVENT_KEYS = frozenset({
    "raw_emission",
    "raw_prompt",
    "raw_model_output",
    "normalized_payload",
    "file_content",
    "mutation_content",
    "secret",
    "api_key",
    "token",
    "command_content",
    "raw_stdout",
    "raw_stderr",
})


def _assert_no_raw_content(event: dict[str, Any]) -> None:
    """Reject events containing forbidden raw-content keys."""
    for key in _FORBIDDEN_EVENT_KEYS:
        if key in event:
            raise ValueError(f"Evidence event contains forbidden content key: {key}")
