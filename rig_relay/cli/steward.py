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
import json
from pathlib import Path
import subprocess
from typing import Any

from rig_relay.cli._steward._capsule import compile_capsule, read_capsule
from rig_relay.cli._steward._classification import classify_state, select_task
from rig_relay.cli._steward._constants import (
    _LAUNCHABLE_STATES,
    _REPAIR_BLOCKER_CLASSES,
    _RUNNABLE_STATUSES,
    BUILD_DIR,
    CAPSULE_PATH,
    STEWARD_STATES,
    append_event,
    now_iso,
    sha256,
    write_last_run,
)
from rig_relay.cli._steward._coordination import (
    StewardCoordinationBridge,
    _cycle_id,
    _worker_id,
)
from rig_relay.cli._steward._execution import try_launch
from rig_relay.cli._steward._issues import read_issue_work_items
from rig_relay.cli._steward._queue import read_lanes, read_queue, update_queue_status
from rig_relay.cli._steward._repair import try_repair
from rig_relay.cli._steward._traces import StewardTrace
from rig_relay.governance.steward_context_assembler import assemble_raw_evidence

_DIRTY_STATUS_PREFIX_LEN = 2


def git_branch(root: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            cwd=root,
            timeout=10,
        )
        if result.returncode != 0:
            return "unknown"
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
        if result.returncode != 0:
            return "unknown"
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
        if result.returncode != 0:
            return {
                "modified_count": 0,
                "staged_count": 0,
                "untracked_count": 0,
                "dirty_files": [],
            }
        for line in result.stdout.strip().split("\n"):
            if not line:
                continue
            dirty_files.append(line)
            x, y = (
                line[:_DIRTY_STATUS_PREFIX_LEN]
                if len(line) >= _DIRTY_STATUS_PREFIX_LEN
                else (" ", " ")
            )
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
    git_info: dict[str, Any],
    *,
    blockers: list[str] | None = None,
    item: dict[str, Any] | None = None,
    comp: dict[str, Any] | None = None,
    command_meta: dict[str, Any] | None = None,
    audit_path: str | None = None,
    error: str | None = None,
) -> None:
    root = git_info["root"]
    dry_run = git_info["dry_run"]
    branch = git_info["branch"]
    head = git_info["head"]
    dirty = git_info["dirty"]
    compiler_fallback_status = git_info.get("compiler_fallback_status")

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


def _run_handoff_subcommand(args: argparse.Namespace, root: Path) -> int:
    session_id = args.session_id
    if not session_id:
        sessions_dir = root / ".build/rig-relay/derived/opencode-steward/sessions"
        if sessions_dir.exists():
            dirs = [d for d in sessions_dir.iterdir() if d.is_dir()]
            if dirs:
                dirs.sort(key=lambda d: d.stat().st_mtime, reverse=True)
                session_id = dirs[0].name
    if not session_id:
        import sys

        print("Error: session-id is required for handoff", file=sys.stderr)
        return 1

    from rig_relay.cli._steward._capsule import compile_handoff_packet

    handoff = compile_handoff_packet(root, session_id)
    print(json.dumps(handoff, indent=2))
    return 0


def _run_subcommand(args: argparse.Namespace, root: Path) -> int | None:
    ret: int | None = None
    match args.subcommand:
        case "impact":
            dirty = git_dirty(root)
            files = sorted(list(dirty_files_set(dirty)))
            from rig_relay.cli._steward._classification import classify_paths

            classified = classify_paths(root, files)
            print(json.dumps(classified, indent=2))
            ret = 0
        case "explain":
            from rig_relay.cli._steward._classification import explain_artifact

            explanation = explain_artifact(root, args.path)
            print(json.dumps(explanation, indent=2))
            ret = 0
        case "validate-plan":
            dirty = git_dirty(root)
            files = sorted(list(dirty_files_set(dirty)))
            from rig_relay.cli._steward._classification import build_validation_plan

            plan = build_validation_plan(root, files)
            print(json.dumps(plan, indent=2))
            ret = 0
        case "handoff":
            ret = _run_handoff_subcommand(args, root)
        case "check-write":
            from rig_relay.cli._steward._classification import check_write_permission

            result = check_write_permission(root, args.path)
            print(json.dumps(result, indent=2))
            ret = 0 if result["allowed"] else 1
        case "record-observation":
            from rig_relay.cli._steward._capsule import append_observation_event

            try:
                payload_data = json.loads(args.payload)
            except Exception:
                payload_data = {"raw": args.payload}
            append_observation_event(
                root, args.session_id, args.event_type, payload_data
            )
            ret = 0
    return ret


