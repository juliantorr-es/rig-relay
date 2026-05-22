"""Steward context assembler — canonical digestion boundary for OpenCode steward evidence.

The steward assembly pipeline:
  source artifacts (queue, lanes, reports, gates, dirty state)
    → assemble_raw_evidence (read + hash source files)
    → digest_to_capsule (compile normalized decision capsule)
    → validate_capsule (check schema, redaction, provenance)

The steward owns wake-up, decision timing, dispatch, and evidence emission.
It calls these functions through the canonical Rig Relay context boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
from typing import Any


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


CAPSULE_SCHEMA_VERSION = "rig.relay.opencode_steward_context_capsule.v1"

DIAGNOSIS_SCHEMA_VERSION = "rig.relay.opencode_steward_substrate_diagnosis.v1"

REPAIR_MISSION_SCHEMA_VERSION = "rig.relay.opencode_steward_substrate_repair_mission.v1"

REPAIR_RESULT_SCHEMA_VERSION = "rig.relay.opencode_steward_repair_result.v1"

_REPAIR_BLOCKER_CLASSES: tuple[str, ...] = (
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

_MAX_REPAIR_ATTEMPTS_PER_BLOCKER = 2


def _resolve_safe(root: Path, relative: str) -> Path | None:
    resolved = (root / relative).resolve()
    if not str(resolved).startswith(str(root.resolve())):
        return None
    return resolved


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    items: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            items.append(json.loads(stripped))
        except json.JSONDecodeError:
            pass
    return items


@dataclass
class RawEvidenceBundle:
    source_paths: list[str]
    source_hashes: list[str]
    queue_items: list[dict[str, Any]]
    lanes: list[dict[str, Any]]
    dirty: dict[str, Any]
    dirty_files: set[str]
    branch: str
    head: str
    worker_reports: list[dict[str, Any]]
    gate_results: list[dict[str, Any]]
    repair_history: list[dict[str, Any]]


@dataclass
class CapsuleDigestionResult:
    capsule: dict[str, Any]
    capsule_sha256: str
    unresolved_seams: list[dict[str, Any]]
    recommended_action: str
    rationale_codes: list[str]


@dataclass
class SubstrateDiagnosis:
    diagnosis_id: str
    blocker_class: str
    generated_at: str
    affected_artifact_paths: list[str]
    artifact_hashes: list[str]
    capsule_problem: str
    capsule_data: dict[str, Any] | None
    recommended_repair_kind: str
    repairable: bool
    repair_attempts_so_far: int
    escalation_reason: str | None


@dataclass
class RepairMissionPacket:
    repair_id: str
    diagnosis_id: str
    blocker_class: str
    title: str
    prompt_text: str
    allowed_files: list[str]
    forbidden_files: list[str]
    targeted_tests: list[str]
    required_artifacts: list[str]
    max_continuations: int


@dataclass
class RepairResult:
    repair_id: str
    diagnosis_id: str
    blocker_class: str
    generated_at: str
    success: bool
    new_capsule_valid: bool
    new_capsule_sha256: str | None
    exit_code: int | None
    duration_ms: int | None
    paths_changed_hashes: list[str]
    test_pass_count: int
    test_fail_count: int
    evidence_paths: list[str]
    redaction_status: str
    summary_text: str


def assemble_raw_evidence(
    project_root: Path,
    queue_rel: str = ".rig/roadmap/queue.jsonl",
    lanes_rel: str = ".rig/roadmap/lanes.jsonl",
    worker_reports_dir: str = ".rig/opencode/worker_reports",
    dirty: dict[str, Any] | None = None,
    branch: str = "unknown",
    head: str = "unknown",
    dirty_files: set[str] | None = None,
    repair_history_path: str | None = None,
) -> RawEvidenceBundle:
    root = project_root.resolve()
    source_paths: list[str] = []
    source_hashes: list[str] = []

    queue_path = root / queue_rel
    lanes_path = root / lanes_rel
    source_paths.extend([str(queue_path), str(lanes_path)])
    if queue_path.exists():
        source_hashes.append(_sha256(queue_path.read_text(encoding="utf-8")))
    else:
        source_hashes.append("")
    if lanes_path.exists():
        source_hashes.append(_sha256(lanes_path.read_text(encoding="utf-8")))
    else:
        source_hashes.append("")

    queue_items = _read_jsonl(queue_path)
    lanes = _read_jsonl(lanes_path)

    reports_dir = root / worker_reports_dir
    worker_reports: list[dict[str, Any]] = []
    if reports_dir.is_dir():
        for rp in sorted(reports_dir.glob("*.json")):
            source_paths.append(str(rp))
            try:
                raw = rp.read_text(encoding="utf-8")
                source_hashes.append(_sha256(raw))
                worker_reports.append(json.loads(raw))
            except (json.JSONDecodeError, OSError):
                source_hashes.append(_sha256("unreadable:" + str(rp)))

    gate_results: list[dict[str, Any]] = []
    gates_dir = root / ".build" / "rig-relay" / "derived"
    for gp in sorted(gates_dir.glob("*gate*.json")):
        source_paths.append(str(gp))
        try:
            raw = gp.read_text(encoding="utf-8")
            source_hashes.append(_sha256(raw))
            gate_results.append(json.loads(raw))
        except (json.JSONDecodeError, OSError):
            source_hashes.append(_sha256("unreadable:" + str(gp)))

    repair_history: list[dict[str, Any]] = []
    if repair_history_path:
        rhp = root / repair_history_path
        if rhp.exists():
            source_paths.append(str(rhp))
            raw_rh = rhp.read_text(encoding="utf-8")
            source_hashes.append(_sha256(raw_rh))
            try:
                repair_history = json.loads(raw_rh).get("attempts", [])
            except json.JSONDecodeError:
                pass

    return RawEvidenceBundle(
        source_paths=source_paths,
        source_hashes=source_hashes,
        queue_items=queue_items,
        lanes=lanes,
        dirty=dirty or {},
        dirty_files=dirty_files or set(),
        branch=branch,
        head=head,
        worker_reports=worker_reports,
        gate_results=gate_results,
        repair_history=repair_history,
    )


def digest_to_capsule(
    evidence: RawEvidenceBundle,
    *,
    selected_item: dict[str, Any] | None = None,
    blockers: list[str] | None = None,
    completion: dict[str, Any] | None = None,
    state: str = "no_action",
    project_root: Path | None = None,
) -> CapsuleDigestionResult:
    capsule_id = _sha256(
        f"{_now_iso()}:{evidence.head}:{len(evidence.queue_items)}:{state}"
    )[:16]
    capsule: dict[str, Any] = {
        "schema_version": CAPSULE_SCHEMA_VERSION,
        "capsule_id": capsule_id,
        "generated_at": _now_iso(),
        "source_artifact_paths": evidence.source_paths,
        "source_artifact_hashes": evidence.source_hashes,
        "active_lane_summary": {
            "total_active_lanes": sum(
                1 for ln in evidence.lanes if ln.get("status") == "active"
            ),
            "lanes": [
                {
                    "lane_id": ln.get("lane_id", ln.get("task_id", "")),
                    "task_id": ln.get("task_id", ""),
                    "status": ln.get("status", ""),
                    "owned_file_count": len(ln.get("owned_files") or []),
                    "last_heartbeat": ln.get("updated_at", ""),
                }
                for ln in evidence.lanes
            ],
        },
        "worker_report_summary": _digest_worker_reports(evidence.worker_reports),
        "lease_summary": {
            "active_lane_leases": sum(
                1 for ln in evidence.lanes if ln.get("status") == "active"
            ),
            "active_path_leases": sum(
                len(ln.get("owned_files") or []) for ln in evidence.lanes
            ),
            "collision_count": _count_collisions(evidence.lanes),
        },
        "dirty_state_summary": {
            "modified_count": evidence.dirty.get("modified_count", 0),
            "staged_count": evidence.dirty.get("staged_count", 0),
            "untracked_count": evidence.dirty.get("untracked_count", 0),
            "dirty_file_hashes": [
                _sha256(f[3:].strip())
                for f in evidence.dirty.get("dirty_files", [])
                if len(f) > 3
            ],
        },
        "evidence_digest": {
            "total_evidence_artifacts": len(evidence.worker_reports)
            + len(evidence.gate_results),
            "relevant_finding_count": 0,
            "relevant_gate_count": len(evidence.gate_results),
            "evidence_path_hashes": [_sha256(p) for p in evidence.source_paths],
        },
        "gate_status": _digest_gates(evidence.gate_results),
        "completion_criteria_status": {
            "required_artifacts_present": completion.get(
                "required_artifacts_present", False
            )
            if completion
            else False,
            "required_tests_present": completion.get("required_tests_present", False)
            if completion
            else False,
            "final_report_present": completion.get("final_report_present", False)
            if completion
            else False,
            "schema_validation_passed": completion.get(
                "schema_validation_passed", False
            )
            if completion
            else False,
            "max_continuations_exceeded": completion.get(
                "max_continuations_exceeded", False
            )
            if completion
            else False,
            "max_failed_attempts_exceeded": completion.get(
                "max_failed_attempts_exceeded", False
            )
            if completion
            else False,
        },
        "unresolved_seams": [],
        "decision_inputs": _build_decision_inputs(
            evidence, selected_item, blockers or [], completion, project_root
        ),
        "recommended_action": state,
        "recommendation_rationale_codes": [f"blocker:{b}" for b in (blockers or [])]
        or ["no_blockers"],
        "redaction_status": "content_light",
        "compiler_fallback_status": "present",
    }
    unresolved = _find_unresolved_seams(evidence, completion, blockers)
    capsule["unresolved_seams"] = unresolved
    capsule_sha256 = _sha256(json.dumps(capsule, sort_keys=True, ensure_ascii=False))

    return CapsuleDigestionResult(
        capsule=capsule,
        capsule_sha256=capsule_sha256,
        unresolved_seams=unresolved,
        recommended_action=state,
        rationale_codes=capsule["recommendation_rationale_codes"],
    )


def validate_capsule(capsule: dict[str, Any]) -> tuple[bool, str | None]:
    if capsule.get("schema_version") != CAPSULE_SCHEMA_VERSION:
        return False, "schema_version_mismatch"
    if capsule.get("redaction_status") not in {"content_light", "redacted_full"}:
        return False, "redaction_status_invalid"
    required = {
        "capsule_id",
        "generated_at",
        "decision_inputs",
        "recommended_action",
        "source_artifact_paths",
        "source_artifact_hashes",
    }
    if not all(k in capsule for k in required):
        return False, "missing_required_keys"
    if not isinstance(capsule.get("source_artifact_hashes"), list):
        return False, "source_hashes_not_list"
    return True, None


def diagnose_substrate(
    blocker_class: str,
    capsule: dict[str, Any] | None,
    evidence: RawEvidenceBundle,
    repair_history: list[dict[str, Any]],
) -> SubstrateDiagnosis:
    generated_at = _now_iso()
    diagnosis_id = _sha256(f"{blocker_class}:{generated_at}")[:16]
    attempts = sum(
        1 for rh in repair_history if rh.get("blocker_class") == blocker_class
    )
    escalate = None
    repairable = blocker_class in _REPAIR_BLOCKER_CLASSES
    if attempts >= _MAX_REPAIR_ATTEMPTS_PER_BLOCKER:
        repairable = False
        escalate = f"max_repair_attempts_exceeded ({attempts}/{_MAX_REPAIR_ATTEMPTS_PER_BLOCKER})"

    return SubstrateDiagnosis(
        diagnosis_id=diagnosis_id,
        blocker_class=blocker_class,
        generated_at=generated_at,
        affected_artifact_paths=evidence.source_paths if evidence else [],
        artifact_hashes=evidence.source_hashes if evidence else [],
        capsule_problem=(
            f"capsule invalid: {validate_capsule(capsule)[1]}"
            if capsule
            else "capsule missing"
        ),
        capsule_data=capsule,
        recommended_repair_kind=f"repair_{blocker_class}",
        repairable=repairable,
        repair_attempts_so_far=attempts,
        escalation_reason=escalate,
    )


def build_repair_mission(
    diagnosis: SubstrateDiagnosis,
    prompt_base: str = "Repair the steward substrate problem identified in the diagnosis.",
) -> RepairMissionPacket:
    repair_id = f"repair_{diagnosis.diagnosis_id}"
    return RepairMissionPacket(
        repair_id=repair_id,
        diagnosis_id=diagnosis.diagnosis_id,
        blocker_class=diagnosis.blocker_class,
        title=f"Self-Repair: {diagnosis.blocker_class}",
        prompt_text=(
            f"{prompt_base}\n\n"
            f"Diagnosis file: .build/rig-relay/derived/opencode_steward_substrate_diagnosis_v1.json\n"
            f"Blocked by: {diagnosis.blocker_class}\n"
            f"Problem: {diagnosis.capsule_problem}\n"
            f"Affected artifacts: {', '.join(diagnosis.affected_artifact_paths[:10])}\n"
        ),
        allowed_files=_repair_allowed_files(diagnosis.blocker_class),
        forbidden_files=[
            ".build/rig-relay/**",
            ".rig/opencode/sessions.jsonl",
            ".rig/opencode/leases.jsonl",
            "docs/findings/**",
            "docs/schemas/*.schema.json",
            ".git/**",
        ],
        targeted_tests=_repair_targeted_tests(diagnosis.blocker_class),
        required_artifacts=[
            ".build/rig-relay/derived/opencode_steward_context_capsule_v1.json",
            ".build/rig-relay/derived/opencode_steward_repair_result_v1.json",
        ],
        max_continuations=2,
    )


def build_repair_result(
    repair_id: str,
    diagnosis_id: str,
    blocker_class: str,
    success: bool,
    capsule_sha256: str | None = None,
    exit_code: int | None = None,
    duration_ms: int | None = None,
    paths_changed: list[str] | None = None,
    test_pass: int = 0,
    test_fail: int = 0,
) -> RepairResult:
    return RepairResult(
        repair_id=repair_id,
        diagnosis_id=diagnosis_id,
        blocker_class=blocker_class,
        generated_at=_now_iso(),
        success=success,
        new_capsule_valid=success and capsule_sha256 is not None,
        new_capsule_sha256=capsule_sha256,
        exit_code=exit_code,
        duration_ms=duration_ms,
        paths_changed_hashes=[_sha256(p) for p in (paths_changed or [])],
        test_pass_count=test_pass,
        test_fail_count=test_fail,
        evidence_paths=[
            ".build/rig-relay/derived/opencode_steward_context_capsule_v1.json",
            ".build/rig-relay/derived/opencode_steward_repair_result_v1.json",
        ],
        redaction_status="content_light",
        summary_text=(
            f"Repair {repair_id} for {blocker_class}: "
            f"{'succeeded' if success else 'failed'}"
        ),
    )


def _digest_worker_reports(reports: list[dict[str, Any]]) -> dict[str, Any]:
    completed_ids: list[str] = []
    summaries: list[dict[str, Any]] = []
    for rp in reports:
        lid = rp.get("lane_id", rp.get("task_id", ""))
        if lid:
            completed_ids.append(lid)
        summaries.append({
            "worker_id": rp.get("worker_id", ""),
            "lane_id": lid,
            "exit_code": rp.get("exit_code"),
            "duration_ms": rp.get("duration_ms"),
            "paths_changed_hashes": rp.get("paths_changed_hashes", []),
            "test_pass_count": rp.get("test_pass_count", 0),
            "test_fail_count": rp.get("test_fail_count", 0),
        })
    return {
        "total_reports": len(reports),
        "completed_lane_ids": completed_ids,
        "reports": summaries,
    }


def _count_collisions(lanes: list[dict[str, Any]]) -> int:
    owned: dict[str, list[str]] = {}
    for ln in lanes:
        for f in ln.get("owned_files") or []:
            owned.setdefault(f, []).append(ln.get("lane_id") or ln.get("task_id") or "")
    return sum(1 for ids in owned.values() if len(ids) > 1)


def _digest_gates(gate_results: list[dict[str, Any]]) -> dict[str, Any]:
    passed = sum(
        1
        for g in gate_results
        if isinstance(g.get("verdict") or g.get("status"), str)
        and (g.get("verdict") or g.get("status") or "").upper()
        in {"PASS", "OK", "ALLOW"}
    )
    failed = sum(
        1
        for g in gate_results
        if isinstance(g.get("verdict") or g.get("status"), str)
        and (g.get("verdict") or g.get("status") or "").upper()
        in {"FAIL", "BLOCKED", "ERROR"}
    )
    return {
        "total_gates_checked": len(gate_results),
        "passed_count": passed,
        "failed_count": failed,
        "missing_count": 0,
    }


def _build_decision_inputs(
    evidence: RawEvidenceBundle,
    item: dict[str, Any] | None,
    blockers: list[str],
    completion: dict[str, Any] | None,
    project_root: Path | None = None,
) -> dict[str, Any]:
    active_ownership: dict[str, str] = {}
    for ln in evidence.lanes:
        if ln.get("status") != "active":
            continue
        lid = ln.get("lane_id") or ln.get("task_id") or ""
        for f in ln.get("owned_files") or []:
            active_ownership[f] = lid

    per_task: list[dict[str, Any]] = []
    blocker_summary: dict[str, int] = {}
    runnable = 0
    active_count = sum(1 for i in evidence.queue_items if i.get("status") == "active")
    completed_count = sum(
        1 for i in evidence.queue_items if i.get("status") == "completed"
    )
    blocked_count = sum(1 for i in evidence.queue_items if i.get("status") == "blocked")

    for qi in evidence.queue_items:
        task_blockers = _classify_item_blockers(
            qi, active_ownership, evidence.dirty_files, completion
        )
        if not task_blockers:
            runnable += 1
        else:
            blocked_count += 1
        for b in task_blockers:
            blocker_summary[b] = blocker_summary.get(b, 0) + 1
        per_task.append({
            "task_id": qi.get("task_id", ""),
            "title": qi.get("title", ""),
            "status": qi.get("status", ""),
            "priority": qi.get("priority", 0),
            "blocker_classes": task_blockers,
        })

    selected_prompt_sha256 = ""
    if item and project_root:
        pp = item.get("prompt_path", "")
        resolved = _resolve_safe(project_root, pp)
        if resolved and resolved.exists():
            selected_prompt_sha256 = _sha256(resolved.read_text(encoding="utf-8"))

    return {
        "total_queue_items": len(evidence.queue_items),
        "runnable_count": runnable,
        "blocked_count": blocked_count,
        "active_count": active_count,
        "completed_count": completed_count,
        "blocker_summary": blocker_summary,
        "selected_task_id": item.get("task_id", "") if item else "",
        "selected_task_status": item.get("status", "") if item else "",
        "selected_task_priority": item.get("priority", 0) if item else 0,
        "selected_task_title": item.get("title", "") if item else "",
        "selected_task_agent": item.get("agent", "") if item else "",
        "selected_task_prompt_sha256": selected_prompt_sha256,
        "selected_task_allowed_file_hashes": [
            _sha256(f) for f in (item.get("allowed_files") or [])
        ]
        if item
        else [],
        "selected_task_blocker_classes": blockers,
        "per_task_blockers": per_task,
        "cross_lane_collisions": [],
    }


def _classify_item_blockers(
    qi: dict[str, Any],
    active_ownership: dict[str, str],
    dirty_files: set[str],
    completion: dict[str, Any] | None,
) -> list[str]:
    blockers: list[str] = []
    allowed = qi.get("allowed_files") or []
    forbidden = qi.get("forbidden_files") or []
    ds = dirty_files or set()
    for f in allowed:
        if f in ds:
            blockers.append("dirty_overlap")
            break
    for f in forbidden:
        if f in ds:
            blockers.append("forbidden_file_scope")
            break
    for f in allowed:
        if f in active_ownership:
            blockers.append("lane_ownership_collision")
            break
    if completion:
        if not completion.get("required_artifacts_present", False):
            blockers.append("missing_required_artifact")
        if not completion.get("final_report_present", False):
            blockers.append("missing_final_report")
        if completion.get("max_continuations_exceeded", False):
            blockers.append("max_attempts_exceeded")
    return list(dict.fromkeys(blockers))


def _find_unresolved_seams(
    evidence: RawEvidenceBundle,
    completion: dict[str, Any] | None,
    blockers: list[str] | None,
) -> list[dict[str, Any]]:
    seams: list[dict[str, Any]] = []
    for i, qi in enumerate(evidence.queue_items):
        criteria = qi.get("completion_criteria") or {}
        for art in criteria.get("required_artifacts") or []:
            seams.append({
                "seam_id": f"SEAM-MISSING-ARTIFACT-{i}",
                "description": f"Task {qi.get('task_id', '')}: missing artifact {art}",
                "severity": "high",
                "affected_artifact_paths": [art],
            })
        report_path = criteria.get("final_report_path")
        if report_path:
            seams.append({
                "seam_id": f"SEAM-MISSING-REPORT-{i}",
                "description": f"Task {qi.get('task_id', '')}: missing report {report_path}",
                "severity": "high",
                "affected_artifact_paths": [report_path],
            })
    return seams


def _repair_allowed_files(blocker_class: str) -> list[str]:
    base = [
        ".build/rig-relay/derived/opencode_steward_context_capsule_v1.json",
        ".build/rig-relay/derived/opencode_idle_steward_last_run_v1.json",
    ]
    if blocker_class in ("context_capsule_invalid", "context_capsule_stale"):
        base.append(".build/rig-relay/derived/**")
    if blocker_class == "steward_schema_validation_failed":
        base.append(
            "docs/schemas/rig.relay.opencode_steward_context_capsule.v1.schema.json"
        )
    return base


def _repair_targeted_tests(blocker_class: str) -> list[str]:
    return [
        "tests/governance/test_opencode_idle_steward.py::TestCapsuleSchemaContract",
        "tests/governance/test_opencode_idle_steward.py::TestCapsuleConsumption",
    ]


__all__ = [
    "CAPSULE_SCHEMA_VERSION",
    "DIAGNOSIS_SCHEMA_VERSION",
    "REPAIR_MISSION_SCHEMA_VERSION",
    "REPAIR_RESULT_SCHEMA_VERSION",
    "CapsuleDigestionResult",
    "RawEvidenceBundle",
    "RepairMissionPacket",
    "RepairResult",
    "SubstrateDiagnosis",
    "assemble_raw_evidence",
    "build_repair_mission",
    "build_repair_result",
    "diagnose_substrate",
    "digest_to_capsule",
    "validate_capsule",
]
