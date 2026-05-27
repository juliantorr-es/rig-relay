"""Append-only content-light JSONL evidence ledger for publication preview receipts.

Durable persistence with fcntl locking, integrity verification, and
content-light enforcement. Every receipt is stored before the governed
result is returned — no silent receipt loss.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
from pathlib import Path
from typing import Any

LEDGER_DIR = Path(".build/rig-relay/publication")
LEDGER_FILE = "publication_preview_evidence.v1.jsonl"


class PublicationEvidenceLedger:
    """Append-only JSONL ledger for publication preview evidence receipts.

    Thread-safe and process-safe via fcntl file locking.
    Durably persists receipts before the service returns results.
    """

    def __init__(self, ledger_path: Path | None = None) -> None:
        if ledger_path is None:
            ledger_path = LEDGER_DIR / LEDGER_FILE
        self._path = ledger_path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock_path = ledger_path.with_suffix(ledger_path.suffix + ".lock")

    def append_receipt(self, receipt_data: dict[str, Any]) -> str:
        """Persist a receipt as a content-light JSONL event.

        Returns the event_digest for the recorded row.
        """
        _assert_content_light(receipt_data)

        event = {
            "schema_version": "rig.relay.publication_preview_event.v1",
            "receipt": receipt_data,
        }
        row_digest = _compute_row_digest(event)
        event["event_digest"] = row_digest

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

        return row_digest

    def load_receipts(self) -> list[dict[str, Any]]:
        """Load all persisted receipts with integrity verification.

        Returns valid receipt data dicts. Corrupt rows produce a warning
        via the logger, not silent drops.
        """
        if not self._path.exists():
            return []

        receipts: list[dict[str, Any]] = []
        corrupt: list[int] = []

        with open(self._path) as f:
            for line_num, line in enumerate(f, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                    _verify_row_integrity(event)
                    receipts.append(event.get("receipt", event))
                except (json.JSONDecodeError, KeyError, ValueError):
                    corrupt.append(line_num)

        if corrupt:
            import logging

            logger = logging.getLogger(__name__)
            logger.warning(
                "Publication evidence ledger %s: %d corrupt lines at %s",
                self._path,
                len(corrupt),
                corrupt[:10],
            )

        return receipts

    def count_receipts(self) -> int:
        """Count persisted receipts (fast, no full parse)."""
        if not self._path.exists():
            return 0
        count = 0
        with open(self._path) as f:
            for line in f:
                if line.strip():
                    count += 1
        return count


def _verify_row_integrity(event: dict[str, Any]) -> None:
    stored = event.pop("event_digest", None)
    computed = _compute_row_digest(event)
    if stored is not None and stored != computed:
        raise ValueError(f"Row integrity failure: stored={stored}, computed={computed}")
    event["event_digest"] = computed


def _compute_row_digest(event: dict[str, Any]) -> str:
    data = {k: v for k, v in event.items() if k != "event_digest"}
    payload = json.dumps(data, sort_keys=True, separators=(",", ":"))
    return f"sha256:{hashlib.sha256(payload.encode()).hexdigest()}"


_FORBIDDEN_RECEIPT_KEYS: frozenset[str] = frozenset({
    "raw_file_contents",
    "raw_prompt",
    "raw_model_output",
    "secret",
    "api_key",
    "token",
    "access_token",
    "private_key",
    "raw_stdout",
    "raw_stderr",
    "file_content",
    "mutation_content",
})


def _assert_content_light(receipt_data: dict[str, Any]) -> None:
    for key in _FORBIDDEN_RECEIPT_KEYS:
        if key in receipt_data:
            raise ValueError(
                f"Publication receipt contains forbidden content key: {key}"
            )
