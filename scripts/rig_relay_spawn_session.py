#!/usr/bin/env python3
# ruff: noqa: PLR0912, PLR0914, PLR0915
"""Rig Relay Spawn Session Planner.

Validates a mission packet against coordination constraints and returns a
content-light spawn plan. This is the dry-run planner — real subprocess
spawning is deferred to the executor slice.

Usage:
    uv run python scripts/rig_relay_spawn_session.py \\
        --mission-packet .build/rig-relay/missions/my_mission.json \\
        --dry-run \\
        --output .build/rig-relay/spawn/my_plan.json

    uv run python scripts/rig_relay_spawn_session.py \\
        --mission-packet .build/rig-relay/missions/my_mission.json \\
        --dry-run \\
        --coordination-root .build/rig-relay/coordination \\
        --max-parallel-sessions 4

Content-light: never includes raw file contents, prompts, model outputs,
stdout/stderr bodies, or diffs.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
import sys
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent

VALID_PROFILES = {"implementer", "tester", "reviewer", "documenter"}
VALID_CHECKPOINT_POLICIES = {"off", "prompt", "auto"}
WRITER_PROFILES = {"implementer", "documenter"}
READONLY_PROFILES = {"tester", "reviewer"}
DEFAULT_MAX_PARALLEL_SESSIONS = 4
DEFAULT_COORD_ROOT = REPO_ROOT / ".build" / "rig-relay" / "coordination"

DEFAULT_FORBIDDEN = [
    "raw_file_contents",
    "secrets",
    "raw_private_code",
    "raw_prompt_text",
    "model_output_text",
    "stdout_bodies",
    "stderr_bodies",
]


def _try_validate_jsonschema(instance: dict, schema_path: Path) -> list[str]:
    """Validate instance against JSON Schema, return error messages."""
    try:
        import jsonschema
    except ImportError:
        return []
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        validator = jsonschema.Draft7Validator(schema)
        return [e.message for e in validator.iter_errors(instance)]
    except Exception as exc:
        return [f"Schema validation error: {exc}"]


def validate_mission_packet(
    packet: dict[str, Any], schema_path: Path | None = None
) -> list[str]:
    """Validate a mission packet, return list of errors (empty = valid)."""
    errors: list[str] = []

    # Schema validation
    if schema_path and schema_path.is_file():
        schema_errors = _try_validate_jsonschema(packet, schema_path)
        errors.extend(schema_errors)
    else:
        # Fallback required-field check
        required = [
            "schema_version",
            "mission_id",
            "parent_sprint_id",
            "agent_profile",
            "mission_title",
            "instructions",
            "tool_policy",
            "coordination_policy",
            "checkpoint_policy",
            "done_when",
            "max_runtime_seconds",
            "created_at",
        ]
        for field in required:
            if field not in packet or packet.get(field) is None:
                errors.append(f"Missing required field: {field}")

    if errors:
        return errors

    # Semantic validation
    profile = packet.get("agent_profile", "")
    if profile not in VALID_PROFILES:
        errors.append(
            f"Invalid agent_profile '{profile}'. Valid: {sorted(VALID_PROFILES)}"
        )

    ckpt = packet.get("checkpoint_policy", "")
    if ckpt not in VALID_CHECKPOINT_POLICIES:
        errors.append(
            f"Invalid checkpoint_policy '{ckpt}'. Valid: {sorted(VALID_CHECKPOINT_POLICIES)}"
        )

    max_runtime = packet.get("max_runtime_seconds", 0)
    if not isinstance(max_runtime, int) or max_runtime < 1:
        errors.append(
            f"max_runtime_seconds must be a positive integer, got {max_runtime}"
        )

    done_when = packet.get("done_when", [])
    if not isinstance(done_when, list) or len(done_when) == 0:
        errors.append("done_when must be a non-empty list of completion criteria")

    tool_policy = packet.get("tool_policy", {})
    if not isinstance(tool_policy, dict):
        errors.append("tool_policy must be an object")
    else:
        allow_write = tool_policy.get("allow_write", False)
        if profile in READONLY_PROFILES and allow_write:
            errors.append(
                f"Read-only profile '{profile}' cannot request write authority"
            )

        allowed_paths = packet.get("allowed_paths", [])
        if allow_write and (
            not isinstance(allowed_paths, list) or len(allowed_paths) == 0
        ):
            errors.append("Writer missions must have non-empty allowed_paths")

        forbidden = packet.get("forbidden_paths", [])
        if isinstance(allowed_paths, list) and isinstance(forbidden, list):
            overlap = set(allowed_paths) & set(forbidden)
            if overlap:
                errors.append(f"Forbidden paths overlap allowed paths: {overlap}")

        # Validation commands for writer/test profiles
        validation_cmds = packet.get("validation_commands", [])
        if profile in {"implementer", "tester"} and (
            not isinstance(validation_cmds, list) or len(validation_cmds) == 0
        ):
            errors.append(f"Profile '{profile}' should have validation_commands")

        # Checkpoint policy warning for writers
        if profile in WRITER_PROFILES and ckpt == "off":
            pass  # This is a warning, not an error

    return errors


def count_active_children(coordination_root: Path) -> int:
    """Count active child sessions from coordination state."""
    if not coordination_root.is_dir():
        return 0
    sessions_dir = coordination_root / "sessions"
    if not sessions_dir.is_dir():
        return 0
    count = 0
    for sf in sessions_dir.glob("*.json"):
        try:
            data = json.loads(sf.read_text(encoding="utf-8"))
            status = data.get("status", "")
            if status in {"active", "running", "granted"}:
                count += 1
        except (json.JSONDecodeError, OSError):
            pass
    return count


def check_write_overlap(coordination_root: Path, allowed_paths: list[str]) -> list[str]:
    """Check if allowed_paths overlap existing write reservations.

    Compares normalized repo-relative paths from lease JSON files
    against allowed_paths using stable_path_key for cross-process
    deterministic comparison.
    """
    if not coordination_root.is_dir():
        return []
    leases_dir = coordination_root / "leases" / "paths"
    if not leases_dir.is_dir():
        return []
    from vibe.core.coordination._models import stable_path_key

    allowed_stable = {stable_path_key(p) for p in allowed_paths}
    overlapping: list[str] = []
    for lf in leases_dir.glob("*.json"):
        try:
            data = json.loads(lf.read_text(encoding="utf-8"))
            mode = data.get("mode", "")
            status = data.get("status", "")
            if mode != "write" or status not in ("active", "granted"):
                continue
            lease_paths = data.get("paths", [])
            for lp in lease_paths:
                lp_stable = stable_path_key(lp)
                if lp_stable in allowed_stable:
                    overlapping.append(lp_stable)
        except (json.JSONDecodeError, OSError):
            pass
    return overlapping


def check_coordination_available(coordination_root: Path) -> bool:
    """Check if coordination root has events or sessions."""
    events_path = coordination_root / "events.jsonl"
    sessions_path = coordination_root / "sessions"
    return events_path.is_file() or sessions_path.is_dir()


def check_dataset_completeness(derived_dir: Path | None = None) -> list[str]:
    """Check which derived datasets exist, return warnings for missing ones."""
    warnings: list[str] = []
    if derived_dir is None:
        derived_dir = REPO_ROOT / ".build" / "rig-relay" / "derived"
    if not derived_dir.is_dir():
        warnings.append("Derived datasets not found")
        return warnings
    expected = [
        "cross_session_coordination_dataset.jsonl",
        "artifact_reuse_dataset.jsonl",
        "coordination_conflict_dataset.jsonl",
        "checkpoint_eval_dataset.jsonl",
        "tool_failure_patterns_dataset.jsonl",
        "provider_task_performance_dataset.jsonl",
        "findings_dataset.jsonl",
    ]
    for name in expected:
        fpath = derived_dir / name
        if not fpath.is_file():
            warnings.append(f"Derived dataset not found: {name}")
    return warnings


def compute_spawn_plan(
    mission_packet: dict[str, Any],
    *,
    coordination_root: Path | None = None,
    derived_dir: Path | None = None,
    max_parallel_sessions: int = DEFAULT_MAX_PARALLEL_SESSIONS,
    schema_path: Path | None = None,
) -> dict[str, Any]:
    """Compute a spawn plan for the given mission packet.

    Returns a content-light spawn plan dict.
    """
    coord_root = coordination_root or DEFAULT_COORD_ROOT
    warnings: list[str] = []
    now = datetime.now(UTC).isoformat()

    # 1. Validate mission packet
    packet_errors = validate_mission_packet(mission_packet, schema_path)
    if packet_errors:
        # Map specific semantic errors to specific refusal codes
        refusal_code: str | None = None
        refusal_reason: str | None = None
        error_text = "; ".join(packet_errors).lower()

        if "read-only" in error_text and "write" in error_text:
            refusal_code = "read_only_profile_requests_write"
        elif "non-empty allowed_paths" in error_text:
            refusal_code = "empty_allowed_paths_for_writer"
        else:
            refusal_code = "invalid_mission_packet"

        refusal_reason = "; ".join(packet_errors)
        return {
            "schema_version": "rig.relay.spawn_plan.v1",
            "mission_id": mission_packet.get("mission_id", "unknown"),
            "parent_sprint_id": mission_packet.get("parent_sprint_id", "unknown"),
            "parent_review_id": mission_packet.get("parent_review_id"),
            "agent_profile": mission_packet.get("agent_profile", "unknown"),
            "can_spawn": False,
            "refusal_code": refusal_code,
            "refusal_reason": refusal_reason,
            "active_child_count": 0,
            "max_parallel_sessions": max_parallel_sessions,
            "available_child_slots": max_parallel_sessions,
            "would_claim_task": False,
            "would_reserve_paths": False,
            "reservation_mode": None,
            "allowed_path_count": 0,
            "forbidden_path_count": 0,
            "validation_command_count": 0,
            "checkpoint_policy": mission_packet.get("checkpoint_policy", "off"),
            "coordination_policy_summary": None,
            "overlapping_path_hashes": [],
            "warnings": warnings,
            "created_at": now,
            "content_policy": "content_light",
            "forbidden_fields": DEFAULT_FORBIDDEN,
        }

    profile = mission_packet.get("agent_profile", "")
    tool_policy = mission_packet.get("tool_policy", {})
    allow_write = tool_policy.get("allow_write", False)
    allowed_paths = mission_packet.get("allowed_paths", [])
    forbidden_paths = mission_packet.get("forbidden_paths", [])
    validation_cmds = mission_packet.get("validation_commands", [])
    coord_policy = mission_packet.get("coordination_policy", {})
    ckpt_policy = mission_packet.get("checkpoint_policy", "off")

    would_claim_task = coord_policy.get("claim_task", False)
    would_reserve_paths = coord_policy.get("reserve_paths", False)
    reservation_mode = "write" if allow_write else "read"

    allowed_path_count = len(allowed_paths) if isinstance(allowed_paths, list) else 0
    forbidden_path_count = (
        len(forbidden_paths) if isinstance(forbidden_paths, list) else 0
    )
    validation_command_count = (
        len(validation_cmds) if isinstance(validation_cmds, list) else 0
    )

    # 2. Check coordination constraints
    coord_available = check_coordination_available(coord_root)
    active_child_count = count_active_children(coord_root) if coord_available else 0
    available_child_slots = max(0, max_parallel_sessions - active_child_count)

    # 3. Determine refusal
    refusal_code: str | None = None
    refusal_reason: str | None = None

    if profile in READONLY_PROFILES and allow_write:
        refusal_code = "read_only_profile_requests_write"
        refusal_reason = f"Profile '{profile}' is read-only but allow_write is True"

    elif allow_write and allowed_path_count == 0:
        refusal_code = "empty_allowed_paths_for_writer"
        refusal_reason = "Writer mission has no allowed_paths"

    elif active_child_count >= max_parallel_sessions:
        refusal_code = "max_children_exceeded"
        refusal_reason = (
            f"Active children ({active_child_count}) >= "
            f"max_parallel_sessions ({max_parallel_sessions})"
        )

    elif allow_write and would_reserve_paths:
        overlapping = check_write_overlap(coord_root, allowed_paths)
        if overlapping:
            refusal_code = "write_overlap_detected"
            refusal_reason = (
                f"Write overlap detected: {len(overlapping)} existing write leases"
            )

    # Warnings (non-fatal)
    if not coord_available:
        warnings.append("Coordination events not available")
    if profile in WRITER_PROFILES and ckpt_policy == "off":
        warnings.append(
            "Writer mission with checkpoint_policy 'off' — changes may be uncommitted"
        )
    if profile in {"implementer", "tester"} and validation_command_count == 0:
        warnings.append(f"Profile '{profile}' has no validation commands")

    derived_warnings = check_dataset_completeness(derived_dir)
    warnings.extend(derived_warnings)

    can_spawn = refusal_code is None

    # Coordination policy summary
    coord_summary_parts = []
    if coord_policy.get("claim_task"):
        coord_summary_parts.append("claim_task")
    if coord_policy.get("reserve_paths"):
        coord_summary_parts.append(f"reserve_paths({reservation_mode})")
    if coord_policy.get("heartbeat"):
        coord_summary_parts.append("heartbeat")
    coord_summary = ", ".join(coord_summary_parts) if coord_summary_parts else None

    return {
        "schema_version": "rig.relay.spawn_plan.v1",
        "mission_id": mission_packet.get("mission_id", ""),
        "parent_sprint_id": mission_packet.get("parent_sprint_id", ""),
        "parent_review_id": mission_packet.get("parent_review_id"),
        "agent_profile": profile,
        "can_spawn": can_spawn,
        "refusal_code": refusal_code,
        "refusal_reason": refusal_reason,
        "active_child_count": active_child_count,
        "max_parallel_sessions": max_parallel_sessions,
        "available_child_slots": available_child_slots,
        "would_claim_task": would_claim_task,
        "would_reserve_paths": would_reserve_paths,
        "reservation_mode": reservation_mode if would_reserve_paths else None,
        "allowed_path_count": allowed_path_count,
        "forbidden_path_count": forbidden_path_count,
        "validation_command_count": validation_command_count,
        "checkpoint_policy": ckpt_policy,
        "coordination_policy_summary": coord_summary,
        "overlapping_path_hashes": [],
        "warnings": warnings if warnings else None,
        "created_at": now,
        "content_policy": "content_light",
        "forbidden_fields": DEFAULT_FORBIDDEN,
    }


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Spawn session planner — validates mission packets against coordination constraints."
    )
    parser.add_argument(
        "--mission-packet", type=Path, required=True, help="Path to mission_packet.json"
    )
    parser.add_argument(
        "--coordination-root",
        type=Path,
        default=DEFAULT_COORD_ROOT,
        help="Coordination store root (default: .build/rig-relay/coordination)",
    )
    parser.add_argument(
        "--derived-dir",
        type=Path,
        default=None,
        help="Derived datasets directory (default: .build/rig-relay/derived)",
    )
    parser.add_argument(
        "--max-parallel-sessions",
        type=int,
        default=DEFAULT_MAX_PARALLEL_SESSIONS,
        help="Maximum parallel child sessions (default: 4)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Required — dry-run validation only (real spawning is future work)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output path for spawn plan JSON (default: .build/rig-relay/spawn/<mission_id>/spawn_plan.json)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    # Read mission packet
    if not args.mission_packet.is_file():
        print(
            f"ERROR: Mission packet not found: {args.mission_packet}", file=sys.stderr
        )
        return 1

    try:
        mission_packet = json.loads(args.mission_packet.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"ERROR: Invalid mission packet JSON: {exc}", file=sys.stderr)
        return 1

    # Schema path
    schema_path = (
        REPO_ROOT / "docs" / "schemas" / "rig.relay.mission_packet.v1.schema.json"
    )

    # Compute plan
    plan = compute_spawn_plan(
        mission_packet,
        coordination_root=args.coordination_root,
        derived_dir=args.derived_dir,
        max_parallel_sessions=args.max_parallel_sessions,
        schema_path=schema_path if schema_path.is_file() else None,
    )

    # Determine output path
    if args.output:
        output_path = args.output
    else:
        mission_id = plan.get("mission_id", "unknown")
        output_path = (
            REPO_ROOT
            / ".build"
            / "rig-relay"
            / "spawn"
            / mission_id
            / "spawn_plan.json"
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(plan, f, indent=2, sort_keys=True, ensure_ascii=False)
        f.write("\n")

    status = "APPROVED" if plan["can_spawn"] else "REFUSED"
    print(f"Spawn plan: {status}")
    print(f"  Mission: {plan['mission_id']}")
    print(f"  Profile: {plan['agent_profile']}")
    if plan["refusal_code"]:
        print(f"  Refusal: {plan['refusal_code']} — {plan['refusal_reason']}")
    print(f"  Active children: {plan['active_child_count']}")
    print(f"  Available slots: {plan['available_child_slots']}")
    print(f"  Warnings: {len(plan.get('warnings') or [])}")
    print(f"  Output: {output_path.resolve()}")

    if not args.dry_run:
        print(
            "NOTE: --dry-run is required. Real subprocess spawning is future work.",
            file=sys.stderr,
        )

    return 0 if plan["can_spawn"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
