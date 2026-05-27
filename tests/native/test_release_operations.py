"""Tests for release operations service."""

from __future__ import annotations

from pathlib import Path

from rig_relay.native._release_operations import ReleaseOperationsService
from rig_relay.native.models import SigningIdentityStatus


def test_signing_identity_status_returns_evidence() -> None:
    svc = ReleaseOperationsService()
    status = svc.signing_identity_status()
    assert isinstance(status, SigningIdentityStatus)
    assert status.schema_version == "rig.relay.native.signing_status.v1"


def test_signing_identity_status_has_key_fields() -> None:
    svc = ReleaseOperationsService()
    status = svc.signing_identity_status()
    assert hasattr(status, "developer_id_available")
    assert hasattr(status, "developer_id_count")
    assert hasattr(status, "has_notary_profile")
    assert hasattr(status, "warnings")
    assert hasattr(status, "blocking_issues")


def test_sign_bundle_missing_app_reports_failure() -> None:
    svc = ReleaseOperationsService()
    evidence = svc.sign_bundle(
        app_path=Path("/nonexistent.app"), signing_identity="Test Identity"
    )
    assert evidence.status == "failed"
    assert len(evidence.warnings) > 0


def test_notarize_bundle_missing_app_reports_failure() -> None:
    svc = ReleaseOperationsService()
    evidence = svc.notarize_bundle(
        app_path=Path("/nonexistent.app"), signing_identity="Test Identity"
    )
    assert evidence.status.value == "failed"
    assert len(evidence.warnings) > 0


def test_staple_ticket_missing_binary_returns_evidence() -> None:
    svc = ReleaseOperationsService()
    evidence = svc.staple_ticket(app_path=Path("/nonexistent.app"))
    assert evidence.ticket_stapled is False
