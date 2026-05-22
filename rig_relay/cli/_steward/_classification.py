"""Task classification and selection for the OpenCode steward.

Owns: queue item validation, blocker classification, gate checking,
completion criteria evaluation, task selection, state classification.
Does not own: queue I/O, git operations, execution, tracing.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from rig_relay.cli._steward._constants import (
    _GATE_FAILURE_VERDICTS,
    PROMPTS_DIR,
    now_iso,
    path_overlaps,
    resolve_safe,
    sha256,
)
from rig_relay.cli._steward._queue import active_lane_files


def validate_queue_item(item: dict[str, Any]) -> list[str]:
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


def check_required_gates(root: Path, gates: list[str]) -> list[str]:
    failures: list[str] = []
    for gate_rel in gates:
        gate_path = resolve_safe(root, gate_rel)
        if gate_path is None:
            failures.append(f"gate_not_found:{gate_rel}")
            continue
        if not gate_path.exists():
            failures.append(f"gate_missing:{gate_rel}")
            continue
        try:
            import json

            gate_data = json.loads(gate_path.read_text(encoding="utf-8"))
            verdict = gate_data.get("verdict") or gate_data.get("status") or ""
            if isinstance(verdict, str) and verdict.upper() in _GATE_FAILURE_VERDICTS:
                failures.append(f"gate_failed:{gate_rel}")
        except Exception:
            failures.append(f"gate_unreadable:{gate_rel}")
    return failures


def check_completion_criteria(root: Path, item: dict[str, Any]) -> dict[str, Any]:
    criteria = item.get("completion_criteria") or {}
    result: dict[str, Any] = {
        "required_artifacts_present": True,
        "required_tests_present": True,
        "final_report_present": True,
        "schema_validation_passed": True,
        "max_continuations_exceeded": False,
        "max_failed_attempts_exceeded": False,
    }
    for art in criteria.get("required_artifacts") or []:
        p = resolve_safe(root, art)
        if p is None or not p.exists():
            result["required_artifacts_present"] = False
    for test_path in criteria.get("required_tests") or []:
        p = resolve_safe(root, test_path)
        if p is None or not p.exists():
            result["required_tests_present"] = False
    report_path = criteria.get("final_report_path")
    if report_path:
        p = resolve_safe(root, report_path)
        if p is None or not p.exists():
            result["final_report_present"] = False
    max_cont = item.get("max_continuations", 3)
    if item.get("continuation_count", 0) >= max_cont:
        result["max_continuations_exceeded"] = True
    max_fail = item.get("max_failed_attempts", 2)
    if item.get("failed_attempts", 0) >= max_fail:
        result["max_failed_attempts_exceeded"] = True
    return result


def all_completion_criteria_satisfied(comp: dict[str, Any]) -> bool:
    return (
        comp["required_artifacts_present"]
        and comp["required_tests_present"]
        and comp["final_report_present"]
        and comp["schema_validation_passed"]
    )


def check_prompt_blocker(item: dict[str, Any], prompt_hash: str | None) -> str | None:
    if prompt_hash is None:
        return "missing_prompt"
    prompt_path = item.get("prompt_path", "")
    prompts_prefix = f"{PROMPTS_DIR}/"
    if not prompt_path.startswith(prompts_prefix):
        return "missing_prompt"
    return None


def check_file_blockers(
    allowed: list[str],
    forbidden: list[str],
    dirty_files: set[str],
    active_ownership: dict[str, str],
    stop_on_dirty_overlap: bool = True,
) -> list[str]:
    result: list[str] = []
    if stop_on_dirty_overlap and any(path_overlaps(f, dirty_files) for f in allowed):
        result.append("dirty_overlap")
    if stop_on_dirty_overlap and any(path_overlaps(f, dirty_files) for f in forbidden):
        result.append("forbidden_file_scope")
    if any(f in active_ownership for f in allowed):
        result.append("lane_ownership_collision")
    return result


def check_completion_blockers(item: dict[str, Any], comp: dict[str, Any]) -> list[str]:
    result: list[str] = []
    if all_completion_criteria_satisfied(comp):
        return result
    if comp["required_artifacts_present"] is False:
        result.append("missing_required_artifact")
    if comp["final_report_present"] is False:
        result.append("missing_final_report")
    if item.get("completion_criteria", {}).get("schema_validation_required"):
        result.append("schema_validation_failure")
    return result


def classify_blockers(
    item: dict[str, Any],
    errors: list[str],
    prompt_hash: str | None,
    dirty_files: set[str],
    active_ownership: dict[str, str],
    gate_failures: list[str],
    comp: dict[str, Any],
) -> list[str]:
    blockers: list[str] = []
    if errors:
        blockers.append("malformed_queue_item")
    if pb := check_prompt_blocker(item, prompt_hash):
        blockers.append(pb)
    blockers.extend(
        check_file_blockers(
            item.get("allowed_files") or [],
            item.get("forbidden_files") or [],
            dirty_files,
            active_ownership,
            stop_on_dirty_overlap=item.get("stop_on_dirty_overlap", True),
        )
    )
    if gate_failures:
        blockers.append("failed_gate")
    if comp["max_continuations_exceeded"] or comp["max_failed_attempts_exceeded"]:
        blockers.append("max_attempts_exceeded")
    blockers.extend(check_completion_blockers(item, comp))
    return list(dict.fromkeys(blockers))


def select_task(
    items: list[dict[str, Any]],
    lanes: list[dict[str, Any]],
    root: Path,
    dirty_files: set[str],
) -> tuple[dict[str, Any] | None, list[str], dict[str, Any] | None]:
    ownership = active_lane_files(lanes)
    active_items = [i for i in items if i.get("status") == "active"]
    active_items.sort(key=lambda i: i.get("priority", 999))

    for active in active_items:
        errors = validate_queue_item(active)
        if errors:
            continue
        prompt_path = active.get("prompt_path", "")
        prompt_hash = _prompt_sha256(root, prompt_path)
        comp = check_completion_criteria(root, active)
        if (
            all_completion_criteria_satisfied(comp)
            and not comp["max_continuations_exceeded"]
        ):
            return active, [], comp
        gates = active.get("required_gates_before") or []
        gate_failures = check_required_gates(root, gates)
        blockers = classify_blockers(
            active, [], prompt_hash, dirty_files, ownership, gate_failures, comp
        )
        if not blockers:
            return active, blockers, comp
        if (
            all_completion_criteria_satisfied(comp)
            and not comp["max_continuations_exceeded"]
        ):
            return active, ["unclear_completion_state"], comp

    queued = [i for i in items if i.get("status") == "queued"]
    queued.sort(key=lambda i: i.get("priority", 999))

    for item in queued:
        errors = validate_queue_item(item)
        prompt_path = item.get("prompt_path", "")
        prompt_hash = _prompt_sha256(root, prompt_path)
        comp = check_completion_criteria(root, item)
        gates = item.get("required_gates_before") or []
        gate_failures = check_required_gates(root, gates)
        blockers = classify_blockers(
            item, errors, prompt_hash, dirty_files, ownership, gate_failures, comp
        )
        if not blockers:
            return item, blockers, comp

    return None, [], None


def classify_state(
    item: dict[str, Any] | None,
    blockers: list[str],
    comp: dict[str, Any] | None,
    is_active: bool,
) -> str:
    if item is None:
        return "audit_unblock_plan" if blockers else "no_action"
    if blockers:
        return "blocked"
    if comp and all_completion_criteria_satisfied(comp):
        return "finalize_lane" if is_active else "advance_to_next_lane"
    return "continue_lane" if is_active else "advance_to_next_lane"


def classify_substrate_blocker(
    capsule: dict[str, Any] | None, fallback_status: str
) -> str | None:
    if fallback_status.startswith("invalid"):
        return "context_capsule_invalid"
    return None


def build_audit(
    root: Path,
    items: list[dict[str, Any]],
    lanes: list[dict[str, Any]],
    dirty: dict[str, Any],
    dirty_files: set[str],
    branch: str,
    head: str,
) -> dict[str, Any]:
    from rig_relay.cli._steward._queue import active_lane_files

    ownership = active_lane_files(lanes)
    per_task: list[dict[str, Any]] = []
    blocker_summary: dict[str, int] = {}
    for qi in items:
        errors = validate_queue_item(qi)
        prompt_path = qi.get("prompt_path", "")
        prompt_hash = _prompt_sha256(root, prompt_path)
        comp = check_completion_criteria(root, qi)
        gates = qi.get("required_gates_before") or []
        gate_failures = check_required_gates(root, gates)
        task_blockers = classify_blockers(
            qi, errors, prompt_hash, dirty_files, ownership, gate_failures, comp
        )
        for b in task_blockers:
            blocker_summary[b] = blocker_summary.get(b, 0) + 1
        per_task.append({
            "task_id": qi.get("task_id", ""),
            "title": qi.get("title", ""),
            "status": qi.get("status", ""),
            "priority": qi.get("priority", 0),
            "blocker_classes": task_blockers,
        })
    ts = now_iso().replace(":", "").replace("-", "").replace("T", "")
    slices: list[dict[str, Any]] = []
    if blocker_summary.get("missing_prompt", 0) > 0:
        slices.append({
            "recommendation_id": f"unblock-{ts}-1",
            "title": "Provision missing prompt files",
            "blocker_classes_addressed": ["missing_prompt"],
            "risk_level": "low",
        })
    if blocker_summary.get("dirty_overlap", 0) > 0:
        slices.append({
            "recommendation_id": f"unblock-{ts}-2",
            "title": "Resolve dirty state overlap",
            "blocker_classes_addressed": ["dirty_overlap"],
            "risk_level": "medium",
        })
    return {
        "schema_version": "rig.relay.opencode_unblock_audit.v1",
        "generated_at": now_iso(),
        "branch": branch,
        "head": head,
        "dirty_state_summary": {
            "modified_count": dirty.get("modified_count", 0),
            "staged_count": dirty.get("staged_count", 0),
            "untracked_count": dirty.get("untracked_count", 0),
        },
        "total_queue_items": len(items),
        "blocker_summary": blocker_summary,
        "per_task_blockers": per_task,
        "recommended_unblock_slices": slices,
        "safety_stop_reason": "No safe non-blocked work available.",
    }


def _prompt_sha256(root: Path, prompt_path: str) -> str | None:
    resolved = resolve_safe(root, prompt_path)
    if resolved is None or not resolved.exists():
        return None
    return sha256(resolved.read_text(encoding="utf-8"))


def read_prompt_text(root: Path, prompt_path: str) -> str | None:
    resolved = resolve_safe(root, prompt_path)
    if resolved is None or not resolved.exists():
        return None
    return resolved.read_text(encoding="utf-8")


__all__ = [
    "all_completion_criteria_satisfied",
    "check_completion_blockers",
    "check_completion_criteria",
    "check_file_blockers",
    "check_prompt_blocker",
    "check_required_gates",
    "classify_blockers",
    "classify_state",
    "classify_substrate_blocker",
    "read_prompt_text",
    "select_task",
    "validate_queue_item",
]
