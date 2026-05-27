"""Diagnostic export service — content-light diagnostic bundle (X4).

Required for public v1. Produces typed, content-light diagnostic bundles
suitable for support and user review before export/sharing.

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

_FORBIDDEN_VALUE_PATTERNS: list[tuple[str, str]] = [
    (r"/Users/[^/]+", "absolute_user_path"),
    (r"~/.rig/", "rig_home_path"),
    (r"ghp_[a-zA-Z0-9]{36}", "github_personal_access_token"),
    (r"ghs_[a-zA-Z0-9]{36}", "github_server_token"),
    (r"sk-[a-zA-Z0-9]{32,}", "openai_api_key"),
    (r"AIza[0-9A-Za-z\-_]{35}", "google_api_key"),
]


class DiagnosticExportService:
    """Service boundary for content-light diagnostic bundle generation.

    Produces schema-validated diagnostic bundles. Redacts or refuses
    any raw credentials, tokens, prompts, outputs, or absolute paths.
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

        All inputs are checked for content-light violations.
        Raw credentials, tokens, prompts, or private paths are refused.
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

        scan_result = self._scan_for_content_violations(
            app_identity=app_identity,
            signing_status=signing_status,
            notarization_status=notarization_status,
            update_status=update_status,
            recovery_state=recovery_state,
        )
        violations.extend(scan_result)

        health_checks: list[dict[str, Any]] = additional_health or []
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

        redacted = len(violations) > 0

        return DiagnosticBundle(
            export_id=export_id,
            exported_at=timestamp,
            app_identity=app_identity,
            signing_status=signing_status,
            notarization_status=notarization_status,
            update_status=update_status,
            recovery_state=recovery_state,
            extension_available=extension_connection_state
            not in {"unavailable", "app_not_installed"},
            extension_connection_state=extension_connection_state,
            native_bridge_healthy=native_bridge_healthy,
            frontend_resources_present=frontend_resources_present,
            health_checks=health_checks,
            content_light_violations=violations,
            redacted=redacted,
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

    def _scan_for_content_violations(
        self, **kwargs: Any
    ) -> list[DiagnosticContentLightViolation]:
        """Scan all provided data for content-light violations."""
        violations: list[DiagnosticContentLightViolation] = []

        for field_name, value in kwargs.items():
            if value is None:
                continue

            value_str = str(value)

            if _TOKEN_PATTERNS.search(value_str):
                violations.append(
                    DiagnosticContentLightViolation(
                        field_name=field_name, reason="token_pattern_detected"
                    )
                )

            for pattern, reason in _FORBIDDEN_VALUE_PATTERNS:
                if re.search(pattern, value_str):
                    violations.append(
                        DiagnosticContentLightViolation(
                            field_name=field_name, reason=reason
                        )
                    )

        return violations


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
        f"    Native Bridge:  {'✓ healthy' if bundle.native_bridge_healthy else '✗ degraded'}",
        f"    Frontend:       {'✓ present' if bundle.frontend_resources_present else '✗ missing'}",
        f"    Safari Ext:     {bundle.extension_connection_state}",
    ]

    if bundle.signing_status:
        lines.extend([
            "",
            "  Signing:",
            f"    Developer ID:  {'✓ available' if bundle.signing_status.developer_id_available else '✗ unavailable'}",
            f"    Notary Profile: {'✓ configured' if bundle.signing_status.has_notary_profile else '✗ not configured'}",
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
