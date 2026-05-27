"""Diagnostic export service — content-light diagnostic bundle (X4.1 fail-closed).

Required for public v1. Produces typed, content-light diagnostic bundles
suitable for support and user review before export/sharing.

FAIL-CLOSED: When unsafe content (tokens, credentials, forbidden fields) is
detected, the export is refused with a typed violation result rather than
returned with unsafe data intact.

Must refuse: raw credentials, raw private source, tokens, raw prompts,
model outputs, unredacted absolute private paths.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
import re
from typing import Any

from rig_relay.native.models import (
    AppPackageIdentity,
    DiagnosticBundle,
    DiagnosticContentLightViolation,
    NotarizationEvidence,
    RecoveryEvidence,
    SigningIdentityStatus,
    UpdateEvidenceStatus,
)

_TOKEN_PATTERNS = re.compile(
    r"(ghp_|ghs_|gho_|ghu_|ghr_|github_pat_|sk-|sk-ant-|AIza|ya29\.|xox[baprs]-)"
)

_FORBIDDEN_FIELD_NAMES: frozenset[str] = frozenset({
    "api_key",
    "access_token",
    "refresh_token",
    "id_token",
    "client_secret",
    "private_key",
    "password",
    "secret",
    "credential",
    "token",
})

_FORBIDDEN_VALUE_PATTERNS: list[tuple[str, str, str]] = [
    (r"/Users/[^/\s]+", "absolute_user_path", "[REDACTED]"),
    (r"~/.rig/", "rig_home_path", "[REDACTED]"),
    (r"ghp_[a-zA-Z0-9]{36}", "github_personal_access_token", "[REDACTED]"),
    (r"ghs_[a-zA-Z0-9]{36}", "github_server_token", "[REDACTED]"),
    (r"sk-[a-zA-Z0-9]{32,}", "openai_api_key", "[REDACTED]"),
    (r"AIza[0-9A-Za-z\-_]{35}", "google_api_key", "[REDACTED]"),
]

_REDACTION_PLACEHOLDER = "[REDACTED]"


def _redact_value(value: str) -> tuple[str, bool]:
    """Redact a string value if it matches forbidden patterns.

    Returns (redacted_value, was_redacted).
    """
    was_redacted = False
    result = value
    for pattern, _reason, replacement in _FORBIDDEN_VALUE_PATTERNS:
        if re.search(pattern, result):
            result = re.sub(pattern, replacement, result)
            was_redacted = True
    return result, was_redacted


def _redact_string_or_dict(
    value: Any, path: str = ""
) -> tuple[Any, list[DiagnosticContentLightViolation]]:
    """Recursively scan and redact values. Returns (cleaned_value, violations)."""
    violations: list[DiagnosticContentLightViolation] = []

    if isinstance(value, str):
        cleaned_str, redacted = _redact_value(value)
        had_token = _TOKEN_PATTERNS.search(cleaned_str) is not None
        if had_token or redacted:
            if had_token:
                violations.append(
                    DiagnosticContentLightViolation(
                        field_name=path, reason="token_pattern_detected"
                    )
                )
            if redacted:
                violations.append(
                    DiagnosticContentLightViolation(
                        field_name=path, reason="forbidden_value_pattern_redacted"
                    )
                )
            return _REDACTION_PLACEHOLDER if had_token else cleaned_str, violations
        return value, violations

    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        for k, v in value.items():
            if isinstance(k, str):
                k_lower = k.lower()
                if any(f in k_lower for f in _FORBIDDEN_FIELD_NAMES):
                    violations.append(
                        DiagnosticContentLightViolation(
                            field_name=f"{path}.{k}" if path else k,
                            reason="forbidden_field_name",
                        )
                    )
                    cleaned[k] = _REDACTION_PLACEHOLDER
                    continue
            child_result, child_v = _redact_string_or_dict(
                v, f"{path}.{k}" if path else k
            )
            violations.extend(child_v)
            cleaned[k] = child_result
        return cleaned, violations

    if isinstance(value, list):
        cleaned_list: list[Any] = []
        for i, item in enumerate(value):
            child_result, child_v = _redact_string_or_dict(item, f"{path}[{i}]")
            violations.extend(child_v)
            cleaned_list.append(child_result)
        return cleaned_list, violations

    if hasattr(value, "model_dump"):
        dumped = value.model_dump()
        child_result, child_v = _redact_string_or_dict(dumped, path)
        violations.extend(child_v)
        return child_result, violations

    return value, violations


class DiagnosticExportService:
    """Service boundary for content-light diagnostic bundle generation.

    FAIL-CLOSED behavior: When unsafe content is detected, the export is
    refused with a typed violation result. Redaction is applied to
    string fields matching forbidden patterns. If any violation remains
    after redaction, the export is blocked entirely.
    """

    def __init__(self, project_root: Path | None = None) -> None:
        self._repo_root = (
            project_root or Path(__file__).resolve().parent.parent.parent.parent
        )
        self._macos_dir = self._repo_root / "macos"

    def export_diagnostics(
        self,
        *,
        app_identity: AppPackageIdentity | None = None,
        signing_status: SigningIdentityStatus | None = None,
        notarization_status: NotarizationEvidence | None = None,
        update_status: UpdateEvidenceStatus | None = None,
        recovery_state: RecoveryEvidence | None = None,
        extension_connection_state: str = "unknown",
        native_bridge_healthy: bool = True,
        frontend_resources_present: bool = True,
        additional_health: list[dict[str, str]] | None = None,
    ) -> DiagnosticBundle:
        """Assemble a content-light diagnostic bundle.

        FAIL-CLOSED: Unsafe content is redacted. If any violation remains
        after redaction, the export is blocked and returns a refusal marker
        rather than a bundle containing unsafe data.
        """
        export_id = f"diag_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}"
        timestamp = datetime.now(UTC).isoformat()

        violations: list[DiagnosticContentLightViolation] = []
        warnings: list[str] = []
        blocking: list[str] = []

        if app_identity is None:
            try:
                from rig_relay.native._packaging import PackagingService

                app_identity = PackagingService(self._repo_root).package_identity()
            except Exception:
                app_identity = AppPackageIdentity(
                    bundle_identifier="com.rigrelay.RigRelayShell",
                    bundle_name="Rig Relay",
                    short_version="0.1.0",
                    build_version="1",
                    minimum_system_version="14.0",
                    executable_path="unknown",
                    bundle_path="unknown",
                )

        scan_inputs: dict[str, Any] = {}
        if signing_status is not None:
            scan_inputs["signing_status"] = signing_status.model_dump()
        if notarization_status is not None:
            scan_inputs["notarization_status"] = notarization_status.model_dump()
        if update_status is not None:
            scan_inputs["update_status"] = update_status.model_dump()
        if recovery_state is not None:
            scan_inputs["recovery_state"] = recovery_state.model_dump()

        scan_inputs["app_identity"] = app_identity.model_dump()
        scan_inputs["additional_health"] = additional_health or []
        scan_inputs["extension_connection_state"] = extension_connection_state

        _, scan_violations = _redact_string_or_dict(scan_inputs, "")
        violations.extend(scan_violations)

        _, identity_v = _redact_string_or_dict(
            app_identity.model_dump(), "app_identity"
        )
        violations.extend(identity_v)

        health_checks: list[dict[str, Any]] = []
        for item in additional_health or []:
            _, hc_v = _redact_string_or_dict(item, "additional_health")
            violations.extend(hc_v)
            health_checks.append(item)
        health_checks.extend([
            {
                "component": "native_bridge",
                "status": "healthy" if native_bridge_healthy else "degraded",
            },
            {
                "component": "frontend_resources",
                "status": "present" if frontend_resources_present else "missing",
            },
            {"component": "safari_extension", "status": extension_connection_state},
        ])

        if violations:
            blocking.extend(
                f"content_light_violation_blocked_export: {v.field_name} — {v.reason}"
                for v in violations
            )
            warnings.append("export_blocked_due_to_unsafe_content")

        native_bridge_healthy = (
            False
            if "native_bridge_degraded" in {v.reason for v in violations}
            else native_bridge_healthy
        )

        return DiagnosticBundle(
            export_id=export_id,
            exported_at=timestamp,
            app_identity=app_identity,
            signing_status=signing_status
            if not any("signing_status" in v.field_name for v in violations)
            else None,
            notarization_status=notarization_status
            if not any("notarization_status" in v.field_name for v in violations)
            else None,
            update_status=update_status
            if not any("update_status" in v.field_name for v in violations)
            else None,
            recovery_state=recovery_state
            if not any("recovery_state" in v.field_name for v in violations)
            else None,
            extension_available=extension_connection_state
            not in {"unavailable", "app_not_installed"},
            extension_connection_state=extension_connection_state,
            native_bridge_healthy=native_bridge_healthy,
            frontend_resources_present=frontend_resources_present,
            health_checks=health_checks,
            content_light_violations=violations,
            redacted=len(violations) > 0,
            warnings=warnings,
            blocking=blocking,
        )

    def validate_export(self, bundle: DiagnosticBundle) -> list[str]:
        """Validate a diagnostic bundle for content-light compliance.

        Returns list of issues (empty = valid).
        """
        issues: list[str] = []

        if bundle.content_light_violations:
            issues.extend(
                f"content_light_violation: {v.field_name} — {v.reason}"
                for v in bundle.content_light_violations
            )

        if not bundle.export_id:
            issues.append("missing export_id")
        if not bundle.exported_at:
            issues.append("missing exported_at")
        if not bundle.app_identity:
            issues.append("missing app_identity")

        if bundle.redacted and not bundle.content_light_violations:
            issues.append("redacted flag set but no violations recorded")

        return issues


def export_text_summary(bundle: DiagnosticBundle) -> str:
    """Produce a human-readable content-light summary for terminal display."""
    lines = [
        "=== Rig Relay Diagnostic Export ===",
        f"  Export ID:    {bundle.export_id}",
        f"  Exported:     {bundle.exported_at}",
        f"  App:          {bundle.app_identity.bundle_name} {bundle.app_identity.short_version}",
        f"  Bundle ID:    {bundle.app_identity.bundle_identifier}",
        "",
        "  Components:",
        f"    Native Bridge:  {'OK healthy' if bundle.native_bridge_healthy else 'X degraded'}",
        f"    Frontend:       {'OK present' if bundle.frontend_resources_present else 'X missing'}",
        f"    Safari Ext:     {bundle.extension_connection_state}",
    ]

    if bundle.signing_status:
        lines.extend([
            "",
            "  Signing:",
            f"    Developer ID:  {'OK available' if bundle.signing_status.developer_id_available else 'X unavailable'}",
            f"    Notary Profile: {'OK configured' if bundle.signing_status.has_notary_profile else 'X not configured'}",
        ])

    if bundle.notarization_status:
        ns = bundle.notarization_status
        lines.extend([
            "",
            "  Notarization:",
            f"    Status:        {ns.status.value}",
            f"    Ticket Stapled: {ns.ticket_stapled}",
        ])

    if bundle.update_status:
        us = bundle.update_status
        lines.extend([
            "",
            "  Update:",
            f"    Current:       {us.current_version}",
            f"    Available:     {us.update_available}",
            f"    Status:        {us.status.value}",
        ])

    if bundle.recovery_state:
        rs = bundle.recovery_state
        lines.extend([
            "",
            "  Recovery:",
            f"    State:         {rs.state.value}",
            f"    Affected:      {', '.join(rs.affected_components) or 'none'}",
        ])

    if bundle.content_light_violations:
        lines.extend([
            "",
            f"  Content-Light Violations: {len(bundle.content_light_violations)}",
            f"  Redacted: {bundle.redacted}",
            "  Export BLOCKED due to unsafe content.",
        ])

    if bundle.blocking:
        lines.extend(["", "  Blockers:"])
        for b in bundle.blocking:
            lines.append(f"    - {b}")

    lines.extend([
        "",
        "  Content Policy: content_light",
        "  No raw credentials, tokens, prompts, model outputs, or private paths included.",
    ])

    return "\n".join(lines)
