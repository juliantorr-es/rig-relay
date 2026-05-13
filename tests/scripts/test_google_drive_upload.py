"""Tests for Google Drive upload client — dry-run and dep isolation."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.rig_relay_upload_google_drive import _upload_dry_run, upload_bundle


def test_google_imports_available():
    """Google Drive deps are core; module loads without ImportError."""
    import google.auth  # noqa: F401
    import google_auth_oauthlib  # noqa: F401
    import googleapiclient  # noqa: F401


def test_dry_run_returns_receipt(tmp_path: Path):
    bundle = tmp_path / "bundle_test.zip"
    bundle.write_bytes(b"test content")
    receipt = _upload_dry_run(
        bundle_path=bundle,
        folder_id="1abc123",
        participant_id="anon_test_001",
        share_level="derived_only",
    )
    assert receipt["status"] == "dry_run"
    assert receipt["schema_version"] == "rig.relay.google_drive_upload_receipt.v1"
    assert receipt["bundle_id"] == "bundle_test"
    assert receipt["participant_id"] == "anon_test_001"
    assert receipt["destination"] == "google_drive"
    assert receipt["drive_file_id"] is None
    assert receipt["drive_folder_id"] == "1abc123"
    assert receipt["bundle_sha256"].startswith("sha256:")
    assert isinstance(receipt["warnings"], list)


def test_dry_run_no_folder_id_warns(tmp_path: Path):
    bundle = tmp_path / "bundle_no_folder.zip"
    bundle.write_bytes(b"data")
    receipt = _upload_dry_run(
        bundle_path=bundle,
        folder_id=None,
        participant_id="anon_test_001",
        share_level="derived_only",
    )
    warnings = receipt["warnings"]
    assert any("No folder ID" in w for w in warnings)


def test_dry_run_via_upload_bundle(tmp_path: Path):
    bundle = tmp_path / "bundle_via_api.zip"
    bundle.write_bytes(b"test data")
    receipt = upload_bundle(
        bundle_path=bundle,
        folder_id="abc123",
        participant_id="anon_test_001",
        share_level="derived_only",
        dry_run=True,
        confirm=False,
    )
    assert receipt["status"] == "dry_run"


def test_dry_run_requires_no_confirm(tmp_path: Path):
    bundle = tmp_path / "bundle_no_confirm.zip"
    bundle.write_bytes(b"data")
    receipt = upload_bundle(bundle_path=bundle, dry_run=True, confirm=False)
    assert receipt["status"] == "dry_run"


def test_dry_run_without_drive_deps_adds_warning(tmp_path: Path):
    bundle = tmp_path / "bundle_no_deps.zip"
    bundle.write_bytes(b"data")
    receipt = _upload_dry_run(
        bundle_path=bundle,
        folder_id=None,
        participant_id="anon_test_001",
        share_level="derived_only",
    )
    warnings = receipt["warnings"]
    drive_warnings = [w for w in warnings if "Google Drive API" in w]
    assert len(drive_warnings) == 0


def test_dry_run_writes_valid_receipt_json(tmp_path: Path):
    bundle = tmp_path / "bundle_valid.zip"
    bundle.write_bytes(b"data")
    receipt = _upload_dry_run(
        bundle_path=bundle,
        folder_id="folder123",
        participant_id="anon_test_001",
        share_level="derived_only",
    )
    json_str = json.dumps(receipt)
    parsed = json.loads(json_str)
    assert parsed["status"] == "dry_run"
    assert parsed["bundle_id"] == "bundle_valid"
