from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from rig_relay.events.storage import StorageBackend, _validate_entry


class WriteAheadLog:
    def __init__(self, backend: StorageBackend, wal_path: Path) -> None:
        self._backend = backend
        self._wal_path = wal_path

    def write(self, entry: dict[str, Any]) -> None:
        _validate_entry(entry)
        self._wal_path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(entry, sort_keys=True) + "\n"
        with open(self._wal_path, "a") as f:
            f.write(line)
            f.flush()

    def commit(self) -> int:
        entries = self._read_wal()
        count = 0
        for entry in entries:
            self._backend.append(entry)
            count += 1
        if count > 0:
            self._clear_wal()
        return count

    def recover(self) -> list[dict[str, Any]]:
        return self._read_wal()

    def truncate(self) -> None:
        self._clear_wal()

    def _read_wal(self) -> list[dict[str, Any]]:
        if not self._wal_path.exists():
            return []
        results: list[dict[str, Any]] = []
        with open(self._wal_path) as f:
            for line in f:
                stripped = line.strip()
                if stripped:
                    results.append(json.loads(stripped))
        return results

    def _clear_wal(self) -> None:
        if self._wal_path.exists():
            self._wal_path.write_text("")


__all__ = ["WriteAheadLog"]
