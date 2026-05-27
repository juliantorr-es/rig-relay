"""Tests for update delivery service."""

from __future__ import annotations

from rig_relay.native._update import UpdateDeliveryService
from rig_relay.native.models import UpdateEvidenceStatus, UpdateStatus


def test_update_status_up_to_date_when_no_latest() -> None:
    svc = UpdateDeliveryService()
    status = svc.update_status(current_version="0.1.0")
    assert isinstance(status, UpdateEvidenceStatus)
    assert status.current_version == "0.1.0"
    assert status.update_available is False
    assert status.status == UpdateStatus.UP_TO_DATE


def test_update_status_detects_newer_version() -> None:
    svc = UpdateDeliveryService()
    status = svc.update_status(current_version="0.1.0", latest_version="0.2.0")
    assert status.update_available is True
    assert status.status == UpdateStatus.UPDATE_AVAILABLE


def test_update_status_same_version_no_update() -> None:
    svc = UpdateDeliveryService()
    status = svc.update_status(current_version="0.1.0", latest_version="0.1.0")
    assert status.update_available is False


def test_record_update_event_tracks_state() -> None:
    svc = UpdateDeliveryService()
    evidence = svc.record_update_event(status=UpdateStatus.INSTALLED, version="0.2.0")
    assert evidence.status == UpdateStatus.INSTALLED
    assert evidence.installed_at is not None


def test_record_rollback_event() -> None:
    svc = UpdateDeliveryService()
    evidence = svc.record_update_event(status=UpdateStatus.ROLLED_BACK, version="0.1.0")
    assert evidence.status == UpdateStatus.ROLLED_BACK
    assert evidence.rolled_back_at is not None


def test_sparkle_required_keys_complete() -> None:
    svc = UpdateDeliveryService()
    keys = svc.sparkle_required_keys()
    assert "SUFeedURL" in keys
    assert "SUPublicEDKey" in keys
    assert "CFBundleVersion" in keys
    assert "CFBundleShortVersionString" in keys
    assert "SUEnableInstallerLauncherService" in keys
    assert "SUVerifyUpdateBeforeExtraction" in keys
    assert "SUEnableAutomaticChecks" in keys
