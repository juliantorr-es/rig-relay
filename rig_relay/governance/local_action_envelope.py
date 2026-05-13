"""Rig Relay Local Action Envelope — Schema and Model.

A signed local action envelope for protected intent requests and
local-to-remote authority mutations. This slice defines the model,
canonicalization, and verification helpers. Cryptographic signing
(full Ed25519 sign/verify) is available via the optional ``cryptography``
dependency (core runtime dep) but is not wired into protected execution yet.

Model fields mirror docs/schemas/rig.relay.local_action_envelope.v1.schema.json.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
import json
import secrets
from typing import Any

# ── Replay Policy Constants ─────────────────────────────────────────────

DEFAULT_REPLAY_WINDOW_SECONDS = 300
"""Default replay window: 5 minutes."""

MAX_REPLAY_WINDOW_SECONDS = 3600
"""Maximum allowed replay window: 1 hour."""

SUPPORTED_SIGNATURE_ALGORITHMS = frozenset({"ed25519"})
"""Signature algorithms accepted by the model."""


# ── Internal helpers ───────────────────────────────────────────────────


def _sha256_bytes(data: bytes) -> str:
    """Return sha256:<hex> of the given bytes."""
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _generate_id(prefix: str = "env_") -> str:
    """Generate a unique identifier with the given prefix."""
    return prefix + secrets.token_hex(16)


def _generate_nonce() -> str:
    """Generate a 32-byte hex nonce."""
    return secrets.token_hex(32)


# ── Canonicalization ───────────────────────────────────────────────────


def canonicalize_payload(payload: dict[str, Any]) -> bytes:
    """Serialize a payload to deterministic JSON bytes.

    Uses ``sort_keys=True`` to ensure key ordering is stable across
    serialization contexts. The output is UTF-8 encoded.

    Args:
        payload: The action payload dict.

    Returns:
        UTF-8 encoded JSON bytes with sorted keys.
    """
    return json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")


def payload_sha256(payload: dict[str, Any]) -> str:
    """Return the sha256:<hex> of the canonicalized payload.

    Args:
        payload: The action payload dict.

    Returns:
        SHA256 digest string (e.g. ``"sha256:abc123..."``).
    """
    return _sha256_bytes(canonicalize_payload(payload))


# ── Envelope build helpers ─────────────────────────────────────────────


def build_unsigned_envelope(
    action_name: str,
    action_payload: dict[str, Any],
    *,
    signer_key_id: str,
    issued_at: datetime | None = None,
    expires_at: datetime | None = None,
    replay_window_seconds: int = DEFAULT_REPLAY_WINDOW_SECONDS,
    authorization_receipt_sha256: str | None = None,
    action_id: str | None = None,
    local_only: bool = True,
) -> dict[str, Any]:
    """Build an unsigned local action envelope dict.

    Args:
        action_name: Name of the action (e.g. ``"checkpoint.commit"``).
        action_payload: Canonical action payload dict.
        signer_key_id: Identifier for the signing key.
        issued_at: Envelope issuance timestamp (defaults to now).
        expires_at: Envelope expiry timestamp (defaults to issued_at +
            replay_window_seconds).
        replay_window_seconds: Seconds until expiry (ignored if expires_at
            is given explicitly).
        authorization_receipt_sha256: Optional SHA256 of an authorization
            receipt authorizing this action.
        action_id: Optional action identifier for idempotency (auto-generated
            if omitted).
        local_only: Whether this envelope is for local-only use.

    Returns:
        Envelope dict with all fields except ``signature`` populated.
        The ``signature`` field is set to an empty string pending signing.

    Raises:
        ValueError: If the replay window exceeds the maximum allowed, or
            if the authorization receipt hash is malformed.
    """
    if replay_window_seconds > MAX_REPLAY_WINDOW_SECONDS:
        raise ValueError(
            f"Replay window {replay_window_seconds}s exceeds maximum "
            f"{MAX_REPLAY_WINDOW_SECONDS}s"
        )

    if (
        authorization_receipt_sha256 is not None
        and not authorization_receipt_sha256.startswith("sha256:")
    ):
        raise ValueError("authorization_receipt_sha256 must start with 'sha256:'")

    now = issued_at or datetime.now(UTC)
    expiry = expires_at or (now + timedelta(seconds=replay_window_seconds))

    can_payload = json.loads(canonicalize_payload(action_payload).decode("utf-8"))
    payload_hash = payload_sha256(action_payload)

    envelope: dict[str, Any] = {
        "schema_version": "rig.relay.local_action_envelope.v1",
        "envelope_id": _generate_id(),
        "action_id": action_id or _generate_id(prefix="act_"),
        "action_name": action_name,
        "action_payload_sha256": payload_hash,
        "canonical_payload": can_payload,
        "nonce": _generate_nonce(),
        "issued_at": now.isoformat(),
        "expires_at": expiry.isoformat(),
        "signer_key_id": signer_key_id,
        "signature_algorithm": "ed25519",
        "signature": "",
        "public_key_id": None,
        "authorization_receipt_sha256": authorization_receipt_sha256,
        "local_only": local_only,
        "replay_window_seconds": replay_window_seconds,
        "warnings": [],
    }

    return envelope


# ── Signing bytes ───────────────────────────────────────────────────────


def envelope_signing_bytes(envelope: dict[str, Any]) -> bytes:
    """Return the canonical bytes to sign or verify for an envelope.

    The signing payload is the deterministic JSON of the envelope with the
    ``signature`` field set to an empty string, sorted by key. This ensures
    the signature field is excluded from the signed payload.

    Args:
        envelope: An envelope dict (signed or unsigned).

    Returns:
        UTF-8 encoded JSON bytes suitable for signing or verification.
    """
    signable = {k: v for k, v in envelope.items() if k != "signature"}
    return json.dumps(signable, sort_keys=True, ensure_ascii=False).encode("utf-8")


# ── Optional cryptography-based signing ─────────────────────────────────


def _has_crypto() -> bool:
    """Check whether the ``cryptography`` package is available."""
    try:
        import cryptography  # noqa: F401

        return True
    except ImportError:
        return False


def _sign_bytes(private_key_bytes: bytes, data: bytes) -> bytes:
    """Sign data bytes with an Ed25519 private key.

    Requires the ``cryptography`` package (core runtime dependency).

    Args:
        private_key_bytes: Raw Ed25519 private key (32 bytes seed or 64 bytes
            expanded key).
        data: Data bytes to sign.

    Returns:
        Raw 64-byte Ed25519 signature.

    Raises:
        ImportError: If the ``cryptography`` package is not available.
    """
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    try:
        private_key = Ed25519PrivateKey.from_private_bytes(private_key_bytes)
    except Exception:
        # Try loading as PKCS8 if raw bytes fail
        from cryptography.hazmat.primitives.serialization import load_der_private_key

        private_key = load_der_private_key(private_key_bytes, password=None)
        if not isinstance(private_key, Ed25519PrivateKey):
            raise TypeError("Key is not an Ed25519 private key")

    return private_key.sign(data)


def sign_envelope(
    envelope: dict[str, Any],
    private_key_bytes: bytes,
    *,
    public_key_id: str | None = None,
) -> dict[str, Any]:
    """Sign an envelope dict in-place and return it.

    Uses the ``cryptography`` package's Ed25519 implementation.

    Args:
        envelope: Unsigned envelope dict (must have empty ``signature`` field).
        private_key_bytes: Raw Ed25519 private key bytes.
        public_key_id: Optional public key identifier to set on the envelope.

    Returns:
        The same envelope dict with ``signature`` and optionally
        ``public_key_id`` populated.

    Raises:
        ImportError: If the ``cryptography`` package is not available.
        ValueError: If the envelope already has a non-empty signature.
    """
    if envelope.get("signature"):
        raise ValueError("Envelope already has a signature")

    data = envelope_signing_bytes(envelope)
    raw_sig = _sign_bytes(private_key_bytes, data)

    import base64

    envelope["signature"] = base64.b64encode(raw_sig).decode("ascii")
    if public_key_id is not None:
        envelope["public_key_id"] = public_key_id

    return envelope


def verify_envelope_signature(
    envelope: dict[str, Any], public_key_bytes: bytes
) -> bool:
    """Verify an envelope's signature against a public key.

    Args:
        envelope: A signed envelope dict with a non-empty ``signature`` field.
        public_key_bytes: Raw Ed25519 public key bytes (32 bytes).

    Returns:
        True if the signature is valid, False otherwise.

    Raises:
        ImportError: If the ``cryptography`` package is not available.
        ValueError: If the envelope has no signature.
    """
    signature_b64 = envelope.get("signature", "")
    if not signature_b64:
        raise ValueError("Envelope has no signature to verify")

    import base64

    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    raw_sig = base64.b64decode(signature_b64)
    data = envelope_signing_bytes(envelope)
    public_key = Ed25519PublicKey.from_public_bytes(public_key_bytes)

    try:
        public_key.verify(raw_sig, data)
        return True
    except Exception:
        return False


# ── Shape validation ────────────────────────────────────────────────────


def verify_envelope_shape(envelope: dict[str, Any]) -> tuple[bool, str]:
    """Verify the structural shape of an envelope without crypto.

    Checks:
    - Required fields present
    - schema_version matches
    - signature_algorithm supported
    - local_only is True (current slice constraint)
    - action_payload_sha256 matches canonical_payload
    - expires_at is in the future (if time can be parsed)
    - authorization_receipt_sha256 format if present
    - replay_window_seconds within bounds

    Args:
        envelope: An envelope dict to validate.

    Returns:
        Tuple of (valid: bool, reason: str).
    """
    issues: list[str] = []

    required_fields = [
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
    ]
    for field in required_fields:
        if field not in envelope:
            issues.append(f"Missing required field: {field}")

    if envelope.get("schema_version") != "rig.relay.local_action_envelope.v1":
        issues.append("Invalid schema_version")

    algo = envelope.get("signature_algorithm", "")
    if algo not in SUPPORTED_SIGNATURE_ALGORITHMS:
        issues.append(f"Unsupported signature algorithm: {algo}")

    if not envelope.get("local_only", False):
        issues.append("local_only must be True in current slice")

    payload = envelope.get("canonical_payload", {})
    expected_hash = payload_sha256(payload)
    actual_hash = envelope.get("action_payload_sha256", "")
    if actual_hash != expected_hash:
        issues.append(
            f"action_payload_sha256 mismatch: expected {expected_hash}, "
            f"got {actual_hash}"
        )

    receipt_hash = envelope.get("authorization_receipt_sha256")
    if receipt_hash is not None:
        if not isinstance(receipt_hash, str) or not receipt_hash.startswith("sha256:"):
            issues.append("authorization_receipt_sha256 must be 'sha256:<hex>'")

    window = envelope.get("replay_window_seconds", 0)
    if not 1 <= window <= MAX_REPLAY_WINDOW_SECONDS:
        issues.append(
            f"replay_window_seconds must be between 1 and {MAX_REPLAY_WINDOW_SECONDS}"
        )

    expires_str = envelope.get("expires_at", "")
    if expires_str:
        try:
            expires_dt = datetime.fromisoformat(expires_str.replace("Z", "+00:00"))
            if expires_dt < datetime.now(UTC):
                issues.append("Envelope expired")
        except (ValueError, TypeError):
            issues.append("Invalid expires_at format")

    if issues:
        return False, issues[0]
    return True, "Envelope shape valid"
