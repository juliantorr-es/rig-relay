"""Release Evidence Gate — Lane B placeholder: static docs and security checks.

This module is a placeholder adapter. When Lane B implements their checks,
they replace the placeholder functions with real implementations.

Interface contract:
    Each check function accepts a CheckContext and returns a CheckResult.

Check IDs owned by Lane B:
    - static.docs.json_schema_validation
    - static.docs.static_render_integrity
    - static.security.vulnerability_scan
"""

from __future__ import annotations

from rig_relay.release_gate.models import (
    CheckContext,
    CheckResult,
    CheckSeverity,
    CheckStatus,
    Finding,
)


def check_docs_json_schema(ctx: CheckContext) -> CheckResult:
    return CheckResult(
        check_id="static.docs.json_schema_validation",
        title="Documentation JSON schema validation",
        status=CheckStatus.DEFERRED,
        severity=CheckSeverity.INFO,
        summary="Lane B check not yet implemented. Validates all docs/schemas/*.json against their JSON Schema definitions using scripts/rig_relay_validate_schemas.py.",
        findings=[
            Finding(
                finding_id="static.docs.json_schema.not_implemented",
                category="release_gate",
                description="Check 'static.docs.json_schema_validation' has no implementation yet.",
                severity=CheckSeverity.MEDIUM,
                source="release_gate._static_checks",
                recommendation="Lane B: implement check_docs_json_schema to invoke schema validation.",
            )
        ],
    )


def check_docs_static_render(ctx: CheckContext) -> CheckResult:
    return CheckResult(
        check_id="static.docs.static_render_integrity",
        title="Documentation static site render integrity",
        status=CheckStatus.DEFERRED,
        severity=CheckSeverity.INFO,
        summary="Lane B check not yet implemented. Verifies that the static documentation site renders correctly and matches canonical JSON sources.",
        findings=[
            Finding(
                finding_id="static.docs.static_render.not_implemented",
                category="release_gate",
                description="Check 'static.docs.static_render_integrity' has no implementation yet.",
                severity=CheckSeverity.MEDIUM,
                source="release_gate._static_checks",
                recommendation="Lane B: implement check_docs_static_render to run scripts/render_static_docs.py and verify output integrity.",
            )
        ],
    )


def check_security_vulnerabilities(ctx: CheckContext) -> CheckResult:
    return CheckResult(
        check_id="static.security.vulnerability_scan",
        title="Security vulnerability scan",
        status=CheckStatus.DEFERRED,
        severity=CheckSeverity.INFO,
        summary="Lane B check not yet implemented. Scans for known vulnerabilities in dependencies and code patterns.",
        findings=[
            Finding(
                finding_id="static.security.vulnerability_scan.not_implemented",
                category="release_gate",
                description="Check 'static.security.vulnerability_scan' has no implementation yet.",
                severity=CheckSeverity.MEDIUM,
                source="release_gate._static_checks",
                recommendation="Lane B: implement check_security_vulnerabilities to run vulnerability scanning.",
            )
        ],
    )
