"""Release Evidence Gate — check registry.

Builds the default check registry by importing Lane C (runtime readiness)
and Lane B (static docs/security) checks. All registered functions accept
CheckContext per the GateRunner protocol.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from rig_relay.release_gate.models import (
    CheckContext,
    CheckResult,
    CheckSeverity,
    CheckStatus,
    Finding,
    ReleaseGateCheck,
)


def build_default_registry(
    *, repo_root: Path | None = None, output_dir: Path | None = None
) -> dict[str, ReleaseGateCheck]:
    registry: dict[str, ReleaseGateCheck] = {}

    _register_runtime_checks(registry)
    _register_static_checks(registry)

    return registry


def _register_runtime_checks(registry: dict[str, ReleaseGateCheck]) -> None:
    """Register Lane C runtime readiness checks via context-adapting wrappers.

    GateRunner.run() calls check_fn(ctx). These wrappers accept CheckContext
    and delegate to the standalone check functions in _runtime_readiness.py.
    """
    try:
        from rig_relay.release_gate._runtime_readiness import (
            check_ci_coverage_ctx,
            check_github_app_audit_ctx,
            check_trace_contract_ctx,
            check_visibility_matrix_ctx,
            check_websocket_security_ctx,
        )

        registry["runtime.trace_contract.clean_or_triaged"] = check_trace_contract_ctx
        registry["runtime.visibility_matrix.release_paths"] = (
            check_visibility_matrix_ctx
        )
        registry["runtime.websocket.security_invariants"] = check_websocket_security_ctx
        registry["runtime.github_app.audit_readiness"] = check_github_app_audit_ctx
        registry["runtime.ci.workflow_coverage"] = check_ci_coverage_ctx
    except ImportError:
        for check_id, title in [
            (
                "runtime.trace_contract.clean_or_triaged",
                "Trace contract enforcement — clean or triaged",
            ),
            (
                "runtime.visibility_matrix.release_paths",
                "Visibility matrix — release-blocking paths verified",
            ),
            (
                "runtime.websocket.security_invariants",
                "WebSocket security invariants verified",
            ),
            (
                "runtime.github_app.audit_readiness",
                "GitHub App audit-to-implementation readiness",
            ),
            (
                "runtime.ci.workflow_coverage",
                "CI workflow coverage for release evidence gate",
            ),
        ]:
            registry[check_id] = _skipped_required_check(check_id, title)


def _register_static_checks(registry: dict[str, ReleaseGateCheck]) -> None:
    """Register Lane B static artifact checks via context-adapting wrappers.

    The real Lane B checks live in _static_artifacts.py and are standalone
    functions with no arguments. These wrappers accept CheckContext and
    delegate, matching the GateRunner protocol.
    """
    try:
        from rig_relay.release_gate._static_artifacts import (
            check_cache_policy,
            check_diagram_safety,
            check_generated_site_present,
            check_schema_coverage,
            check_schema_validation,
            check_secret_leakage,
        )

        def _wrap(fn: Any) -> ReleaseGateCheck:
            def _ctx(ctx: CheckContext) -> CheckResult:
                return fn()  # type: ignore[misc]

            return _ctx  # type: ignore[return-value]

        registry["static.schemas.valid_json_documents"] = _wrap(check_schema_validation)
        registry["static.schemas.schema_registry_coverage"] = _wrap(
            check_schema_coverage
        )
        registry["static.renderer.generated_site_present"] = _wrap(
            check_generated_site_present
        )
        registry["static.renderer.no_secret_leakage"] = _wrap(check_secret_leakage)
        registry["static.diagrams.safe_sources"] = _wrap(check_diagram_safety)
        registry["static.generated_artifacts.cache_policy"] = _wrap(check_cache_policy)
    except ImportError:
        for check_id, title in [
            (
                "static.schemas.valid_json_documents",
                "Schema-backed docs JSON documents validated",
            ),
            (
                "static.schemas.schema_registry_coverage",
                "Schema registry coverage for rendered doc types",
            ),
            (
                "static.renderer.generated_site_present",
                "Generated static site artifacts present",
            ),
            (
                "static.renderer.no_secret_leakage",
                "No secret leakage in generated static site",
            ),
            ("static.diagrams.safe_sources", "Diagram source data and content safety"),
            (
                "static.generated_artifacts.cache_policy",
                "Committed cache and generated artifact hygiene",
            ),
        ]:
            registry[check_id] = _skipped_required_check(check_id, title)


def _skipped_required_check(check_id: str, title: str) -> ReleaseGateCheck:
    def _check(ctx: object) -> CheckResult:
        return CheckResult(
            check_id=check_id,
            title=title,
            status=CheckStatus.DEFERRED,
            severity=CheckSeverity.INFO,
            summary=f"Check module not yet implemented. Lane B/C owner: implement {check_id}.",
            findings=[
                Finding(
                    finding_id=f"{check_id}.not_implemented",
                    category="release_gate",
                    description=f"Check '{check_id}' has no registered implementation.",
                    severity=CheckSeverity.MEDIUM,
                    source="release_gate._checks_registry",
                    recommendation=f"Implement the check function for {check_id} in the appropriate lane module.",
                )
            ],
        )

    return _check
