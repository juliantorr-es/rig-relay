#!/usr/bin/env python3
"""OpenCode Idle Lane Steward — bounded Rig foreman for OpenCode.

Classification-only steward. Reads roadmap queue, selects at most one safe task,
constructs a bounded OpenCode command, or produces an unblock audit.

Usage:
  uv run python scripts/rig_opencode_idle_steward.py --project-root <path> --worktree <path>
  uv run python scripts/rig_opencode_idle_steward.py --project-root <path> --worktree <path> --dry-run
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading

from rig_relay.governance.steward_context_assembler import (
    RepairResult,
    SubstrateDiagnosis,
    assemble_raw_evidence,
    build_repair_mission,
    diagnose_substrate,
    digest_to_capsule,
    validate_capsule,
)

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

_GIT_PORCELAIN_STATUS_WIDTH = 2
_GATE_FAILURE_VERDICTS: frozenset[str] = frozenset({"FAIL", "BLOCKED", "ERROR"})
_RUNNABLE_STATUSES: frozenset[str] = frozenset({"queued", "active", "blocked"})
_LAUNCHABLE_STATES: frozenset[str] = frozenset({
    "continue_lane",
    "advance_to_next_lane",
    "repair_steward_substrate",
})
_FINALIZE_STATES: frozenset[str] = frozenset({"finalize_lane"})

ROADMAP_DIR = ".rig/roadmap"
QUEUE_PATH = f"{ROADMAP_DIR}/queue.jsonl"
LANES_PATH = f"{ROADMAP_DIR}/lanes.jsonl"
PROMPTS_DIR = f"{ROADMAP_DIR}/prompts"
BUILD_DIR = ".build/rig-relay/derived"
CAPSULE_PATH = f"{BUILD_DIR}/opencode_steward_context_capsule_v1.json"

_REPAIR_BLOCKER_CLASSES: set[str] = {
    "context_capsule_invalid",
    "context_capsule_stale",
    "context_compiler_invocation_failed",
    "worker_report_ingestion_failed",
    "lane_projection_invalid",
    "steward_schema_validation_failed",
    "steward_redaction_violation",
    "idle_event_routing_failed",
    "steward_command_construction_failed",
}


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _resolve_safe(root: Path, relative: str) -> Path | None:
    resolved = (root / relative).resolve()
    if not str(resolved).startswith(str(root.resolve())):
        return None
    return resolved


def _git_branch(root: Path) -> str:
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


def _git_head(root: Path) -> str:
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


def _git_dirty(root: Path) -> dict:
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
            x, y = (
                line[:_GIT_PORCELAIN_STATUS_WIDTH]
                if len(line) >= _GIT_PORCELAIN_STATUS_WIDTH
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


def _dirty_files_set(dirty: dict) -> set[str]:
    files: set[str] = set()
    for line in dirty.get("dirty_files", []):
        path = line[3:].strip()
        if path:
            files.add(path)
    return files


def _read_jsonl(path: Path) -> list[dict]:
    items: list[dict] = []
    if not path.exists():
        return items
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            items.append(json.loads(stripped))
        except json.JSONDecodeError:
            pass
    return items


def _validate_queue_item(item: dict) -> list[str]:
    errors: list[str] = []
    required = {
        "schema_version",
        "task_id",
        "status",
        "priority",
        "prompt_path",
        "title",
        "agent",
    }
    for key in required:
        if key not in item:
            errors.append(f"missing_required_field:{key}")
    status = item.get("status")
    if status not in {"queued", "active", "completed", "blocked", "failed"}:
        errors.append(f"invalid_status:{status}")
    prio = item.get("priority")
    if not isinstance(prio, (int, float)):
        errors.append("invalid_priority_type")
    return errors


def _prompt_sha256(root: Path, prompt_path: str) -> str | None:
    resolved = _resolve_safe(root, prompt_path)
    if resolved is None or not resolved.exists():
        return None
    return _sha256(resolved.read_text(encoding="utf-8"))


def _read_prompt_text(root: Path, prompt_path: str) -> str | None:
    resolved = _resolve_safe(root, prompt_path)
    if resolved is None or not resolved.exists():
        return None
    return resolved.read_text(encoding="utf-8")


def _check_required_gates(root: Path, gates: list[str]) -> list[str]:
    failures: list[str] = []
    for gate_rel in gates:
        gate_path = _resolve_safe(root, gate_rel)
        if gate_path is None:
            failures.append(f"gate_not_found:{gate_rel}")
            continue
        if not gate_path.exists():
            failures.append(f"gate_missing:{gate_rel}")
            continue
        try:
            gate_data = json.loads(gate_path.read_text(encoding="utf-8"))
            verdict = gate_data.get("verdict") or gate_data.get("status") or ""
            if isinstance(verdict, str) and verdict.upper() in _GATE_FAILURE_VERDICTS:
                failures.append(f"gate_failed:{gate_rel}")
        except Exception:
            failures.append(f"gate_unreadable:{gate_rel}")
    return failures


def _check_completion_criteria(root: Path, item: dict) -> dict:
    criteria = item.get("completion_criteria") or {}
    result: dict = {
        "required_artifacts_present": True,
        "required_tests_present": True,
        "final_report_present": True,
        "schema_validation_passed": True,
        "max_continuations_exceeded": False,
        "max_failed_attempts_exceeded": False,
    }
    for art in criteria.get("required_artifacts") or []:
        p = _resolve_safe(root, art)
        if p is None or not p.exists():
            result["required_artifacts_present"] = False
    for test_path in criteria.get("required_tests") or []:
        p = _resolve_safe(root, test_path)
        if p is None or not p.exists():
            result["required_tests_present"] = False
    report_path = criteria.get("final_report_path")
    if report_path:
        p = _resolve_safe(root, report_path)
        if p is None or not p.exists():
            result["final_report_present"] = False
    max_cont = item.get("max_continuations", 3)
    if item.get("continuation_count", 0) >= max_cont:
        result["max_continuations_exceeded"] = True
    max_fail = item.get("max_failed_attempts", 2)
    if item.get("failed_attempts", 0) >= max_fail:
        result["max_failed_attempts_exceeded"] = True
    return result


def _all_completion_criteria_satisfied(comp: dict) -> bool:
    return (
        comp["required_artifacts_present"]
        and comp["required_tests_present"]
        and comp["final_report_present"]
        and comp["schema_validation_passed"]
    )


def _read_lanes(root: Path) -> list[dict]:
    lanes_path = root / LANES_PATH
    return _read_jsonl(lanes_path)


def _active_lane_files(lanes: list[dict]) -> dict[str, str]:
    owned: dict[str, str] = {}
    for lane in lanes:
        if lane.get("status") != "active":
            continue
        lane_id = lane.get("lane_id") or lane.get("task_id") or ""
        for f in lane.get("owned_files") or []:
            owned[f] = lane_id
    return owned


def _check_prompt_blocker(item: dict, prompt_hash: str | None) -> str | None:
    if prompt_hash is None:
        return "missing_prompt"
    prompt_path = item.get("prompt_path", "")
    prompts_prefix = f"{PROMPTS_DIR}/"
    if not prompt_path.startswith(prompts_prefix):
        return "missing_prompt"
    return None


def _path_overlaps(target: str, dirty_set: set[str]) -> bool:
    if target in dirty_set:
        return True
    for d in dirty_set:
        if d.endswith("/") and target.startswith(d):
            return True
        if target.endswith("/") and d.startswith(target):
            return True
    return False


def _check_file_blockers(
    allowed: list[str],
    forbidden: list[str],
    dirty_files: set[str],
    active_ownership: dict[str, str],
) -> list[str]:
    result: list[str] = []
    if any(_path_overlaps(f, dirty_files) for f in allowed):
        result.append("dirty_overlap")
    if any(_path_overlaps(f, dirty_files) for f in forbidden):
        result.append("forbidden_file_scope")
    if any(f in active_ownership for f in allowed):
        result.append("lane_ownership_collision")
    return result


def _check_completion_blockers(item: dict, comp: dict) -> list[str]:
    result: list[str] = []
    if _all_completion_criteria_satisfied(comp):
        return result
    if comp["required_artifacts_present"] is False:
        result.append("missing_required_artifact")
    if comp["final_report_present"] is False:
        result.append("missing_final_report")
    if item.get("completion_criteria", {}).get("schema_validation_required"):
        result.append("schema_validation_failure")
    return result


def _classify_blockers(
    item: dict,
    errors: list[str],
    prompt_hash: str | None,
    dirty_files: set[str],
    active_ownership: dict[str, str],
    gate_failures: list[str],
    comp: dict,
) -> list[str]:
    blockers: list[str] = []
    if errors:
        blockers.append("malformed_queue_item")
    if pb := _check_prompt_blocker(item, prompt_hash):
        blockers.append(pb)
    blockers.extend(
        _check_file_blockers(
            item.get("allowed_files") or [],
            item.get("forbidden_files") or [],
            dirty_files,
            active_ownership,
        )
    )
    if gate_failures:
        blockers.append("failed_gate")
    if comp["max_continuations_exceeded"] or comp["max_failed_attempts_exceeded"]:
        blockers.append("max_attempts_exceeded")
    blockers.extend(_check_completion_blockers(item, comp))
    return list(dict.fromkeys(blockers))


def _select_task(
    items: list[dict], lanes: list[dict], root: Path, dirty_files: set[str]
) -> tuple[dict | None, list[str], dict | None]:
    active_ownership = _active_lane_files(lanes)
    active_items = [i for i in items if i.get("status") == "active"]
    active_items.sort(key=lambda i: i.get("priority", 999))

    for active in active_items:
        errors = _validate_queue_item(active)
        if errors:
            continue
        prompt_path = active.get("prompt_path", "")
        prompt_hash = _prompt_sha256(root, prompt_path)
        comp = _check_completion_criteria(root, active)
        if (
            _all_completion_criteria_satisfied(comp)
            and not comp["max_continuations_exceeded"]
        ):
            return active, [], comp
        gates = active.get("required_gates_before") or []
        gate_failures = _check_required_gates(root, gates)
        blockers = _classify_blockers(
            active, [], prompt_hash, dirty_files, active_ownership, gate_failures, comp
        )
        if not blockers:
            return active, blockers, comp
        if (
            _all_completion_criteria_satisfied(comp)
            and not comp["max_continuations_exceeded"]
        ):
            return active, ["unclear_completion_state"], comp

    queued = [i for i in items if i.get("status") == "queued"]
    queued.sort(key=lambda i: i.get("priority", 999))

    for item in queued:
        errors = _validate_queue_item(item)
        prompt_path = item.get("prompt_path", "")
        prompt_hash = _prompt_sha256(root, prompt_path)
        comp = _check_completion_criteria(root, item)
        gates = item.get("required_gates_before") or []
        gate_failures = _check_required_gates(root, gates)
        blockers = _classify_blockers(
            item,
            errors,
            prompt_hash,
            dirty_files,
            active_ownership,
            gate_failures,
            comp,
        )
        if not blockers:
            return item, blockers, comp

    return None, [], None


def _build_command(
    item: dict, project_root: Path, worktree: str, *, opencode_path: str = "opencode"
) -> list[str]:
    title = item.get("title", "Idle Steward Task")
    agent = item.get("agent", "build")
    model = item.get("model")
    cmd = [
        opencode_path,
        "run",
        "--pure",
        "--format",
        "json",
        "--thinking",
        "--title",
        title,
        "--agent",
        agent,
        "--dir",
        str(project_root),
    ]
    if model:
        cmd.extend(["--model", model])
    return cmd


def _classify_state(
    item: dict | None, blockers: list[str], comp: dict | None, is_active: bool
) -> str:
    if item is None:
        return "audit_unblock_plan" if blockers else "no_action"
    if blockers:
        return "blocked"
    if comp and _all_completion_criteria_satisfied(comp):
        return "finalize_lane" if is_active else "advance_to_next_lane"
    return "continue_lane" if is_active else "advance_to_next_lane"


def _write_last_run(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def _append_event(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(data, ensure_ascii=False) + "\n")


def _build_audit_items(
    items: list[dict],
    root: Path,
    dirty_files: set[str],
    active_ownership: dict[str, str],
) -> tuple[
    list[dict], dict[str, int], list[dict], list[dict], list[dict], int, int, int, int
]:
    per_task: list[dict] = []
    blocker_summary: dict[str, int] = {b: 0 for b in BLOCKER_CLASSES}
    failed_gates_list: list[dict] = []
    missing_artifacts_list: list[dict] = []
    missing_reports_list: list[dict] = []
    runnable = blocked_count = active_count = completed_count = 0

    for item in items:
        status = item.get("status", "unknown")
        if status == "completed":
            completed_count += 1
        elif status == "active":
            active_count += 1
        elif status == "blocked":
            blocked_count += 1
        errors = _validate_queue_item(item)
        prompt_path = item.get("prompt_path", "")
        prompt_hash = _prompt_sha256(root, prompt_path)
        comp = _check_completion_criteria(root, item)
        gates = item.get("required_gates_before") or []
        gate_failures = _check_required_gates(root, gates)
        task_blockers = _classify_blockers(
            item,
            errors,
            prompt_hash,
            dirty_files,
            active_ownership,
            gate_failures,
            comp,
        )
        if not task_blockers:
            runnable += 1
        else:
            blocked_count += 1
        for b in task_blockers:
            blocker_summary[b] = blocker_summary.get(b, 0) + 1
        per_task.append({
            "task_id": item.get("task_id", ""),
            "title": item.get("title", ""),
            "status": status,
            "priority": item.get("priority", 0),
            "blocker_classes": task_blockers,
            "details": {
                "errors": errors,
                "gate_failures": gate_failures,
                "completion": comp,
            },
        })
        for gf in gate_failures:
            failed_gates_list.append({
                "task_id": item.get("task_id", ""),
                "gate_name": gf,
                "gate_path": gf.split(":", 1)[-1] if ":" in gf else gf,
            })
        _collect_missing_artifacts(item, root, missing_artifacts_list)
        _collect_missing_reports(item, root, missing_reports_list)

    return (
        per_task,
        blocker_summary,
        failed_gates_list,
        missing_artifacts_list,
        missing_reports_list,
        runnable,
        blocked_count,
        active_count,
        completed_count,
    )


def _collect_missing_artifacts(item: dict, root: Path, collector: list[dict]) -> None:
    for art in (item.get("completion_criteria") or {}).get("required_artifacts") or []:
        p = _resolve_safe(root, art)
        if p is None or not p.exists():
            collector.append({"task_id": item.get("task_id", ""), "artifact_path": art})


def _collect_missing_reports(item: dict, root: Path, collector: list[dict]) -> None:
    report_path = (item.get("completion_criteria") or {}).get("final_report_path")
    if report_path:
        p = _resolve_safe(root, report_path)
        if p is None or not p.exists():
            collector.append({
                "task_id": item.get("task_id", ""),
                "report_path": report_path,
            })


def _build_cross_lane_collisions(lanes: list[dict]) -> list[dict]:
    owned_files: dict[str, list[str]] = {}
    cross_lane: list[dict] = []
    for lane in lanes:
        for f in lane.get("owned_files") or []:
            owned_files.setdefault(f, []).append(
                lane.get("lane_id") or lane.get("task_id") or ""
            )
    for f, lane_ids in owned_files.items():
        if len(lane_ids) > 1:
            cross_lane.append({"file": f, "lane_ids": lane_ids})
    return cross_lane


def _build_audit_slices(blocker_summary: dict[str, int]) -> list[dict]:
    ts = _now_iso().replace(":", "").replace("-", "").replace("T", "")
    slices: list[dict] = []
    if blocker_summary.get("missing_prompt", 0) > 0:
        slices.append({
            "recommendation_id": f"unblock-{ts}-1",
            "title": "Provision missing prompt files for blocked queue items",
            "blocker_classes_addressed": ["missing_prompt"],
            "rationale": "One or more queue items reference prompt paths that do not exist or are outside the allowed prompts directory.",
            "allowed_files": [f"{PROMPTS_DIR}/**"],
            "forbidden_files": [],
            "required_artifacts": [],
            "targeted_tests": [],
            "expected_evidence": ["prompt files created under .rig/roadmap/prompts/"],
            "risk_level": "low",
            "estimated_lane": "prompt-provisioning",
            "should_auto_queue": False,
            "requires_human_review": True,
        })
    if blocker_summary.get("malformed_queue_item", 0) > 0:
        slices.append({
            "recommendation_id": f"unblock-{ts}-2",
            "title": "Repair malformed queue items",
            "blocker_classes_addressed": ["malformed_queue_item"],
            "rationale": "Queue items are missing required fields or have invalid status/priority values.",
            "allowed_files": [f"{QUEUE_PATH}"],
            "forbidden_files": [],
            "required_artifacts": [f"{QUEUE_PATH}"],
            "targeted_tests": [],
            "expected_evidence": ["repaired queue items with valid schema"],
            "risk_level": "low",
            "estimated_lane": "queue-repair",
            "should_auto_queue": False,
            "requires_human_review": True,
        })
    if blocker_summary.get("dirty_overlap", 0) > 0:
        slices.append({
            "recommendation_id": f"unblock-{ts}-3",
            "title": "Resolve dirty state overlap with pending task files",
            "blocker_classes_addressed": ["dirty_overlap", "lane_ownership_collision"],
            "rationale": "Dirty files overlap with task allowed_files. Commit, stash, or reassign ownership.",
            "allowed_files": [],
            "forbidden_files": [],
            "required_artifacts": [f"{QUEUE_PATH}", f"{LANES_PATH}"],
            "targeted_tests": [],
            "expected_evidence": [
                "clean git status on affected files",
                "updated lane ledger",
            ],
            "risk_level": "medium",
            "estimated_lane": "dirty-resolution",
            "should_auto_queue": False,
            "requires_human_review": True,
        })
    return slices


def _build_audit(
    root: Path, items: list[dict], lanes: list[dict], dirty: dict, dirty_files: set[str]
) -> dict:
    active_ownership = _active_lane_files(lanes)
    (
        per_task,
        blocker_summary,
        failed_gates_list,
        missing_artifacts_list,
        missing_reports_list,
        runnable,
        blocked_count,
        active_count,
        completed_count,
    ) = _build_audit_items(items, root, dirty_files, active_ownership)
    cross_lane = _build_cross_lane_collisions(lanes)
    slices = _build_audit_slices(blocker_summary)

    return {
        "schema_version": "rig.relay.opencode_unblock_audit.v1",
        "generated_at": _now_iso(),
        "branch": _git_branch(root),
        "head": _git_head(root),
        "dirty_state_summary": {
            "modified_count": dirty.get("modified_count", 0),
            "staged_count": dirty.get("staged_count", 0),
            "untracked_count": dirty.get("untracked_count", 0),
        },
        "queue_path": QUEUE_PATH,
        "lane_ledger_path": LANES_PATH,
        "total_queue_items": len(items),
        "runnable_count": runnable,
        "blocked_count": blocked_count,
        "active_count": active_count,
        "completed_count": completed_count,
        "blocker_summary": blocker_summary,
        "per_task_blockers": per_task,
        "cross_lane_collisions": cross_lane,
        "failed_gates": failed_gates_list,
        "missing_artifacts": missing_artifacts_list,
        "missing_reports": missing_reports_list,
        "dependency_policy_findings": [],
        "recommended_unblock_slices": slices,
        "recommended_queue_order": [],
        "architecture_convergence_notes": [],
        "telemetry_redaction_implications": [
            "Unblock audit is content-light: no raw prompt text, no source code, no secrets.",
            "File paths and hashes only; auditable without exposing proprietary code.",
        ],
        "safety_stop_reason": "No safe non-blocked work available. Audit produced for human review.",
    }


def _build_dirty_summary(dirty: dict) -> dict:
    return {
        "modified_count": dirty.get("modified_count", 0),
        "staged_count": dirty.get("staged_count", 0),
        "untracked_count": dirty.get("untracked_count", 0),
        "dirty_files": dirty.get("dirty_files", []),
    }


def _write_run_and_event(
    last_run_path: Path,
    events_path: Path,
    state: str,
    reason: str,
    root: Path,
    worktree: str,
    dry_run: bool,
    branch: str,
    head: str,
    dirty: dict,
    *,
    blockers: list[str] | None = None,
    item: dict | None = None,
    comp: dict | None = None,
    command_meta: dict | None = None,
    audit_path: str | None = None,
    error: str | None = None,
    compiler_fallback_status: str | None = None,
) -> None:
    run_data = {
        "schema_version": "rig.relay.opencode_idle_steward_run.v1",
        "generated_at": _now_iso(),
        "project_root": str(root),
        "worktree": worktree,
        "steward_state": state,
        "dry_run": dry_run,
        "branch": branch,
        "head": head,
        "dirty_state_summary": _build_dirty_summary(dirty),
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
    _write_last_run(last_run_path, run_data)
    _append_event(
        events_path,
        {
            "event": "steward_run",
            "state": state,
            "generated_at": run_data["generated_at"],
            "reason": reason,
            "selected_task_id": item.get("task_id") if item else None,
            "compiler_fallback_status": compiler_fallback_status,
        },
    )


def _handle_audit_path(
    root: Path,
    build_dir: Path,
    items: list[dict],
    lanes: list[dict],
    dirty: dict,
    dirty_files: set[str],
    last_run_path: Path,
    events_path: Path,
    worktree: str,
    dry_run: bool,
    branch: str,
    head: str,
    *,
    compiler_fallback_status: str | None = None,
) -> None:
    audit = _build_audit(root, items, lanes, dirty, dirty_files)
    audit_path = build_dir / "opencode_idle_steward_unblock_audit_v1.json"
    candidates_path = build_dir / "opencode_idle_steward_unblock_candidates_v1.jsonl"
    _write_last_run(audit_path, audit)
    for task in audit.get("per_task_blockers") or []:
        _append_event(
            candidates_path,
            {
                "event": "unblock_candidate",
                "task_id": task.get("task_id"),
                "blocker_classes": task.get("blocker_classes"),
                "generated_at": audit["generated_at"],
            },
        )
    _write_run_and_event(
        last_run_path,
        events_path,
        "audit_unblock_plan",
        "audit_unblock_plan",
        root,
        worktree,
        dry_run,
        branch,
        head,
        dirty,
        blockers=["no_runnable_work"],
        audit_path=str(audit_path),
        compiler_fallback_status=compiler_fallback_status,
    )


def _compile_and_write_capsule(
    capsule_path: Path,
    root: Path,
    items: list[dict],
    lanes: list[dict],
    dirty: dict,
    dirty_files: set[str],
    item: dict | None,
    blockers: list[str],
    comp: dict | None,
    state: str,
    compiler_fallback_status: str,
) -> None:
    capsule = _compile_steward_capsule(
        root, items, lanes, dirty, dirty_files, item, blockers, comp, state
    )
    capsule["compiler_fallback_status"] = compiler_fallback_status
    _write_last_run(capsule_path, capsule)


def _try_launch(
    item: dict,
    state: str,
    root: Path,
    worktree: str,
    dry_run: bool,
    *,
    no_stream: bool = False,
    show_reasoning: bool = False,
    opencode_path: str = "opencode",
    events_path: Path | None = None,
) -> dict | None:
    if state not in _LAUNCHABLE_STATES:
        return None
    prompt_path = item.get("prompt_path", "")
    prompt_text = _read_prompt_text(root, prompt_path)
    if prompt_text is None:
        return None
    argv = _build_command(item, root, worktree, opencode_path=opencode_path)
    prompt_hash = _sha256(prompt_text)
    argv_sha256 = _sha256(json.dumps(argv, sort_keys=True))
    base_meta = {
        "prompt_path": prompt_path,
        "prompt_sha256": prompt_hash,
        "title": item.get("title", ""),
        "agent": item.get("agent", "general-purpose"),
        "argv": argv + ["<prompt body omitted>"],
        "argv_sha256": argv_sha256,
    }
    if dry_run:
        return {**base_meta, "launched": False, "dry_run": True, "streaming": True}
    if no_stream:
        result = subprocess.run(argv + [prompt_text], cwd=root)
        return {
            **base_meta,
            "launched": True,
            "dry_run": False,
            "streaming": False,
            "exit_code": result.returncode,
        }
    streaming_meta = _stream_opencode(
        argv, prompt_text, root, show_reasoning=show_reasoning, events_path=events_path
    )
    return {**base_meta, "launched": True, "dry_run": False, **streaming_meta}


def _sanitize_env_for_subprocess() -> dict[str, str]:
    env = os.environ.copy()
    blocklist = {
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "GITHUB_TOKEN",
        "GH_TOKEN",
        "GITLAB_TOKEN",
        "BITBUCKET_TOKEN",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "GOOGLE_API_KEY",
        "COHERE_API_KEY",
        "DEEPSEEK_API_KEY",
        "MISTRAL_API_KEY",
        "TOGETHER_API_KEY",
        "OPENCODE_SERVER_PASSWORD",
        "OPENCODE_API_KEY",
        "NPM_TOKEN",
        "PYPI_TOKEN",
        "DOCKER_PASSWORD",
        "RIG_RELAY_TOKEN",
        "RIG_TOKEN",
        "AZURE_CLIENT_SECRET",
        "GCP_SA_KEY",
        "SSH_AUTH_SOCK",
        "SSH_AGENT_PID",
        "GNUPGHOME",
        "KEYCHAIN",
        "KEYRING",
    }
    for key in blocklist:
        env.pop(key, None)
    return env


def _parse_opencode_line(line: str) -> dict | None:
    try:
        return json.loads(line)
    except (json.JSONDecodeError, TypeError):
        return None


_BOUNDED_SUMMARY_MAX_CHARS = 200


def _extract_paths_from_tool_input_input(tool_input: dict) -> list[str]:
    paths: list[str] = []
    for key in ("filePath", "path", "target_directory", "dir", "file_path"):
        val = tool_input.get(key)
        if isinstance(val, str) and val:
            paths.append(val)
            return paths
    return paths


def _extract_paths_from_tool_output_output(output: str) -> list[str]:
    paths: list[str] = []
    for line in output.splitlines():
        stripped = line.strip()
        if stripped.startswith("<path>") and stripped.endswith("</path>"):
            path = stripped[len("<path>") : -len("</path>")]
            if path:
                paths.append(path)
        if stripped.startswith("<content>") or stripped.startswith("</content>"):
            break
    return paths


def _to_stream_event(raw: dict, *, redact_reasoning: bool) -> dict:
    event_type = raw.get("type", "unknown")
    part = raw.get("part", {})
    session_id = raw.get("sessionID", "")
    timestamp_ms = raw.get("timestamp")
    generated_at = _now_iso()

    role: str | None = None
    tool_name: str | None = None
    tool_status: str | None = None
    tool_title: str | None = None
    paths: list[str] = []
    path_hashes: list[str] = []
    summary_text: str = ""
    reasoning_redacted = False
    exit_code: int | None = None
    tokens: dict | None = None
    cost: float | None = None

    if event_type == "reasoning":
        reasoning_redacted = True
        summary_text = "<reasoning redacted>"
        if not redact_reasoning and part.get("text"):
            raw_text = str(part["text"])
            summary_text = raw_text[:_BOUNDED_SUMMARY_MAX_CHARS]

    elif event_type == "text":
        role = "assistant"
        raw_text = part.get("text", "")
        summary_text = str(raw_text)[:_BOUNDED_SUMMARY_MAX_CHARS]

    elif event_type in ("tool_use", "tool_result"):
        tool_name = part.get("tool", "")
        state = part.get("state", {})
        tool_status = state.get("status", "")
        tool_title = state.get("title", "")
        exit_code_raw = state.get("metadata", {}).get("exit")
        if isinstance(exit_code_raw, int):
            exit_code = exit_code_raw
        tool_input = state.get("input", {})
        paths = _extract_paths_from_tool_input_input(tool_input)
        for p in paths:
            path_hashes.append(_sha256(p))
        output_raw = state.get("output", "")
        if isinstance(output_raw, str):
            for p in _extract_paths_from_tool_output_output(output_raw):
                if p not in paths:
                    paths.append(p)
                    path_hashes.append(_sha256(p))
        if tool_title:
            summary_text = f"{tool_name}: {tool_title}"
        else:
            summary_text = f"{tool_name}"
        summary_text = summary_text[:_BOUNDED_SUMMARY_MAX_CHARS]

    elif event_type == "step_start":
        summary_text = "step start"

    elif event_type == "step_finish":
        summary_text = "step finish"
        tok = part.get("tokens", {})
        if tok:
            tokens = {
                "input": tok.get("input", 0),
                "output": tok.get("output", 0),
                "total": tok.get("total", 0),
            }
        cost = part.get("cost")

    elif event_type == "error":
        err = raw.get("error", {})
        summary_text = str(err.get("name", err.get("message", "unknown error")))[
            :_BOUNDED_SUMMARY_MAX_CHARS
        ]

    else:
        summary_text = event_type

    return {
        "event": "opencode_stream",
        "generated_at": generated_at,
        "session_id": session_id,
        "timestamp_ms": timestamp_ms,
        "stream_event_type": event_type,
        "role": role,
        "tool_name": tool_name,
        "tool_status": tool_status,
        "tool_title": tool_title,
        "summary_text": summary_text,
        "paths": paths,
        "path_hashes": path_hashes,
        "reasoning_redacted": reasoning_redacted,
        "exit_code": exit_code,
        "tokens": tokens,
        "cost": cost,
    }


def _print_compact_progress(raw: dict, *, show_reasoning: bool) -> None:
    event_type = raw.get("type", "unknown")
    part = raw.get("part", {})

    if event_type == "step_start":
        print("\u25b6 step start", flush=True)

    elif event_type == "step_finish":
        tok = part.get("tokens", {})
        inp = tok.get("input", 0)
        out = tok.get("output", 0)
        print(f"\u25c0 step done \u00b7 {inp}\u2192{out} tokens", flush=True)

    elif event_type == "reasoning":
        if show_reasoning:
            text = part.get("text", "")
            truncated = str(text)[:120]
            print(f"  \U0001f9e0 thinking: {truncated}", flush=True)

    elif event_type == "text":
        text = part.get("text", "")
        truncated = str(text).replace("\n", " ")[:150]
        if truncated:
            print(f"  \U0001f4ac assistant: {truncated}", flush=True)

    elif event_type in ("tool_use", "tool_result"):
        tool_name = part.get("tool", "?")
        state = part.get("state", {})
        title = state.get("title", "")
        status = state.get("status", "")
        exit_code_raw = state.get("metadata", {}).get("exit")
        status_icon = "\u2713" if status == "completed" else "\u2026"
        exit_str = f" (exit {exit_code_raw})" if isinstance(exit_code_raw, int) else ""
        label = f"{title}" if title else tool_name
        print(f"  \U0001f527 {tool_name}: {label} {status_icon}{exit_str}", flush=True)

    elif event_type == "error":
        err = raw.get("error", {})
        msg = err.get("name") or err.get("message", "unknown error")
        print(f"  \u26a0 error: {msg}", flush=True)


def _stream_opencode(
    argv: list[str],
    prompt_text: str,
    root: Path,
    *,
    show_reasoning: bool,
    events_path: Path | None,
) -> dict:
    env = _sanitize_env_for_subprocess()
    try:
        process = subprocess.Popen(
            argv + [prompt_text],
            cwd=root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )
    except FileNotFoundError:
        return {
            "exit_code": -1,
            "stderr_sha256": None,
            "stderr_truncated_bytes": 0,
            "streaming": True,
            "duration_ms": 0,
            "stream_error": "opencode binary not found",
        }

    stderr_lines: list[str] = []

    def _read_stderr() -> None:
        if process.stderr:
            for line in process.stderr:
                stderr_lines.append(line.rstrip("\n"))

    stderr_thread = threading.Thread(target=_read_stderr, daemon=True)
    stderr_thread.start()

    start_time = datetime.now(UTC)
    try:
        if process.stdout:
            for line in process.stdout:
                line = line.rstrip("\n")
                if not line:
                    continue
                raw = _parse_opencode_line(line)
                if raw is None:
                    continue
                _print_compact_progress(raw, show_reasoning=show_reasoning)
                if events_path:
                    event = _to_stream_event(raw, redact_reasoning=True)
                    _append_event(events_path, event)
        process.wait()
    except KeyboardInterrupt:
        process.send_signal(signal.SIGINT)
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()

    stderr_thread.join(timeout=5)
    exit_code = process.returncode
    stderr_text = "\n".join(stderr_lines)

    max_stderr_bytes = 4_096
    stderr_bytes = stderr_text.encode("utf-8", errors="replace")
    if len(stderr_bytes) > max_stderr_bytes:
        stderr_bytes = stderr_bytes[:max_stderr_bytes]
    stderr_truncated = stderr_bytes.decode("utf-8", errors="replace")
    stderr_hash = _sha256(stderr_truncated) if stderr_truncated else None
    duration_ms = int((datetime.now(UTC) - start_time).total_seconds() * 1000)

    return {
        "exit_code": exit_code,
        "stderr_sha256": stderr_hash,
        "stderr_truncated_bytes": len(stderr_truncated.encode()),
        "streaming": True,
        "duration_ms": duration_ms,
    }


def _compile_steward_capsule(
    root: Path,
    items: list[dict],
    lanes: list[dict],
    dirty: dict,
    dirty_files: set[str],
    item: dict | None,
    blockers: list[str],
    comp: dict | None,
    state: str,
) -> dict:
    evidence = assemble_raw_evidence(
        root,
        dirty=dirty,
        dirty_files=dirty_files,
        branch=_git_branch(root),
        head=_git_head(root),
    )
    result = digest_to_capsule(
        evidence,
        selected_item=item,
        blockers=blockers,
        completion=comp,
        state=state,
        project_root=root,
    )
    return result.capsule


def _read_steward_capsule(root: Path) -> tuple[dict | None, str]:
    capsule_path = root / CAPSULE_PATH
    if not capsule_path.exists():
        return None, "missing"
    try:
        capsule = json.loads(capsule_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None, "invalid"
    valid, fail_reason = validate_capsule(capsule)
    if not valid:
        return None, f"invalid:{fail_reason}"
    return capsule, "present"


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="OpenCode Idle Lane Steward — bounded Rig foreman for OpenCode."
    )
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--worktree", type=str, required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--no-stream",
        action="store_true",
        help="Fall back to non-streaming subprocess.run execution.",
    )
    parser.add_argument(
        "--show-reasoning-stream",
        action="store_true",
        help="Display reasoning/thinking events in terminal (never stored in artifacts).",
    )
    parser.add_argument(
        "--opencode-path",
        type=str,
        default="opencode",
        help="Path to the opencode binary (default: opencode).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    root = args.project_root.resolve()
    worktree = args.worktree
    dry_run = args.dry_run
    build_dir = root / BUILD_DIR
    last_run_path = build_dir / "opencode_idle_steward_last_run_v1.json"
    events_path = build_dir / "opencode_idle_steward_events_v1.jsonl"
    capsule_path = root / CAPSULE_PATH

    capsule, compiler_fallback_status = _read_steward_capsule(root)

    dirty = _git_dirty(root)
    branch = _git_branch(root)
    head = _git_head(root)
    items = _read_jsonl(root / QUEUE_PATH)
    lanes = _read_lanes(root)

    if not items:
        _write_run_and_event(
            last_run_path,
            events_path,
            "no_action",
            "no_queue_items",
            root,
            worktree,
            dry_run,
            branch,
            head,
            dirty,
            blockers=["no_queue_items"],
            compiler_fallback_status=compiler_fallback_status,
        )
        return 0

    item, blockers, comp = _select_task(items, lanes, root, _dirty_files_set(dirty))

    if item is None and any(i.get("status") in _RUNNABLE_STATUSES for i in items):
        _handle_audit_path(
            root,
            build_dir,
            items,
            lanes,
            dirty,
            _dirty_files_set(dirty),
            last_run_path,
            events_path,
            worktree,
            dry_run,
            branch,
            head,
            compiler_fallback_status=compiler_fallback_status,
        )
        _compile_and_write_capsule(
            capsule_path,
            root,
            items,
            lanes,
            dirty,
            _dirty_files_set(dirty),
            item,
            blockers,
            comp,
            "audit_unblock_plan",
            compiler_fallback_status,
        )
        return 0

    state = _classify_state(
        item, blockers, comp, item.get("status") == "active" if item else False
    )

    if capsule and compiler_fallback_status == "present":
        capsule_action = capsule.get("recommended_action", "")
        if capsule_action in STEWARD_STATES and capsule_action != state:
            capsule_rationale = capsule.get("recommendation_rationale_codes", [])
            _append_event(
                events_path,
                {
                    "event": "capsule_action_mismatch",
                    "generated_at": _now_iso(),
                    "capsule_action": capsule_action,
                    "steward_action": state,
                    "capsule_rationale": capsule_rationale,
                    "note": "Steward retains dispatch authority; capsule recommendation is advisory only.",
                },
            )

    command_meta: dict | None = None
    if item and not blockers:
        command_meta = _try_launch(
            item,
            state,
            root,
            worktree,
            dry_run,
            no_stream=args.no_stream,
            show_reasoning=args.show_reasoning_stream,
            opencode_path=args.opencode_path,
            events_path=events_path,
        )
        if command_meta is None and state in _LAUNCHABLE_STATES:
            blockers = ["missing_prompt"]
            state = "blocked"

    _compile_and_write_capsule(
        capsule_path,
        root,
        items,
        lanes,
        dirty,
        _dirty_files_set(dirty),
        item,
        blockers,
        comp,
        state,
        compiler_fallback_status,
    )

    _write_run_and_event(
        last_run_path,
        events_path,
        state,
        "steward_run",
        root,
        worktree,
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
    return 0


def _write_diagnosis(build_dir: Path, diagnosis: SubstrateDiagnosis) -> None:
    diagnosis_path = build_dir / "opencode_steward_substrate_diagnosis_v1.json"
    _write_last_run(
        diagnosis_path,
        {
            "schema_version": "rig.relay.opencode_steward_substrate_diagnosis.v1",
            "diagnosis_id": diagnosis.diagnosis_id,
            "blocker_class": diagnosis.blocker_class,
            "generated_at": diagnosis.generated_at,
            "affected_artifact_paths": diagnosis.affected_artifact_paths,
            "artifact_hashes": diagnosis.artifact_hashes,
            "capsule_problem": diagnosis.capsule_problem,
            "recommended_repair_kind": diagnosis.recommended_repair_kind,
            "repairable": diagnosis.repairable,
            "repair_attempts_so_far": diagnosis.repair_attempts_so_far,
            "escalation_reason": diagnosis.escalation_reason,
        },
    )


def _write_repair_result(build_dir: Path, result: RepairResult) -> None:
    result_path = build_dir / "opencode_steward_repair_result_v1.json"
    _write_last_run(
        result_path,
        {
            "schema_version": "rig.relay.opencode_steward_repair_result.v1",
            "repair_id": result.repair_id,
            "diagnosis_id": result.diagnosis_id,
            "blocker_class": result.blocker_class,
            "generated_at": result.generated_at,
            "success": result.success,
            "new_capsule_valid": result.new_capsule_valid,
            "new_capsule_sha256": result.new_capsule_sha256,
            "exit_code": result.exit_code,
            "duration_ms": result.duration_ms,
            "paths_changed_hashes": result.paths_changed_hashes,
            "test_pass_count": result.test_pass_count,
            "test_fail_count": result.test_fail_count,
            "evidence_paths": result.evidence_paths,
            "redaction_status": result.redaction_status,
            "summary_text": result.summary_text,
        },
    )


def _try_repair(
    root: Path,
    build_dir: Path,
    events_path: Path,
    worktree: str,
    dry_run: bool,
    capsule: dict | None,
    compiler_fallback_status: str,
    opencode_path: str,
    no_stream: bool,
    show_reasoning: bool,
) -> str:
    blocker_class = _classify_substrate_blocker(capsule, compiler_fallback_status)
    if blocker_class is None:
        return "no_action"
    dirty = _git_dirty(root)
    evidence = assemble_raw_evidence(
        root,
        dirty=dirty,
        dirty_files=_dirty_files_set(dirty),
        branch=_git_branch(root),
        head=_git_head(root),
        repair_history_path=".build/rig-relay/derived/opencode_steward_repair_history_v1.json",
    )
    diagnosis = diagnose_substrate(blocker_class, capsule, evidence, [])
    _write_diagnosis(build_dir, diagnosis)
    if not diagnosis.repairable:
        _append_event(
            events_path,
            {
                "event": "repair_not_eligible",
                "blocker_class": blocker_class,
                "reason": diagnosis.escalation_reason or "not_repairable",
                "generated_at": _now_iso(),
            },
        )
        return "audit_unblock_plan"
    mission = build_repair_mission(diagnosis)
    item = {
        "task_id": f"steward_repair_{diagnosis.diagnosis_id[:8]}",
        "title": mission.title,
        "agent": "general-purpose",
        "status": "queued",
        "priority": 0,
        "prompt_path": "",
        "allowed_files": mission.allowed_files,
        "forbidden_files": mission.forbidden_files,
        "completion_criteria": {
            "required_artifacts": mission.required_artifacts,
            "required_tests": mission.targeted_tests,
            "max_continuations": mission.max_continuations,
        },
    }
    _ = _try_launch(
        item,
        "repair_steward_substrate",
        root,
        worktree,
        dry_run,
        no_stream=no_stream,
        show_reasoning=show_reasoning,
        opencode_path=opencode_path,
        events_path=events_path,
    )
    _append_event(
        events_path,
        {
            "event": "repair_dispatched",
            "blocker_class": blocker_class,
            "diagnosis_id": diagnosis.diagnosis_id,
            "generated_at": _now_iso(),
        },
    )
    return "repair_steward_substrate"


def _classify_substrate_blocker(
    capsule: dict | None, fallback_status: str
) -> str | None:
    if fallback_status.startswith("invalid"):
        return "context_capsule_invalid"
    if capsule is None and fallback_status == "missing":
        return None
    if fallback_status == "missing":
        return None
    return None


if __name__ == "__main__":
    sys.exit(main())
