"""Queue read/write for the OpenCode steward.

Owns: queue.jsonl and lanes.jsonl I/O, task status updates.
Does not own: classification logic, git operations, execution.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from rig_relay.cli._steward._constants import (
    LANES_PATH,
    QUEUE_PATH,
    read_jsonl,
    write_jsonl,
)


def read_queue(root: Path) -> list[dict[str, Any]]:
    return read_jsonl(root / QUEUE_PATH)


def read_lanes(root: Path) -> list[dict[str, Any]]:
    return read_jsonl(root / LANES_PATH)


def update_queue_status(root: Path, task_id: str, new_status: str) -> bool:
    queue_path = root / QUEUE_PATH
    items = read_queue(root)
    updated = False
    for item in items:
        if item.get("task_id") == task_id:
            item["status"] = new_status
            updated = True
    if updated:
        write_jsonl(queue_path, items)
    return updated


def active_lane_files(lanes: list[dict[str, Any]]) -> dict[str, str]:
    owned: dict[str, str] = {}
    for lane in lanes:
        if lane.get("status") != "active":
            continue
        lane_id = lane.get("lane_id") or lane.get("task_id") or ""
        for f in lane.get("owned_files") or []:
            owned[f] = lane_id
    return owned


__all__ = ["active_lane_files", "read_lanes", "read_queue", "update_queue_status"]
