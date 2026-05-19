"""GitHub provider redaction helpers — token detection, content-light assertions."""

from __future__ import annotations

import hashlib
import re

_GITHUB_TOKEN_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"ghp_[a-zA-Z0-9]{20,}"),
    re.compile(r"gho_[a-zA-Z0-9]{20,}"),
    re.compile(r"ghu_[a-zA-Z0-9]{20,}"),
    re.compile(r"ghs_[a-zA-Z0-9]{20,}"),
    re.compile(r"ghr_[a-zA-Z0-9]{20,}"),
    re.compile(r"github_pat_[a-zA-Z0-9]{20,}"),
]

_FORBIDDEN_RECEIPT_FIELDS = frozenset({
    "raw_token",
    "raw_repository_content",
    "raw_private_file_content",
    "raw_prompt",
    "raw_credential",
    "raw_absolute_path",
    "oauth_code",
    "client_secret",
})


def hash_identifier(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def assert_no_raw_github_token(value: str) -> None:
    for pattern in _GITHUB_TOKEN_PATTERNS:
        if pattern.search(value):
            raise ValueError(
                "raw_github_token_detected: value contains a GitHub token-like string"
            )


def assert_content_light_mapping(mapping: dict[str, object]) -> None:
    for key in _FORBIDDEN_RECEIPT_FIELDS:
        if key in mapping:
            raise ValueError(
                f"raw_content_field_detected: receipt contains forbidden field '{key}'"
            )


def scan_for_tokens(text: str) -> list[str]:
    found: list[str] = []
    for pattern in _GITHUB_TOKEN_PATTERNS:
        if pattern.search(text):
            found.append("github_token_pattern")
    return found
