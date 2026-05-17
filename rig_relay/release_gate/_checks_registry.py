"""Release Evidence Gate — check registry.

Builds the default check registry by importing Lane C (runtime readiness)
and Lane B (static docs/security) checks. Placeholder adapters are
provided for Lane B until those modules exist.

Prefer explicit imports over magic discovery.
"""

from __future__ import annotations

from pathlib import Path

from rig_relay.release_gate.models import (
    CheckResult,
    CheckSeverity,
    CheckStatus,
    Finding,
)


def build_default_registry(
    *, repo_root: Path | None = None, output_dir: Path | None = None
) -> dict[str, object]:
    registry: dict[str, object] = {}

    _register_runtime_checks(registry, repo_root=repo_root, output_dir=output_dir)
    _register_static_checks(registry, repo_root=repo_root, output_dir=output_dir)

    return registry


def _register_runtime_checks(
    registry: dict[str, object],
    *,
    repo_root: Path | None = None,
    output_dir: Path | None = None,
) -> None:
    try:
        from rig_relay.release_gate._runtime_readiness import (
            check_ci_coverage,
            check_github_app_audit,
            check_trace_contract,
            check_visibility_matrix,
            check_websocket_security,
        )

        registry["runtime.trace_contract.clean_or_triaged"] = check_trace_contract
        registry["runtime.visibility_matrix.release_paths"] = check_visibility_matrix
        registry["runtime.websocket.security_invariants"] = check_websocket_security
        registry["runtime.github_app.audit_readiness"] = check_github_app_audit
        registry["runtime.ci.workflow_coverage"] = check_ci_coverage
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


def _register_static_checks(
    registry: dict[str, object],
    *,
    repo_root: Path | None = None,
    output_dir: Path | None = None,
) -> None:
    try:
        from rig_relay.release_gate._static_checks import (
            check_docs_json_schema,
            check_docs_static_render,
            check_security_vulnerabilities,
        )

        registry["static.docs.json_schema_validation"] = check_docs_json_schema
        registry["static.docs.static_render_integrity"] = check_docs_static_render
        registry["static.security.vulnerability_scan"] = check_security_vulnerabilities
    except ImportError:
        for check_id, title in [
            (
                "static.docs.json_schema_validation",
                "Documentation JSON schema validation",
            ),
            (
                "static.docs.static_render_integrity",
                "Documentation static site render integrity",
            ),
            ("static.security.vulnerability_scan", "Security vulnerability scan"),
        ]:
            registry[check_id] = _skipped_required_check(check_id, title)


def _skipped_required_check(check_id: str, title: str) -> object:
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
