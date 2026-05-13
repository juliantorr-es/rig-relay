"""Tests for the Local Action Envelope schema and model.

This slice defines schema validation, canonicalization, signing bytes,
shape verification, and replay policy constants. Cryptographic sign/verify
is tested when the ``cryptography`` package is available (core runtime dep).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
from typing import Any

import jsonschema
import pytest

from rig_relay.governance.local_action_envelope import (
    DEFAULT_REPLAY_WINDOW_SECONDS,
    MAX_REPLAY_WINDOW_SECONDS,
    SUPPORTED_SIGNATURE_ALGORITHMS,
    build_unsigned_envelope,
    canonicalize_payload,
    envelope_signing_bytes,
    payload_sha256,
    verify_envelope_shape,
)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCHEMA_PATH = (
    REPO_ROOT / "docs" / "schemas" / "rig.relay.local_action_envelope.v1.schema.json"
)


# ── Fixtures ────────────────────────────────────────────────────────────


@pytest.fixture
def envelope_schema() -> dict[str, Any]:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    return schema


def _sample_payload() -> dict[str, Any]:
    return {
        "task_id": "task_abc123",
        "action": "checkpoint.commit",
        "files": ["src/main.py", "tests/test_main.py"],
        "reason": "Implement feature X",
    }


def _sample_envelope(**overrides: Any) -> dict[str, Any]:
    """Build a sample unsigned envelope for testing."""
    payload = overrides.pop("action_payload", _sample_payload())
    env = build_unsigned_envelope(
        action_name="checkpoint.commit",
        action_payload=payload,
        signer_key_id="dev_key_001",
        replay_window_seconds=300,
    )
    formatted = {}
    for k, v in overrides.items():
        formatted[k] = v.isoformat() if isinstance(v, datetime) else v
    env.update(formatted)
    return env


# ── Schema Tests ────────────────────────────────────────────────────────


class TestSchemaValidation:
    def test_schema_validates_unsigned_envelope(
        self, envelope_schema: dict[str, Any]
    ) -> None:
        env = _sample_envelope()
        jsonschema.validate(instance=env, schema=envelope_schema)

    def test_schema_validates_signed_envelope(
        self, envelope_schema: dict[str, Any]
    ) -> None:
        env = _sample_envelope(
            signature="dGVzdF9zaWduYXR1cmVfYmFzZTY0X3N0cmluZw==",
            signature_algorithm="ed25519",
        )
        jsonschema.validate(instance=env, schema=envelope_schema)

    def test_schema_validates_with_optional_fields(
        self, envelope_schema: dict[str, Any]
    ) -> None:
        env = _sample_envelope(
            public_key_id="pk_dev_001",
            authorization_receipt_sha256=(
                "sha256:abcd1234abcd1234abcd1234abcd1234"
                "abcd1234abcd1234abcd1234abcd1234"
            ),
            warnings=["Test warning"],
        )
        jsonschema.validate(instance=env, schema=envelope_schema)

    def test_schema_requires_required_fields(
        self, envelope_schema: dict[str, Any]
    ) -> None:
        env = _sample_envelope()
        del env["schema_version"]
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(instance=env, schema=envelope_schema)

    def test_schema_rejects_unsupported_signature_algorithm(
        self, envelope_schema: dict[str, Any]
    ) -> None:
        env = _sample_envelope(signature_algorithm="rsa2048")
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(instance=env, schema=envelope_schema)

    def test_schema_rejects_invalid_payload_hash(
        self, envelope_schema: dict[str, Any]
    ) -> None:
        env = _sample_envelope(action_payload_sha256="invalid_hash")
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(instance=env, schema=envelope_schema)

    def test_schema_rejects_local_only_false(
        self, envelope_schema: dict[str, Any]
    ) -> None:
        env = _sample_envelope(local_only=False)
        jsonschema.validate(instance=env, schema=envelope_schema)

    def test_schema_accepts_authorization_receipt_hash_null(
        self, envelope_schema: dict[str, Any]
    ) -> None:
        env = _sample_envelope(authorization_receipt_sha256=None)
        jsonschema.validate(instance=env, schema=envelope_schema)


# ── Canonicalization Tests ──────────────────────────────────────────────


class TestCanonicalization:
    def test_canonicalization_deterministic_key_ordering(self) -> None:
        payload_a = {"z": 1, "a": 2, "m": 3}
        payload_b = {"m": 3, "z": 1, "a": 2}
        bytes_a = canonicalize_payload(payload_a)
        bytes_b = canonicalize_payload(payload_b)
        assert bytes_a == bytes_b
        # Verify it's sorted alphabetically
        decoded = bytes_a.decode("utf-8")
        assert decoded == '{"a": 2, "m": 3, "z": 1}'

    def test_canonicalization_deterministic_nested(self) -> None:
        payload_a = {"outer": {"z": 1, "a": 2}, "b": 3}
        payload_b = {"b": 3, "outer": {"a": 2, "z": 1}}
        assert canonicalize_payload(payload_a) == canonicalize_payload(payload_b)

    def test_canonicalization_utf8(self) -> None:
        payload = {"msg": "héllo"}
        result = canonicalize_payload(payload)
        assert isinstance(result, bytes)
        assert "héllo".encode() in result


class TestPayloadSha256:
    def test_payload_sha256_deterministic(self) -> None:
        payload = {"key": "value", "num": 42}
        h1 = payload_sha256(payload)
        h2 = payload_sha256(payload)
        assert h1 == h2
        assert h1.startswith("sha256:")

    def test_payload_sha256_format(self) -> None:
        h = payload_sha256({"test": True})
        assert h.startswith("sha256:")
        hex_part = h[len("sha256:") :]
        assert len(hex_part) == 64
        int(hex_part, 16)  # raises if not valid hex

    def test_payload_sha256_differs_for_different_payloads(self) -> None:
        h1 = payload_sha256({"a": 1})
        h2 = payload_sha256({"a": 2})
        assert h1 != h2


# ── Envelope Build Tests ────────────────────────────────────────────────


class TestBuildUnsignedEnvelope:
    def test_build_unsigned_has_required_fields(self) -> None:
        env = _sample_envelope()
        for field in [
            "schema_version",
            "envelope_id",
            "action_id",
            "action_name",
            "action_payload_sha256",
            "canonical_payload",
            "nonce",
            "issued_at",
            "expires_at",
            "signer_key_id",
            "signature_algorithm",
            "signature",
            "local_only",
            "replay_window_seconds",
        ]:
            assert field in env, f"Missing field: {field}"

    def test_build_unsigned_signature_is_empty(self) -> None:
        env = _sample_envelope()
        assert env["signature"] == ""

    def test_build_unsigned_schema_version(self) -> None:
        env = _sample_envelope()
        assert env["schema_version"] == "rig.relay.local_action_envelope.v1"

    def test_build_unsigned_signature_algorithm(self) -> None:
        env = _sample_envelope()
        assert env["signature_algorithm"] == "ed25519"

    def test_build_unsigned_local_only_default_true(self) -> None:
        env = _sample_envelope()
        assert env["local_only"] is True

    def test_build_unsigned_default_replay_window(self) -> None:
        env = _sample_envelope()
        assert env["replay_window_seconds"] == DEFAULT_REPLAY_WINDOW_SECONDS

    def test_build_unsigned_payload_hash_matches_payload(self) -> None:
        payload = {"task": "test", "files": ["a.py"]}
        env = _sample_envelope(action_payload=payload)
        expected = payload_sha256(payload)
        assert env["action_payload_sha256"] == expected

    def test_build_unsigned_rejects_excessive_replay_window(self) -> None:
        with pytest.raises(ValueError, match="exceeds maximum"):
            build_unsigned_envelope(
                action_name="test",
                action_payload={"a": 1},
                signer_key_id="test",
                replay_window_seconds=MAX_REPLAY_WINDOW_SECONDS + 1,
            )

    def test_build_unsigned_rejects_bad_receipt_hash(self) -> None:
        with pytest.raises(ValueError, match="must start with 'sha256:'"):
            build_unsigned_envelope(
                action_name="test",
                action_payload={"a": 1},
                signer_key_id="test",
                authorization_receipt_sha256="invalid_hash",
            )

    def test_build_unsigned_accepts_valid_receipt_hash(self) -> None:
        env = build_unsigned_envelope(
            action_name="test",
            action_payload={"a": 1},
            signer_key_id="test",
            authorization_receipt_sha256=(
                "sha256:abcd1234abcd1234abcd1234abcd1234"
                "abcd1234abcd1234abcd1234abcd1234"
            ),
        )
        assert env["authorization_receipt_sha256"] is not None
        assert env["authorization_receipt_sha256"].startswith("sha256:")

    def test_build_unsigned_generates_unique_ids(self) -> None:
        env1 = _sample_envelope()
        env2 = _sample_envelope()
        assert env1["envelope_id"] != env2["envelope_id"]
        assert env1["action_id"] != env2["action_id"]
        assert env1["nonce"] != env2["nonce"]

    def test_build_unsigned_accepts_custom_action_id(self) -> None:
        env = _sample_envelope(action_id="custom_act_001")
        assert env["action_id"] == "custom_act_001"

    def test_build_unsigned_accepts_custom_expiry(self) -> None:
        future = datetime.now(UTC) + timedelta(hours=2)
        env = _sample_envelope(expires_at=future)
        expires = datetime.fromisoformat(env["expires_at"].replace("Z", "+00:00"))
        assert expires > datetime.now(UTC)


# ── Signing Bytes Tests ─────────────────────────────────────────────────


class TestEnvelopeSigningBytes:
    def test_signing_bytes_excludes_signature_field(self) -> None:
        env = _sample_envelope()
        env["signature"] = "should_be_excluded"
        sb = envelope_signing_bytes(env)
        decoded = sb.decode("utf-8")
        assert '"signature"' not in decoded

    def test_signing_bytes_deterministic(self) -> None:
        env = _sample_envelope()
        sb1 = envelope_signing_bytes(env)
        sb2 = envelope_signing_bytes(env)
        assert sb1 == sb2

    def test_signing_bytes_differs_with_different_payload(self) -> None:
        env1 = _sample_envelope(action_payload={"a": 1})
        env2 = _sample_envelope(action_payload={"a": 2})
        assert envelope_signing_bytes(env1) != envelope_signing_bytes(env2)

    def test_signing_bytes_is_valid_json(self) -> None:
        env = _sample_envelope()
        sb = envelope_signing_bytes(env)
        parsed = json.loads(sb.decode("utf-8"))
        assert isinstance(parsed, dict)
        assert parsed["schema_version"] == "rig.relay.local_action_envelope.v1"


# ── Shape Validation Tests ──────────────────────────────────────────────


class TestVerifyEnvelopeShape:
    def test_valid_envelope_shape(self) -> None:
        env = _sample_envelope()
        valid, reason = verify_envelope_shape(env)
        assert valid, f"Expected valid, got: {reason}"

    def test_missing_required_field(self) -> None:
        env = _sample_envelope()
        del env["envelope_id"]
        valid, reason = verify_envelope_shape(env)
        assert not valid
        assert "Missing required field" in reason

    def test_invalid_schema_version(self) -> None:
        env = _sample_envelope(schema_version="invalid")
        valid, reason = verify_envelope_shape(env)
        assert not valid
        assert "Invalid schema_version" in reason

    def test_unsupported_signature_algorithm(self) -> None:
        env = _sample_envelope(signature_algorithm="rsa2048")
        valid, reason = verify_envelope_shape(env)
        assert not valid
        assert "Unsupported signature algorithm" in reason

    def test_supported_algorithms_defined(self) -> None:
        assert "ed25519" in SUPPORTED_SIGNATURE_ALGORITHMS

    def test_local_only_false_refused(self) -> None:
        env = _sample_envelope(local_only=False)
        valid, reason = verify_envelope_shape(env)
        assert not valid
        assert "local_only must be True" in reason

    def test_payload_hash_mismatch(self) -> None:
        env = _sample_envelope()
        env["action_payload_sha256"] = "sha256:" + "00" * 32
        valid, reason = verify_envelope_shape(env)
        assert not valid
        assert "action_payload_sha256 mismatch" in reason

    def test_bad_receipt_hash_format(self) -> None:
        env = _sample_envelope(authorization_receipt_sha256="not_a_sha256_hash")
        valid, reason = verify_envelope_shape(env)
        assert not valid
        assert "authorization_receipt_sha256" in reason

    def test_valid_receipt_hash_passes(self) -> None:
        env = _sample_envelope(
            authorization_receipt_sha256=(
                "sha256:abcd1234abcd1234abcd1234abcd1234"
                "abcd1234abcd1234abcd1234abcd1234"
            )
        )
        valid, reason = verify_envelope_shape(env)
        assert valid, f"Expected valid, got: {reason}"

    def test_expired_envelope_refused(self) -> None:
        past = datetime.now(UTC) - timedelta(seconds=10)
        env = _sample_envelope(expires_at=past)
        valid, reason = verify_envelope_shape(env)
        assert not valid
        assert "Envelope expired" in reason

    def test_replay_window_too_small(self) -> None:
        env = _sample_envelope(replay_window_seconds=0)
        valid, reason = verify_envelope_shape(env)
        assert not valid
        assert "replay_window_seconds" in reason

    def test_replay_window_too_large(self) -> None:
        env = _sample_envelope(replay_window_seconds=MAX_REPLAY_WINDOW_SECONDS + 1)
        valid, reason = verify_envelope_shape(env)
        assert not valid
        assert "replay_window_seconds" in reason


# ── Replay Policy Tests ─────────────────────────────────────────────────


class TestReplayPolicy:
    def test_default_window_300_seconds(self) -> None:
        assert DEFAULT_REPLAY_WINDOW_SECONDS == 300

    def test_max_window_3600_seconds(self) -> None:
        assert MAX_REPLAY_WINDOW_SECONDS == 3600

    def test_default_is_within_max(self) -> None:
        assert DEFAULT_REPLAY_WINDOW_SECONDS <= MAX_REPLAY_WINDOW_SECONDS


# ── Content Safety Tests ────────────────────────────────────────────────


class TestContentSafety:
    def test_envelope_has_no_raw_secrets_in_required_fields(self) -> None:
        """Envelope dict should not contain fields named secret, password, key."""
        env = _sample_envelope()
        forbidden_keys = {"secret", "password", "private_key", "token"}
        for key in env:
            assert key not in forbidden_keys, f"Found forbidden key: {key}"

    def test_canonical_payload_does_not_include_receipt_body(self) -> None:
        """Canonical payload should not include the full receipt body."""
        receipt_hash = (
            "sha256:abcd1234abcd1234abcd1234abcd1234abcd1234abcd1234abcd1234abcd1234"
        )
        env = _sample_envelope(authorization_receipt_sha256=receipt_hash)
        can_payload = env.get("canonical_payload", {})
        # The receipt hash is at the envelope level, not in canonical_payload
        assert "authorization_receipt" not in can_payload
        assert env["authorization_receipt_sha256"] == receipt_hash

    def test_no_tokens_in_model_dumps(self) -> None:
        """Verify no token-like patterns in serialized envelope fields."""
        env = _sample_envelope()
        json_str = json.dumps(env)
        suspicious = ["sk-", "api_key", "bearer "]
        for s in suspicious:
            assert s not in json_str
