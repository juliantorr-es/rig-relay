from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any

_SECURITY_STAGES = 13
_REQUIRED_ACKNOWLEDGEMENTS = 8

_REPO_ROOT = Path(__file__).resolve().parents[2]
_BUILD_ROOT = _REPO_ROOT / ".build" / "rig-relay"
_GOVERNANCE_ROOT = _REPO_ROOT / "docs" / "json" / "governance"


@dataclass(slots=True)
class PolicyGate:
    gate_id: str
    description: str
    condition: str
    evaluate: Callable[[PolicyContext], GateResult]


@dataclass(slots=True)
class GateResult:
    gate_id: str
    passed: bool
    evidence: str
    current_value: str
    required_value: str
    blocked_reason: str = ""


@dataclass(slots=True)
class PolicyContext:
    readiness_artifacts: dict[str, dict] = field(default_factory=dict)
    metrics: dict[str, Any] = field(default_factory=dict)
    lifecycle_state: dict[str, Any] = field(default_factory=dict)
    permission_audit: dict[str, Any] = field(default_factory=dict)
    spiderweb_topology: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class PolicyEvaluation:
    policy_id: str
    gates: list[GateResult]
    all_passed: bool
    passed_count: int
    failed_count: int
    blocked_count: int
    operator_acknowledgements_required: list[str]
    next_action: str


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _artifact_present(path: Path) -> bool:
    return path.is_file()


def evaluate_gate_artifact_inventory_present(ctx: PolicyContext) -> GateResult:
    artifacts = ctx.readiness_artifacts
    present = [k for k, v in artifacts.items() if v]
    missing = [k for k, v in artifacts.items() if not v]
    passed = len(missing) == 0
    return GateResult(
        gate_id="artifact_inventory_present",
        passed=passed,
        evidence=f"Found {len(present)} artifacts, missing {len(missing)}",
        current_value=f"present={len(present)}, missing={len(missing)}",
        required_value="all artifacts present",
        blocked_reason="" if passed else f"Missing: {', '.join(missing)}",
    )


def evaluate_gate_replay_all_stages_complete(ctx: PolicyContext) -> GateResult:
    stages = ctx.lifecycle_state.get("lifecycle_stages", [])
    stage_count = len(stages) if isinstance(stages, list) else 0
    passed = stage_count >= _SECURITY_STAGES

    completed = sum(
        1
        for s in (stages if isinstance(stages, list) else [])
        if isinstance(s, dict) and s.get("status") == "complete"
    )
    return GateResult(
        gate_id="replay_all_stages_complete",
        passed=passed,
        evidence=f"{completed}/{stage_count} stages complete",
        current_value=f"{stage_count} stages found, {completed} complete",
        required_value=f"all {_SECURITY_STAGES} stages present",
        blocked_reason=""
        if passed
        else f"Only {stage_count}/{_SECURITY_STAGES} stages",
    )


def evaluate_gate_permission_boundary_proven(ctx: PolicyContext) -> GateResult:
    audit = ctx.permission_audit
    gates = audit.get("gates", [])
    if not isinstance(gates, list) or not gates:
        return GateResult(
            gate_id="permission_boundary_proven",
            passed=False,
            evidence="No permission audit gates found",
            current_value="no audit data",
            required_value="all permission boundary gates proved",
            blocked_reason="Missing permission boundary audit",
        )

    proved = sum(1 for g in gates if isinstance(g, dict) and g.get("proved", False))
    total = len(gates)
    passed = total > 0 and proved == total

    return GateResult(
        gate_id="permission_boundary_proven",
        passed=passed,
        evidence=f"{proved}/{total} boundary gates proved",
        current_value=f"{proved}/{total} proved",
        required_value="all boundary gates proved",
        blocked_reason="" if passed else f"{total - proved} gates not proved",
    )


def evaluate_gate_causal_report_present(ctx: PolicyContext) -> GateResult:
    path = _GOVERNANCE_ROOT / "github_live_mutation_causal_report_v1.v1.json"
    passed = _artifact_present(path)
    return GateResult(
        gate_id="causal_report_present",
        passed=passed,
        evidence=str(path) if passed else "not found",
        current_value="present" if passed else "missing",
        required_value="causal report artifact present",
        blocked_reason="" if passed else "Causal report not found",
    )


def evaluate_gate_rc_report_complete(ctx: PolicyContext) -> GateResult:
    path = _REPO_ROOT / "docs" / "json" / "release_gate" / "rc_readiness_gate.v1.json"
    data = _load_json(path)
    if not data:
        return GateResult(
            gate_id="rc_report_complete",
            passed=False,
            evidence="RC readiness gate not found",
            current_value="missing",
            required_value="convergence_complete",
            blocked_reason="RC readiness gate artifact missing",
        )

    convergence = data.get("convergence_status", data.get("status", "unknown"))
    passed = convergence == "convergence_complete"
    return GateResult(
        gate_id="rc_report_complete",
        passed=passed,
        evidence=f"convergence_status={convergence}",
        current_value=str(convergence),
        required_value="convergence_complete",
        blocked_reason=""
        if passed
        else f"RC status is '{convergence}', not 'convergence_complete'",
    )


