"""Rig Relay Current State Analysis Tool — core module.

Reads the live coordination projection and derived datasets, then emits a
compact content-light JSON cockpit pulse for parent/reviewer agents.

Content-light: never includes raw file contents, prompts, model outputs,
stdout/stderr bodies, or diffs. Uses DuckDB if available; falls back to
stdlib JSONL aggregation.

Provenance (Rig-to-Relay porting doctrine):
  Porting status: relay_native (no Rig origin — designed for Relay).
  See docs/governance/rig-to-relay-pattern-inventory.md for pattern map.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any

import duckdb

from rig_relay.evidence.storage_lifecycle import compute_storage_summary

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_COORD_ROOT = REPO_ROOT / ".build" / "rig-relay" / "coordination"
DEFAULT_DERIVED_DIR = REPO_ROOT / ".build" / "rig-relay" / "derived"
DEFAULT_MAX_CHILDREN = 4

DEFAULT_FORBIDDEN = [
    "raw_file_contents",
    "secrets",
    "raw_private_code",
    "raw_prompt_text",
    "model_output_text",
    "stdout_bodies",
    "stderr_bodies",
]


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    """Read JSONL file, return list of parsed dicts."""
    if not path.is_file():
        return []
    items: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    items.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return items


def _count_jsonl_rows(path: Path) -> int:
    """Count rows in a JSONL file."""
    if not path.is_file():
        return 0
    return _count_lines(path)


def _count_lines(path: Path) -> int:
    if not path.is_file():
        return 0
    with path.open("rb") as f:
        return sum(1 for _ in f)


def _read_derived(path: Path) -> list[dict[str, Any]]:
    """Read derived dataset JSONL using DuckDB."""
    if not path.is_file():
        return []
    try:
        con = duckdb.connect()
        result = con.execute(f"SELECT * FROM read_json_auto('{path}')").fetchdf()
        con.close()
        return result.to_dict(orient="records")
    except Exception:
        return _read_jsonl(path)


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


def _read_coordination_events(root: Path) -> list[dict[str, Any]]:
    """Read coordination events for recent activity."""
    events_path = root / "events.jsonl"
    return _read_jsonl(events_path)


def generate_current_state(
    *,
    coordination_root: Path | None = None,
    derived_dir: Path | None = None,
    sprint_id: str | None = None,
    parent_session_id: str | None = None,
    max_children: int = DEFAULT_MAX_CHILDREN,
) -> dict[str, Any]:
    """Generate a compact current state pulse.

    Returns a content-light current_state dict.
    """
    coord_root = coordination_root or DEFAULT_COORD_ROOT
    ddir = derived_dir or DEFAULT_DERIVED_DIR
    now = datetime.now(UTC)
    warnings: list[str] = []

    sessions = _read_coordination_sessions(coord_root)
    leases = _read_coordination_leases(coord_root)
    events = _read_coordination_events(coord_root)

    coord_rows = _count_jsonl_rows(ddir / "cross_session_coordination_dataset.jsonl")
    artifact_rows = _count_jsonl_rows(ddir / "artifact_reuse_dataset.jsonl")
    conflict_rows = _count_jsonl_rows(ddir / "coordination_conflict_dataset.jsonl")
    checkpoint_rows = _count_jsonl_rows(ddir / "checkpoint_eval_dataset.jsonl")
    tool_failure_rows = _count_jsonl_rows(ddir / "tool_failure_patterns_dataset.jsonl")
    provider_perf_rows = _count_jsonl_rows(
        ddir / "provider_task_performance_dataset.jsonl"
    )
    findings_rows = _count_jsonl_rows(ddir / "findings_dataset.jsonl")

    active_sessions = [
        s for s in sessions if s.get("status") in {"active", "running", "granted"}
    ]
    active_children = len(active_sessions)
    available_child_slots = max(0, max_children - active_children)

    writers = 0
    readers = 0
    for s in active_sessions:
        profile = (s.get("agent_profile") or "").lower()
        if profile in {"implementer", "documenter"}:
            writers += 1
        else:
            readers += 1

    children: list[dict[str, Any]] = []
    stale_leases_count = 0
    conflicts_count = 0
    checkpoint_commits = 0
    checkpoint_refusals = 0

    recent_artifacts: list[dict[str, Any]] = []
    recent_conflicts: list[dict[str, Any]] = []
    stale_items: list[dict[str, Any]] = []

    for event in reversed(events[-200:]):
        name = event.get("event_name", "")
        payload = event.get("payload", {})
        if name == "coord.artifact.published":
            recent_artifacts.append({
                "session_id": payload.get("session_id", ""),
                "artifact_kind": payload.get("artifact_kind", ""),
                "artifact_sha256": payload.get("artifact_sha256", ""),
            })
        elif name == "coord.conflict.reported":
            recent_conflicts.append({
                "conflict_id": payload.get("conflict_id", ""),
                "kind": payload.get("conflict_kind", "conflict"),
                "other_session_id": payload.get("other_session_id"),
            })
            conflicts_count += 1
        elif name == "coord.lease.marked_stale":
            stale_items.append({
                "session_id": payload.get("session_id", ""),
                "kind": "stale_lease",
                "age_seconds": None,
            })
            stale_leases_count += 1
        elif name == "coord.path.reservation_refused":
            conflicts_count += 1
        elif name == "rig.relay.checkpoint.committed":
            checkpoint_commits += 1
        elif name == "rig.relay.checkpoint.refused":
            checkpoint_refusals += 1

    for s in active_sessions:
        sid = s.get("session_id", "")
        profile = s.get("agent_profile", "unknown")
        updated = s.get("updated_at") or s.get("created_at", "")
        heartbeat_age = None
        if updated:
            try:
                hb_time = datetime.fromisoformat(updated)
                heartbeat_age = (now - hb_time).total_seconds()
            except (ValueError, TypeError):
                pass

        session_reservations = [
            l
            for l in leases
            if l.get("session_id") == sid and l.get("status") == "active"
        ]
        reservation_count = len(session_reservations)

        risk = "normal"
        recommended_action = "wait"
        if heartbeat_age is not None and heartbeat_age > 180:
            risk = "critical"
            recommended_action = "mark_stale"
        elif heartbeat_age is not None and heartbeat_age > 90:
            risk = "needs_attention"
            recommended_action = "request_status"

        children.append({
            "session_id": sid,
            "task_id": s.get("task_id"),
            "agent_profile_name": profile,
            "status": s.get("status", "unknown"),
            "current_step": s.get("current_step"),
            "last_heartbeat_age_seconds": round(heartbeat_age, 1)
            if heartbeat_age is not None
            else None,
            "reservation_count": reservation_count,
            "recent_artifact_hashes": [],
            "risk": risk,
            "recommended_parent_action": recommended_action,
        })

    active_reservations: list[dict[str, Any]] = []
    for l in leases:
        if l.get("status") == "active":
            active_reservations.append({
                "session_id": l.get("session_id", ""),
                "mode": l.get("mode", "read"),
                "path_count": len(l.get("paths", [])),
                "status": l.get("status", "active"),
            })

    recommendations: list[str] = []
    if active_children >= max_children:
        recommendations.append(
            f"Active children ({active_children}) at or above max ({max_children}). Wait."
        )
    elif available_child_slots > 0:
        recommendations.append(f"{available_child_slots} child slot(s) available.")
    if writers > 0:
        recommendations.append(
            f"Active writer(s): {writers}. Do not launch another writer in the same checkout."
        )
    if stale_leases_count > 0:
        recommendations.append(f"Inspect {stale_leases_count} stale lease(s).")
    if conflicts_count > 0:
        recommendations.append(f"Inspect {conflicts_count} conflict(s) or refusal(s).")
    if available_child_slots > 0 and writers == 0 and active_children > 0:
        implementer_completed = any(
            s.get("agent_profile") == "implementer" and s.get("status") == "completed"
            for s in sessions
        )
        if implementer_completed:
            recommendations.append("Implementer completed. Consider launching tester.")
    if checkpoint_commits == 0 and writers > 0:
        recommendations.append(
            "No checkpoints committed yet. Consider checkpoint policy."
        )
    if not warnings:
        recommendations.append("Continue monitoring.")
    else:
        recommendations.append("Resolve warnings before launching new work.")

    dataset_completeness: dict[str, int] = {}
    for key, val in [
        ("coordination_rows", coord_rows),
        ("artifact_reuse_rows", artifact_rows),
        ("conflict_rows", conflict_rows),
        ("checkpoint_rows", checkpoint_rows),
        ("tool_failure_rows", tool_failure_rows),
        ("provider_perf_rows", provider_perf_rows),
        ("findings_rows", findings_rows),
    ]:
        if val > 0:
            dataset_completeness[key] = val

    if coord_rows == 0:
        warnings.append("Derived coordination dataset is empty. Run dataset export.")
    if checkpoint_rows == 0 and writers > 0:
        warnings.append("No checkpoint rows in dataset despite active writers.")

    storage_status = compute_storage_summary()

    return {
        "schema_version": "rig.relay.current_state.v1",
        "generated_at": now.isoformat(),
        "scope": "sprint" if sprint_id else "sprint",
        "sprint_id": sprint_id,
        "parent_session_id": parent_session_id,
        "summary": {
            "active_children": active_children,
            "max_children": max_children,
            "available_child_slots": available_child_slots,
            "active_writers": writers,
            "active_readers": readers,
            "conflicts": conflicts_count,
            "stale_leases": stale_leases_count,
            "checkpoint_commits": checkpoint_commits,
            "checkpoint_refusals": checkpoint_refusals,
        },
        "children": children,
        "active_reservations": active_reservations,
        "recent_artifacts": recent_artifacts[:20],
        "recent_conflicts": recent_conflicts[:20],
        "stale_items": stale_items[:20],
        "dataset_completeness": dataset_completeness,
        "storage_status": storage_status,
        "recommendations": recommendations,
        "warnings": warnings if warnings else None,
        "content_policy": "content_light",
        "forbidden_fields": DEFAULT_FORBIDDEN,
    }


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a compact current-state orchestration pulse for parent/reviewer agents."
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
        default=DEFAULT_DERIVED_DIR,
        help="Derived datasets directory (default: .build/rig-relay/derived)",
    )
    parser.add_argument(
        "--sprint-id", type=str, default=None, help="Sprint identifier (optional)"
    )
    parser.add_argument(
        "--parent-session-id",
        type=str,
        default=None,
        help="Parent/reviewer session identifier (optional)",
    )
    parser.add_argument(
        "--max-children",
        type=int,
        default=DEFAULT_MAX_CHILDREN,
        help="Maximum parallel child sessions (default: 4)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output path for current_state JSON (default: .build/rig-relay/current_state.json)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    state = generate_current_state(
        coordination_root=args.coordination_root,
        derived_dir=args.derived_dir,
        sprint_id=args.sprint_id,
        parent_session_id=args.parent_session_id,
        max_children=args.max_children,
    )

    if args.output:
        output_path = args.output
    else:
        output_path = REPO_ROOT / ".build" / "rig-relay" / "current_state.json"

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, sort_keys=True, ensure_ascii=False)
        f.write("\n")

    print(f"Current state generated at {output_path.resolve()}")
    print(f"  Active children: {state['summary']['active_children']}")
    print(f"  Available slots: {state['summary']['available_child_slots']}")
    print(f"  Writers: {state['summary']['active_writers']}")
    print(f"  Conflicts: {state['summary']['conflicts']}")
    print(f"  Recommendations: {len(state['recommendations'])}")
    print("  DuckDB: available (core dependency)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
