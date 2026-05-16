"""Ralph decision events — append-only event ledger + content-addressed receipts.

Events are appended to .rig/ralph/events/ralph_decisions.jsonl.
Receipts are individual JSON files under .rig/ralph/receipts/.

Content-light: hashes only, no raw transcripts or file contents.
"""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

DECISION_EVENT_VERSION = "rig.ralph_decision_event.v1"
DECISION_RECEIPT_VERSION = "rig.ralph_decision_receipt.v1"


class DecisionEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = DECISION_EVENT_VERSION
    event_id: str = Field(default_factory=lambda: str(uuid4()))
    event_kind: str = ""
    occurred_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    run_id: str = ""
    scan_id: str = ""
    panel_sha256: str = ""
    mission_candidate_sha256: str = ""
    input_snapshot_sha256: str = ""
    decision_action: str = ""
    approval_state_before: str = "not_requested"
    approval_state_after: str = "not_requested"
    status: str = ""
    error_code: str | None = None
    message: str | None = None
    execution_enabled: bool = False
    actor_kind: str = "user"
    actor_id: str | None = None
    previous_event_sha256: str | None = None
    event_sha256: str = ""

    def compute_sha256(self) -> str:
        payload = self.model_dump_json(
            exclude={"event_sha256", "occurred_at", "event_id"}, exclude_none=True
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class DecisionReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    receipt_schema_version: str = DECISION_RECEIPT_VERSION
    receipt_id: str = Field(default_factory=lambda: str(uuid4()))
    event_id: str = ""
    event_sha256: str = ""
    run_id: str = ""
    scan_id: str = ""
    decision_action: str = ""
    status: str = ""
    error_code: str | None = None
    execution_enabled: bool = False
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    receipt_sha256: str = ""

    def compute_sha256(self) -> str:
        payload = self.model_dump_json(
            exclude={"receipt_sha256", "created_at"}, exclude_none=True
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class DecisionEventStore:
    """Append-only JSONL event ledger + content-addressed receipt store."""

    def __init__(self, root: Path | None = None) -> None:
        self._root = (root or Path(".rig/ralph")).resolve()
        self._events_path = self._root / "events" / "ralph_decisions.jsonl"
        self._receipts_dir = self._root / "receipts"
        self._events_path.parent.mkdir(parents=True, exist_ok=True)
        self._receipts_dir.mkdir(parents=True, exist_ok=True)

    def append_event(self, event: DecisionEvent) -> DecisionEvent:
        event.event_sha256 = event.compute_sha256()
        self._append_jsonl(self._events_path, event.model_dump(mode="json"))
        return event

    def create_receipt(self, event: DecisionEvent) -> DecisionReceipt:
        receipt = DecisionReceipt(
            event_id=event.event_id,
            event_sha256=event.event_sha256,
            run_id=event.run_id,
            scan_id=event.scan_id,
            decision_action=event.decision_action,
            status=event.status,
            error_code=event.error_code,
            execution_enabled=False,
        )
        receipt.receipt_sha256 = receipt.compute_sha256()

        path = self._receipts_dir / f"receipt_{receipt.receipt_id}.json"
        self._atomic_write(path, receipt.model_dump_json(indent=2))
        return receipt

    def list_events(self, limit: int = 50) -> list[DecisionEvent]:
        events: list[DecisionEvent] = []
        if not self._events_path.is_file():
            return events
        for line in self._events_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                events.append(DecisionEvent.model_validate_json(line))
            except Exception:
                continue
        return events[-limit:]

    @staticmethod
    def _append_jsonl(path: Path, data: dict) -> None:
        line = json.dumps(data, sort_keys=True, ensure_ascii=False) + "\n"
        with open(path, "a", encoding="utf-8") as f:
            f.write(line)

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
    "DECISION_EVENT_VERSION",
    "DECISION_RECEIPT_VERSION",
    "DecisionEvent",
    "DecisionEventStore",
    "DecisionReceipt",
]
