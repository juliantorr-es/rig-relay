"""Steward domain constants and shared helpers.

Owns: constants, hashing, ISO timestamps, safe path resolution.
No other steward module owns cross-cutting primitives.
"""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
from typing import Any

STEWARD_STATES: tuple[str, ...] = (
    "no_action",
    "blocked",
    "continue_lane",
    "finalize_lane",
    "advance_to_next_lane",
    "audit_unblock_plan",
    "repair_steward_substrate",
)

BLOCKER_CLASSES: tuple[str, ...] = (
    "missing_prompt",
    "malformed_queue_item",
    "dirty_overlap",
    "lane_ownership_collision",
    "failed_gate",
    "gate_unreadable",
    "missing_final_report",
    "missing_required_artifact",
    "schema_validation_failure",
    "test_collection_failure",
    "dependency_policy_violation",
    "forbidden_file_scope",
    "max_attempts_exceeded",
    "unclear_completion_state",
    "context_capsule_invalid",
    "context_capsule_stale",
    "context_compiler_invocation_failed",
    "worker_report_ingestion_failed",
    "lane_projection_invalid",
    "steward_schema_validation_failed",
    "steward_redaction_violation",
    "idle_event_routing_failed",
    "steward_command_construction_failed",
)

_REPAIR_BLOCKER_CLASSES: frozenset[str] = frozenset({
    "context_capsule_invalid",
    "context_capsule_stale",
    "context_compiler_invocation_failed",
    "worker_report_ingestion_failed",
    "lane_projection_invalid",
    "steward_schema_validation_failed",
    "steward_redaction_violation",
    "idle_event_routing_failed",
    "steward_command_construction_failed",
})

_GATE_FAILURE_VERDICTS: frozenset[str] = frozenset({
    "FAIL",
    "BLOCKED",
    "ERROR",
    "PENDING",
    "RUNNING",
})
_RUNNABLE_STATUSES: frozenset[str] = frozenset({"queued", "active", "blocked"})
_LAUNCHABLE_STATES: frozenset[str] = frozenset({
    "continue_lane",
    "advance_to_next_lane",
    "repair_steward_substrate",
})
_BOUNDED_SUMMARY_MAX_CHARS = 200

ROADMAP_DIR = ".rig/roadmap"
QUEUE_PATH = f"{ROADMAP_DIR}/queue.jsonl"
LANES_PATH = f"{ROADMAP_DIR}/lanes.jsonl"
PROMPTS_DIR = f"{ROADMAP_DIR}/prompts"
BUILD_DIR = ".build/rig-relay/derived"
CAPSULE_PATH = f"{BUILD_DIR}/opencode_steward_context_capsule_v1.json"


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def resolve_safe(root: Path, relative: str) -> Path | None:
    resolved = (root / relative).resolve()
    if not str(resolved).startswith(str(root.resolve())):
        return None
    return resolved


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    items: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            items.append(json.loads(stripped))
        except json.JSONDecodeError:
            pass
    return items


def write_jsonl(path: Path, items: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for item in items:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")


def write_last_run(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def append_event(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(data, ensure_ascii=False) + "\n")


def path_overlaps(target: str, dirty_set: set[str]) -> bool:
    if target in dirty_set:
        return True
    for d in dirty_set:
        if d.endswith("/") and target.startswith(d):
            return True
        if target.endswith("/") and d.startswith(target):
            return True
    return False


__all__ = [
    "BLOCKER_CLASSES",
    "BUILD_DIR",
    "CAPSULE_PATH",
    "LANES_PATH",
    "PROMPTS_DIR",
    "QUEUE_PATH",
    "ROADMAP_DIR",
    "STEWARD_STATES",
    "append_event",
    "now_iso",
    "path_overlaps",
    "read_jsonl",
    "resolve_safe",
    "sha256",
    "write_jsonl",
    "write_last_run",
]
