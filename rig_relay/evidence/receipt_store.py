"""ReceiptStore protocol and filesystem-backed implementation.

Provides append/get/list operations on ReceiptEnvelope objects, stored as
canonical JSON files in a structured directory hierarchy.

Pattern source: Rig's ReceiptStore protocol and FilesystemReceiptStore
(receipts.py), but adapted to Rig Relay's Pydantic ReceiptEnvelope and
content-light conventions.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol, runtime_checkable

from rig_relay.evidence.receipt_envelope import ReceiptEnvelope


@runtime_checkable
class ReceiptStore(Protocol):
    """Protocol for persisting and querying receipt envelopes.

    Implementations store ReceiptEnvelope objects and provide
    append/get/list operations.
    """

    def append(self, envelope: ReceiptEnvelope) -> Path:
        """Persist a receipt envelope and return its file path."""
        ...

    def get(self, envelope_id: str) -> ReceiptEnvelope | None:
        """Retrieve a receipt envelope by ID, or None if not found."""
        ...

    def list(
        self, limit: int = 100, offset: int = 0
    ) -> list[ReceiptEnvelope]:
        """List receipt envelopes ordered by creation time (newest first)."""
        ...

    def list_by_session(
        self, session_id: str, limit: int = 100, offset: int = 0
    ) -> list[ReceiptEnvelope]:
        """List receipt envelopes for a given session ID."""
        ...

    def count(self) -> int:
        """Return the total number of stored receipt envelopes."""
        ...


class FilesystemReceiptStore:
    """Filesystem-backed receipt store.

    Stores envelopes as canonical JSON files under ``root/envelopes/``,
    sharded by first two hex characters of the envelope ID for
    directory performance.

    A manifest at ``root/manifest.jsonl`` maintains an append-only
    ordered index for efficient list/query without directory walks.
    """

    def __init__(self, root: Path) -> None:
        self._root = root.resolve()
        self._envelopes_dir = self._root / "envelopes"
        self._manifest_path = self._root / "manifest.jsonl"
        self._envelopes_dir.mkdir(parents=True, exist_ok=True)

    # ── Public API ──────────────────────────────────────────────────

    def append(self, envelope: ReceiptEnvelope) -> Path:
        """Persist a receipt envelope and return its file path.

        The envelope is written as canonical JSON to a sharded path.
        The manifest is appended atomically.
        """
        path = self._envelope_path(envelope.envelope_id)
        path.parent.mkdir(parents=True, exist_ok=True)

        data = envelope.model_dump(mode="json")
        path.write_text(json.dumps(data, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")

        manifest_line = json.dumps({
            "envelope_id": envelope.envelope_id,
            "receipt_kind": envelope.receipt_kind,
            "session_id": envelope.subject.session_id,
            "created_at": envelope.created_at,
        }, sort_keys=True)
        with self._manifest_path.open("a", encoding="utf-8") as f:
            f.write(manifest_line + "\n")

        return path

    def get(self, envelope_id: str) -> ReceiptEnvelope | None:
        path = self._envelope_path(envelope_id)
        if not path.is_file():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return ReceiptEnvelope.model_validate(data)
        except (json.JSONDecodeError, ValueError, KeyError):
            return None

    def list(
        self, limit: int = 100, offset: int = 0
    ) -> list[ReceiptEnvelope]:
        return self._list_from_manifest(limit=limit, offset=offset)

    def list_by_session(
        self, session_id: str, limit: int = 100, offset: int = 0
    ) -> list[ReceiptEnvelope]:
        return self._list_from_manifest(
            session_id=session_id, limit=limit, offset=offset
        )

    def count(self) -> int:
        return self._manifest_line_count()

    # ── Internal helpers ────────────────────────────────────────────

    def _envelope_path(self, envelope_id: str) -> Path:
        return self._envelopes_dir / envelope_id[:2] / f"{envelope_id}.json"

    def _manifest_line_count(self) -> int:
        if not self._manifest_path.is_file():
            return 0
        count = 0
        with self._manifest_path.open("r", encoding="utf-8") as f:
            for _ in f:
                count += 1
        return count

    def _list_from_manifest(
        self,
        session_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ReceiptEnvelope]:
        if not self._manifest_path.is_file():
            return []

        entries: list[dict[str, str]] = []
        with self._manifest_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if session_id and entry.get("session_id") != session_id:
                    continue
                entries.append(entry)

        # Newest first (manifest is append-only, so reverse)
        entries.reverse()
        sliced = entries[offset:offset + limit]

        result: list[ReceiptEnvelope] = []
        for entry in sliced:
            env = self.get(entry["envelope_id"])
            if env is not None:
                result.append(env)
        return result


__all__ = [
    "FilesystemReceiptStore",
    "ReceiptStore",
]
