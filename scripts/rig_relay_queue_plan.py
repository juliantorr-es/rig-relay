#!/usr/bin/env python3
# ruff: noqa: PLR0912, PLR0914, PLR0915
"""Rig Relay Queue Planner.

Reads a pending work queue and coordination state, then computes a ready work plan
separating items into ready (dispatchable now), blocked (with reasons), and waiting
(for dependencies/leases).

This is a dry-run planner only — it does NOT dispatch child sessions or mutate state.

Usage:
    uv run python scripts/rig_relay_queue_plan.py \\
        --queue .build/rig-relay/queue/work_queue.json \\
        --coordination-root .build/rig-relay/coordination \\
        --max-items 4 \\
        --output .build/rig-relay/queue/ready_plan.json

Content-light: never includes raw file contents, prompts, model outputs, stdout/stderr
bodies, or diffs.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_COORD_ROOT = REPO_ROOT / ".build" / "rig-relay" / "coordination"
DEFAULT_QUEUE_DIR = REPO_ROOT / ".build" / "rig-relay" / "queue"
DEFAULT_MAX_ITEMS = 4

DEFAULT_FORBIDDEN = [
    "raw_file_contents",
    "secrets",
    "raw_private_code",
    "raw_prompt_text",
    "model_output_text",
    "stdout_bodies",
    "stderr_bodies",
]


def _read_json(path: Path) -> dict[str, Any]:
    """Read and parse a JSON file."""
    return json.loads(path.read_text(encoding="utf-8"))


def _read_coordination_leases(root: Path) -> list[dict[str, Any]]:
    """Read lease (reservation) files from coordination store."""
    leases_dir = root / "leases" / "paths"
    if not leases_dir.is_dir():
        return []
    leases: list[dict[str, Any]] = []
    for lf in sorted(leases_dir.glob("*.json")):
        try:
            leases.append(json.loads(lf.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            pass
    return leases


def _read_coordination_sessions(root: Path) -> list[dict[str, Any]]:
    """Read session state files from coordination store."""
    sessions_dir = root / "sessions"
    if not sessions_dir.is_dir():
        return []
    sessions: list[dict[str, Any]] = []
    for sf in sorted(sessions_dir.glob("*.json")):
        try:
            sessions.append(json.loads(sf.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            pass
    return sessions


def _get_active_write_paths(leases: list[dict[str, Any]]) -> set[str]:
    """Get set of path hashes for active write leases."""
    paths: set[str] = set()
    for l in leases:
        if l.get("status") == "active" and l.get("mode") == "write":
            for p in l.get("paths", []):
                paths.add(p)
    return paths


def _dependencies_completed(
    item: dict[str, Any], completed_ids: set[str], failed_ids: set[str]
) -> bool:
    """Check if all dependencies are completed (not failed/blocked)."""
    for dep in item.get("dependencies", []):
        dep_id = dep.get("work_item_id", "")
        if dep_id in failed_ids:
            return False
        if dep_id not in completed_ids:
            return False
    return True


def compute_ready_plan(
    queue: dict[str, Any],
    *,
    coordination_root: Path | None = None,
    max_items: int = DEFAULT_MAX_ITEMS,
    profiles: list[str] | None = None,
) -> dict[str, Any]:
    """Compute a ready work plan from the work queue.

    Reads the queue and coordination state, then separates items into ready,
    blocked, and waiting. Returns a content-light ready_work_plan dict.
    """
    coord_root = coordination_root or DEFAULT_COORD_ROOT
    now = datetime.now(UTC)
    warnings: list[str] = []

    # Read coordination state
    leases = _read_coordination_leases(coord_root)
    sessions = _read_coordination_sessions(coord_root)
    active_write_paths = _get_active_write_paths(leases)

    # Build sets of completed and failed work item IDs
    work_items: list[dict[str, Any]] = queue.get("work_items", [])
    completed_ids: set[str] = set()
    failed_ids: set[str] = set()
    work_item_map: dict[str, dict[str, Any]] = {}

    for wi in work_items:
        wid = wi.get("work_item_id", "")
        work_item_map[wid] = wi
        status = wi.get("status", "")
        if status == "completed":
            completed_ids.add(wid)
        elif status in {"failed", "refused", "cancelled", "superseded"}:
            failed_ids.add(wid)

    # Active session count from coordination state
    active_sessions = [
        s for s in sessions if s.get("status") in {"active", "running", "granted"}
    ]
    active_count = len(active_sessions)
    max_parallel = queue.get("max_parallel_children", 4)
    available_slots = max(0, max_parallel - active_count)

    # Separate items
    ready_items: list[dict[str, Any]] = []
    blocked_items: list[dict[str, Any]] = []
    waiting_items: list[dict[str, Any]] = []

    # Sort by priority (lower = higher priority)
    sorted_items = sorted(
        work_items, key=lambda w: (w.get("priority", 50), w.get("work_item_id", ""))
    )

    for wi in sorted_items:
        wid = wi.get("work_item_id", "")
        status = wi.get("status", "pending")
        title = wi.get("title", "untitled")
        profile = wi.get("agent_profile", "")
        allowed_paths: list[str] = wi.get("allowed_paths", [])
        allow_write = wi.get("tool_policy", {}).get("allow_write", False)

        # Skip terminal items
        if status in {"completed", "failed", "refused", "cancelled", "superseded"}:
            continue

        # Skip already active items
        if status in {"claimed", "dispatched", "running"}:
            continue

        # Profile filter
        if profiles is not None and profile and profile not in profiles:
            continue

        # Check if blocked
        if status == "blocked":
            blocked_reason = "; ".join(wi.get("blocked_by", ["manually blocked"]))
            blocked_items.append({
                "work_item_id": wid,
                "title": title,
                "blocked_reason": blocked_reason,
            })
            continue

        # Check dependency status
        if not _dependencies_completed(wi, completed_ids, failed_ids):
            dep_ids = [d.get("work_item_id", "") for d in wi.get("dependencies", [])]
            waiting_items.append({
                "work_item_id": wid,
                "title": title,
                "waiting_reason": "Waiting for dependencies to complete",
                "waiting_on_ids": dep_ids,
            })
            continue

        # Check specific waiting/blocked statuses
        if status == "waiting_dependency":
            dep_ids = [d.get("work_item_id", "") for d in wi.get("dependencies", [])]
            waiting_items.append({
                "work_item_id": wid,
                "title": title,
                "waiting_reason": "Waiting for dependencies to complete",
                "waiting_on_ids": dep_ids,
            })
            continue

        if status == "waiting_lease":
            waiting_items.append({
                "work_item_id": wid,
                "title": title,
                "waiting_reason": "Waiting for path leases to become available",
                "waiting_on_ids": [],
            })
            continue

        if status == "waiting_validation_stage":
            waiting_items.append({
                "work_item_id": wid,
                "title": title,
                "waiting_reason": "Waiting for validation stage",
                "waiting_on_ids": [],
            })
            continue

        # Check write path overlap
        if allow_write and allowed_paths:
            overlapping = [p for p in allowed_paths if p in active_write_paths]
            if overlapping:
                waiting_items.append({
                    "work_item_id": wid,
                    "title": title,
                    "waiting_reason": f"Write path(s) overlap active leases: {overlapping}",
                    "waiting_on_ids": [],
                })
                continue

        # Check available slots (cap by both max_items and available_slots)
        if len(ready_items) >= max_items or (
            available_slots > 0 and len(ready_items) >= available_slots
        ):
            break

        # Item is ready
        ready_items.append({
            "work_item_id": wid,
            "title": title,
            "agent_profile": profile,
            "execution_mode": wi.get("execution_mode", "delegate"),
            "allowed_paths": allowed_paths,
            "forbidden_paths": wi.get("forbidden_paths", []),
            "tool_policy": wi.get("tool_policy", {}),
            "coordination_policy": wi.get("coordination_policy", {}),
            "checkpoint_policy": wi.get("checkpoint_policy", "off"),
            "validation_commands": wi.get("validation_commands", []),
            "done_when": wi.get("done_when", []),
            "priority": wi.get("priority", 50),
            "parallelism_policy": wi.get("parallelism_policy")
            or {"mode": "parallel_if_safe", "max_parallel_children": 4},
        })

    # Deterministic recommendations
    recommendations: list[str] = []
    if ready_items:
        recommendations.append(
            f"dispatch_ready_work: {len(ready_items)} item(s) ready."
        )
    if blocked_items:
        recommendations.append(
            f"inspect_blocked_items: {len(blocked_items)} item(s) blocked."
        )
    if waiting_items:
        has_dep = any(
            w.get("waiting_reason", "").startswith("Waiting for dependencies")
            for w in waiting_items
        )
        has_lease = any(
            w.get("waiting_reason", "").startswith("Write path") for w in waiting_items
        )
        if has_dep:
            recommendations.append(
                "wait_for_dependencies: Some items waiting for dependencies."
            )
        if has_lease:
            recommendations.append(
                "inspect_write_lease_conflicts: Some items waiting for path leases."
            )
    if available_slots == 0:
        recommendations.append(
            "run_current_state: No available slots. Check current state."
        )
    if not ready_items and not blocked_items and not waiting_items:
        recommendations.append("no_ready_work: No items to process.")

    if not coord_root.exists():
        warnings.append("Coordination root does not exist.")

    return {
        "schema_version": "rig.relay.ready_work_plan.v1",
        "sprint_id": queue.get("sprint_id", ""),
        "generated_at": now.isoformat(),
        "max_items": max_items,
        "ready_items": ready_items,
        "blocked_items": blocked_items,
        "waiting_items": waiting_items,
        "active_count": active_count,
        "available_slots": available_slots,
        "recommendations": recommendations,
        "warnings": warnings,
        "content_policy": "content_light",
        "forbidden_fields": DEFAULT_FORBIDDEN,
    }


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compute a ready work plan from the pending work queue."
    )
    parser.add_argument(
        "--queue", type=Path, required=True, help="Path to the work queue JSON file."
    )
    parser.add_argument(
        "--coordination-root",
        type=Path,
        default=DEFAULT_COORD_ROOT,
        help="Coordination store root (default: .build/rig-relay/coordination)",
    )
    parser.add_argument(
        "--max-items",
        type=int,
        default=DEFAULT_MAX_ITEMS,
        help="Maximum ready items to return (default: 4)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output path for the ready plan JSON (default: .build/rig-relay/queue/ready_plan.json)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    if not args.queue.is_file():
        print(f"Error: Queue file not found: {args.queue}")
        return 1

    queue = _read_json(args.queue)
    plan = compute_ready_plan(
        queue, coordination_root=args.coordination_root, max_items=args.max_items
    )

    if args.output:
        output_path = args.output
    else:
        output_path = DEFAULT_QUEUE_DIR / "ready_plan.json"

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(plan, f, indent=2, sort_keys=True, ensure_ascii=False)
        f.write("\n")

    print(f"Ready plan generated at {output_path.resolve()}")
    print(f"  Ready items: {len(plan['ready_items'])}")
    print(f"  Blocked items: {len(plan['blocked_items'])}")
    print(f"  Waiting items: {len(plan['waiting_items'])}")
    print(f"  Active children: {plan['active_count']}")
    print(f"  Available slots: {plan['available_slots']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
