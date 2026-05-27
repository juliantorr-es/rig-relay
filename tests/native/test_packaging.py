"""Tests for native packaging service."""

from __future__ import annotations

from pathlib import Path

from rig_relay.native._packaging import PackagingService
from rig_relay.native.models import AppPackageEvidence


def test_packaging_service_creates_identity() -> None:
    svc = PackagingService()
    identity = svc.package_identity()
    assert identity.bundle_identifier == "com.rigrelay.RigRelayShell"
    assert identity.bundle_name == "Rig Relay"
    assert identity.minimum_system_version == "14.0"


def test_packaging_evidence_has_required_fields() -> None:
    svc = PackagingService()
    evidence = svc.build_bundle(config="debug")
    assert isinstance(evidence, AppPackageEvidence)
    assert evidence.build_config == "debug"
    assert evidence.identity.bundle_identifier == "com.rigrelay.RigRelayShell"


def test_packaging_evidence_missing_build_script_reported() -> None:
    svc = PackagingService(project_root=Path("/nonexistent"))
    evidence = svc.build_bundle(config="debug")
    assert len(evidence.blocking_issues) > 0
    assert any("Build script not found" in b for b in evidence.blocking_issues)


def test_validate_bundle_structure_checks_all_paths() -> None:
    svc = PackagingService()
    issues = svc.validate_bundle_structure(Path("/nonexistent.app"))
    assert len(issues) >= 3
    assert any("Info.plist" in i for i in issues)
    assert any("RigRelayShell" in i for i in issues)
    assert any("GridlineFrontend" in i for i in issues)
