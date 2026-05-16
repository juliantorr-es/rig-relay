"""Trace attribute redaction — sanitize before writing to JSONL.

Rules:
- Keys containing token/api_key/password/secret/credential/authorization/cookie/bearer are redacted.
- token_present and token_length may be logged.
- token value must never be logged.
- Long strings are truncated.
- Nested dicts/lists sanitized recursively.
- Bytes converted to safe summary.
"""

from __future__ import annotations

from typing import Any

REDACT_KEYS = frozenset({
    "token",
    "auth_token",
    "api_key",
    "apikey",
    "password",
    "passwd",
    "secret",
    "credential",
    "credentials",
    "authorization",
    "auth",
    "cookie",
    "bearer",
})

SAFE_TOKEN_ADJACENT = frozenset({
    "token_present",
    "token_length",
    "token_value_included",
    "contains_secret",
    "secret_fields_redacted",
})

MAX_STRING_LENGTH = 1000
MAX_BYTES_LENGTH = 128
MAX_SANITIZE_DEPTH = 20


def sanitize_trace_attributes(  # noqa: PLR0911
    obj: Any, _depth: int = 0
) -> Any:
    if _depth > MAX_SANITIZE_DEPTH:
        return "<max depth exceeded>"

    if obj is None:
        return None

    if isinstance(obj, bool):
        return obj

    if isinstance(obj, (int, float)):
        return obj

    if isinstance(obj, str):
        if len(obj) > MAX_STRING_LENGTH:
            return obj[:MAX_STRING_LENGTH] + f"…<truncated {len(obj)} chars>"
        return obj

    if isinstance(obj, bytes):
        summary = f"<bytes len={len(obj)}>"
        if len(obj) <= MAX_BYTES_LENGTH:
            summary += " " + repr(obj[:MAX_BYTES_LENGTH])[:MAX_BYTES_LENGTH]
        return summary

    if isinstance(obj, dict):
        return {
            k: (
                "<redacted>"
                if _is_redacted_key(str(k))
                else sanitize_trace_attributes(v, _depth + 1)
            )
            for k, v in obj.items()
        }

    if isinstance(obj, (list, tuple)):
        return [sanitize_trace_attributes(v, _depth + 1) for v in obj]

    try:
        return str(obj)[:MAX_STRING_LENGTH]
    except Exception:
        return "<unserializable>"


def _is_redacted_key(key: str) -> bool:
    lower = key.lower()
    if lower in SAFE_TOKEN_ADJACENT:
        return False
    for rk in REDACT_KEYS:
        if rk in lower:
            return True
    return False


__all__ = ["sanitize_trace_attributes"]
