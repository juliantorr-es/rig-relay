"""RalphRunStateStore — durable run-state persistence for Ralph HITL.

Provides protocol, in-memory, and filesystem implementations.
All state is content-light: hashes, IDs, status enums, no raw data.

Storage: .rig/ralph/runs/run_<run_id>.json (one file per run)
"""

from __future__ import annotations

from datetime import UTC, datetime
import json
import os
from pathlib import Path
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field


class RalphRunStateRecord(BaseModel):
    """Durable Ralph run state — one per scan cycle."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "rig.ralph_run_state.v1"
    run_id: str = ""
    scan_id: str = ""
    status: str = "idle"
    phase: str = "scan"
    approval_state: str = "not_requested"
    panel_sha256: str = ""
    mission_candidate_sha256: str = ""
    input_snapshot_sha256: str = ""
    selected_candidate_id: str = ""
    decision_id: str = ""
    decision_required: bool = False
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    expires_at: str = ""
    ttl_seconds: int = 3600
    execution_enabled: bool = False
    latest_decision_event_id: str | None = None
    latest_decision_receipt_sha256: str | None = None


@runtime_checkable
class RalphRunStateStore(Protocol):
    """Protocol for persisting and querying Ralph run states."""

    def save_run_state(self, record: RalphRunStateRecord) -> Path: ...
    def load_run_state(self, run_id: str) -> RalphRunStateRecord | None: ...
    def load_current_run_state(self) -> RalphRunStateRecord | None: ...
    def mark_current_run(self, run_id: str) -> None: ...
    def clear_current_run(self) -> None: ...
    def list_run_states(self, limit: int = 20) -> list[RalphRunStateRecord]: ...
    def expire_run_state(self, run_id: str, reason: str) -> None: ...


class InMemoryRalphRunStateStore:
    """In-memory store for tests and transient usage."""

    def __init__(self) -> None:
        self._records: dict[str, RalphRunStateRecord] = {}
        self._current_run_id: str | None = None

    def save_run_state(self, record: RalphRunStateRecord) -> Path:
        self._records[record.run_id] = record
        return Path(f"/memory/run_{record.run_id}")

    def load_run_state(self, run_id: str) -> RalphRunStateRecord | None:
        return self._records.get(run_id)

    def load_current_run_state(self) -> RalphRunStateRecord | None:
        if self._current_run_id:
            return self._records.get(self._current_run_id)
        return None

    def mark_current_run(self, run_id: str) -> None:
        self._current_run_id = run_id

    def clear_current_run(self) -> None:
        self._current_run_id = None

    def list_run_states(self, limit: int = 20) -> list[RalphRunStateRecord]:
        return sorted(self._records.values(), key=lambda r: r.created_at, reverse=True)[
            :limit
        ]

    def expire_run_state(self, run_id: str, reason: str) -> None:
        if run_id in self._records:
            record = self._records[run_id]
            record.approval_state = "expired"
            record.status = "expired"
            record.updated_at = datetime.now(UTC).isoformat()


class FilesystemRalphRunStateStore:
    """Filesystem-backed store under .rig/ralph/runs/."""

    def __init__(self, root: Path | None = None) -> None:
        self._root = (root or Path(".rig/ralph")).resolve()
        self._runs_dir = self._root / "runs"
        self._current_path = self._root / "current_run.json"
        self._runs_dir.mkdir(parents=True, exist_ok=True)

    def save_run_state(self, record: RalphRunStateRecord) -> Path:
        path = self._run_path(record.run_id)
        self._atomic_write(path, record.model_dump_json(indent=2))
        return path

    def load_run_state(self, run_id: str) -> RalphRunStateRecord | None:
        path = self._run_path(run_id)
        if not path.is_file():
            return None
        return RalphRunStateRecord.model_validate_json(path.read_text(encoding="utf-8"))

    def load_current_run_state(self) -> RalphRunStateRecord | None:
        if not self._current_path.is_file():
            return None
        try:
            data = json.loads(self._current_path.read_text(encoding="utf-8"))
            run_id = data.get("run_id", "")
            if run_id:
                return self.load_run_state(run_id)
        except (json.JSONDecodeError, OSError):
            pass
        return None

    def mark_current_run(self, run_id: str) -> None:
        self._atomic_write(self._current_path, json.dumps({"run_id": run_id}, indent=2))

    def clear_current_run(self) -> None:
        if self._current_path.is_file():
            self._current_path.unlink()

    def list_run_states(self, limit: int = 20) -> list[RalphRunStateRecord]:
        records: list[RalphRunStateRecord] = []
        if not self._runs_dir.is_dir():
            return records
        for p in sorted(
            self._runs_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True
        ):
            if not p.is_file():
                continue
            try:
                records.append(
                    RalphRunStateRecord.model_validate_json(
                        p.read_text(encoding="utf-8")
                    )
                )
            except (json.JSONDecodeError, OSError):
                continue
            if len(records) >= limit:
                break
        return records

    def expire_run_state(self, run_id: str, reason: str) -> None:
        record = self.load_run_state(run_id)
        if record is None:
            return
        record.approval_state = "expired"
        record.status = "expired"
        record.updated_at = datetime.now(UTC).isoformat()
        self.save_run_state(record)

    def _run_path(self, run_id: str) -> Path:
        return self._runs_dir / f"run_{run_id}.json"

    @staticmethod
    def _atomic_write(path: Path, content: str) -> None:
        tmp = path.with_suffix(f".tmp.{os.getpid()}")
        try:
            tmp.write_text(content, encoding="utf-8")
            tmp.replace(path)
        finally:
            if tmp.exists():
                tmp.unlink()


__all__ = [
    "FilesystemRalphRunStateStore",
    "InMemoryRalphRunStateStore",
    "RalphRunStateRecord",
    "RalphRunStateStore",
]
