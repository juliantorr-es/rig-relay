from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any

_ENVELOPE_FIELDS: frozenset[str] = frozenset({
    "schema_version",
    "event_id",
    "event_type",
    "source",
    "occurred_at",
    "producer",
    "correlation_id",
    "causation_id",
    "command_id",
    "trace_id",
    "span_id",
    "sequence",
    "subject",
    "payload_schema",
    "payload_hash",
    "sensitivity_class",
    "redaction_status",
    "content_light",
    "resource_tags",
    "policy_tags",
})


class LogShipper:
    def __init__(self, ship_dir: Path) -> None:
        self._ship_dir = ship_dir
        self._ship_dir.mkdir(parents=True, exist_ok=True)
        self._current_path = self._ship_dir / "ship_current.jsonl"

    def ship_event(self, event: dict[str, Any]) -> None:
        envelope_only = {k: v for k, v in event.items() if k in _ENVELOPE_FIELDS}
        envelope_only["shipped_at"] = datetime.now(UTC).isoformat()
        line = json.dumps(envelope_only, sort_keys=True) + "\n"
        with open(self._current_path, "a") as f:
            f.write(line)
            f.flush()

    def ship_metric_snapshot(self, metrics: dict[str, Any]) -> None:
        entry = {
            "metrics": metrics,
            "shipped_at": datetime.now(UTC).isoformat(),
            "type": "metric_snapshot",
        }
        line = json.dumps(entry, sort_keys=True) + "\n"
        with open(self._current_path, "a") as f:
            f.write(line)
            f.flush()

    def rotate(self) -> Path:
        if not self._current_path.exists() or self._current_path.stat().st_size == 0:
            return self._current_path

        timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        rotated_path = self._ship_dir / f"ship_{timestamp}.jsonl"
        self._current_path.rename(rotated_path)
        return rotated_path

    @property
    def current_path(self) -> Path:
        return self._current_path


__all__ = ["LogShipper"]
