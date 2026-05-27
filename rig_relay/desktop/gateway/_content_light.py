"""Content-light enforcement for gateway projections — Lane S2.

Scans projection payloads before they leave the gateway for forbidden
content patterns: tokens, raw paths, secrets, file contents, or
private identifying data. Runs at projection-build time and at
intent-result time.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

# ── Forbidden content patterns ──────────────────────────────────────

# GitHub personal access tokens and OAuth tokens
_TOKEN_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"ghp_[A-Za-z0-9]{36,}", re.IGNORECASE),
    re.compile(r"github_pat_[A-Za-z0-9_]{22,}", re.IGNORECASE),
    re.compile(r"gho_[A-Za-z0-9]{36,}", re.IGNORECASE),
    re.compile(r"ghu_[A-Za-z0-9]{36,}", re.IGNORECASE),
    re.compile(r"ghs_[A-Za-z0-9]{36,}", re.IGNORECASE),
    re.compile(r"ghr_[A-Za-z0-9]{36,}", re.IGNORECASE),
    re.compile(r"sk-[A-Za-z0-9_-]{32,}", re.IGNORECASE),  # OpenAI / Anthropic
    re.compile(r"AIza[0-9A-Za-z_-]{35}", re.IGNORECASE),  # Google
    re.compile(r"Bearer [A-Za-z0-9._~+/-]+=*", re.IGNORECASE),
]

# Raw absolute filesystem paths that would leak machine identity
_PATH_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"/Users/[^/\s]+"),  # macOS home
    re.compile(r"/home/[^/\s]+"),  # Linux home
    re.compile(r"C:\\Users\\[^\\\s]+"),  # Windows home
]

# Private IP ranges and localhost
_PRIVATE_IP_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"127\.0\.0\.\d+"),
    re.compile(r"10\.\d+\.\d+\.\d+"),
    re.compile(r"172\.(1[6-9]|2\d|3[01])\.\d+\.\d+"),
    re.compile(r"192\.168\.\d+\.\d+"),
    re.compile(r"::1"),
    re.compile(r"localhost"),
]

# Raw file contents (heuristic: long unstructured strings that look like code)
_CONTENT_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"^import [a-z_]+", re.MULTILINE),
    re.compile(r"^from [a-z_.]+ import", re.MULTILINE),
    re.compile(r"^def [a-z_]+\(", re.MULTILINE),
    re.compile(r"^class [A-Z][A-Za-z]*", re.MULTILINE),
]

# Forbidden field names that should not appear in projections
_FORBIDDEN_FIELD_NAMES: frozenset[str] = frozenset({
    "access_token",
    "refresh_token",
    "id_token",
    "api_key",
    "client_secret",
    "private_key",
    "password",
    "secret",
    "token_value",
    "raw_content",
    "raw_output",
    "raw_prompt",
    "raw_response",
    "file_contents",
    "source_code",
    "stdout_body",
    "stderr_body",
    "diff_body",
})

# Maximum allowed string length for any single field value in a projection
_MAX_FIELD_LENGTH = 2000


def _scan_value(value: Any, path: str = "$") -> list[str]:
    """Recursively scan a value for forbidden content patterns.

    Returns a list of violation descriptions (empty if clean).
    """
    violations: list[str] = []

    if isinstance(value, str):
        if len(value) > _MAX_FIELD_LENGTH:
            violations.append(
                f"{path}: string too long ({len(value)} > {_MAX_FIELD_LENGTH})"
            )

        for pat in _TOKEN_PATTERNS:
            if m := pat.search(value):
                prefix = m.group()[:20]
                violations.append(
                    f"{path}: token-like pattern at offset {m.start()} ({prefix}...)"
                )

        for pat in _PATH_PATTERNS:
            if pat.search(value):
                violations.append(f"{path}: raw filesystem path detected")

        for pat in _CONTENT_PATTERNS:
            if pat.search(value):
                violations.append(f"{path}: raw code content detected")

        for pat in _PRIVATE_IP_PATTERNS:
            if pat.search(value):
                violations.append(f"{path}: private IP or localhost detected")

    elif isinstance(value, dict):
        for key, val in value.items():
            if key in _FORBIDDEN_FIELD_NAMES:
                violations.append(f"{path}.{key}: forbidden field name '{key}'")
            if isinstance(val, (dict, list, str)):
                violations.extend(_scan_value(val, f"{path}.{key}"))

    elif isinstance(value, list):
        for i, item in enumerate(value):
            if isinstance(item, (dict, list, str)):
                violations.extend(_scan_value(item, f"{path}[{i}]"))

    return violations


def enforce_content_light(
    payload: dict[str, Any], *, source_label: str = "projection"
) -> list[str]:
    """Scan a projection or intent-result payload for forbidden content.

    Args:
        payload: The dict to scan.
        source_label: Human-readable label for violation messages.

    Returns:
        List of violation strings (empty if the payload is content-light safe).
    """
    return _scan_value(payload, source_label)


def compute_content_safety_hash(payload: dict[str, Any]) -> str:
    """Compute a content-light safety hash for the payload.

    The hash covers the serialized payload so downstream consumers can
    verify that the payload they received is exactly what passed the
    content-light scan.
    """
    import json

    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return f"sha256:{hashlib.sha256(canonical.encode()).hexdigest()}"


__all__ = ["compute_content_safety_hash", "enforce_content_light"]
