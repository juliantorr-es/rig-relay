from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from rig_relay.governance.decisions import GovernanceDecisionKind
from rig_relay.governance.local_action_envelope import (
    build_unsigned_envelope,
    sign_envelope,
)
from rig_relay.governance.local_action_gate import require_signed_envelope


def _generate_keypair() -> tuple[bytes, bytes]:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    private_key = Ed25519PrivateKey.generate()
    private_bytes = private_key.private_bytes_raw()
    public_bytes = private_key.public_key().public_bytes_raw()
    return private_bytes, public_bytes


def _build_signed_envelope(
    action: str,
    payload: dict[str, Any],
    *,
    private_key_bytes: bytes,
    public_key_id: str = "test_key_001",
    replay_window_seconds: int = 300,
    expires_at: datetime | None = None,
) -> dict[str, Any]:
    env = build_unsigned_envelope(
        action_name=action,
        action_payload=payload,
        signer_key_id=public_key_id,
        replay_window_seconds=replay_window_seconds,
    )
    env["public_key_id"] = public_key_id
    sign_envelope(env, private_key_bytes, public_key_id=None)
    if expires_at is not None:
        env["expires_at"] = expires_at.isoformat()
    return env


def _public_key_provider(public_key_id: str) -> bytes | None:
    if public_key_id == "test_key_001":
        _, pub = _generate_keypair_test_keys()
        return pub
    return None


_test_keys: tuple[bytes, bytes] | None = None


def _generate_keypair_test_keys() -> tuple[bytes, bytes]:
    global _test_keys
    if _test_keys is None:
        _test_keys = _generate_keypair()
    return _test_keys


class TestRequireSignedEnvelopeMutation:
    def test_missing_envelope_blocks_mutation(self) -> None:
        decision = require_signed_envelope(
            action="write_file",
            payload={"path": "test.py"},
            required_capability="tool:WriteFileTool",
            envelope=None,
        )
        assert decision.decision == GovernanceDecisionKind.BLOCKED
        assert decision.reasons
        assert "envelope_missing" in decision.reasons[0].code

    def test_valid_signed_envelope_allows_mutation(self) -> None:
        priv, _ = _generate_keypair_test_keys()
        payload = {"path": "test.py", "content": "print('hello')"}
        env = _build_signed_envelope("write_file", payload, private_key_bytes=priv)
        decision = require_signed_envelope(
            action="write_file",
            payload=payload,
            required_capability="tool:WriteFileTool",
            envelope=env,
            public_key_provider=_public_key_provider,
        )
        assert decision.decision == GovernanceDecisionKind.ALLOWED

    def test_invalid_signature_blocks_mutation(self) -> None:
        priv1, _ = _generate_keypair()
        priv2, _ = _generate_keypair()
        payload = {"path": "test.py"}
        env = _build_signed_envelope(
            "write_file", payload, private_key_bytes=priv1, public_key_id="other_key"
        )
        decision = require_signed_envelope(
            action="write_file",
            payload=payload,
            required_capability="tool:WriteFileTool",
            envelope=env,
            public_key_provider=_public_key_provider,
        )
        assert decision.decision == GovernanceDecisionKind.BLOCKED
        assert decision.reasons
        assert "envelope_signature_invalid" in decision.reasons[0].code

    def test_expired_envelope_blocks_mutation(self) -> None:
        priv, _ = _generate_keypair_test_keys()
        payload = {"path": "test.py"}
        past = datetime.now(UTC) - timedelta(seconds=10)
        env = _build_signed_envelope(
            "write_file", payload, private_key_bytes=priv, expires_at=past
        )
        decision = require_signed_envelope(
            action="write_file",
            payload=payload,
            required_capability="tool:WriteFileTool",
            envelope=env,
            public_key_provider=_public_key_provider,
        )
        assert decision.decision == GovernanceDecisionKind.BLOCKED
        assert decision.reasons
        assert "envelope_shape_invalid" in decision.reasons[0].code
        assert "Envelope expired" in decision.reasons[0].message


class TestRequireSignedEnvelopeNonMutation:
    def test_read_only_tool_passes_without_envelope(self) -> None:
        decision = require_signed_envelope(
            action="read_file",
            payload={"path": "test.py"},
            required_capability="tool:ReadFileTool",
            envelope=None,
        )
        assert decision.decision == GovernanceDecisionKind.ALLOWED

    def test_provider_status_passes_without_envelope(self) -> None:
        decision = require_signed_envelope(
            action="provider_status",
            payload={},
            required_capability="provider_status",
            envelope=None,
        )
        assert decision.decision == GovernanceDecisionKind.ALLOWED

    def test_validation_suite_passes_without_envelope(self) -> None:
        decision = require_signed_envelope(
            action="run_validation_suite",
            payload={},
            required_capability="run_validation_suite",
            envelope=None,
        )
        assert decision.decision == GovernanceDecisionKind.ALLOWED


class TestRequireSignedEnvelopeEdgeCases:
    def test_no_key_provider_blocks_mutation(self) -> None:
        priv, _ = _generate_keypair_test_keys()
        payload = {"path": "test.py"}
        env = _build_signed_envelope("write_file", payload, private_key_bytes=priv)
        decision = require_signed_envelope(
            action="write_file",
            payload=payload,
            required_capability="tool:WriteFileTool",
            envelope=env,
            public_key_provider=None,
        )
        assert decision.decision == GovernanceDecisionKind.BLOCKED
        assert decision.reasons
        assert "envelope_no_key_provider" in decision.reasons[0].code

    def test_bash_tool_requires_envelope(self) -> None:
        decision = require_signed_envelope(
            action="bash",
            payload={"command": "echo hello"},
            required_capability="tool:BashTool",
            envelope=None,
        )
        assert decision.decision == GovernanceDecisionKind.BLOCKED

    def test_checkpoint_commit_requires_envelope(self) -> None:
        decision = require_signed_envelope(
            action="checkpoint.commit",
            payload={"message": "test"},
            required_capability="checkpoint.commit",
            envelope=None,
        )
        assert decision.decision == GovernanceDecisionKind.BLOCKED


class TestContentSafety:
    def test_gate_decision_no_raw_payload(self) -> None:
        payload = {"secret": "should-not-appear", "token": "abc123"}
        decision = require_signed_envelope(
            action="write_file",
            payload=payload,
            required_capability="tool:WriteFileTool",
            envelope=None,
        )
        serialized = decision.model_dump_json()
        assert "should-not-appear" not in serialized
        assert "abc123" not in serialized
        assert "secret" not in serialized
        assert "token" not in serialized

    def test_envelope_signature_is_base64_not_raw(self) -> None:
        priv, _ = _generate_keypair_test_keys()
        payload = {"path": "test.py"}
        env = _build_signed_envelope("write_file", payload, private_key_bytes=priv)
        sig = env.get("signature", "")
        assert sig
        try:
            base64.b64decode(sig)
        except Exception:
            pytest.fail("signature is not valid base64")
