"""OpenCode Idle Lane Steward — canonical Rig Relay CLI command.

Bounded foreman for OpenCode that reads the roadmap queue, selects one safe task,
launches OpenCode in streaming mode, writes content-light event records, and
updates queue status after completion.

Usage:
  uv run rig-relay steward --dry-run
  uv run rig-relay steward --show-reasoning-stream
  uv run python -m rig_relay.cli.steward --project-root . --worktree default
"""

from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
from typing import Any

from rig_relay.cli._steward._capsule import compile_capsule, read_capsule
from rig_relay.cli._steward._classification import classify_state, select_task
from rig_relay.cli._steward._constants import (
    _LAUNCHABLE_STATES,
    _RUNNABLE_STATUSES,
    BUILD_DIR,
    CAPSULE_PATH,
    STEWARD_STATES,
    append_event,
    now_iso,
    write_last_run,
)
from rig_relay.cli._steward._execution import try_launch
from rig_relay.cli._steward._queue import read_lanes, read_queue, update_queue_status
from rig_relay.cli._steward._traces import StewardTrace


def git_branch(root: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            cwd=root,
            timeout=10,
        )
        return result.stdout.strip()
    except Exception:
        return "unknown"


def git_head(root: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            cwd=root,
            timeout=10,
        )
        return result.stdout.strip()
    except Exception:
        return "unknown"


def git_dirty(root: Path) -> dict[str, Any]:
    dirty_files: list[str] = []
    modified = staged = untracked = 0
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain=v1"],
            capture_output=True,
            text=True,
            cwd=root,
            timeout=10,
        )
        for line in result.stdout.strip().split("\n"):
            if not line:
                continue
            dirty_files.append(line)
            x, y = line[:2] if len(line) >= 2 else (" ", " ")
            if x != " ":
                staged += 1
            if y != " ":
                modified += 1
            if x == "?" and y == "?":
                untracked += 1
    except Exception:
        pass
    return {
        "modified_count": modified,
        "staged_count": staged,
        "untracked_count": untracked,
        "dirty_files": dirty_files,
    }


def dirty_files_set(dirty: dict[str, Any]) -> set[str]:
    files: set[str] = set()
    for line in dirty.get("dirty_files", []):
        path = line[3:].strip()
        if path:
            files.add(path)
    return files


def build_dirty_summary(dirty: dict[str, Any]) -> dict[str, Any]:
    return {
        "modified_count": dirty.get("modified_count", 0),
        "staged_count": dirty.get("staged_count", 0),
        "untracked_count": dirty.get("untracked_count", 0),
        "dirty_files": dirty.get("dirty_files", []),
    }


def write_run_and_event(
    last_run_path: Path,
    events_path: Path,
    state: str,
    root: Path,
    dry_run: bool,
    branch: str,
    head: str,
    dirty: dict[str, Any],
    *,
    blockers: list[str] | None = None,
    item: dict[str, Any] | None = None,
    comp: dict[str, Any] | None = None,
    command_meta: dict[str, Any] | None = None,
    audit_path: str | None = None,
    error: str | None = None,
    compiler_fallback_status: str | None = None,
) -> None:
    run_data = {
        "schema_version": "rig.relay.opencode_idle_steward_run.v1",
        "generated_at": now_iso(),
        "project_root": str(root),
        "worktree": "default",
        "steward_state": state,
        "dry_run": dry_run,
        "branch": branch,
        "head": head,
        "dirty_state_summary": build_dirty_summary(dirty),
        "blocker_reasons": blockers or [],
        "selected_task": {
            "task_id": item.get("task_id", ""),
            "title": item.get("title", ""),
            "status": item.get("status", ""),
            "priority": item.get("priority", 0),
        }
        if item
        else None,
        "command_meta": command_meta,
        "completion_check": comp,
        "audit_path": audit_path,
        "error": error,
        "compiler_fallback_status": compiler_fallback_status,
    }
    write_last_run(last_run_path, run_data)
    append_event(
        events_path,
        {
            "event": "steward_run",
            "state": state,
            "generated_at": run_data["generated_at"],
            "reason": "steward_run",
            "selected_task_id": item.get("task_id") if item else None,
            "compiler_fallback_status": compiler_fallback_status,
        },
    )


