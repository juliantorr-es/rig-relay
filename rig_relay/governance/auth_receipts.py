# ruff: noqa: PLR0911
"""Rig Relay Authorization Receipts — Governance Seam.

Owned by ``rig_relay.governance``. Legacy adapter at ``vibe.core.auth.receipt``.

Usage:
    from rig_relay.governance.auth_receipts import validate_receipt, generate_dev_receipt
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import hashlib
import json
import secrets
from typing import Any


@dataclass
class AuthorizationResult:
    authorized: bool
    receipt: dict[str, Any] | None = None
    reason: str | None = None


DEFAULT_POLICY: dict[str, Any] = {
    "schema_version": "rig.relay.authorization_policy.v1",
    "protected_actions": [
        "remote_upload.confirm",
        "telemetry.share_level.change",
        "checkpoint.commit",
        "spawn.execute",
        "fleet.execute",
        "lease_cleanup.archive",
        "lease_cleanup.remove",
        "credentials.configure",
        "update.restart_now",
        "review_projection.disclose.authorize",
    ],
    "action_methods": {
        "remote_upload.confirm": [
            "none_dev_only",
            "local_system_auth",
            "passkey_webauthn",
        ],
        "telemetry.share_level.change": ["none_dev_only", "local_system_auth"],
        "checkpoint.commit": ["none_dev_only", "local_system_auth"],
        "spawn.execute": ["none_dev_only", "local_system_auth"],
        "fleet.execute": ["none_dev_only", "local_system_auth"],
        "lease_cleanup.archive": ["none_dev_only", "local_system_auth"],
        "lease_cleanup.remove": ["none_dev_only", "local_system_auth"],
        "credentials.configure": ["none_dev_only", "local_system_auth"],
        "update.restart_now": ["none_dev_only", "local_system_auth"],
        "review_projection.disclose.authorize": ["none_dev_only", "local_system_auth"],
    },
    "receipt_ttl_seconds": 300,
    "default_method": "local_system_auth",
    "allow_dev_bypass": True,
    "warnings": [],
}

READ_ONLY_ACTIONS = frozenset({
    "current_state.view",
    "dataset_report.read",
    "cockpit.read",
    "dry_run.upload",
    "dry_run.spawn_plan",
    "dry_run.lease_cleanup",
    "schema.validate",
    "search.read",
})


def _sha256_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _generate_id() -> str:
    return "authz_" + secrets.token_hex(16)


def action_requires_authorization(
    action: str, policy: dict[str, Any] | None = None
) -> bool:
    """Check whether an action requires step-up authorization."""
    if policy is None:
        policy = DEFAULT_POLICY
    return action in policy.get("protected_actions", [])


def is_read_only_action(action: str) -> bool:
    """Check whether an action is read-only and does not require step-up."""
    return action in READ_ONLY_ACTIONS


def validate_receipt(
    receipt: dict[str, Any],
    action: str,
    action_scope: dict[str, Any] | None = None,
    policy: dict[str, Any] | None = None,
) -> tuple[bool, str]:
    """Validate an authorization receipt against an action and optional scope.

    Args:
        receipt: Authorization receipt dict.
        action: Action to validate against.
        action_scope: Optional scope dict with target_sha256.
        policy: Authorization policy dict. Uses defaults if None.

    Returns:
        Tuple of (valid: bool, reason: str).
    """
    if policy is None:
        policy = DEFAULT_POLICY

    if receipt.get("schema_version") != "rig.relay.step_up_authorization_receipt.v1":
        return False, "Invalid schema version"

    receipt_action = receipt.get("action")
    if receipt_action != action:
        return (
            False,
            f"Action mismatch: receipt for '{receipt_action}', expected '{action}'",
        )

    if receipt.get("user_verified") is not True:
        return False, "User not verified"

    expires_at_str = receipt.get("expires_at", "")
    if not expires_at_str:
        return False, "Missing expires_at"

    try:
        expires_dt = datetime.fromisoformat(expires_at_str.replace("Z", "+00:00"))
        if expires_dt < datetime.now(UTC):
            return False, "Receipt expired"
    except (ValueError, TypeError):
        return False, "Invalid expires_at format"

    if action_scope and action_scope.get("target_sha256"):
        receipt_scope = receipt.get("action_scope") or {}
        if receipt_scope.get("target_sha256") != action_scope["target_sha256"]:
            return False, "Action scope target_sha256 mismatch"

    method = receipt.get("method", "")
    allowed = policy.get("action_methods", {}).get(
        action, [policy.get("default_method", "local_system_auth")]
    )

    if method not in allowed:
        return False, f"Method '{method}' not allowed for action '{action}'"

    # ── Mission-issued receipt: verify provenance fields ──────────
    if receipt.get("authorization_source") == "mission_execution_authority":
        mission_id = receipt.get("mission_identity")
        provenance = receipt.get("authority_provenance_sha256")
        claim_id = receipt.get("claim_id")
        if not mission_id:
            return False, "Mission-issued receipt missing mission_identity"
        if not provenance or not provenance.startswith("sha256:"):
            return (
                False,
                "Mission-issued receipt missing valid authority_provenance_sha256",
            )
        if not claim_id:
            return False, "Mission-issued receipt missing claim_id"
        receipt_action_scope = receipt.get("action_scope") or {}
        if not receipt_action_scope.get("branch") and not receipt_action_scope.get(
            "include_paths"
        ):
            return False, "Mission-issued receipt missing action_scope binding"

    return True, "Receipt valid"


def generate_dev_receipt(
    action: str, action_scope: dict[str, Any] | None = None, ttl_seconds: int = 300
) -> dict[str, Any]:
    """Generate a developer/test authorization receipt (none_dev_only method).

    Args:
        action: Action to authorize.
        action_scope: Optional scope dict.
        ttl_seconds: Receipt TTL in seconds.

    Returns:
        Authorization receipt dict.
    """
    now = datetime.now(UTC)
    expires = now + timedelta(seconds=ttl_seconds)
    authz_id = _generate_id()
    challenge = secrets.token_bytes(32)
    challenge_hash = _sha256_bytes(challenge)

    receipt = {
        "schema_version": "rig.relay.step_up_authorization_receipt.v1",
        "authorization_id": authz_id,
        "created_at": now.isoformat(),
        "action": action,
        "action_scope": action_scope or {},
        "method": "none_dev_only",
        "user_verified": True,
        "expires_at": expires.isoformat(),
        "challenge_sha256": challenge_hash,
        "credential_id_hash": None,
        "receipt_sha256": "sha256:0000000000000000000000000000000000000000000000000000000000000000",
        "warnings": ["Dev receipt — no real user verification performed"],
    }

    receipt_data = json.dumps(receipt, sort_keys=True).encode("utf-8")
    receipt["receipt_sha256"] = _sha256_bytes(receipt_data)
    return receipt


def generate_mission_checkpoint_receipt(
    *,
    mission_id: str | None = None,
    authority_provenance_sha256: str | None = None,
    claim_id: str | None = None,
    session_id: str = "",
    task_id: str = "",
    branch: str = "",
    include_paths: list[str] | None = None,
    ttl_seconds: int = 300,
) -> dict[str, Any]:
    """Generate a checkpoint authorization receipt issued under mission authority.

    This receipt carries authorization_source="mission_execution_authority"
    and records the canonical claim provenance. It satisfies the same
    receipt validation as a human-issued receipt, but requires no step-up
    approval because the mission authority already admitted the checkpoint.
    """
    now = datetime.now(UTC)
    expires = now + timedelta(seconds=ttl_seconds)
    authz_id = _generate_id()
    challenge = secrets.token_bytes(32)
    challenge_hash = _sha256_bytes(challenge)

    action_scope: dict[str, Any] = {}
    if include_paths:
        action_scope["include_paths"] = include_paths
    if branch:
        action_scope["branch"] = branch
    if session_id:
        action_scope["session_id"] = session_id
    if task_id:
        action_scope["task_id"] = task_id

    receipt: dict[str, Any] = {
        "schema_version": "rig.relay.step_up_authorization_receipt.v1",
        "authorization_id": authz_id,
        "created_at": now.isoformat(),
        "action": "checkpoint.commit",
        "action_scope": action_scope,
        "method": "none_dev_only",
        # user_verified=True is a transitive truth: the mission authority was
        # admitted by a verified user decision. Per-checkpoint user interaction
        # did not occur. The `authorization_source` field distinguishes
        # mission_execution_authority from human_consequential_approval.
        "user_verified": True,
        "user_verified_kind": "transitive_mission_authority",
        "expires_at": expires.isoformat(),
        "challenge_sha256": challenge_hash,
        "credential_id_hash": None,
        "authorization_source": "mission_execution_authority",
        "mission_identity": mission_id,
        "authority_provenance_sha256": authority_provenance_sha256,
        "claim_id": claim_id,
        "receipt_sha256": "",
        "warnings": [],
    }

    receipt_data = json.dumps(receipt, sort_keys=True).encode("utf-8")
    receipt["receipt_sha256"] = _sha256_bytes(receipt_data)
    return receipt


def resolve_authorization(
    action: str,
    receipt_json: str | None = None,
    action_scope: dict[str, Any] | None = None,
    policy: dict[str, Any] | None = None,
) -> AuthorizationResult:
    if policy is None:
        policy = DEFAULT_POLICY

    if receipt_json:
        try:
            receipt = json.loads(receipt_json)
        except json.JSONDecodeError:
            return AuthorizationResult(authorized=False, reason="Invalid receipt JSON")
        valid, reason = validate_receipt(receipt, action, action_scope, policy)
        if not valid:
            return AuthorizationResult(authorized=False, reason=reason)
        return AuthorizationResult(authorized=True, receipt=receipt)

    return AuthorizationResult(authorized=False, reason="missing_receipt")


def mint_dev_receipt(
    action: str, action_scope: dict[str, Any] | None = None, ttl_seconds: int = 300
) -> dict[str, Any] | None:
    return generate_dev_receipt(action, action_scope, ttl_seconds)


__all__ = [
    "DEFAULT_POLICY",
    "READ_ONLY_ACTIONS",
    "AuthorizationResult",
    "action_requires_authorization",
    "generate_dev_receipt",
    "generate_mission_checkpoint_receipt",
    "is_read_only_action",
    "mint_dev_receipt",
    "resolve_authorization",
    "validate_receipt",
]