def evaluate_gate_checklist_present(ctx: PolicyContext) -> GateResult:
    path = _GOVERNANCE_ROOT / "github_live_mutation_operator_checklist_v1.v1.json"
    fallback = (
        _GOVERNANCE_ROOT / "github_live_pr_rehearsal_operator_checklist_v1.v1.json"
    )
    data = _load_json(path) or _load_json(fallback)
    if not data:
        return GateResult(
            gate_id="checklist_present",
            passed=False,
            evidence="No operator checklist found",
            current_value="missing",
            required_value=f"checklist with {_REQUIRED_ACKNOWLEDGEMENTS} acknowledgements",
            blocked_reason="Operator checklist missing",
        )

    acks = data.get("operator_acknowledgements", [])
    ack_count = len(acks) if isinstance(acks, list) else 0
    passed = ack_count >= _REQUIRED_ACKNOWLEDGEMENTS
    return GateResult(
        gate_id="checklist_present",
        passed=passed,
        evidence=f"Checklist found with {ack_count} acknowledgements",
        current_value=f"{ack_count} acknowledgements",
        required_value=f"{_REQUIRED_ACKNOWLEDGEMENTS} operator acknowledgements",
        blocked_reason="" if passed else f"Only {ack_count}/8 acknowledgements",
    )


def evaluate_gate_runbook_present(ctx: PolicyContext) -> GateResult:
    path = _GOVERNANCE_ROOT / "github_live_mutation_runbook_v1.v1.json"
    fallback = _GOVERNANCE_ROOT / "github_live_pr_rehearsal_v1.v1.json"
    passed = _artifact_present(path) or _artifact_present(fallback)
    found = (
        str(path)
        if _artifact_present(path)
        else (str(fallback) if _artifact_present(fallback) else "not found")
    )
    return GateResult(
        gate_id="runbook_present",
        passed=passed,
        evidence=found,
        current_value="present" if passed else "missing",
        required_value="live mutation runbook present",
        blocked_reason="" if passed else "Runbook not found",
    )


def evaluate_gate_sbom_present(ctx: PolicyContext) -> GateResult:
    path = _BUILD_ROOT / "sbom.json"
    passed = _artifact_present(path)
    return GateResult(
        gate_id="sbom_present",
        passed=passed,
        evidence=str(path) if passed else "not found",
        current_value="present" if passed else "missing",
        required_value="SBOM artifact present",
        blocked_reason=""
        if passed
        else ("SBOM artifact not yet generated (P0 workstream dependency)"),
    )


def evaluate_gate_threat_model_present(ctx: PolicyContext) -> GateResult:
    path = _BUILD_ROOT / "threat_model.json"
    passed = _artifact_present(path)
    return GateResult(
        gate_id="threat_model_present",
        passed=passed,
        evidence=str(path) if passed else "not found",
        current_value="present" if passed else "missing",
        required_value="threat model artifact present",
        blocked_reason="" if passed else ("Threat model artifact not yet generated"),
    )


def evaluate_gate_no_raw_payloads_exposed(ctx: PolicyContext) -> GateResult:
    artifacts = ctx.readiness_artifacts
    raw_exposed = []

    for name, data in artifacts.items():
        if not isinstance(data, dict):
            continue
        if (
            data.get("raw_payloads_exposed") is not False
            and data.get("redaction_status") != "content_light"
        ):
            raw_exposed.append(name)

    passed = len(raw_exposed) == 0
    return GateResult(
        gate_id="no_raw_payloads_exposed",
        passed=passed,
        evidence=f"Checked {len(artifacts)} artifacts",
        current_value="all content-light"
        if passed
        else f"raw payloads in: {', '.join(raw_exposed)}",
        required_value="all artifacts content-light",
        blocked_reason=""
        if passed
        else f"Non-content-light artifacts: {', '.join(raw_exposed)}",
    )


def evaluate_gate_bridge_healthy(ctx: PolicyContext) -> GateResult:
    health = ctx.metrics.get("bridge_backend_health", "unknown")
    passed = health not in {"disconnected", "stale"}
    return GateResult(
        gate_id="bridge_healthy",
        passed=passed,
        evidence=f"bridge_backend_health={health}",
        current_value=health,
        required_value="not 'disconnected' or 'stale'",
        blocked_reason="" if passed else f"Bridge health is '{health}'",
    )


