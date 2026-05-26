"""Deterministic canonicalization and integrity digests for A2A evidence.

All durable A2A evidence must be canonically serializable for
integrity verification. This module provides canonical JSON helpers
and SHA256 digest computation matching the rest of Rig Relay's
evidence pattern.
"""

from __future__ import annotations

import hashlib
import json


def dump_canonical_json(obj: object) -> bytes:
    """Serialize an object to deterministic canonical JSON bytes.

    Keys are sorted, no trailing whitespace, UTF-8 encoding.
    Compatible with the existing coordination _canonical_json pattern.
    """
    return json.dumps(
        obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def compute_digest(obj: object) -> str:
    """Compute SHA256 hex digest of a canonically serialized object."""
    return hashlib.sha256(dump_canonical_json(obj)).hexdigest()


def compute_agent_card_digest(card_dict: dict[str, object]) -> str:
    """Compute integrity digest for an agent card dict."""
    stable = {k: card_dict[k] for k in sorted(card_dict) if k not in {"generated_at"}}
    return compute_digest(stable)


def compute_task_card_digest(card_dict: dict[str, object]) -> str:
    """Compute integrity digest for a task card dict.

    Excludes generation timestamp to produce stable digests
    for the same logical task state.
    """
    stable = {
        k: card_dict[k]
        for k in sorted(card_dict)
        if k not in {"generated_at", "updated_at"}
    }
    return compute_digest(stable)


def compute_governance_binding_digest(binding_dict: dict[str, object]) -> str:
    """Compute integrity digest for a governance binding dict."""
    return compute_digest(binding_dict)


def verify_digest(obj: object, expected_digest: str) -> bool:
    """Verify an object's canonical digest matches an expected value."""
    return compute_digest(obj) == expected_digest


def content_integrity_chain(*digests: str) -> str:
    """Build a content-integrity chain hash from ordered digests.

    Useful for linking multiple evidence artifacts.
    """
    chain_input = "|".join(digests).encode("utf-8")
    return hashlib.sha256(chain_input).hexdigest()


__all__ = [
    "compute_agent_card_digest",
    "compute_digest",
    "compute_governance_binding_digest",
    "compute_task_card_digest",
    "content_integrity_chain",
    "dump_canonical_json",
    "verify_digest",
]
