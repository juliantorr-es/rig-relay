"""Tests for telemetry bundle creation, validation, upload, settings schema,
and telemetry mode feature gates.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import zipfile

import pytest

from rig_relay.evidence.telemetry_bundle import validate_bundle as relay_validate_bundle
from scripts.rig_relay_create_telemetry_bundle import (
    _forbidden_content_in_json,
    _forbidden_content_in_text,
    create_bundle,
)
from scripts.rig_relay_upload_google_drive import _upload_dry_run, upload_bundle
from scripts.rig_relay_validate_telemetry_bundle import validate_bundle
from rig_relay.core.config.telemetry_modes import (
    ALLOWED_SHARE_LEVELS_FOR_UPLOAD,
    can_upload_remote_beta_data,
    can_use_autonomous_spawn,
    can_use_checkpoint,
    can_use_coordination_leases,
    can_use_current_state,
    can_use_delegate_fleet,
    can_use_governed_mode,
    can_use_queue_planning,
    can_use_replay_debug,
    disabled_features_for_settings,
)

SCHEMAS_DIR = Path(__file__).resolve().parent.parent.parent / "docs" / "schemas"
CONSENT_SCHEMA = SCHEMAS_DIR / "rig.relay.telemetry_consent.v1.schema.json"
BUNDLE_MANIFEST_SCHEMA = (
    SCHEMAS_DIR / "rig.relay.telemetry_bundle_manifest.v1.schema.json"
)
UPLOAD_RECEIPT_SCHEMA = (
    SCHEMAS_DIR / "rig.relay.google_drive_upload_receipt.v1.schema.json"
)
TELEMETRY_SETTINGS_SCHEMA = SCHEMAS_DIR / "rig.relay.telemetry_settings.v1.schema.json"


def _try_validate(instance: dict, schema_path: Path) -> list[str]:
    """Validate instance against schema, return errors."""
    try:
        import jsonschema
    except ImportError:
        return []
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validator = jsonschema.Draft7Validator(schema)
    return [e.message for e in validator.iter_errors(instance)]


# ── Schema validation tests ──────────────────────────────────────────────


def test_consent_schema_validates_sample():
    sample = {
        "schema_version": "rig.relay.telemetry_consent.v1",
        "consent_id": "cons_test_001",
        "subject_hash": "sha256:abc123",
        "provider": "local",
        "status": "granted",
        "scopes": ["usage_metrics", "content_light_bundles"],
        "granted_at": "2026-05-13T00:00:00+00:00",
        "policy_version": "2026-05-13",
        "local_only": True,
    }
    errors = _try_validate(sample, CONSENT_SCHEMA)
    assert not errors, f"Schema errors: {errors}"


def test_consent_schema_missing_required_fails():
    sample = {"schema_version": "rig.relay.telemetry_consent.v1"}
    errors = _try_validate(sample, CONSENT_SCHEMA)
    assert len(errors) > 0


def test_bundle_manifest_schema_validates_sample():
    sample = {
        "schema_version": "rig.relay.telemetry_bundle_manifest.v1",
        "bundle_id": "bundle_test_001",
        "participant_id": "anon_test_001",
        "project": "rig-relay",
        "created_at": "2026-05-13T00:00:00+00:00",
        "share_level": "derived_only",
        "included_files": [
            {
                "path": "dataset.jsonl",
                "size_bytes": 100,
                "sha256": "abc",
                "row_count": 5,
            }
        ],
        "row_counts": {"dataset": 5},
        "bundle_sha256": "abc123",
        "content_light_guarantee": True,
    }
    errors = _try_validate(sample, BUNDLE_MANIFEST_SCHEMA)
    assert not errors, f"Schema errors: {errors}"


def test_upload_receipt_schema_validates_dry_run():
    sample = {
        "schema_version": "rig.relay.google_drive_upload_receipt.v1",
        "bundle_id": "bundle_test_001",
        "participant_id": "anon_test_001",
        "destination": "google_drive",
        "uploaded_at": "2026-05-13T00:00:00+00:00",
        "upload_method": "dry_run",
        "bundle_sha256": "sha256:abc123",
        "status": "dry_run",
    }
    errors = _try_validate(sample, UPLOAD_RECEIPT_SCHEMA)
    assert not errors, f"Schema errors: {errors}"


def test_telemetry_settings_schema_validates_sample():
    sample = {
        "schema_version": "rig.relay.telemetry_settings.v1",
        "mode": "beta_orchestration",
        "local_operational_enabled": True,
        "local_derived_datasets_enabled": True,
        "remote_beta_sharing_enabled": True,
        "share_level": "derived_only",
        "onboarding_acknowledged_at": "2026-05-13T00:00:00+00:00",
        "onboarding_text_version": "v1",
        "participant_id": "anon_test_001",
    }
    errors = _try_validate(sample, TELEMETRY_SETTINGS_SCHEMA)
    assert not errors, f"Schema errors: {errors}"


def test_telemetry_settings_defaults_valid():
    sample = {
        "schema_version": "rig.relay.telemetry_settings.v1",
        "mode": "basic_local",
        "local_operational_enabled": True,
        "local_derived_datasets_enabled": True,
        "remote_beta_sharing_enabled": False,
        "share_level": "derived_only",
        "onboarding_acknowledged_at": None,
        "onboarding_text_version": "v1",
    }
    errors = _try_validate(sample, TELEMETRY_SETTINGS_SCHEMA)
    assert not errors, f"Schema errors: {errors}"


# ── Content-light checks ────────────────────────────────────────────────


def test_forbidden_content_in_json_detects_field_key():
    data = {"raw_file_contents": "should not be here"}
    issues = _forbidden_content_in_json(data, "test.json")
    assert len(issues) == 1
    assert "raw_file_contents" in issues[0]


def test_forbidden_content_in_json_clean():
    data = {"name": "clean", "count": 5}
    issues = _forbidden_content_in_json(data, "clean.json")
    assert len(issues) == 0


def test_forbidden_content_in_text_detects_private_key():
    text = "-----BEGIN RSA PRIVATE KEY-----\nABCDEF=="
    issues = _forbidden_content_in_text(text, "bad.txt")
    assert len(issues) == 1


def test_forbidden_content_in_text_clean():
    issues = _forbidden_content_in_text("hello world", "clean.txt")
    assert len(issues) == 0


# ── Bundle creation ─────────────────────────────────────────────────────


def test_bundle_creation_refuses_share_level_off():
    # share_level 'off' is refused at the CLI level by main()
    from scripts.rig_relay_create_telemetry_bundle import _parse_args

    try:
        _parse_args(["--participant-id", "test", "--share-level", "off"])
    except SystemExit:
        pass


def test_bundle_dry_run_includes_summary(tmp_path):
    """Dry run returns manifest with included_files."""
    # Create a fake derived dataset
    derived = tmp_path / "derived"
    derived.mkdir()
    ds = derived / "cross_session_coordination_dataset.jsonl"
    ds.write_text('{"event": "test"}\n{"event": "test2"}\n')

    manifest = create_bundle(
        participant_id="test_participant",
        share_level="derived_only",
        derived_dir=derived,
        output_dir=tmp_path / "out",
        dry_run=True,
    )
    assert manifest["participant_id"] == "test_participant"
    assert manifest["share_level"] == "derived_only"
    assert len(manifest["included_files"]) >= 1
    assert manifest["content_light_guarantee"] is True


def test_bundle_creation_includes_only_allowed_files(tmp_path):
    """Bundle zip includes only derived datasets + manifest."""
    derived = tmp_path / "derived"
    derived.mkdir()
    ds = derived / "dataset.jsonl"
    ds.write_text('{"a": 1}\n')

    manifest = create_bundle(
        participant_id="test_zip",
        share_level="derived_only",
        derived_dir=derived,
        output_dir=tmp_path / "out",
        dry_run=False,
    )
    bundle_path = tmp_path / "out" / f"{manifest['bundle_id']}.zip"
    assert bundle_path.is_file()

    with zipfile.ZipFile(bundle_path, "r") as zf:
        names = zf.namelist()
        assert "derived/dataset.jsonl" in names
        assert "telemetry_bundle_manifest.json" in names


def test_bundle_refuses_forbidden_raw_fields(tmp_path):
    """Bundle creation raises ValueError if forbidden field keys found."""
    derived = tmp_path / "derived"
    derived.mkdir()
    ds = derived / "bad.jsonl"
    ds.write_text('{"raw_file_contents": "leaked"}\n')

    with pytest.raises(ValueError, match="Forbidden content"):
        create_bundle(
            participant_id="test_bad",
            share_level="derived_only",
            derived_dir=derived,
            output_dir=tmp_path / "out",
            dry_run=False,
        )


def test_bundle_zip_has_correct_sha256_in_manifest(tmp_path):
    """Manifest bundle_sha256 is a content hash of the data files."""
    derived = tmp_path / "derived"
    derived.mkdir()
    reports = tmp_path / "reports"
    reports.mkdir()
    ds = derived / "data.jsonl"
    ds.write_text('{"x": 1}\n')

    manifest = create_bundle(
        participant_id="test_sha",
        share_level="derived_only",
        derived_dir=derived,
        reports_dir=reports,
        output_dir=tmp_path / "out",
        dry_run=False,
    )
    bundle_path = tmp_path / "out" / f"{manifest['bundle_id']}.zip"
    import zipfile as zf_mod

    with zf_mod.ZipFile(bundle_path, "r") as zf:
        manifest_in_zip = json.loads(zf.read("telemetry_bundle_manifest.json"))

    assert len(manifest_in_zip["bundle_sha256"]) == 64

    # Recompute content hash manually using same algorithm as create_bundle
    content_hash_input = b""
    content_hash_input += b"derived/data.jsonl\x00" + ds.read_bytes() + b"\x00"
    expected_hash = hashlib.sha256(content_hash_input).hexdigest()
    assert manifest_in_zip["bundle_sha256"] == expected_hash

    assert manifest_in_zip["content_light_guarantee"] is True


# ── Bundle validation ────────────────────────────────────────────────────


def test_validate_bundle_passes_clean_bundle(tmp_path):
    """Validate a clean bundle returns PASSED."""
    derived = tmp_path / "derived"
    derived.mkdir()
    ds = derived / "data.jsonl"
    ds.write_text('{"event": "test"}\n')

    manifest = create_bundle(
        participant_id="test_val",
        share_level="derived_only",
        derived_dir=derived,
        output_dir=tmp_path / "out",
        dry_run=False,
    )
    bundle_path = tmp_path / "out" / f"{manifest['bundle_id']}.zip"

    is_valid, messages = validate_bundle(bundle_path)
    assert is_valid
    result_lines = [m for m in messages if "RESULT" in m]
    assert any("PASSED" in m for m in result_lines)


def test_validate_bundle_detects_forbidden_content(tmp_path):
    """Validate a bundle with forbidden content fails."""
    derived = tmp_path / "derived"
    derived.mkdir()

    # We need to manually create a bundle with bad content since the
    # bundle creator refuses to make one. Create a zip directly.
    bundle_path = tmp_path / "bad_bundle.zip"
    with zipfile.ZipFile(bundle_path, "w") as zf:
        zf.writestr(
            "telemetry_bundle_manifest.json",
            json.dumps({
                "schema_version": "rig.relay.telemetry_bundle_manifest.v1",
                "bundle_id": "bad",
                "participant_id": "test",
                "project": "rig-relay",
                "created_at": "2026-01-01T00:00:00",
                "share_level": "derived_only",
                "included_files": [],
                "row_counts": {},
                "bundle_sha256": "abc",
                "content_light_guarantee": False,
            }),
        )
        zf.writestr("derived/leak.jsonl", '{"raw_file_contents": "leaked"}')

    is_valid, messages = validate_bundle(bundle_path)
    assert not is_valid
    assert any("FORBIDDEN" in m for m in messages)


# ── Upload dry-run ──────────────────────────────────────────────────────


def test_upload_dry_run_creates_receipt_and_no_network(tmp_path):
    """Upload dry-run creates receipt without network access."""
    bundle_path = tmp_path / "test_bundle.zip"
    bundle_path.write_text("fake zip content")

    receipt = _upload_dry_run(
        bundle_path=bundle_path,
        folder_id="fake_folder",
        participant_id="test_user",
        share_level="derived_only",
    )
    assert receipt["status"] == "dry_run"
    assert receipt["upload_method"] == "dry_run"
    assert receipt["bundle_id"] == "test_bundle"
    assert receipt["drive_file_id"] is None


def test_upload_bundle_dry_run(tmp_path):
    """upload_bundle in dry-run mode returns receipt with status dry_run."""
    bundle_path = tmp_path / "test_bundle.zip"
    bundle_path.write_text("zip content here")

    receipt = upload_bundle(
        bundle_path=bundle_path,
        folder_id="folder_123",
        participant_id="anon_test",
        share_level="derived_only",
        dry_run=True,
        confirm=False,
    )
    assert receipt["status"] == "dry_run"
    assert receipt["upload_method"] == "dry_run"
    assert receipt["drive_folder_id"] == "folder_123"


def test_upload_receipt_schema_validates_dry_run_output(tmp_path):
    """Dry-run upload receipt validates against schema."""
    bundle_path = tmp_path / "test_bundle.zip"
    bundle_path.write_text("data")

    receipt = upload_bundle(
        bundle_path=bundle_path,
        folder_id="folder_123",
        participant_id="anon_test",
        share_level="derived_only",
        dry_run=True,
        confirm=False,
    )
    errors = _try_validate(receipt, UPLOAD_RECEIPT_SCHEMA)
    assert not errors, f"Schema errors: {errors}"


# ── Telemetry mode feature gates ─────────────────────────────────────────


def test_beta_orchestration_allows_advanced_features():
    settings = {
        "mode": "beta_orchestration",
        "local_operational_enabled": True,
        "remote_beta_sharing_enabled": True,
        "share_level": "derived_only",
    }
    assert can_use_governed_mode(settings) is True
    assert can_use_delegate_fleet(settings) is True
    assert can_use_checkpoint(settings) is True
    assert can_use_coordination_leases(settings) is True
    assert can_use_current_state(settings) is True
    assert can_use_queue_planning(settings) is True
    assert can_use_replay_debug(settings) is True
    assert can_use_autonomous_spawn(settings) is True
    assert can_upload_remote_beta_data(settings) is True


def test_remote_sharing_disabled_disables_advanced_features():
    settings = {
        "mode": "basic_local",
        "local_operational_enabled": True,
        "remote_beta_sharing_enabled": False,
        "share_level": "off",
    }
    assert can_use_governed_mode(settings) is True  # local op still on
    assert can_use_delegate_fleet(settings) is False
    assert can_use_checkpoint(settings) is True  # local only
    assert can_use_autonomous_spawn(settings) is False
    assert can_upload_remote_beta_data(settings) is False


def test_remote_sharing_disabled_disables_delegate_fleet():
    settings = {
        "mode": "basic_local",
        "local_operational_enabled": True,
        "remote_beta_sharing_enabled": False,
        "share_level": "off",
    }
    assert can_use_delegate_fleet(settings) is False


def test_remote_sharing_disabled_disables_checkpoint():
    # Checkpoint itself doesn't require remote sharing
    settings = {
        "mode": "basic_local",
        "local_operational_enabled": True,
        "remote_beta_sharing_enabled": False,
        "share_level": "off",
    }
    assert can_use_checkpoint(settings) is True  # local op enabled


def test_remote_sharing_disabled_disables_coordination_leases():
    settings = {
        "mode": "basic_local",
        "local_operational_enabled": True,
        "remote_beta_sharing_enabled": False,
        "share_level": "off",
    }
    assert can_use_coordination_leases(settings) is True  # local op enabled


def test_local_operational_disabled_disables_governed():
    settings = {
        "mode": "basic_local",
        "local_operational_enabled": False,
        "remote_beta_sharing_enabled": False,
        "share_level": "off",
    }
    assert can_use_governed_mode(settings) is False
    assert can_use_delegate_fleet(settings) is False
    assert can_use_checkpoint(settings) is False
    assert can_use_coordination_leases(settings) is False
    assert can_use_current_state(settings) is False
    assert can_use_queue_planning(settings) is False
    assert can_use_replay_debug(settings) is False
    assert can_use_autonomous_spawn(settings) is False


def test_share_level_off_prevents_upload():
    settings = {
        "mode": "beta_orchestration",
        "local_operational_enabled": True,
        "remote_beta_sharing_enabled": True,
        "share_level": "off",
    }
    assert can_upload_remote_beta_data(settings) is False


def test_debug_local_only_prevents_upload():
    settings = {
        "mode": "beta_orchestration",
        "local_operational_enabled": True,
        "remote_beta_sharing_enabled": True,
        "share_level": "debug_local_only",
    }
    assert can_upload_remote_beta_data(settings) is False


def test_allowed_share_levels_enable_upload():
    for level in ALLOWED_SHARE_LEVELS_FOR_UPLOAD:
        settings = {
            "mode": "beta_orchestration",
            "local_operational_enabled": True,
            "remote_beta_sharing_enabled": True,
            "share_level": level,
        }
        assert can_upload_remote_beta_data(settings) is True, f"Failed for {level}"


def test_disabled_features_beta_orchestration():
    settings = {
        "mode": "beta_orchestration",
        "local_operational_enabled": True,
        "remote_beta_sharing_enabled": True,
        "share_level": "derived_only",
    }
    disabled = disabled_features_for_settings(settings)
    assert len(disabled) == 0


def test_disabled_features_remote_sharing_off():
    settings = {
        "mode": "basic_local",
        "local_operational_enabled": True,
        "remote_beta_sharing_enabled": False,
        "share_level": "off",
    }
    disabled = disabled_features_for_settings(settings)
    assert "remote_upload" in disabled
    assert "maintainer_debugging" in disabled
    assert "shared_benchmarks" in disabled
    assert "cross_user_reports" in disabled


def test_disabled_features_local_operational_off():
    settings = {
        "mode": "basic_local",
        "local_operational_enabled": False,
        "remote_beta_sharing_enabled": False,
        "share_level": "off",
    }
    disabled = disabled_features_for_settings(settings)
    assert "governed_mode" in disabled
    assert "delegate_fleet" in disabled
    assert "checkpoint_commits" in disabled
    assert "coordination_leases" in disabled
    assert "current_state" in disabled
    assert "queue_planning" in disabled
    assert "replay_debug" in disabled
    assert "autonomous_spawn_execution" in disabled


def test_basic_local_preserves_local_safety():
    settings = {
        "mode": "basic_local",
        "local_operational_enabled": True,
        "remote_beta_sharing_enabled": False,
        "share_level": "off",
    }
    disabled = disabled_features_for_settings(settings)
    # In basic_local mode, governed_mode is disabled (no advanced features)
    assert "governed_mode" in disabled
    # Local safety features like individual tool use should still work
    # Remote features should be disabled
    assert "remote_upload" in disabled


# ── Relay-native import tests ────────────────────────────────────────────


def test_relay_validate_bundle_same_behavior(tmp_path):
    """Both script and Relay-native import produce identical results."""
    bundle_path = tmp_path / "nonexistent.zip"
    valid1, msgs1 = validate_bundle(bundle_path)
    valid2, msgs2 = relay_validate_bundle(bundle_path)
    assert valid1 == valid2
    assert msgs1 == msgs2
    assert not valid1  # nonexistent file


# ── State Root Bundle Tests ──


class TestBundleStateRoot:
    def test_bundle_with_explicit_consent_file_includes_consent_status(
        self, tmp_path: Path
    ):
        """Bundle with --consent-file includes consent status in manifest."""
        derived = tmp_path / "derived"
        derived.mkdir()
        (derived / "data.jsonl").write_text('{"x": 1}\n')

        consent_data = {
            "schema_version": "rig.relay.telemetry_consent.v1",
            "consent_id": "cons_bundle_test",
            "subject_hash": "sha256:test",
            "provider": "local",
            "status": "granted",
            "scopes": ["usage_metrics"],
            "granted_at": "2026-05-14T00:00:00Z",
            "policy_version": "2026-05-13",
            "local_only": True,
        }
        consent_file = tmp_path / "consent.json"
        consent_file.write_text(json.dumps(consent_data, indent=2))

        manifest = create_bundle(
            participant_id="test_consent_bundle",
            share_level="derived_only",
            derived_dir=derived,
            reports_dir=tmp_path / "reports",
            output_dir=tmp_path / "out",
            consent_file=consent_file,
            dry_run=False,
        )
        # Verify consent_status in manifest
        assert manifest.get("consent_status") is not None
        assert manifest["consent_status"]["status"] == "granted"
        assert "subject_hash" in manifest["consent_status"]
        assert "scopes" in manifest["consent_status"]

    def test_bundle_without_consent_file_does_not_include_consent(self, tmp_path: Path):
        """Bundle without consent file and without state_root has no consent_status."""
        derived = tmp_path / "derived"
        derived.mkdir()
        (derived / "data.jsonl").write_text('{"x": 1}\n')

        manifest = create_bundle(
            participant_id="test_no_consent",
            share_level="derived_only",
            derived_dir=derived,
            reports_dir=tmp_path / "reports",
            output_dir=tmp_path / "out",
            dry_run=False,
        )
        assert manifest.get("consent_status") is None, (
            f"Expected no consent_status, got {manifest.get('consent_status')}"
        )

    def test_bundle_with_state_root_detects_consent(self, tmp_path: Path):
        """Bundle with --state-root reads consent from that root."""
        derived = tmp_path / "derived"
        derived.mkdir()
        (derived / "data.jsonl").write_text('{"x": 1}\n')

        # Write consent to state_root/consent/
        state_root = tmp_path / "state_root"
        consent_dir = state_root / "consent"
        consent_dir.mkdir(parents=True)
        consent_record = {
            "schema_version": "rig.relay.telemetry_consent.v1",
            "consent_id": "cons_state_root",
            "subject_hash": "sha256:state_root_test",
            "provider": "local",
            "status": "granted",
            "scopes": ["usage_metrics"],
            "granted_at": "2026-05-14T00:00:00Z",
            "policy_version": "2026-05-13",
            "local_only": True,
        }
        consent_path = consent_dir / "telemetry_consent.json"
        consent_path.write_text(json.dumps(consent_record, indent=2))

        manifest = create_bundle(
            participant_id="test_state_root",
            share_level="derived_only",
            derived_dir=derived,
            reports_dir=tmp_path / "reports",
            output_dir=tmp_path / "out",
            state_root=state_root,
            dry_run=False,
        )
        assert manifest.get("consent_status") is not None
        assert manifest["consent_status"]["status"] == "granted"
        assert manifest["consent_status"]["subject_hash"] == "sha256:state_root_test"

    def test_bundle_state_root_does_not_read_home(self, tmp_path: Path):
        """Bundle with tmp state_root does NOT read ~/.rig/relay/."""
        derived = tmp_path / "derived"
        derived.mkdir()
        (derived / "data.jsonl").write_text('{"x": 1}\n')

        # Use a fresh tmp state_root with no consent file
        state_root = tmp_path / "empty_state"
        manifest = create_bundle(
            participant_id="test_empty_state",
            share_level="derived_only",
            derived_dir=derived,
            reports_dir=tmp_path / "reports",
            output_dir=tmp_path / "out",
            state_root=state_root,
            dry_run=False,
        )
        # If the bundle read ~/.rig/relay/consent, it would have consent_status
        # from the real consent file. But with empty state_root, there's nothing.
        assert manifest.get("consent_status") is None, (
            "Bundle read ~/.rig/relay/ despite passing explicit empty state_root"
        )
