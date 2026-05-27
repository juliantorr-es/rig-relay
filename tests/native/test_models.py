"""Tests for native model-schema compatibility."""

from __future__ import annotations

from rig_relay.native.models import (
    AppPackageEvidence,
    AppPackageIdentity,
    DiagnosticBundle,
    NotarizationEvidence,
    NotarizationStatus,
    RecoveryEvidence,
    RecoveryState,
    SigningEvidence,
    SigningIdentityStatus,
    UpdateEvidenceStatus,
    UpdateStatus,
)


def test_app_package_evidence_schema_version() -> None:
    evidence = AppPackageEvidence(
        identity=AppPackageIdentity(
            bundle_identifier="com.test.app",
            bundle_name="Test",
            short_version="1.0",
            build_version="1",
            minimum_system_version="14.0",
            executable_path="test",
            bundle_path="test",
        ),
        build_config="debug",
        build_sha256="sha256:test",
        timestamp="2026-01-01T00:00:00Z",
    )
    assert evidence.schema_version == "rig.relay.native.package_evidence.v1"


def test_signing_evidence_schema_version() -> None:
    evidence = SigningEvidence(
        identity_used="sha256:test",
        identity_type="Developer ID Application",
        entitlements_sha256="sha256:test",
        bundle_sha256_after="sha256:test",
        signed_at="2026-01-01T00:00:00Z",
        status="signed",
    )
    assert evidence.schema_version == "rig.relay.native.signing_evidence.v1"


def test_notarization_evidence_schema_version() -> None:
    evidence = NotarizationEvidence(bundle_sha256="sha256:test")
    assert evidence.schema_version == "rig.relay.native.notarization_evidence.v1"
    assert evidence.status == NotarizationStatus.NOT_SUBMITTED


def test_update_evidence_schema_version() -> None:
    evidence = UpdateEvidenceStatus(
        current_version="0.1.0", update_available=False, status=UpdateStatus.UP_TO_DATE
    )
    assert evidence.schema_version == "rig.relay.native.update_evidence.v1"


def test_recovery_evidence_schema_version() -> None:
    evidence = RecoveryEvidence(state=RecoveryState.HEALTHY)
    assert evidence.schema_version == "rig.relay.native.recovery_evidence.v1"


def test_diagnostic_export_schema_version() -> None:
    bundle = DiagnosticBundle(
        export_id="diag_test",
        exported_at="2026-01-01T00:00:00Z",
        app_identity=AppPackageIdentity(
            bundle_identifier="com.test.app",
            bundle_name="Test",
            short_version="1.0",
            build_version="1",
            minimum_system_version="14.0",
            executable_path="test",
            bundle_path="test",
        ),
    )
    assert bundle.schema_version == "rig.relay.native.diagnostic_export.v1"
    assert bundle.content_policy == "content_light"


def test_signing_identity_status_defaults() -> None:
    status = SigningIdentityStatus()
    assert status.developer_id_available is False
    assert status.developer_id_count == 0
    assert status.identities == []


def test_notarization_evidence_default_status() -> None:
    evidence = NotarizationEvidence(bundle_sha256="test")
    assert evidence.status == NotarizationStatus.NOT_SUBMITTED
    assert evidence.ticket_stapled is False