def _scan_repository(
    git_info: dict[str, Any],
    sess_id: str,
    coord: StewardCoordinationBridge,
    trace: StewardTrace,
) -> None:
    trace.span("git_scan")
    dirty = git_dirty(git_info["root"])
    branch = git_branch(git_info["root"])
    head = git_head(git_info["root"])
    trace.end_span("git_scan")

    git_info["dirty"] = dirty
    git_info["branch"] = branch
    git_info["head"] = head

    _dirty_fs = dirty_files_set(dirty)
    _dirty_file_hashes = sorted(sha256(f) for f in _dirty_fs)
    coord.record_git_scan(
        sess_id,
        branch,
        head,
        dirty.get("modified_count", 0),
        dirty.get("staged_count", 0),
        dirty.get("untracked_count", 0),
        _dirty_file_hashes,
    )


def _read_queue_and_lanes(
    root: Path, sess_id: str, coord: StewardCoordinationBridge, trace: StewardTrace
) -> dict[str, Any]:
    trace.span("queue_read")
    queue_items = read_queue(root)
    issue_items = read_issue_work_items(root)
    lanes = read_lanes(root)
    trace.end_span("queue_read")
    claimed_task_ids = set(coord.store.read_state_projection().active_task_claims)

    items = queue_items + issue_items
    coord.record_queue_read(
        sess_id,
        len(queue_items),
        len(lanes),
        issue_item_count=len(issue_items),
        work_item_count=len(items),
    )
    return {"items": items, "lanes": lanes, "claims": claimed_task_ids}


def _run_execution(
    root: Path,
    item: dict[str, Any],
    state: str,
    git_info: dict[str, Any],
    coord: StewardCoordinationBridge,
    sess_id: str,
    trace: StewardTrace,
    events_path: Path,
) -> tuple[str, dict[str, Any] | None]:
    import threading

    show_reasoning = git_info["show_reasoning"]
    no_stream = git_info["no_stream"]
    opencode_path = git_info["opencode_path"]
    dry_run = git_info["dry_run"]

    task_id = item.get("task_id", "")
    worker = _worker_id(task_id)

    cmd_args = [
        opencode_path,
        "run",
        "--pure",
        "--format",
        "json",
        "--title",
        item.get("title", ""),
        "--agent",
        item.get("agent", "build"),
        "--dir",
        str(root),
    ]
    if show_reasoning:
        cmd_args.append("--thinking")
    if item.get("model"):
        cmd_args.extend(["--model", item["model"]])
    _cmd_sha256 = sha256(" ".join(cmd_args))

    coord.record_dispatch(
        sess_id, task_id, worker, _cmd_sha256, dry_run, stream_mode=not no_stream
    )

    stop_heartbeat = threading.Event()

    def run_heartbeat() -> None:
        while not stop_heartbeat.wait(60.0):
            try:
                coord.heartbeat(sess_id, task_id, "running")
            except Exception:
                pass

    hb_thread = threading.Thread(target=run_heartbeat, daemon=True)
    hb_thread.start()

    command_meta = None
    try:
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
    finally:
        stop_heartbeat.set()
        hb_thread.join(timeout=1.0)

    if command_meta and not dry_run:
        exit_code = command_meta.get("exit_code")
        duration_ms = command_meta.get("duration_ms", 0)
        if exit_code == 0:
            coord.record_completion(sess_id, task_id, worker, 0, duration_ms)
            update_queue_status(root, task_id, "completed")
        else:
            coord.record_failure(
                sess_id,
                task_id,
                worker,
                exit_code if isinstance(exit_code, int) else -1,
                duration_ms,
            )
            update_queue_status(root, task_id, "failed", increment_failed_attempts=True)

    return state, command_meta