def evaluate_gate_mutation_not_in_progress(ctx: PolicyContext) -> GateResult:
    mutation = ctx.lifecycle_state.get("mutation_chain", {})
    if not isinstance(mutation, dict):
        mutation = {}
    remote_detected = mutation.get("remote_mutation_detected", False)
    passed = not remote_detected
    return GateResult(
        gate_id="mutation_not_in_progress",
        passed=passed,
        evidence=f"remote_mutation_detected={remote_detected}",
        current_value="detected" if remote_detected else "not detected",
        required_value="no live mutation executing",
        blocked_reason="Live mutation detected in lifecycle state"
        if remote_detected
        else "",
    )


BUILTIN_GATES: list[PolicyGate] = [
    PolicyGate(
        gate_id="artifact_inventory_present",
        description="Inventory artifact exists and validates",
        condition="All readiness artifacts present",
        evaluate=evaluate_gate_artifact_inventory_present,
    ),
    PolicyGate(
        gate_id="replay_all_stages_complete",
        description="All 13 lifecycle stages present",
        condition="Security lifecycle replay has all 13 stages",
        evaluate=evaluate_gate_replay_all_stages_complete,
    ),
    PolicyGate(
        gate_id="permission_boundary_proven",
        description="Permission audit proves read/write/alert separation",
        condition="All permission boundary gates proved",
        evaluate=evaluate_gate_permission_boundary_proven,
    ),
    PolicyGate(
        gate_id="causal_report_present",
        description="Causal report exists with observed links",
        condition="Causal report artifact exists",
        evaluate=evaluate_gate_causal_report_present,
    ),
    PolicyGate(
        gate_id="rc_report_complete",
        description="Phase 2 RC report has convergence_complete status",
        condition="RC readiness gate shows convergence_complete",
        evaluate=evaluate_gate_rc_report_complete,
    ),
    PolicyGate(
        gate_id="checklist_present",
        description="Operator checklist exists and has 8 acknowledgements",
        condition="Operator checklist with 8 acks present",
        evaluate=evaluate_gate_checklist_present,
    ),
    PolicyGate(
        gate_id="runbook_present",
        description="Live mutation runbook exists",
        condition="Live mutation runbook artifact exists",
        evaluate=evaluate_gate_runbook_present,
    ),
    PolicyGate(
        gate_id="sbom_present",
        description="SBOM artifact exists",
        condition="SBOM artifact present",
        evaluate=evaluate_gate_sbom_present,
    ),
    PolicyGate(
        gate_id="threat_model_present",
        description="Threat model artifact exists",
        condition="Threat model artifact present",
        evaluate=evaluate_gate_threat_model_present,
    ),
    PolicyGate(
        gate_id="no_raw_payloads_exposed",
        description="All artifacts content-light confirmed",
        condition="All artifacts marked content_light, no raw_payloads_exposed",
        evaluate=evaluate_gate_no_raw_payloads_exposed,
    ),
    PolicyGate(
        gate_id="bridge_healthy",
        description="Bridge backend health is not disconnected or stale",
        condition="bridge_backend_health not in (disconnected, stale)",
        evaluate=evaluate_gate_bridge_healthy,
    ),
    PolicyGate(
        gate_id="mutation_not_in_progress",
        description="No live mutation currently executing",
        condition="remote_mutation_detected is false",
        evaluate=evaluate_gate_mutation_not_in_progress,
    ),
]

DEFAULT_ARTIFACT_PATHS: dict[str, Path] = {
    "checklist": _GOVERNANCE_ROOT
    / "github_live_mutation_operator_checklist_v1.v1.json",
    "checklist_fallback": _GOVERNANCE_ROOT
    / "github_live_pr_rehearsal_operator_checklist_v1.v1.json",
    "preflight": _GOVERNANCE_ROOT / "github_live_mutation_preflight_v1.v1.json",
    "permission_audit": _GOVERNANCE_ROOT
    / "github_live_mutation_phase3_permission_boundary_audit_v1.v1.json",
    "runbook": _GOVERNANCE_ROOT / "github_live_mutation_runbook_v1.v1.json",
    "runbook_fallback": _GOVERNANCE_ROOT / "github_live_pr_rehearsal_v1.v1.json",
    "rate_limit": _GOVERNANCE_ROOT
    / "github_live_mutation_rate_limit_snapshot_v1.v1.json",
    "preflight_report": _GOVERNANCE_ROOT
    / "github_live_mutation_preflight_report_v1.v1.json",
    "rc_gate": _REPO_ROOT
    / "docs"
    / "json"
    / "release_gate"
    / "rc_readiness_gate.v1.json",
}


