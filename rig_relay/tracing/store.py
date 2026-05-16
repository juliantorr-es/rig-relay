"""Trace stores — InMemory, JSONL file, Null (no-op)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import IO, Protocol

from rig_relay.tracing.models import RigTraceEvent
from rig_relay.tracing.redaction import sanitize_trace_attributes


class TraceStore(Protocol):
    def write(self, event: RigTraceEvent) -> None: ...

    def close(self) -> None: ...


def _default_trace_dir() -> Path:
    env_path = os.getenv("RIG_RELAY_TRACE_PATH")
    if env_path:
        return Path(env_path).parent

    app_support = os.path.expanduser("~/Library/Application Support/Rig Relay")
    app_support_path = Path(app_support)
    if app_support_path.exists():
        return app_support_path / "traces"

    return Path(".build") / "rig-relay" / "traces"


class NullTraceStore:
    def write(self, event: RigTraceEvent) -> None:
        pass

    def close(self) -> None:
        pass


class InMemoryTraceStore:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    def write(self, event: RigTraceEvent) -> None:
        self.events.append(event.to_dict())

    def close(self) -> None:
        pass


class JSONLTraceStore:
    def __init__(self, path: Path | None = None) -> None:
        self._path = path or _default_trace_dir() / "trace_events.jsonl"
        self._file: IO[str] | None = None
        self._opened = False

    def _ensure_open(self) -> None:
        if self._opened:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._file = open(str(self._path), "a")
        self._opened = True

    def write(self, event: RigTraceEvent) -> None:
        if not _tracing_enabled():
            return
        self._ensure_open()
        safe = sanitize_trace_attributes(event.to_dict())
        if self._file is not None:
            self._file.write(json.dumps(safe, default=str) + "\n")
            self._file.flush()

    def close(self) -> None:
        if self._file is not None:
            self._file.close()
            self._file = None
        self._opened = False


_TRACE_DISABLED_VALUES: frozenset[str] = frozenset({"0", "false", "no", "off"})


def _tracing_enabled() -> bool:
    val = os.getenv("RIG_RELAY_TRACE", "1")
    return val not in _TRACE_DISABLED_VALUES


def get_default_trace_store() -> JSONLTraceStore:
    return JSONLTraceStore()


__all__ = [
    "InMemoryTraceStore",
    "JSONLTraceStore",
    "NullTraceStore",
    "TraceStore",
    "_tracing_enabled",
    "get_default_trace_store",
]