def _execute_dispatch(
    root: Path,
    item: dict[str, Any],
    state: str,
    blockers: list[str],
    git_info: dict[str, Any],
    coord: StewardCoordinationBridge,
    sess_id: str,
    trace: StewardTrace,
    events_path: Path,
) -> tuple[str, list[str], dict[str, Any] | None]:
    dry_run = git_info["dry_run"]
    task_id = item.get("task_id", "")
    allowed = item.get("allowed_files", [])

    coord.record_task_considered(
        sess_id,
        task_id,
        item.get("title", ""),
        item.get("status", ""),
        item.get("priority", 0),
        eligible=True,
        blocker_classes=None,
    )

    if not dry_run:
        claimed = coord.claim_task(sess_id, task_id, allowed, ttl_seconds=1800)
        if not claimed:
            coord.record_blocked(sess_id, task_id, ["lane_ownership_collision"])
            state = "blocked"
            blockers = ["lane_ownership_collision"]
        else:
            reserved = coord.reserve_paths(sess_id, task_id, allowed, ttl_seconds=1800)
            if not reserved:
                coord.record_blocked(sess_id, task_id, ["dirty_overlap"])
                state = "blocked"
                blockers = ["dirty_overlap"]

    command_meta: dict[str, Any] | None = None
    if state != "blocked":
        state, command_meta = _run_execution(
            root, item, state, git_info, coord, sess_id, trace, events_path
        )
        if command_meta is None and state in _LAUNCHABLE_STATES:
            blockers = ["missing_prompt"]
            state = "blocked"
            coord.record_blocked(sess_id, task_id, blockers)
        elif command_meta and not dry_run:
            coord.release_paths(sess_id, task_id, allowed)

    return state, blockers, command_meta


def _check_capsule_mismatch(
    git_info: dict[str, Any], state: str, events_path: Path
) -> None:
    if git_info["capsule"] and git_info["compiler_fallback_status"] == "present":
        capsule_action = git_info["capsule"].get("recommended_action", "")
        if capsule_action in STEWARD_STATES and capsule_action != state:
            append_event(
                events_path,
                {
                    "event": "capsule_action_mismatch",
                    "generated_at": now_iso(),
                    "capsule_action": capsule_action,
                    "steward_action": state,
                    "capsule_rationale": git_info["capsule"].get(
                        "recommendation_rationale_codes", []
                    ),
                    "note": "Steward retains dispatch authority.",
                },
            )


