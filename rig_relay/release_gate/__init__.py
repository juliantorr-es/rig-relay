"""Release Evidence Gate v1 — public API.

Lane A: top-level gate aggregator, runner, receipt, and CLI.
Lane C integration point for Lane A:
    from rig_relay.release_gate import run_all_runtime_checks
    gate_result = run_all_runtime_checks()  # → GateResult (Lane A format)
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from rig_relay.release_gate._checks_registry import build_default_registry
from rig_relay.release_gate._runtime_readiness import (
    check_ci_coverage,
    check_github_app_audit,
    check_trace_contract,
    check_visibility_matrix,
    check_websocket_security,
    load_triage_policy,
)
from rig_relay.release_gate.models import (
    SEVERITY_DESCENDING,
    SEVERITY_RANK,
    CheckContext,
    CheckResult,
    CheckSeverity,
    CheckStatus,
    Finding,
    GatePolicy,
    GatePolicyOverrides,
    GateResult,
    GateSeverity,
    GateStatus,
    GateSummary,
    ReleaseGateCheck,
    TriageEntry,
    TriagePolicy,
)
from rig_relay.release_gate.receipt import serialize_gate_result, write_receipt
from rig_relay.release_gate.runner import GateRunner

__all__ = [
    "SEVERITY_DESCENDING",
    "SEVERITY_RANK",
    "Finding",
    "GatePolicy",
    "GatePolicyOverrides",
    "GateRunner",
    "GateSeverity",
    "ReleaseGateCheck",
    "TriageEntry",
    "build_default_registry",
    "check_ci_coverage",
    "check_github_app_audit",
    "check_trace_contract",
    "check_visibility_matrix",
    "check_websocket_security",
    "load_triage_policy",
    "register_checks",
    "run_all_runtime_checks",
    "run_runtime_check",
    "serialize_gate_result",
    "write_receipt",
]

RUNTIME_CHECKS: dict[str, tuple[str, str]] = {
    "runtime.trace_contract.clean_or_triaged": (
        "Trace contract enforcement — clean or triaged",
        "trace_contract",
    ),
    "runtime.visibility_matrix.release_paths": (
        "Visibility matrix — release-blocking paths verified",
        "visibility_matrix",
    ),
    "runtime.websocket.security_invariants": (
        "WebSocket security invariants verified",
        "websocket_security",
    ),
    "runtime.github_app.audit_readiness": (
        "GitHub App audit-to-implementation readiness",
        "github_app_audit",
    ),
    "runtime.ci.workflow_coverage": (
        "CI workflow coverage for release evidence gate",
        "ci_workflow",
    ),
}


def run_runtime_check(check_id: str, triage: TriagePolicy | None = None) -> CheckResult:
    """Run a single runtime readiness check by its check_id."""
    match check_id:
        case "runtime.trace_contract.clean_or_triaged":
            return check_trace_contract(triage=triage)
        case "runtime.visibility_matrix.release_paths":
            return check_visibility_matrix()
        case "runtime.websocket.security_invariants":
            return check_websocket_security()
        case "runtime.github_app.audit_readiness":
            return check_github_app_audit()
        case "runtime.ci.workflow_coverage":
            return check_ci_coverage()
        case _:
            return CheckResult(
                check_id=check_id,
                title="Unknown check",
                status=CheckStatus.FAIL,
                severity=CheckSeverity.BLOCKER,
                summary=f"No check registered for id: {check_id}",
            )


def _check_result_to_dict(cr: CheckResult) -> dict[str, Any]:
    """Convert a CheckResult to a dict for Lane A's GateResult.checks."""
    return {
        "check_id": cr.check_id,
        "title": cr.title,
        "status": cr.status.value,
        "severity": cr.severity.value,
        "summary": cr.summary,
        "findings": [
            {
                "finding_id": f.finding_id,
                "category": f.category,
                "description": f.description,
                "severity": f.severity.value,
                "source": f.source,
                "recommendation": f.recommendation,
            }
            for f in cr.findings
        ],
        "evidence": {
            k: str(v)
            if not isinstance(v, (str, int, float, bool, list, dict, type(None)))
            else v
            for k, v in cr.evidence.items()
        },
    }


def run_all_runtime_checks(
    triage: TriagePolicy | None = None, *, skip: set[str] | None = None
) -> GateResult:
    """Run all runtime readiness checks and return a GateResult.

    Single integration point for Lane A. Constructs a GateResult in Lane A's
    format (overall_status: GateStatus, checks: list[dict]).
    """
    skip_set = skip or set()
    results: list[CheckResult] = []
    findings_by_severity: dict[str, int] = {}

    checks: list[tuple[str, Any, dict[str, Any]]] = [
        (
            "runtime.trace_contract.clean_or_triaged",
            check_trace_contract,
            {"triage": triage},
        ),
        ("runtime.visibility_matrix.release_paths", check_visibility_matrix, {}),
        ("runtime.websocket.security_invariants", check_websocket_security, {}),
        ("runtime.github_app.audit_readiness", check_github_app_audit, {}),
        ("runtime.ci.workflow_coverage", check_ci_coverage, {}),
    ]

    for check_id, fn, kwargs in checks:
        if check_id in skip_set:
            continue
        try:
            result = fn(**kwargs)
        except Exception as exc:
            result = CheckResult(
                check_id=check_id,
                title=f"Runtime check failed: {check_id}",
                status=CheckStatus.FAIL,
                severity=CheckSeverity.BLOCKER,
                summary=f"Unhandled exception: {exc}",
            )
        results.append(result)
        for f in result.findings:
            sev = f.severity.value
            findings_by_severity[sev] = findings_by_severity.get(sev, 0) + 1

    total_findings = sum(findings_by_severity.values())
    summary = GateSummary(
        total_checks=len(results),
        total_findings=total_findings,
        findings_by_severity=findings_by_severity,
    )
    for r in results:
        match r.status:
            case CheckStatus.PASS:
                summary.passed += 1
            case CheckStatus.FAIL:
                summary.failed += 1
            case CheckStatus.WARN:
                summary.warning += 1
            case CheckStatus.DEFERRED:
                summary.skipped += 1

    has_blockers = any(
        r.severity == CheckSeverity.BLOCKER and r.status == CheckStatus.FAIL
        for r in results
    )
    has_failures = summary.failed > 0
    has_warnings = summary.warning > 0

    if has_blockers:
        overall_status = GateStatus.FAILED
    elif has_failures:
        overall_status = GateStatus.FAILED
    elif has_warnings:
        overall_status = GateStatus.WARNING
    else:
        overall_status = GateStatus.PASSED

    return GateResult(
        gate_id="runtime_readiness",
        overall_status=overall_status,
        summary=summary,
        checks=[_check_result_to_dict(r) for r in results],
    )


def register_checks(registry: dict[str, Any]) -> None:
    """Lane A compatibility: register runtime checks into a gate registry.

    Each registered value is a callable satisfying ReleaseGateCheck protocol:
    it accepts CheckContext and returns CheckResult.

    Call from Lane A gate aggregator:
        from rig_relay.release_gate import register_checks
        registry: dict[str, Callable[[CheckContext], CheckResult]] = {}
        register_checks(registry)
    """
    for check_id, (_title, _category) in RUNTIME_CHECKS.items():

        def _make_runner(cid: str) -> Callable[[CheckContext], CheckResult]:
            def _run(ctx: CheckContext) -> CheckResult:
                return run_runtime_check(cid, triage=ctx.triage)

            return _run

        registry[check_id] = _make_runner(check_id)
