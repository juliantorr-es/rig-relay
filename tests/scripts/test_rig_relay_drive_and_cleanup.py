"""Tests for Google Drive upload and coordination lease cleanup scripts."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent



pytestmark = [pytest.mark.migration]

def _load_script(name: str):
    import importlib.util as iu

    path = REPO_ROOT / "scripts" / name
    spec = iu.spec_from_file_location(name.replace(".py", ""), path)
    assert spec is not None
    assert spec.loader is not None
    mod = iu.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ══════════════════════════════════════════════════════════════════════════
# Google Drive Upload
# ══════════════════════════════════════════════════════════════════════════


class TestGoogleDriveUpload:
    @pytest.fixture(scope="class")
    def up(self):
        return _load_script("rig_relay_upload_google_drive.py")

    def test_drive_deps_available(self, up):
        """Google Drive deps are core; module-level imports succeed."""
        import google.auth  # noqa: F401
        import google_auth_oauthlib  # noqa: F401
        import googleapiclient  # noqa: F401

    def test_dry_run_creates_receipt(self, up, tmp_path):
        """Dry-run should create a receipt without network access."""
        bundle = tmp_path / "test_bundle.zip"
        bundle.write_text("fake bundle content")
        receipt = up._upload_dry_run(
            bundle_path=bundle,
            folder_id="fake-folder-id",
            participant_id="anon_test",
            share_level="derived_only",
        )
        assert receipt["status"] == "dry_run"
        assert receipt["upload_method"] == "dry_run"
        assert receipt["bundle_sha256"].startswith("sha256:")
        assert receipt["drive_file_id"] is None

    def test_real_upload_without_confirm_refuses(self, up, tmp_path):
        """upload_bundle should refuse real upload without --confirm."""
        bundle = tmp_path / "test_bundle.zip"
        bundle.write_text("fake content")
        with pytest.raises((ImportError, RuntimeError)):
            up._upload_real(
                bundle_path=bundle,
                folder_id="fake-folder-id",
                participant_id="anon_test",
                share_level="derived_only",
            )

    def test_upload_bundle_dry_run_default(self, up, tmp_path):
        """upload_bundle should default to dry-run when confirm=False."""
        bundle = tmp_path / "test_bundle.zip"
        bundle.write_text("fake content")
        receipt = up.upload_bundle(
            bundle_path=bundle,
            folder_id="fake-folder-id",
            participant_id="anon_test",
            share_level="derived_only",
            dry_run=True,
            confirm=False,
        )
        assert receipt["status"] == "dry_run"

    def test_real_upload_without_bundle_refuses(self, up):
        """main should refuse real upload when bundle is missing."""
        import subprocess

        result = subprocess.run(
            [
                "python",
                str(REPO_ROOT / "scripts" / "rig_relay_upload_google_drive.py"),
                "--bundle",
                "/nonexistent/bundle.zip",
                "--folder-id",
                "fake-id",
                "--no-dry-run",
                "--confirm",
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode != 0

    def test_real_upload_without_confirm_flag_refuses(self, up, tmp_path):
        """CLI should refuse when --no-dry-run is set without --confirm."""
        import subprocess

        bundle = tmp_path / "test_bundle.zip"
        bundle.write_text("fake")
        result = subprocess.run(
            [
                "python",
                str(REPO_ROOT / "scripts" / "rig_relay_upload_google_drive.py"),
                "--bundle",
                str(bundle),
                "--folder-id",
                "fake-id",
                "--no-dry-run",
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode != 0
        assert "confirm" in result.stderr.lower()


# ══════════════════════════════════════════════════════════════════════════
# Stale Lease Cleanup
# ══════════════════════════════════════════════════════════════════════════


class TestStaleLeaseCleanup:
    @pytest.fixture(scope="class")
    def cl(self):
        return _load_script("rig_relay_cleanup_coordination_leases.py")

    def test_dry_run_reports_nothing_when_empty(self, cl, tmp_path):
        """Dry-run on empty coordination root should report nothing."""
        coord = tmp_path / "coordination"
        (coord / "leases" / "paths").mkdir(parents=True)
        result = cl.run_cleanup(coord, dry_run=True, confirm=False)
        assert result["action"] == "none" or result["action"] == "dry_run"
        assert result["stats"]["total_cleanable"] == 0

    def test_reports_stale_leases(self, cl, tmp_path):
        """Stale lease files appear in cleanup report."""
        coord = tmp_path / "coordination"
        leases_dir = coord / "leases" / "paths"
        leases_dir.mkdir(parents=True)

        # Create a stale lease
        stale = leases_dir / "stale_lease.json"
        stale.write_text(
            json.dumps({
                "path_hash": "abc123",
                "status": "stale",
                "mode": "write",
                "session_id": "s1",
            })
        )

        result = cl.run_cleanup(coord, dry_run=True, confirm=False)
        assert result["stats"]["leases_stale"] >= 1
        assert result["stats"]["total_cleanable"] >= 1

    def test_never_archives_active_leases(self, cl, tmp_path):
        """Active leases must never be archived."""
        coord = tmp_path / "coordination"
        leases_dir = coord / "leases" / "paths"
        leases_dir.mkdir(parents=True)

        active = leases_dir / "active_lease.json"
        active.write_text(
            json.dumps({
                "path_hash": "def456",
                "status": "active",
                "mode": "write",
                "session_id": "s2",
                "expires_at": "2099-12-31T23:59:59+00:00",
            })
        )

        result = cl.run_cleanup(coord, dry_run=True, confirm=False)
        assert result["stats"]["leases_active"] >= 1
        assert result["stats"]["leases_stale"] == 0

    def test_archive_requires_confirm(self, cl, tmp_path):
        """Archive mode without confirm should not move files."""
        coord = tmp_path / "coordination"
        leases_dir = coord / "leases" / "paths"
        leases_dir.mkdir(parents=True)

        stale = leases_dir / "stale_lease.json"
        stale.write_text(json.dumps({"path_hash": "abc123", "status": "stale"}))

        result = cl.run_cleanup(coord, dry_run=False, archive=True, confirm=False)
        assert result["action"] == "skipped"
        assert stale.is_file()

    def test_archive_moves_stale_with_confirm(self, cl, tmp_path):
        """Archive with confirm should move stale files."""
        coord = tmp_path / "coordination"
        leases_dir = coord / "leases" / "paths"
        leases_dir.mkdir(parents=True)

        stale = leases_dir / "stale_lease.json"
        stale.write_text(json.dumps({"path_hash": "abc123", "status": "stale"}))

        result = cl.run_cleanup(coord, dry_run=False, archive=True, confirm=True)
        assert result["action"] == "archived"
        # File should no longer be in original location
        assert not stale.is_file()

    def test_output_is_content_light(self, cl, tmp_path):
        """Cleanup output must not contain raw content patterns."""
        coord = tmp_path / "coordination"
        leases_dir = coord / "leases" / "paths"
        leases_dir.mkdir(parents=True)

        stale = leases_dir / "stale_lease.json"
        stale.write_text(json.dumps({"path_hash": "abc123", "status": "stale"}))

        result = cl.run_cleanup(coord, dry_run=True, confirm=False)
        output = json.dumps(result)
        assert "-----BEGIN RSA PRIVATE KEY" not in output
        assert "/Users/" not in output

    def test_cleanup_manifest_records_counts(self, cl, tmp_path):
        """Cleanup should produce a result dict with stats."""
        coord = tmp_path / "coordination"
        leases_dir = coord / "leases" / "paths"
        leases_dir.mkdir(parents=True)

        stale = leases_dir / "stale_lease.json"
        stale.write_text(json.dumps({"path_hash": "abc123", "status": "stale"}))

        result = cl.run_cleanup(coord, dry_run=False, archive=True, confirm=True)
        assert "stats" in result
        assert "errors" in result
        assert "action" in result
        assert isinstance(result["stats"], dict)


# ══════════════════════════════════════════════════════════════════════════
# Authorization Gate Tests
# ══════════════════════════════════════════════════════════════════════════


class TestUploadAuthorizationGate:
    """Authorization receipt gates for Google Drive upload."""

    @pytest.fixture(scope="class")
    def up(self):
        return _load_script("rig_relay_upload_google_drive.py")

    def test_real_upload_refused_without_receipt(self, up, tmp_path):
        """Real upload without --authorization-receipt or --dev-bypass must be refused."""
        import subprocess

        bundle = tmp_path / "test_bundle.zip"
        bundle.write_text("fake bundle content")
        result = subprocess.run(
            [
                "python",
                str(REPO_ROOT / "scripts" / "rig_relay_upload_google_drive.py"),
                "--bundle",
                str(bundle),
                "--folder-id",
                "fake-id",
                "--no-dry-run",
                "--confirm",
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode != 0
        assert (
            "authorization-receipt" in result.stderr.lower()
            or "dev-bypass" in result.stderr.lower()
        )

    def test_real_upload_accepted_with_dev_bypass(self, up, tmp_path):
        """Real upload with --dev-bypass should pass the auth gate."""
        import subprocess

        bundle = tmp_path / "test_bundle.zip"
        bundle.write_text("fake bundle content")
        result = subprocess.run(
            [
                "python",
                str(REPO_ROOT / "scripts" / "rig_relay_upload_google_drive.py"),
                "--bundle",
                str(bundle),
                "--folder-id",
                "fake-id",
                "--no-dry-run",
                "--confirm",
                "--dev-bypass",
            ],
            capture_output=True,
            text=True,
        )
        # The dev bypass passes the auth gate; real upload still fails (no Drive deps)
        assert "authorization" not in result.stderr.lower()

    def test_real_upload_refused_with_expired_receipt(self, up, tmp_path):
        """Real upload with expired receipt must be refused."""
        import json
        import subprocess

        from rig_relay.core.auth.receipt import generate_dev_receipt

        bundle = tmp_path / "test_bundle.zip"
        bundle.write_text("fake bundle content")
        expired = generate_dev_receipt("remote_upload.confirm", ttl_seconds=-1)
        receipt_path = tmp_path / "expired_receipt.json"
        receipt_path.write_text(json.dumps(expired))

        result = subprocess.run(
            [
                "python",
                str(REPO_ROOT / "scripts" / "rig_relay_upload_google_drive.py"),
                "--bundle",
                str(bundle),
                "--folder-id",
                "fake-id",
                "--no-dry-run",
                "--confirm",
                "--authorization-receipt",
                str(receipt_path),
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode != 0
        assert "expired" in result.stderr.lower()

    def test_real_upload_refused_with_wrong_action_receipt(self, up, tmp_path):
        """Real upload with receipt for wrong action must be refused."""
        import json
        import subprocess

        from rig_relay.core.auth.receipt import generate_dev_receipt

        bundle = tmp_path / "test_bundle.zip"
        bundle.write_text("fake bundle content")
        wrong = generate_dev_receipt("lease_cleanup.archive")
        receipt_path = tmp_path / "wrong_receipt.json"
        receipt_path.write_text(json.dumps(wrong))

        result = subprocess.run(
            [
                "python",
                str(REPO_ROOT / "scripts" / "rig_relay_upload_google_drive.py"),
                "--bundle",
                str(bundle),
                "--folder-id",
                "fake-id",
                "--no-dry-run",
                "--confirm",
                "--authorization-receipt",
                str(receipt_path),
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode != 0
        assert "mismatch" in result.stderr.lower()


class TestCleanupAuthorizationGate:
    """Authorization receipt gates for coordination lease cleanup."""

    @pytest.fixture(scope="class")
    def cl(self):
        return _load_script("rig_relay_cleanup_coordination_leases.py")

    def test_cleanup_refused_without_receipt(self, cl, tmp_path):
        """Destructive cleanup without receipt must be refused."""
        import subprocess

        coord = tmp_path / "coordination"
        (coord / "leases" / "paths").mkdir(parents=True)
        (coord / "leases" / "paths" / "stale.json").write_text(
            '{"status": "stale", "path_hash": "abc"}'
        )

        result = subprocess.run(
            [
                "python",
                str(REPO_ROOT / "scripts" / "rig_relay_cleanup_coordination_leases.py"),
                "--coordination-root",
                str(coord),
                "--no-dry-run",
                "--confirm",
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode != 0
        assert (
            "authorization-receipt" in result.stderr.lower()
            or "dev-bypass" in result.stderr.lower()
        )

    def test_cleanup_accepted_with_dev_bypass(self, cl, tmp_path):
        """Cleanup with --dev-bypass should pass the auth gate."""
        import subprocess

        coord = tmp_path / "coordination"
        (coord / "leases" / "paths").mkdir(parents=True)
        (coord / "leases" / "paths" / "stale.json").write_text(
            '{"status": "stale", "path_hash": "abc"}'
        )

        result = subprocess.run(
            [
                "python",
                str(REPO_ROOT / "scripts" / "rig_relay_cleanup_coordination_leases.py"),
                "--coordination-root",
                str(coord),
                "--no-dry-run",
                "--confirm",
                "--dev-bypass",
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "Warning: Dev bypass" in result.stdout

    def test_cleanup_archive_refused_with_expired_receipt(self, cl, tmp_path):
        """Archive cleanup with expired receipt must be refused."""
        import json
        import subprocess

        from rig_relay.core.auth.receipt import generate_dev_receipt

        coord = tmp_path / "coordination"
        (coord / "leases" / "paths").mkdir(parents=True)
        (coord / "leases" / "paths" / "stale.json").write_text(
            '{"status": "stale", "path_hash": "abc"}'
        )

        expired = generate_dev_receipt("lease_cleanup.archive", ttl_seconds=-1)
        receipt_path = tmp_path / "expired_receipt.json"
        receipt_path.write_text(json.dumps(expired))

        result = subprocess.run(
            [
                "python",
                str(REPO_ROOT / "scripts" / "rig_relay_cleanup_coordination_leases.py"),
                "--coordination-root",
                str(coord),
                "--no-dry-run",
                "--confirm",
                "--archive",
                "--authorization-receipt",
                str(receipt_path),
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode != 0
        assert "expired" in result.stderr.lower()

    def test_cleanup_remove_refused_with_wrong_action_receipt(self, cl, tmp_path):
        """Permanent removal with receipt for wrong action must be refused."""
        import json
        import subprocess

        from rig_relay.core.auth.receipt import generate_dev_receipt

        coord = tmp_path / "coordination"
        (coord / "leases" / "paths").mkdir(parents=True)
        (coord / "leases" / "paths" / "stale.json").write_text(
            '{"status": "stale", "path_hash": "abc"}'
        )

        wrong = generate_dev_receipt("remote_upload.confirm")
        receipt_path = tmp_path / "wrong_receipt.json"
        receipt_path.write_text(json.dumps(wrong))

        result = subprocess.run(
            [
                "python",
                str(REPO_ROOT / "scripts" / "rig_relay_cleanup_coordination_leases.py"),
                "--coordination-root",
                str(coord),
                "--no-dry-run",
                "--confirm",
                "--authorization-receipt",
                str(receipt_path),
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode != 0
        assert "mismatch" in result.stderr.lower()

    def test_cleanup_archive_accepted_with_valid_receipt(self, cl, tmp_path):
        """Archive cleanup with valid receipt should proceed."""
        import json
        import subprocess

        from rig_relay.core.auth.receipt import generate_dev_receipt

        coord = tmp_path / "coordination"
        (coord / "leases" / "paths").mkdir(parents=True)
        (coord / "leases" / "paths" / "stale.json").write_text(
            '{"status": "stale", "path_hash": "abc"}'
        )

        valid = generate_dev_receipt("lease_cleanup.archive")
        receipt_path = tmp_path / "valid_receipt.json"
        receipt_path.write_text(json.dumps(valid))

        result = subprocess.run(
            [
                "python",
                str(REPO_ROOT / "scripts" / "rig_relay_cleanup_coordination_leases.py"),
                "--coordination-root",
                str(coord),
                "--no-dry-run",
                "--confirm",
                "--archive",
                "--authorization-receipt",
                str(receipt_path),
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "Archived" in result.stdout
