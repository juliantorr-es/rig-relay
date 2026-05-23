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
            verdict = gate_data.get("verdict")
            if verdict is None:
                verdict = gate_data.get("status") or ""
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
        if any(f.startswith("gate_unreadable:") for f in gate_failures):
            blockers.append("gate_unreadable")
        else:
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
    *,
    claimed_task_ids: set[str] | None = None,
) -> tuple[dict[str, Any] | None, list[str], dict[str, Any] | None]:
    ownership = active_lane_files(lanes)
    claimed_task_ids = claimed_task_ids or set()
    skipped_blockers: list[str] = []
    active_items = [i for i in items if i.get("status") == "active"]
    active_items.sort(key=lambda i: i.get("priority", 999))

    for active in active_items:
        task_id = str(active.get("task_id", ""))
        if task_id and task_id in claimed_task_ids:
            skipped_blockers.append("lane_ownership_collision")
            continue
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
        task_id = str(item.get("task_id", ""))
        if task_id and task_id in claimed_task_ids:
            skipped_blockers.append("lane_ownership_collision")
            continue
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

    return None, list(dict.fromkeys(skipped_blockers)), None


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
    if fallback_status == "stale":
        return "context_capsule_stale"
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


def classify_paths(root: Path, paths: list[str]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {
        "implementation_files": [],
        "schemas": [],
        "canonical_configs": [],
        "generated_derived": [],
        "tests": [],
        "telemetry": [],
        "projections": [],
        "unknown_unclassified": [],
    }
    for p in paths:
        p_clean = p.replace("\\", "/")
        if (
            "rig_relay/core/telemetry/" in p_clean
            or "rig_relay/core/telemetry_runtime/" in p_clean
            or "telemetry-contribution-policy" in p_clean
            or p_clean.endswith("telemetry.py")
        ):
            result["telemetry"].append(p)
        elif (
            "rig_relay/desktop/projection.py" in p_clean
            or "rig_relay/review_projection/" in p_clean
            or "docs/json/site/" in p_clean
        ):
            result["projections"].append(p)
        elif (
            "tests/" in p_clean
            or p_clean.endswith("_test.py")
            or p_clean.startswith("test_")
        ):
            result["tests"].append(p)
        elif "docs/schemas/" in p_clean:
            result["schemas"].append(p)
        elif "docs/json/governance/" in p_clean or "docs/json/issues/" in p_clean:
            result["canonical_configs"].append(p)
        elif (
            ".build/" in p_clean
            or ".rig/opencode/worker_reports/" in p_clean
            or p_clean.endswith(".html")
            or "search-index.json" in p_clean
        ):
            result["generated_derived"].append(p)
        elif p_clean.endswith(".py") and (
            "rig_relay/" in p_clean or p_clean.startswith("scripts/")
        ):
            result["implementation_files"].append(p)
        else:
            result["unknown_unclassified"].append(p)
    return result


def _glob_match(path: str, pattern: str) -> bool:
    import re

    # Normalize slashes
    p_path = path.replace("\\", "/")
    p_pat = pattern.replace("\\", "/")

    # Replace **/ with a special marker first to avoid conflicts
    p = p_pat.replace("**/", "<GLOBSTAR_SLASH>")
    p = p.replace("**", "<GLOBSTAR>")
    # Escape the rest
    escaped = re.escape(p)
    # Replace markers
    escaped = escaped.replace("<GLOBSTAR_SLASH>", "(?:.*/)?")
    escaped = escaped.replace("<GLOBSTAR>", ".*")
    escaped = escaped.replace(r"\*", "[^/]*")
    escaped = escaped.replace(r"\?", "[^/]")
    regex_str = "^" + escaped + "$"
    return bool(re.match(regex_str, p_path))


def explain_artifact(root: Path, path: str) -> dict[str, Any]:
    try:
        path_obj = Path(path)
        if not path_obj.is_absolute():
            resolved = (root / path_obj).resolve()
        else:
            resolved = path_obj.resolve()
        resolved_root = root.resolve()
        if not str(resolved).startswith(str(resolved_root)):
            return {
                "family_name": "External Path",
                "class": "unknown",
                "governing_schema": "none",
                "mutation_path": "Path lies outside workspace boundary. Do not modify.",
                "content_light": True,
                "validation_command": "none",
                "related_artifacts": [],
                "risk": "Traversal outside workspace.",
                "protected_write_disposition": "deny",
            }
        rel_path = str(resolved.relative_to(resolved_root)).replace("\\", "/")
    except Exception:
        return {
            "family_name": "Invalid Path",
            "class": "unknown",
            "governing_schema": "none",
            "mutation_path": "Path cannot be resolved safely.",
            "content_light": True,
            "validation_command": "none",
            "related_artifacts": [],
            "risk": "Invalid path syntax or traversal.",
            "protected_write_disposition": "deny",
        }

    profile_path = root / "docs/json/governance/steward_profile.v1.json"
    profile: dict[str, Any] = {}
    if profile_path.exists():
        try:
            import json

            profile = json.loads(profile_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    families = profile.get("artifact_families", [])
    for family in families:
        for pattern in family.get("patterns", []):
            if _glob_match(rel_path, pattern):
                return {
                    "family_name": family["name"],
                    "class": family["class"],
                    "governing_schema": family.get("governing_schema", "none"),
                    "mutation_path": family["mutation_path"],
                    "content_light": family["content_light"],
                    "validation_command": family["validation_command"],
                    "related_artifacts": family["related_artifacts"],
                    "risk": family["risk"],
                    "protected_write_disposition": family[
                        "protected_write_disposition"
                    ],
                }

    return {
        "family_name": "Generic Workspace File",
        "class": "unknown",
        "governing_schema": "none",
        "mutation_path": "Edit as normal.",
        "content_light": False,
        "validation_command": "uv run pytest",
        "related_artifacts": [],
        "risk": "None identified.",
        "protected_write_disposition": "allow",
    }


def check_write_permission(root: Path, path: str) -> dict[str, Any]:
    explanation = explain_artifact(root, path)
    disp = explanation["protected_write_disposition"]
    if disp == "deny":
        return {
            "allowed": False,
            "action": "deny",
            "reason": f"Access denied: {explanation['family_name']} - {explanation['mutation_path']}",
        }
    return {
        "allowed": True,
        "action": disp,
        "reason": f"{explanation['family_name']}: {explanation['mutation_path']}",
    }


def build_validation_plan(root: Path, paths: list[str]) -> dict[str, Any]:
    targeted: list[dict[str, Any]] = []
    deferred: list[dict[str, Any]] = [
        {
            "command": "uv run pytest",
            "reason": "Full-suite pass should run once after the patch stabilizes",
        }
    ]
    skipped: list[dict[str, Any]] = []

    seen_cmds = set()

    for p in paths:
        p_clean = p.replace("\\", "/")
        explanation = explain_artifact(root, p)
        val_cmd = explanation.get("validation_command")

        if (
            "rig_relay/core/telemetry/" in p_clean
            or "rig_relay/core/telemetry_runtime/" in p_clean
            or "telemetry-contribution-policy" in p_clean
        ):
            cmd = "uv run pytest tests/telemetry/"
            if cmd not in seen_cmds:
                seen_cmds.add(cmd)
                targeted.append({
                    "command": cmd,
                    "classification": ["unit", "integration", "telemetry"],
                    "reason": "Validates telemetry emission and formatting changes",
                })
        elif (
            "rig_relay/cli/_steward/" in p_clean
            or "rig_relay/cli/steward.py" in p_clean
            or "rig_relay/governance/steward_context_assembler.py" in p_clean
        ):
            cmd = "uv run pytest tests/governance/test_opencode_idle_steward.py"
            if cmd not in seen_cmds:
                seen_cmds.add(cmd)
                targeted.append({
                    "command": cmd,
                    "classification": ["integration", "real-artifact"],
                    "reason": "Validates steward loop and dispatch logic",
                })
            cmd2 = "uv run pytest tests/governance/test_steward_actions.py"
            if cmd2 not in seen_cmds:
                seen_cmds.add(cmd2)
                targeted.append({
                    "command": cmd2,
                    "classification": ["integration", "real-artifact"],
                    "reason": "Validates steward v0 companion subcommands",
                })
        elif (
            "rig_relay/coordination/" in p_clean
            or "rig_relay/cli/_steward/_coordination.py" in p_clean
        ):
            cmd = "uv run pytest tests/coordination/test_steward_coordination_bridge.py"
            if cmd not in seen_cmds:
                seen_cmds.add(cmd)
                targeted.append({
                    "command": cmd,
                    "classification": ["integration", "substrate"],
                    "reason": "Validates coordination state projection and lease handling",
                })
        elif p_clean.endswith(".md"):
            skipped.append({
                "path": p,
                "reason": "Markdown documentation files do not affect runtime execution.",
            })
        elif "tests/" in p_clean:
            cmd = f"uv run pytest {p}"
            if cmd not in seen_cmds:
                seen_cmds.add(cmd)
                targeted.append({
                    "command": cmd,
                    "classification": ["unit"],
                    "reason": f"Verifies changed test file {p}",
                })
        elif val_cmd and val_cmd not in {"none", "uv run pytest"}:
            if val_cmd not in seen_cmds:
                seen_cmds.add(val_cmd)
                targeted.append({
                    "command": val_cmd,
                    "classification": ["integration"],
                    "reason": f"Validator for {explanation['family_name']} family",
                })

    return {
        "recommended_targeted_validation": targeted,
        "defer_until_converged": deferred,
        "intentionally_skipped_validation": skipped,
    }


__all__ = [
    "all_completion_criteria_satisfied",
    "build_validation_plan",
    "check_completion_blockers",
    "check_completion_criteria",
    "check_file_blockers",
    "check_prompt_blocker",
    "check_required_gates",
    "check_write_permission",
    "classify_blockers",
    "classify_paths",
    "classify_state",
    "classify_substrate_blocker",
    "explain_artifact",
    "read_prompt_text",
    "select_task",
    "validate_queue_item",
]
