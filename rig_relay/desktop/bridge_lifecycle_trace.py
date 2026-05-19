from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import jsonschema

from rig_relay.desktop.bridge_refusals import (
    MAX_LIFECYCLE_TRACE_FILE_BYTES,
    MAX_LIFECYCLE_TRACE_ROW_BYTES,
)

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_DEFAULT_TRACE_DIR = _REPO_ROOT / ".build" / "rig-relay" / "desktop"

_SCHEMA_PATH = (
    _REPO_ROOT / "docs" / "schemas" / "rig.relay.bridge_lifecycle_event.v1.schema.json"
)


def _load_schema() -> dict[str, Any]:
    return json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))


class BridgeLifecycleTraceWriter:
    _schema: dict[str, Any] | None = None

    def __init__(self, output_path: str | Path | None = None) -> None:
        if output_path is None:
            output_path = _DEFAULT_TRACE_DIR / "lifecycle_trace.jsonl"
        self._output_path = Path(output_path)
        self._total_bytes_written = 0
        self._rejected_row_count = 0

    @property
    def output_path(self) -> Path:
        return self._output_path

    @property
    def total_bytes_written(self) -> int:
        return self._total_bytes_written

    @property
    def rejected_row_count(self) -> int:
        return self._rejected_row_count

    def write_event(self, event: dict[str, Any]) -> None:
        if BridgeLifecycleTraceWriter._schema is None:
            BridgeLifecycleTraceWriter._schema = _load_schema()

        jsonschema.validate(instance=event, schema=BridgeLifecycleTraceWriter._schema)

        line = json.dumps(event, sort_keys=True) + "\n"
        line_bytes = len(line.encode("utf-8"))

        if line_bytes > MAX_LIFECYCLE_TRACE_ROW_BYTES:
            self._rejected_row_count += 1
            logger.warning(
                "audit.lifecycle_trace.row_oversized size=%s max=%s event_id=%s",
                line_bytes,
                MAX_LIFECYCLE_TRACE_ROW_BYTES,
                event.get("event_id", ""),
            )
            raise ValueError(
                f"Lifecycle trace row exceeds maximum size: "
                f"{line_bytes} > {MAX_LIFECYCLE_TRACE_ROW_BYTES} bytes"
            )

        if (
            self._total_bytes_written + line_bytes
            > MAX_LIFECYCLE_TRACE_FILE_BYTES * 0.9
        ):
            logger.warning(
                "audit.lifecycle_trace.file_size_approaching_limit "
                "current=%s warning_threshold=%s",
                self._total_bytes_written + line_bytes,
                int(MAX_LIFECYCLE_TRACE_FILE_BYTES * 0.9),
            )

        self._output_path.parent.mkdir(parents=True, exist_ok=True)

        # flush-only write — no fsync. Rotation is deferred to a future slice.
        with self._output_path.open("a", encoding="utf-8") as f:
            f.write(line)
            f.flush()

        self._total_bytes_written += line_bytes

    def read_events(self) -> list[dict[str, Any]]:
        if not self._output_path.is_file():
            return []
        events: list[dict[str, Any]] = []
        for line in self._output_path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped:
                events.append(json.loads(stripped))
        return events

    def event_count(self) -> int:
        if not self._output_path.is_file():
            return 0
        count = 0
        for line in self._output_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                count += 1
        return count
