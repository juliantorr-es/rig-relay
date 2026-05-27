"""Standalone digest helpers for repository estate evidence.

Content-light: only SHA256 hex digests. No raw file contents, paths, or secrets
are ever emitted.
"""

from __future__ import annotations

import hashlib
from pathlib import Path


def digest_text(text: str) -> str:
    """SHA256 hex digest of a UTF-8 string."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def digest_path(path: Path) -> str:
    """SHA256 hex digest of a resolved absolute path string."""
    return digest_text(str(path.resolve()))


def digest_bytes(data: bytes) -> str:
    """SHA256 hex digest of raw bytes."""
    return hashlib.sha256(data).hexdigest()


def sha256_prefix(data: str) -> str:
    """Canonical sha256: prefix format used across the evidence layer."""
    return f"sha256:{data}"


def digest_canonical_json(obj: dict | list) -> str:
    """SHA256 hex digest of a canonical JSON serialization.

    Uses sort_keys=True, compact separators for deterministic output.
    """
    from rig_relay.coordination._canonical_json import dump_canonical_json

    return digest_text(dump_canonical_json(obj))
