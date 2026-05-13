#!/usr/bin/env python3
# ruff: noqa: PLR0912, PLR0914, PLR0915
"""Rig Relay Sprint Cockpit Generator.

Reads available local state and produces a sprint cockpit packet for the
reviewer orchestrator.

Outputs:
    .build/rig-relay/cockpit/current_sprint_cockpit.json
    .build/rig-relay/cockpit/current_sprint_cockpit.md

Usage:
    uv run python scripts/rig_relay_create_sprint_cockpit.py
    uv run python scripts/rig_relay_create_sprint_cockpit.py --output-dir .build/rig-relay/cockpit
    uv run python scripts/rig_relay_create_sprint_cockpit.py --dataset-report .build/rig-relay/reports/dataset-summary.md

Content-light: never includes raw file contents, prompts, model outputs,
stdout/stderr bodies, or diffs.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
BUILD_ROOT = REPO_ROOT / ".build" / "rig-relay"
COORD_EVENTS = BUILD_ROOT / "coordination" / "events.jsonl"
FINDINGS_PATH = REPO_ROOT / "docs" / "findings" / "out-of-scope-findings.jsonl"
DEFAULT_OUTPUT_DIR = BUILD_ROOT / "cockpit"

AVAILABLE_REVIEWER_TOOLS = [
    "rig_relay_read_cockpit",
    "rig_relay_read_coordination_state",
    "rig_relay_read_dataset_report",
    "rig_relay_spawn_session",
    "rig_relay_cancel_session",
    "rig_relay_request_checkpoint",
    "rig_relay_aggregate_reports",
]

DEFAULT_CONSTRAINTS = [
    "max_parallel_sessions=4",
    "no_push",
    "no_direct_git_add_or_commit",
    "one_writer_per_path",
]

DEFAULT_FORBIDDEN = [
    "raw_file_contents",
    "secrets",
    "raw_private_code",
    "raw_prompt_text",
    "model_output_text",
    "stdout_bodies",
    "stderr_bodies",
]

MAX_CHECKPOINTS = 10


def _run_git(args: list[str], cwd: Path | None = None) -> str:
    """Run git command and return stdout stripped."""
    result = subprocess.run(
        ["git"] + args,
        capture_output=True,
        text=True,
        cwd=cwd or REPO_ROOT,
        timeout=10,
    )
    return result.stdout.strip()


def _count_lines(path: Path) -> int:
    """Count lines in a file efficiently."""
    if not path.is_file():
        return 0
    with path.open("rb") as f:
        return sum(1 for _ in f)


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


def _read_findings(path: Path) -> list[dict[str, Any]]:
    """Read findings JSONL, return content-light summary rows."""
    findings = _read_jsonl(path)
    summary: list[dict[str, Any]] = []
    for f in findings:
        summary.append({
            "finding_id": f.get("finding_id", "unknown"),
            "severity": f.get("severity", "unknown"),
            "title": f.get("title", "Untitled"),
        })
    return summary


def _get_repo_state_sha256() -> str:
    """Compute a SHA256 of canonical git state."""
    branch = _run_git(["rev-parse", "--abbrev-ref", "HEAD"])
    head = _run_git(["rev-parse", "HEAD"])
    status = _run_git(["status", "--porcelain=v1"])
    state_str = f"branch={branch}\nhead={head}\nstatus={status}\n"
    return f"sha256:{hashlib.sha256(state_str.encode('utf-8')).hexdigest()}"


def _get_dirty_summary() -> dict[str, int]:
    """Count dirty files from git status."""
    status = _run_git(["status", "--porcelain=v1"])
    lines = [l for l in status.split("\n") if l.strip()]
    tracked_modified = 0
    untracked = 0
    for line in lines:
        if line.startswith("??"):
            untracked += 1
        elif line.strip():
            tracked_modified += 1
    return {
        "tracked_modified_count": tracked_modified,
        "untracked_count": untracked,
        "protected_dirty_count": tracked_modified,
    }


def _get_coordination_summary() -> dict[str, Any]:
    """Read coordination events and produce a summary."""
    if not COORD_EVENTS.is_file():
        return {"available": False}

    events = _read_jsonl(COORD_EVENTS)
    active_sessions: set[str] = set()
    active_tasks: set[str] = set()
    write_leases: int = 0
    conflicts: int = 0
    stale_leases: int = 0

    for event in events:
        name = event.get("event_name", "")
        payload = event.get("payload", {})
        session_id = payload.get("session_id", "")

        if name == "coord.session.registered":
            active_sessions.add(session_id)
        elif name == "coord.session.heartbeat":
            active_sessions.add(session_id)
        elif name == "coord.task.claimed":
            active_tasks.add(payload.get("task_id", ""))
        elif name == "coord.task.released":
            active_tasks.discard(payload.get("task_id", ""))
        elif name == "coord.path.reserved":
            if payload.get("reservation_mode") == "write":
                write_leases += 1
        elif name == "coord.path.released":
            write_leases = max(0, write_leases - 1)
        elif name == "coord.conflict.reported":
            conflicts += 1
        elif name == "coord.lease.marked_stale":
            stale_leases += 1

    return {
        "available": True,
        "active_sessions": len(active_sessions),
        "active_tasks": len(active_tasks),
        "active_write_leases": write_leases,
        "conflicts": conflicts,
        "stale_leases": stale_leases,
        "events_jsonl_path": str(COORD_EVENTS.resolve()) if COORD_EVENTS.is_file() else None,
    }


def _get_dataset_summary(dataset_report_path: Path | None = None) -> dict[str, Any]:
    """Read dataset report Markdown and extract summary metrics."""
    report_path: Path | None = None
    if dataset_report_path and dataset_report_path.is_file():
        report_path = dataset_report_path
    elif (BUILD_ROOT / "reports" / "dataset-summary.md").is_file():
        report_path = BUILD_ROOT / "reports" / "dataset-summary.md"

    if not report_path:
        return {"available": False}

    text = report_path.read_text(encoding="utf-8")

    def _extract(label: str) -> int:
        import re
        m = re.search(rf"\|\s*{label}\s*\|\s*(\d+)", text)
        if m:
            return int(m.group(1))
        coords = set()
        for line in text.split("\n"):
            if "Coord" in line or "coordination" in line.lower():
                m2 = re.search(r"\|\s*(\d+)", line)
                if m2:
                    coords.add(int(m2.group(1)))
        return 0

    return {
        "available": True,
        "sessions": _extract("Sessions observed"),
        "observability_events": _extract("Observability events"),
        "coordination_events": _extract("Coordination events"),
        "tool_calls": _extract("Tool calls"),
        "open_findings": _extract("Open findings"),
        "report_path": str(report_path.resolve()),
    }


def _get_recent_checkpoints() -> list[dict[str, Any]]:
    """Scan observability logs for checkpoint events."""
    checkpoints: list[dict[str, Any]] = []
    sessions_dir = Path.home() / ".rig" / "relay" / "sessions"
    if not sessions_dir.is_dir():
        return checkpoints
    for obs_path in sorted(sessions_dir.glob("*/observability.jsonl")):
        for line in _read_jsonl(obs_path):
            name = line.get("event_name", "")
            if name in {"rig.relay.checkpoint.committed", "rig.relay.checkpoint.refused"}:
                payload = line.get("payload", {})
                checkpoints.append({
                    "session_id": payload.get("session_id", ""),
                    "commit_sha": (
                        payload.get("commit_sha", "")[:12]
                        if name == "rig.relay.checkpoint.committed"
                        else ""
                    ),
                    "files_committed_count": payload.get("files_committed_count", 0),
                    "status": "committed" if name == "rig.relay.checkpoint.committed" else "refused",
                    "created_at": line.get("created_at", ""),
                })
        if len(checkpoints) >= MAX_CHECKPOINTS:
            break
    return checkpoints[-MAX_CHECKPOINTS:]


def _get_active_sessions() -> list[dict[str, Any]]:
    """Read coordination state for active sessions."""
    sessions: list[dict[str, Any]] = []
    sessions_dir = BUILD_ROOT / "coordination" / "sessions"
    if not sessions_dir.is_dir():
        return sessions
    for sf in sorted(sessions_dir.glob("*.json")):
        try:
            data = json.loads(sf.read_text(encoding="utf-8"))
            sessions.append({
                "session_id": data.get("session_id", sf.stem),
                "agent_profile": data.get("agent_profile", "unknown"),
                "task_id": data.get("task_id"),
                "status": data.get("status", "active"),
                "last_heartbeat": data.get("last_heartbeat"),
            })
        except (json.JSONDecodeError, OSError):
            pass
    return sessions


def _get_active_path_reservations() -> list[dict[str, Any]]:
    """Read coordination state for active path reservations."""
    reservations: list[dict[str, Any]] = []
    leases_dir = BUILD_ROOT / "coordination" / "leases"
    if not leases_dir.is_dir():
        return reservations
    for lf in sorted(leases_dir.glob("*.json")):
        try:
            data = json.loads(lf.read_text(encoding="utf-8"))
            reservations.append({
                "session_id": data.get("session_id", ""),
                "path_hashes": data.get("path_hashes", []),
                "mode": data.get("mode", "read"),
                "status": data.get("status", "granted"),
            })
        except (json.JSONDecodeError, OSError):
            pass
    return reservations


def generate_cockpit(
    *,
    output_dir: Path | None = None,
    dataset_report_path: Path | None = None,
    sprint_mission: str = "",
) -> tuple[dict[str, Any], str]:
    """Generate the sprint cockpit packet.

    Returns (packet_dict, markdown_string).
    """
    sprint_id = f"sprint_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}"
    branch = _run_git(["rev-parse", "--abbrev-ref", "HEAD"])
    head = _run_git(["rev-parse", "HEAD"])
    repo_sha = _get_repo_state_sha256()
    dirty = _get_dirty_summary()
    coord = _get_coordination_summary()
    dataset = _get_dataset_summary(dataset_report_path)
    findings = _read_findings(FINDINGS_PATH)
    checkpoints = _get_recent_checkpoints()
    active_sessions = _get_active_sessions()
    active_reservations = _get_active_path_reservations()
    warnings: list[str] = []

    if not coord.get("available"):
        warnings.append("Coordination events not available")
    if not dataset.get("available"):
        warnings.append("Dataset report not available")

    now = datetime.now(UTC).isoformat()

    packet: dict[str, Any] = {
        "schema_version": "rig.relay.sprint_cockpit.v1",
        "sprint_id": sprint_id,
        "branch": branch,
        "head": head,
        "repo_state_sha256": repo_sha,
        "dirty_summary": dirty,
        "coordination_summary": coord,
        "dataset_summary": dataset,
        "open_findings": findings,
        "recent_checkpoints": checkpoints,
        "active_sessions": active_sessions,
        "active_path_reservations": active_reservations,
        "sprint_mission": sprint_mission,
        "constraints": DEFAULT_CONSTRAINTS,
        "available_reviewer_tools": AVAILABLE_REVIEWER_TOOLS,
        "created_at": now,
        "content_policy": "content_light",
        "forbidden_fields": DEFAULT_FORBIDDEN,
        "warnings": warnings if warnings else None,
    }

    # Build Markdown summary
    lines: list[str] = []
    lines.append(f"# Sprint Cockpit: {sprint_id}")
    lines.append("")
    lines.append(f"*Generated: {now}*")
    lines.append("")
    lines.append("## Repository")
    lines.append("")
    lines.append("| Field | Value |")
    lines.append("|-------|-------|")
    lines.append(f"| Branch | `{branch}` |")
    lines.append(f"| HEAD | `{head[:12]}` |")
    lines.append(f"| State SHA256 | `{repo_sha}` |")
    lines.append(f"| Tracked modified | {dirty['tracked_modified_count']} |")
    lines.append(f"| Untracked | {dirty['untracked_count']} |")
    lines.append(f"| Protected dirty | {dirty['protected_dirty_count']} |")
    lines.append("")
    lines.append("## Coordination")
    lines.append("")
    if coord.get("available"):
        lines.append("| Field | Value |")
        lines.append("|-------|-------|")
        lines.append(f"| Active sessions | {coord.get('active_sessions', 0)} |")
        lines.append(f"| Active tasks | {coord.get('active_tasks', 0)} |")
        lines.append(f"| Active write leases | {coord.get('active_write_leases', 0)} |")
        lines.append(f"| Conflicts | {coord.get('conflicts', 0)} |")
        lines.append(f"| Stale leases | {coord.get('stale_leases', 0)} |")
    else:
        lines.append("*Coordination events not available.*")
    lines.append("")
    lines.append("## Dataset")
    lines.append("")
    if dataset.get("available"):
        lines.append("| Field | Value |")
        lines.append("|-------|-------|")
        lines.append(f"| Sessions | {dataset.get('sessions', 0)} |")
        lines.append(f"| Observability events | {dataset.get('observability_events', 0)} |")
        lines.append(f"| Coordination events | {dataset.get('coordination_events', 0)} |")
        lines.append(f"| Tool calls | {dataset.get('tool_calls', 0)} |")
        lines.append(f"| Open findings | {dataset.get('open_findings', 0)} |")
    else:
        lines.append("*Dataset report not available.*")
    lines.append("")
    lines.append("## Open Findings")
    lines.append("")
    if findings:
        lines.append("| ID | Severity | Title |")
        lines.append("|----|----------|-------|")
        for f in findings:
            lines.append(f"| {f['finding_id']} | {f['severity']} | {f['title']} |")
    else:
        lines.append("*No open findings.*")
    lines.append("")
    lines.append("## Recent Checkpoints")
    lines.append("")
    if checkpoints:
        lines.append("| Session | Commit | Files | Status |")
        lines.append("|---------|--------|-------|--------|")
        for c in checkpoints:
            lines.append(f"| {c['session_id'][:12]} | `{c['commit_sha'][:12]}` | {c['files_committed_count']} | {c['status']} |")
    else:
        lines.append("*No recent checkpoints.*")
    lines.append("")
    lines.append("## Active Sessions")
    lines.append("")
    if active_sessions:
        lines.append("| Session | Profile | Task | Status |")
        lines.append("|---------|---------|------|--------|")
        for s in active_sessions:
            lines.append(f"| {s['session_id'][:12]} | {s['agent_profile']} | {s.get('task_id', '-') or '-'} | {s['status']} |")
    else:
        lines.append("*No active sessions.*")
    lines.append("")
    lines.append("## Sprint Mission")
    lines.append("")
    if sprint_mission:
        lines.append(sprint_mission)
    else:
        lines.append("*No sprint mission defined.*")
    lines.append("")
    lines.append("## Constraints")
    lines.append("")
    for c in DEFAULT_CONSTRAINTS:
        lines.append(f"- {c}")
    lines.append("")
    lines.append("## Available Reviewer Tools")
    lines.append("")
    for t in AVAILABLE_REVIEWER_TOOLS:
        lines.append(f"- `{t}`")
    lines.append("")
    if warnings:
        lines.append("## Warnings")
        lines.append("")
        for w in warnings:
            lines.append(f"- {w}")

    markdown = "\n".join(lines)
    return packet, markdown


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate the sprint cockpit packet for the reviewer orchestrator."
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Output directory for cockpit files (default: .build/rig-relay/cockpit)",
    )
    parser.add_argument(
        "--dataset-report",
        type=Path,
        default=None,
        help="Path to dataset report Markdown file",
    )
    parser.add_argument(
        "--sprint-mission",
        type=str,
        default="",
        help="Sprint mission description (optional)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    packet, markdown = generate_cockpit(
        output_dir=output_dir,
        dataset_report_path=args.dataset_report,
        sprint_mission=args.sprint_mission,
    )

    # Write JSON
    json_path = output_dir / "current_sprint_cockpit.json"
    with json_path.open("w", encoding="utf-8") as f:
        json.dump(packet, f, indent=2, sort_keys=True, ensure_ascii=False)
        f.write("\n")

    # Write Markdown
    md_path = output_dir / "current_sprint_cockpit.md"
    md_path.write_text(markdown, encoding="utf-8")

    print(f"Sprint cockpit created at {output_dir.resolve()}")
    print(f"  {json_path.name}")
    print(f"  {md_path.name}")
    print(f"  sprint_id: {packet['sprint_id']}")
    print(f"  branch: {packet['branch']}")
    print(f"  head: {packet['head'][:12]}")
    print(f"  warnings: {len(packet.get('warnings') or [])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
