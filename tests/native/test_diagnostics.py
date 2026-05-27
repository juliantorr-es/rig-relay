"""Tests for diagnostic export service."""

from __future__ import annotations

import pytest

from rig_relay.native._diagnostics import DiagnosticExportService, export_text_summary
from rig_relay.native.models import (
    AppPackageIdentity,
    DiagnosticBundle,
    DiagnosticContentLightViolation,
    DiagnosticExportBlocked,
    SigningIdentityStatus,
)


def test_export_diagnostics_returns_bundle() -> None:
    svc = DiagnosticExportService()
    identity = AppPackageIdentity(
        bundle_identifier="com.rigrelay.RigRelayShell",
        bundle_name="Rig Relay",
        short_version="0.1.0",
        build_version="1",
        minimum_system_version="14.0",
        executable_path="test",
        bundle_path="test",
    )
    bundle = svc.export_diagnostics(app_identity=identity)
    assert isinstance(bundle, DiagnosticBundle)
    assert bundle.export_id.startswith("diag_")
    assert bundle.content_policy == "content_light"


def test_export_diagnostics_includes_health_checks() -> None:
    svc = DiagnosticExportService()
    identity = AppPackageIdentity(
        bundle_identifier="com.rigrelay.RigRelayShell",
        bundle_name="Rig Relay",
        short_version="0.1.0",
        build_version="1",
        minimum_system_version="14.0",
        executable_path="test",
        bundle_path="test",
    )
    bundle = svc.export_diagnostics(app_identity=identity, native_bridge_healthy=False)
    assert bundle.native_bridge_healthy is False
    assert any("native_bridge" in h["component"] for h in bundle.health_checks)


def test_export_diagnostics_refuses_tokens() -> None:
    """X4.4: Fail-closed — token detection raises DiagnosticExportBlocked."""
    svc = DiagnosticExportService()
    identity = AppPackageIdentity(
        bundle_identifier="com.rigrelay.RigRelayShell",
        bundle_name="Rig Relay",
        short_version="0.1.0",
        build_version="1",
        minimum_system_version="14.0",
        executable_path="test",
        bundle_path="test",
    )
    with pytest.raises(DiagnosticExportBlocked) as exc_info:
        svc.export_diagnostics(
            app_identity=identity,
            signing_status=SigningIdentityStatus(identities=["ghp_test_token_pattern"]),
        )
    assert exc_info.value.violation_count > 0
    assert any("blocked_export" in r for r in exc_info.value.blocking_reasons)


def test_export_diagnostics_blocks_unsafe_status() -> None:
    """X4.4: Fail-closed — token in signing status raises DiagnosticExportBlocked."""
    svc = DiagnosticExportService()
    identity = AppPackageIdentity(
        bundle_identifier="com.rigrelay.RigRelayShell",
        bundle_name="Rig Relay",
        short_version="0.1.0",
        build_version="1",
        minimum_system_version="14.0",
        executable_path="test",
        bundle_path="test",
    )
    with pytest.raises(DiagnosticExportBlocked) as exc_info:
        svc.export_diagnostics(
            app_identity=identity,
            signing_status=SigningIdentityStatus(identities=["ghp_token_1234"]),
        )
    assert exc_info.value.violation_count > 0
    assert any("blocked_export" in r for r in exc_info.value.blocking_reasons)


def test_export_diagnostics_scans_additional_health() -> None:
    """X4.4: Fail-closed — tokens in additional_health raise DiagnosticExportBlocked."""
    svc = DiagnosticExportService()
    identity = AppPackageIdentity(
        bundle_identifier="com.rigrelay.RigRelayShell",
        bundle_name="Rig Relay",
        short_version="0.1.0",
        build_version="1",
        minimum_system_version="14.0",
        executable_path="test",
        bundle_path="test",
    )
    with pytest.raises(DiagnosticExportBlocked) as exc_info:
        svc.export_diagnostics(
            app_identity=identity,
            additional_health=[{"detail": "ghp_test_token_as_health"}],
        )
    assert exc_info.value.violation_count > 0


def test_validate_export_no_violations() -> None:
    svc = DiagnosticExportService()
    identity = AppPackageIdentity(
        bundle_identifier="com.rigrelay.RigRelayShell",
        bundle_name="Rig Relay",
        short_version="0.1.0",
        build_version="1",
        minimum_system_version="14.0",
        executable_path="test",
        bundle_path="test",
    )
    bundle = svc.export_diagnostics(app_identity=identity)
    issues = svc.validate_export(bundle)
    assert len(issues) == 0


def test_validate_export_reports_violations() -> None:
    """X4.4: When violations exist, export is blocked — validate_export
    can still be tested by constructing a DiagnosticBundle directly.
    """
    identity = AppPackageIdentity(
        bundle_identifier="com.rigrelay.RigRelayShell",
        bundle_name="Rig Relay",
        short_version="0.1.0",
        build_version="1",
        minimum_system_version="14.0",
        executable_path="test",
        bundle_path="test",
    )
    bundle = DiagnosticBundle(
        export_id="diag_test",
        exported_at="2026-01-01T00:00:00Z",
        app_identity=identity,
        content_light_violations=[
            DiagnosticContentLightViolation(field_name="test", reason="test")
        ],
        redacted=True,
        blocking=["blocked_reason"],
    )
    svc = DiagnosticExportService()
    issues = svc.validate_export(bundle)
    assert len(issues) > 0


def test_export_text_summary_produces_output() -> None:
    identity = AppPackageIdentity(
        bundle_identifier="com.rigrelay.RigRelayShell",
        bundle_name="Rig Relay",
        short_version="0.1.0",
        build_version="1",
        minimum_system_version="14.0",
        executable_path="test",
        bundle_path="test",
    )
    bundle = DiagnosticBundle(
        export_id="diag_test", exported_at="2026-01-01T00:00:00Z", app_identity=identity
    )
    summary = export_text_summary(bundle)
    assert "Rig Relay" in summary
    assert "diag_test" in summary
    assert "content_light" in summary
