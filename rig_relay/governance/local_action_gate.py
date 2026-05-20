"""Rig Relay Local Action Gate — signed envelope enforcement point.

Wires the Ed25519-signed local action envelope model into mutation
command paths. Every mutation tool execution and protected intent
must present a valid signed envelope before the action is allowed.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from rig_relay.governance.decisions import (
    DecisionReason,
    GateDecision,
    GovernanceDecisionKind,
    GovernanceReasonSeverity,
)
from rig_relay.governance.local_action_envelope import verify_envelope_shape

MUTATION_CAPABILITIES_REQUIRING_ENVELOPE: frozenset[str] = frozenset({
    "tool:BashTool",
    "tool:WriteFileTool",
    "tool:SearchReplaceTool",
    "tool:CheckpointTool",
    "tool:CoordinationTool",
    "tool:BehaviorPatchTool",
    "tool:TaskTool",
    "checkpoint.commit",
    "lease_cleanup.archive",
    "write_file",
    "search_replace",
    "bash",
    "shell",
})


def _is_mutation_capability(capability: str) -> bool:
    return capability in MUTATION_CAPABILITIES_REQUIRING_ENVELOPE


def _make_gate_decision(
    *, allowed: bool, gate: str, reason_code: str = "", reason_message: str = ""
) -> GateDecision:
    decision_kind = (
        GovernanceDecisionKind.ALLOWED if allowed else GovernanceDecisionKind.BLOCKED
    )
    reasons: list[DecisionReason] = []
    if reason_code:
        reasons.append(
            DecisionReason(
                code=reason_code,
                message=reason_message or reason_code,
                severity=GovernanceReasonSeverity.ERROR,
            )
        )
    return GateDecision(
        schema_version="rig.relay.governance_decision.v1",
        gate=gate,
        decision=decision_kind,
        reasons=reasons,
    )


def _verify_envelope_crypto(
    envelope: dict[str, Any], public_key_provider: Callable[[str], bytes | None]
) -> tuple[bool, str]:
    from rig_relay.governance.local_action_envelope import verify_envelope_signature

    signer_key_id = str(envelope.get("signer_key_id", ""))
    public_key_id = envelope.get("public_key_id")
    lookup_id = str(public_key_id) if public_key_id else signer_key_id

    if not lookup_id:
        return False, "envelope has neither signer_key_id nor public_key_id"

    public_key_bytes = public_key_provider(lookup_id)
    if public_key_bytes is None:
        return False, f"no public key found for {lookup_id}"

    try:
        valid = verify_envelope_signature(envelope, public_key_bytes)
    except ImportError:
        return False, "cryptography library not available for signature verification"
    except Exception as exc:
        return False, f"signature verification error: {exc}"

    if not valid:
        return False, "signature verification failed"

    return True, ""


def require_signed_envelope(
    *,
    action: str,
    payload: dict[str, Any] | None = None,
    required_capability: str,
    envelope: dict[str, Any] | None = None,
    public_key_provider: Callable[[str], bytes | None] | None = None,
) -> GateDecision:
    """Enforce signed envelope requirement for mutation capabilities.

    For non-mutation capabilities, the gate passes immediately.
    For mutation capabilities, a valid signed envelope with a
    verified signature and non-expired replay window is required.

    Args:
        action: Name of the action being performed.
        payload: The action payload dict (used for shape hash validation).
        required_capability: The capability being checked (e.g. ``"tool:WriteFileTool"``).
        envelope: The signed envelope dict, or None if no envelope is provided.
        public_key_provider: Callable mapping signer_key_id → public_key_bytes,
            or None to use a no-op provider (always fails for mutations).

    Returns:
        GateDecision with ALLOWED or BLOCKED.
    """
    gate_name = "rig_relay.gate.local_action_envelope"

    if not _is_mutation_capability(required_capability):
        return _make_gate_decision(allowed=True, gate=gate_name)

    if envelope is None:
        return _make_gate_decision(
            allowed=False,
            gate=gate_name,
            reason_code="envelope_missing",
            reason_message=(
                f"mutation capability '{required_capability}' "
                f"requires a signed local action envelope, but none was provided"
            ),
        )

    shape_ok, shape_reason = verify_envelope_shape(envelope)
    if not shape_ok:
        return _make_gate_decision(
            allowed=False,
            gate=gate_name,
            reason_code="envelope_shape_invalid",
            reason_message=(
                f"envelope shape invalid for '{required_capability}': {shape_reason}"
            ),
        )

    if public_key_provider is None:
        return _make_gate_decision(
            allowed=False,
            gate=gate_name,
            reason_code="envelope_no_key_provider",
            reason_message="no public_key_provider configured for envelope verification",
        )

    sig_ok, sig_reason = _verify_envelope_crypto(envelope, public_key_provider)
    if not sig_ok:
        return _make_gate_decision(
            allowed=False,
            gate=gate_name,
            reason_code="envelope_signature_invalid",
            reason_message=(
                f"signature verification failed for '{required_capability}': "
                f"{sig_reason}"
            ),
        )

    return _make_gate_decision(allowed=True, gate=gate_name)
