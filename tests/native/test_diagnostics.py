"""Tests for diagnostic export service."""

from __future__ import annotations

from rig_relay.native._diagnostics import DiagnosticExportService, export_text_summary
from rig_relay.native.models import (
    AppPackageIdentity,
    DiagnosticBundle,
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


def test_export_diagnostics_detects_tokens() -> None:
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
    bundle = svc.export_diagnostics(
        app_identity=identity,
        signing_status=SigningIdentityStatus(identities=["ghp_test_token_pattern"]),
    )
    assert bundle.redacted is True
    assert len(bundle.content_light_violations) > 0


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
    bundle = svc.export_diagnostics(
        app_identity=identity,
        signing_status=SigningIdentityStatus(
            identities=["sk-api-key-pattern-detected"] * 5
        ),
    )
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