def _run_foreman(args: argparse.Namespace, root: Path) -> int:
    git_info = {
        "root": root,
        "dry_run": getattr(args, "dry_run", False),
        "show_reasoning": getattr(args, "show_reasoning_stream", False),
        "no_stream": getattr(args, "no_stream", False),
        "opencode_path": getattr(args, "opencode_path", "opencode"),
    }
    paths = {
        "last_run": root / BUILD_DIR / "opencode_idle_steward_last_run_v1.json",
        "events": root / BUILD_DIR / "opencode_idle_steward_events_v1.jsonl",
        "capsule": root / CAPSULE_PATH,
    }

    coord = StewardCoordinationBridge(root)
    sess_id = _cycle_id()

    trace = StewardTrace(task_id="", project_root=str(root))
    trace.start()
    coord.set_trace_id(trace.trace_id)

    git_info["capsule"], git_info["compiler_fallback_status"] = read_capsule(root)
    trace.event(
        "capsule_read",
        {
            "fallback_status": git_info["compiler_fallback_status"],
            "capsule_id": git_info["capsule"].get("capsule_id", "")
            if git_info["capsule"]
            else "none",
        },
    )

    _scan_repository(git_info, sess_id, coord, trace)

    queue_data = _read_queue_and_lanes(root, sess_id, coord, trace)
    coord.register_cycle(
        sess_id, git_info["branch"], git_info["head"], lane_id="default"
    )

    evidence = assemble_raw_evidence(
        project_root=root,
        dirty=git_info["dirty"],
        branch=git_info["branch"],
        head=git_info["head"],
        dirty_files=dirty_files_set(git_info["dirty"]),
    )

    if not queue_data["items"]:
        coord.record_cycle_finished(sess_id, "no_action", 0)
        write_run_and_event(
            paths["last_run"],
            paths["events"],
            "no_action",
            git_info,
            blockers=["no_queue_items"],
        )
        trace.finish("no_action")
        return 0

    trace.span("classification")
    selection = select_task(
        queue_data["items"],
        queue_data["lanes"],
        root,
        dirty_files_set(git_info["dirty"]),
        claimed_task_ids=queue_data["claims"],
    )
    trace.end_span("classification")

    if selection[0] is None and any(
        i.get("status") in _RUNNABLE_STATUSES for i in queue_data["items"]
    ):
        coord.record_cycle_finished(sess_id, "audit_unblock_plan", 0)
        audit_path = _write_audit(
            root,
            root / BUILD_DIR,
            queue_data["items"],
            queue_data["lanes"],
            git_info["dirty"],
            git_info["branch"],
            git_info["head"],
        )
        write_run_and_event(
            paths["last_run"],
            paths["events"],
            "audit_unblock_plan",
            git_info,
            blockers=["no_runnable_work"],
            audit_path=audit_path,
        )
        trace.finish("audit_unblock_plan")
        return 0

    state = classify_state(
        selection[0],
        selection[1],
        selection[2],
        selection[0].get("status") == "active" if selection[0] else False,
    )
    trace.event(
        "classified",
        {
            "state": state,
            "task_id": selection[0].get("task_id", "") if selection[0] else "",
            "blocker_count": len(selection[1]) if selection[1] else 0,
        },
    )

    _check_capsule_mismatch(git_info, state, paths["events"])

    command_meta = None
    if selection[0] and selection[1]:
        _substrate_blockers = [b for b in selection[1] if b in _REPAIR_BLOCKER_CLASSES]
        if _substrate_blockers:
            coord.record_repair_proposed(
                sess_id, _substrate_blockers[0], "", repairable=True, repair_attempts=0
            )
            r_state = try_repair(
                root,
                root / BUILD_DIR,
                paths["events"],
                git_info["dry_run"],
                git_info["capsule"],
                git_info["compiler_fallback_status"],
                git_info["opencode_path"],
                git_info["no_stream"],
                git_info["show_reasoning"],
                evidence,
            )
            if r_state != "no_action":
                coord.record_cycle_finished(sess_id, r_state, 0)
                trace.finish(r_state)
                return 0
    elif selection[0] and not selection[1]:
        blockers = list(selection[1])
        state, blockers, command_meta = _execute_dispatch(
            root,
            selection[0],
            state,
            blockers,
            git_info,
            coord,
            sess_id,
            trace,
            paths["events"],
        )
    elif selection[1]:
        coord.record_blocked(
            sess_id,
            selection[0].get("task_id", "") if selection[0] else "",
            selection[1],
        )

    trace.span("capsule_assembly")
    capsule_data = compile_capsule(
        root,
        evidence,
        selection[0],
        selection[1] or [],
        selection[2],
        state,
        git_info["compiler_fallback_status"],
    )
    write_last_run(paths["capsule"], capsule_data)
    coord.publish_artifact_ref(
        sess_id,
        selection[0].get("task_id") if selection[0] else None,
        "steward_context_capsule",
        str(paths["capsule"]),
        sha256(json.dumps(capsule_data, sort_keys=True, ensure_ascii=False)),
        "rig.relay.opencode_steward_context_capsule.v1",
    )
    trace.end_span("capsule_assembly")

    write_run_and_event(
        paths["last_run"],
        paths["events"],
        state,
        git_info,
        blockers=selection[1],
        item=selection[0],
        comp=selection[2],
        command_meta=command_meta,
    )
    coord.record_cycle_finished(sess_id, state, 0)
    trace.finish(state)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    root = getattr(args, "project_root", Path.cwd()).resolve()

    ret = _run_subcommand(args, root)
    if ret is not None:
        return ret

    return _run_foreman(args, root)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="OpenCode Idle Lane Steward — bounded Rig foreman."
    )
    subparsers = parser.add_subparsers(dest="subcommand")

    subparsers.add_parser("impact")

    explain_p = subparsers.add_parser("explain")
    explain_p.add_argument("path", type=str)

    subparsers.add_parser("validate-plan")

    handoff_p = subparsers.add_parser("handoff")
    handoff_p.add_argument("--session-id", type=str, required=False)

    check_p = subparsers.add_parser("check-write")
    check_p.add_argument("path", type=str)

    rec_p = subparsers.add_parser("record-observation")
    rec_p.add_argument("--session-id", type=str, required=True)
    rec_p.add_argument("--event-type", type=str, required=True)
    rec_p.add_argument("--payload", type=str, required=True)

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