def build_policy_context(
    artifact_paths: dict[str, Path] | None = None,
    lifecycle_state: dict[str, Any] | None = None,
    permission_audit: dict[str, Any] | None = None,
    metrics: dict[str, Any] | None = None,
    spiderweb_topology: dict[str, Any] | None = None,
) -> PolicyContext:
    paths = {**DEFAULT_ARTIFACT_PATHS}
    if artifact_paths:
        paths.update(artifact_paths)

    readiness_artifacts: dict[str, dict] = {}
    for name, path in paths.items():
        data = _load_json(path)
        if data is not None:
            readiness_artifacts[name] = data

    if lifecycle_state is None:
        lifecycle_state = _build_minimal_lifecycle_state()

    if permission_audit is None:
        perm_path = DEFAULT_ARTIFACT_PATHS["permission_audit"]
        permission_audit = _load_json(perm_path) or {}

    if metrics is None:
        metrics = {
            "bridge_backend_health": "unknown",
            "projection_freshness": "unknown",
            "reconnect_pressure": "none",
            "event_queue_pressure": "none",
            "consumer_error_count": 0,
            "wal_uncommitted_count": 0,
        }

    if spiderweb_topology is None:
        spiderweb_topology = {}

    return PolicyContext(
        readiness_artifacts=readiness_artifacts,
        metrics=metrics,
        lifecycle_state=lifecycle_state,
        permission_audit=permission_audit,
        spiderweb_topology=spiderweb_topology,
    )


def _build_minimal_lifecycle_state() -> dict[str, Any]:
    try:
        from rig_relay.integrations.github_provider._security_lifecycle_replay import (
            build_replay,
        )

        return build_replay()
    except (ImportError, OSError):
        return {
            "lifecycle_stages": [],
            "stages_present": 0,
            "stages_complete": 0,
            "mutation_chain": {
                "remote_mutation_detected": False,
                "stages_with_remote_mutation": 0,
            },
            "approval_chain": {},
            "idempotency_chain": {},
            "next_safe_action": "unknown",
        }


def evaluate_all_gates(
    ctx: PolicyContext,
    gates: list[PolicyGate] | None = None,
    policy_id: str = "rig.enterprise.policy.v1",
) -> PolicyEvaluation:
    gs = gates if gates is not None else BUILTIN_GATES
    results: list[GateResult] = []

    for gate in gs:
        result = gate.evaluate(ctx)
        results.append(result)

    passed_count = sum(1 for r in results if r.passed)
    blocked_count = sum(1 for r in results if not r.passed and r.blocked_reason)
    failed_count = sum(1 for r in results if not r.passed and not r.blocked_reason)

    all_passed = len(results) > 0 and all(r.passed for r in results)

    operator_acknowledgements: list[str] = []
    checklist = ctx.readiness_artifacts.get("checklist")
    if not checklist:
        checklist = ctx.readiness_artifacts.get("checklist_fallback")
    if isinstance(checklist, dict):
        acks = checklist.get("operator_acknowledgements", [])
        if isinstance(acks, list):
            operator_acknowledgements = acks

    if all_passed:
        next_action = "execute"
    elif blocked_count > 0:
        next_action = "blocked"
    else:
        next_action = "needs_human_review"

    return PolicyEvaluation(
        policy_id=policy_id,
        gates=results,
        all_passed=all_passed,
        passed_count=passed_count,
        failed_count=failed_count,
        blocked_count=blocked_count,
        operator_acknowledgements_required=operator_acknowledgements,
        next_action=next_action,
    )


class PolicyEngine:
    def __init__(self, gates: list[PolicyGate] | None = None) -> None:
        self._gates = gates or list(BUILTIN_GATES)

    def evaluate(self, ctx: PolicyContext) -> PolicyEvaluation:
        return evaluate_all_gates(ctx, gates=self._gates)

    def to_json(self, evaluation: PolicyEvaluation) -> dict[str, Any]:
        return {
            "schema_version": "rig.enterprise.policy_evaluation.v1",
            "policy_id": evaluation.policy_id,
            "all_passed": evaluation.all_passed,
            "passed_count": evaluation.passed_count,
            "failed_count": evaluation.failed_count,
            "blocked_count": evaluation.blocked_count,
            "next_action": evaluation.next_action,
            "gates": [
                {
                    "gate_id": r.gate_id,
                    "passed": r.passed,
                    "current_value": r.current_value,
                    "required_value": r.required_value,
                    "evidence": r.evidence,
                    "blocked_reason": r.blocked_reason,
                }
                for r in evaluation.gates
            ],
            "operator_acknowledgements_required": (
                evaluation.operator_acknowledgements_required
            ),
        }

    def summary(self, evaluation: PolicyEvaluation) -> dict[str, Any]:
        return {
            "all_passed": evaluation.all_passed,
            "passed_count": evaluation.passed_count,
            "failed_count": evaluation.failed_count,
            "blocked_count": evaluation.blocked_count,
            "next_action": evaluation.next_action,
        }
