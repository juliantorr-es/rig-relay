"""Substrate self-repair for the OpenCode steward.

Owns: diagnosis generation, repair mission dispatch, repair result recording.
Does not own: classification, capsule assembly, execution, tracing.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from rig_relay.cli._steward._constants import (
    _REPAIR_BLOCKER_CLASSES,
    append_event,
    now_iso,
    write_last_run,
)
from rig_relay.governance.steward_context_assembler import (
    RepairResult,
    SubstrateDiagnosis,
    build_repair_mission,
    diagnose_substrate,
)


def try_repair(
    root: Path,
    build_dir: Path,
    events_path: Path,
    dry_run: bool,
    capsule: dict[str, Any] | None,
    compiler_fallback_status: str,
    opencode_path: str,
    no_stream: bool,
    show_reasoning: bool,
) -> str:
    from rig_relay.cli._steward._classification import classify_substrate_blocker
    from rig_relay.cli._steward._execution import try_launch

    blocker_class = classify_substrate_blocker(capsule, compiler_fallback_status)
    if blocker_class is None or blocker_class not in _REPAIR_BLOCKER_CLASSES:
        return "no_action"

    diagnosis = diagnose_substrate(blocker_class, capsule, None, [])  # type: ignore[arg-type]
    write_diagnosis(build_dir, diagnosis)

    if not diagnosis.repairable:
        append_event(
            events_path,
            {
                "event": "repair_not_eligible",
                "blocker_class": blocker_class,
                "reason": diagnosis.escalation_reason or "not_repairable",
                "generated_at": now_iso(),
            },
        )
        return "audit_unblock_plan"

    mission = build_repair_mission(diagnosis)
    item: dict[str, Any] = {
        "task_id": f"steward_repair_{diagnosis.diagnosis_id[:8]}",
        "title": mission.title,
        "agent": "build",
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
    _ = try_launch(
        item,
        "repair_steward_substrate",
        root,
        dry_run,
        no_stream=no_stream,
        show_reasoning=show_reasoning,
        opencode_path=opencode_path,
        events_path=events_path,
    )
    append_event(
        events_path,
        {
            "event": "repair_dispatched",
            "blocker_class": blocker_class,
            "diagnosis_id": diagnosis.diagnosis_id,
            "generated_at": now_iso(),
        },
    )
    return "repair_steward_substrate"


def write_diagnosis(build_dir: Path, diagnosis: SubstrateDiagnosis) -> None:
    diagnosis_path = build_dir / "opencode_steward_substrate_diagnosis_v1.json"
    write_last_run(
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


def write_repair_result(build_dir: Path, result: RepairResult) -> None:
    result_path = build_dir / "opencode_steward_repair_result_v1.json"
    write_last_run(
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


__all__ = ["try_repair", "write_diagnosis", "write_repair_result"]
