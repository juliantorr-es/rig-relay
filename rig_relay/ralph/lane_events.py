"""Ralph lane events — append-only event ledger + content-addressed receipts.

Events appended to .rig/ralph/lanes/events/ralph_lane_events.jsonl.
Receipts under .rig/ralph/lanes/receipts/receipt_<id>.json.

Content-light: hashes, IDs, status enums. No raw payloads.
No git commands, no worktree creation, no merge.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

LANE_EVENT_VERSION = "rig.ralph_lane_event.v1"
LANE_RECEIPT_VERSION = "rig.ralph_lane_receipt.v1"


class LaneEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = LANE_EVENT_VERSION
    event_id: str = Field(default_factory=lambda: str(uuid4()))
    event_kind: str = ""
    occurred_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    lane_id: str = ""
    mission_id: str = ""
    run_id: str | None = None
    scan_id: str | None = None
    branch_name: str | None = None
    worktree_path: str | None = None
    base_head: str | None = None
    latest_commit_sha: str | None = None
    review_bundle_sha256: str | None = None
    adoption_proposal_id: str | None = None
    status_before: str | None = None
    status_after: str | None = None
    approval_state_before: str | None = None
    approval_state_after: str | None = None
    execution_enabled: bool = False
    merge_enabled: bool = False
    push_enabled: bool = False
    actor_kind: str = "system"
    actor_id: str | None = None
    error_code: str | None = None
    message: str | None = None
    previous_event_sha256: str | None = None
    event_sha256: str = ""

    def compute_sha256(self) -> str:
        payload = self.model_dump_json(
            exclude={"event_sha256", "occurred_at", "event_id"},
            exclude_none=True,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class LaneReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = LANE_RECEIPT_VERSION
    receipt_id: str = Field(default_factory=lambda: str(uuid4()))
    event_id: str = ""
    event_sha256: str = ""
    lane_id: str = ""
    mission_id: str = ""
    event_kind: str = ""
    status_after: str = ""
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    receipt_sha256: str = ""
    execution_enabled: bool = False
    merge_enabled: bool = False

    def compute_sha256(self) -> str:
        payload = self.model_dump_json(
            exclude={"receipt_sha256", "created_at"},
            exclude_none=True,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class LaneEventStore:
    """Append-only lane event ledger + content-addressed receipt store."""

    def __init__(self, root: Path | None = None) -> None:
        self._root = (root or Path(".rig/ralph/lanes")).resolve()
        self._events_path = self._root / "events" / "ralph_lane_events.jsonl"
        self._receipts_dir = self._root / "receipts"
        self._events_path.parent.mkdir(parents=True, exist_ok=True)
        self._receipts_dir.mkdir(parents=True, exist_ok=True)

    def append_event(self, event: LaneEvent) -> LaneEvent:
        event.event_sha256 = event.compute_sha256()
        self._append_jsonl(self._events_path, event.model_dump(mode="json"))
        return event

    def create_receipt(self, event: LaneEvent) -> LaneReceipt:
        receipt = LaneReceipt(
            event_id=event.event_id,
            event_sha256=event.event_sha256,
            lane_id=event.lane_id,
            mission_id=event.mission_id,
            event_kind=event.event_kind,
            status_after=event.status_after or "",
            execution_enabled=False,
            merge_enabled=False,
        )
        receipt.receipt_sha256 = receipt.compute_sha256()
        path = self._receipts_dir / f"receipt_{receipt.receipt_id}.json"
        self._atomic_write(path, receipt.model_dump_json(indent=2))
        return receipt

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
    "LANE_EVENT_VERSION",
    "LANE_RECEIPT_VERSION",
    "LaneEvent",
    "LaneEventStore",
    "LaneReceipt",
]
