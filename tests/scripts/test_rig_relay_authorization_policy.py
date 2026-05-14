"""Tests for step-up authorization policy, receipts, and gate checks."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _load_script(name: str):
    import importlib.util as iu

    path = REPO_ROOT / "scripts" / name
    spec = iu.spec_from_file_location(name.replace(".py", ""), path)
    assert spec is not None
    assert spec.loader is not None
    mod = iu.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="session")
def ap():
    return _load_script("rig_relay_authorization_policy.py")


# ── Schema validation ────────────────────────────────────────────────────


def _load_schema(name: str) -> dict:
    path = REPO_ROOT / "docs" / "schemas" / name
    return json.loads(path.read_text(encoding="utf-8"))


def _try_validate(instance: dict, schema: dict) -> list[str]:
    try:
        import jsonschema
    except ImportError:
        return []
    validator = jsonschema.Draft7Validator(schema)
    return [e.message for e in validator.iter_errors(instance)]


class TestPolicySchema:
    def test_policy_schema_validates_sample(self):
        schema = _load_schema("rig.relay.authorization_policy.v1.schema.json")
        sample = {
            "schema_version": "rig.relay.authorization_policy.v1",
            "protected_actions": ["remote_upload.confirm", "checkpoint.commit"],
            "action_methods": {
                "remote_upload.confirm": ["none_dev_only", "local_system_auth"],
                "checkpoint.commit": ["none_dev_only"],
            },
            "receipt_ttl_seconds": 300,
            "default_method": "local_system_auth",
            "allow_dev_bypass": True,
        }
        errors = _try_validate(sample, schema)
        assert not errors, f"Schema errors: {errors}"

    def test_policy_rejects_missing_required(self):
        schema = _load_schema("rig.relay.authorization_policy.v1.schema.json")
        errors = _try_validate({}, schema)
        assert len(errors) > 0


class TestRequestSchema:
    def test_request_schema_validates_sample(self, ap):
        schema = _load_schema("rig.relay.step_up_authorization_request.v1.schema.json")
        now = datetime.now(UTC)
        import secrets

        sample = {
            "schema_version": "rig.relay.step_up_authorization_request.v1",
            "authorization_id": "authz_" + secrets.token_hex(16),
            "requested_at": now.isoformat(),
            "action": "remote_upload.confirm",
            "action_scope": {"target_sha256": "sha256:" + "0" * 64},
            "requested_method": "local_system_auth",
            "allowed_methods": ["none_dev_only", "local_system_auth"],
            "expires_at": (now + timedelta(minutes=5)).isoformat(),
            "reason": "Need to upload telemetry bundle.",
        }
        errors = _try_validate(sample, schema)
        assert not errors, f"Schema errors: {errors}"


class TestReceiptSchema:
    def test_receipt_schema_validates_sample(self, ap):
        schema = _load_schema("rig.relay.step_up_authorization_receipt.v1.schema.json")
        receipt = ap.generate_dev_receipt("remote_upload.confirm")
        errors = _try_validate(receipt, schema)
        assert not errors, f"Schema errors: {errors}"

    def test_receipt_contains_no_secrets(self, ap):
        """Receipt must not contain private keys, biometric data, or passwords."""
        receipt = ap.generate_dev_receipt("checkpoint.commit")
        output = json.dumps(receipt)
        assert "PRIVATE KEY" not in output
        assert "biometric" not in output.lower()
        assert "fingerprint" not in output.lower()
        assert "password" not in output.lower()
        assert "face" not in output.lower()


# ── Gate checks ──────────────────────────────────────────────────────────


class TestActionGates:
    def test_protected_actions_require_authorization(self, ap):
        for action in ap.DEFAULT_POLICY["protected_actions"]:
            assert ap.action_requires_authorization(action) is True

    def test_read_only_actions_do_not_require_authorization(self, ap):
        from rig_relay.core.auth.receipt import READ_ONLY_ACTIONS, is_read_only_action

        for action in READ_ONLY_ACTIONS:
            assert ap.action_requires_authorization(action) is False
            assert is_read_only_action(action) is True

    def test_unknown_action_not_protected(self, ap):
        assert ap.action_requires_authorization("nonexistent.action") is False


class TestReceiptValidation:
    def test_valid_receipt_passes(self, ap):
        receipt = ap.generate_dev_receipt("remote_upload.confirm")
        valid, reason = ap.validate_receipt(receipt, "remote_upload.confirm")
        assert valid is True
        assert reason == "Receipt valid"

    def test_expired_receipt_fails(self, ap):
        receipt = ap.generate_dev_receipt("remote_upload.confirm", ttl_seconds=-1)
        valid, reason = ap.validate_receipt(receipt, "remote_upload.confirm")
        assert valid is False
        assert "expired" in reason.lower()

    def test_mismatched_action_fails(self, ap):
        receipt = ap.generate_dev_receipt("remote_upload.confirm")
        valid, reason = ap.validate_receipt(receipt, "checkpoint.commit")
        assert valid is False
        assert "mismatch" in reason.lower()

    def test_mismatched_scope_hash_fails(self, ap):
        scope1 = {"target_sha256": "sha256:" + "a" * 64}
        scope2 = {"target_sha256": "sha256:" + "b" * 64}
        receipt = ap.generate_dev_receipt("remote_upload.confirm", action_scope=scope1)
        valid, reason = ap.validate_receipt(
            receipt, "remote_upload.confirm", action_scope=scope2
        )
        assert valid is False
        assert "mismatch" in reason.lower()

    def test_missing_schema_version_fails(self, ap):
        receipt = {"action": "remote_upload.confirm"}
        valid, reason = ap.validate_receipt(receipt, "remote_upload.confirm")
        assert valid is False

    def test_user_not_verified_fails(self, ap):
        receipt = ap.generate_dev_receipt("remote_upload.confirm")
        receipt["user_verified"] = False
        valid, reason = ap.validate_receipt(receipt, "remote_upload.confirm")
        assert valid is False
        assert "verified" in reason.lower()

    def test_disallowed_method_fails(self, ap):
        policy = dict(ap.DEFAULT_POLICY)
        policy["action_methods"] = {"remote_upload.confirm": ["local_system_auth"]}
        receipt = ap.generate_dev_receipt("remote_upload.confirm")
        receipt["method"] = "passkey_webauthn"
        valid, reason = ap.validate_receipt(
            receipt, "remote_upload.confirm", policy=policy
        )
        assert valid is False
        assert "not allowed" in reason.lower()

    def test_dev_generate_output_validates(self, ap):
        receipt = ap.generate_dev_receipt("lease_cleanup.archive")
        assert receipt["schema_version"] == "rig.relay.step_up_authorization_receipt.v1"
        assert receipt["action"] == "lease_cleanup.archive"
        assert receipt["authorization_id"].startswith("authz_")
        assert receipt["method"] == "none_dev_only"
        assert receipt["user_verified"] is True
        assert receipt["receipt_sha256"].startswith("sha256:")


class TestCLI:
    def test_check_action_cli(self, ap):
        import subprocess

        result = subprocess.run(
            [
                "python",
                str(REPO_ROOT / "scripts" / "rig_relay_authorization_policy.py"),
                "--check-action",
                "remote_upload.confirm",
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "requires authorization" in result.stdout

    def test_check_read_only_action_cli(self, ap):
        import subprocess

        result = subprocess.run(
            [
                "python",
                str(REPO_ROOT / "scripts" / "rig_relay_authorization_policy.py"),
                "--check-action",
                "cockpit.read",
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "read-only" in result.stdout

    def test_dev_generate_cli(self, ap, tmp_path):
        import subprocess

        out = tmp_path / "receipt.json"
        result = subprocess.run(
            [
                "python",
                str(REPO_ROOT / "scripts" / "rig_relay_authorization_policy.py"),
                "--dev-generate-receipt",
                "--action",
                "checkpoint.commit",
                "--output",
                str(out),
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert out.is_file()

    def test_receipt_validates_via_cli(self, ap, tmp_path):
        import subprocess

        out = tmp_path / "receipt.json"
        subprocess.run(
            [
                "python",
                str(REPO_ROOT / "scripts" / "rig_relay_authorization_policy.py"),
                "--dev-generate-receipt",
                "--action",
                "remote_upload.confirm",
                "--output",
                str(out),
            ],
            capture_output=True,
            text=True,
        )
        result = subprocess.run(
            [
                "python",
                str(REPO_ROOT / "scripts" / "rig_relay_authorization_policy.py"),
                "--validate-receipt",
                str(out),
                "--action",
                "remote_upload.confirm",
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "VALID" in result.stdout