def _write_audit(
    root: Path,
    build_dir: Path,
    items: list[dict[str, Any]],
    lanes: list[dict[str, Any]],
    dirty: dict[str, Any],
    branch: str,
    head: str,
) -> str:
    from rig_relay.cli._steward._classification import build_audit as _build

    dirty_fs = dirty_files_set(dirty)
    audit = _build(root, items, lanes, dirty, dirty_fs, branch, head)
    audit_path = build_dir / "opencode_idle_steward_unblock_audit_v1.json"
    candidates_path = build_dir / "opencode_idle_steward_unblock_candidates_v1.jsonl"
    write_last_run(audit_path, audit)
    for task in audit.get("per_task_blockers") or []:
        append_event(
            candidates_path,
            {
                "event": "unblock_candidate",
                "task_id": task.get("task_id", ""),
                "blocker_classes": task.get("blocker_classes", []),
                "generated_at": audit["generated_at"],
            },
        )

    return str(audit_path)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    root = args.project_root.resolve()
    dry_run = args.dry_run
    show_reasoning = args.show_reasoning_stream
    no_stream = args.no_stream
    opencode_path = args.opencode_path

    build_dir = root / BUILD_DIR
    last_run_path = build_dir / "opencode_idle_steward_last_run_v1.json"
    events_path = build_dir / "opencode_idle_steward_events_v1.jsonl"
    capsule_path = root / CAPSULE_PATH

    trace = StewardTrace(task_id="", project_root=str(root))
    trace.start()

    capsule, compiler_fallback_status = read_capsule(root)
    trace.event(
        "capsule_read",
        {
            "fallback_status": compiler_fallback_status,
            "capsule_id": capsule.get("capsule_id", "") if capsule else "none",
        },
    )

    trace.span("git_scan")
    dirty = git_dirty(root)
    branch = git_branch(root)
    head = git_head(root)
    trace.end_span("git_scan")

    trace.span("queue_read")
    items = read_queue(root)
    lanes = read_lanes(root)
    trace.end_span("queue_read")

    if not items:
        write_run_and_event(
            last_run_path,
            events_path,
            "no_action",
            root,
            dry_run,
            branch,
            head,
            dirty,
            blockers=["no_queue_items"],
            compiler_fallback_status=compiler_fallback_status,
        )
        trace.finish("no_action")
        return 0

    trace.span("classification")
    item, blockers, comp = select_task(items, lanes, root, dirty_files_set(dirty))
    trace.end_span("classification")

    if item is None and any(i.get("status") in _RUNNABLE_STATUSES for i in items):
        audit_path = _write_audit(root, build_dir, items, lanes, dirty, branch, head)
        write_run_and_event(
            last_run_path,
            events_path,
            "audit_unblock_plan",
            root,
            dry_run,
            branch,
            head,
            dirty,
            blockers=["no_runnable_work"],
            compiler_fallback_status=compiler_fallback_status,
            audit_path=audit_path,
        )
        trace.finish("audit_unblock_plan")
        return 0

    state = classify_state(
        item, blockers, comp, item.get("status") == "active" if item else False
    )
    trace.event(
        "classified",
        {
            "state": state,
            "task_id": item.get("task_id", "") if item else "",
            "blocker_count": len(blockers) if blockers else 0,
        },
    )

    if capsule and compiler_fallback_status == "present":
        capsule_action = capsule.get("recommended_action", "")
        if capsule_action in STEWARD_STATES and capsule_action != state:
            capsule_rationale = capsule.get("recommendation_rationale_codes", [])
            append_event(
                events_path,
                {
                    "event": "capsule_action_mismatch",
                    "generated_at": now_iso(),
                    "capsule_action": capsule_action,
                    "steward_action": state,
                    "capsule_rationale": capsule_rationale,
                    "note": "Steward retains dispatch authority.",
                },
            )

    command_meta: dict[str, Any] | None = None
    if item and not blockers:
        task_id = item.get("task_id", "")
        if not dry_run:
            update_queue_status(root, task_id, "active")
        trace.span("opencode_execution")
        command_meta = try_launch(
            item,
            state,
            root,
            dry_run,
            no_stream=no_stream,
            show_reasoning=show_reasoning,
            opencode_path=opencode_path,
            events_path=events_path,
        )
        trace.end_span("opencode_execution")
        if command_meta is None and state in _LAUNCHABLE_STATES:
            blockers = ["missing_prompt"]
            state = "blocked"
        elif command_meta and not dry_run:
            exit_code = command_meta.get("exit_code")
            if exit_code == 0:
                update_queue_status(root, task_id, "completed")
            else:
                update_queue_status(root, task_id, "failed")

    trace.span("capsule_assembly")
    capsule_data = compile_capsule(
        root,
        items,
        lanes,
        dirty,
        dirty_files_set(dirty),
        item,
        blockers,
        comp,
        state,
        compiler_fallback_status,
    )
    write_last_run(capsule_path, capsule_data)
    trace.end_span("capsule_assembly")

    write_run_and_event(
        last_run_path,
        events_path,
        state,
        root,
        dry_run,
        branch,
        head,
        dirty,
        blockers=blockers,
        item=item,
        comp=comp,
        command_meta=command_meta,
        compiler_fallback_status=compiler_fallback_status,
    )
    trace.finish(state)
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="OpenCode Idle Lane Steward — bounded Rig foreman."
    )
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--worktree", type=str, default="default")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--no-stream", action="store_true", help="Fall back to non-streaming execution."
    )
    parser.add_argument(
        "--show-reasoning-stream",
        action="store_true",
        help="Display reasoning in terminal (never in artifacts).",
    )
    parser.add_argument(
        "--opencode-path", type=str, default="opencode", help="Path to opencode binary."
    )
    return parser.parse_args(argv)


__all__ = ["main"]
