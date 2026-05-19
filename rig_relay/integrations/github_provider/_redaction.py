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

_JWT_PATTERN = re.compile(r"eyJ[A-Za-z0-9\-_]+\.(?:[A-Za-z0-9\-_]+)?\.[A-Za-z0-9\-_]+")
_PEM_KEY_PATTERN = re.compile(r"-----BEGIN (?:RSA |EC |DSA )?PRIVATE KEY-----")
_OAUTH_CLIENT_SECRET_PATTERN = re.compile(r"[A-Za-z0-9+/]{80,}={0,2}")


def hash_identifier(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def hash_private_field(data: dict, field: str) -> dict:
    result = dict(data)
    if field in result and isinstance(result[field], str):
        result[field] = "sha256:" + hash_identifier(result[field])
    return result


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


def assert_response_content_light(
    response_data: dict, forbidden_fields: list[str]
) -> None:
    for field in forbidden_fields:
        if field in response_data:
            raise ValueError(f"forbidden_response_field_detected: field '{field}'")


def scan_for_tokens(text: str) -> list[str]:
    found: list[str] = []
    for pattern in _GITHUB_TOKEN_PATTERNS:
        if pattern.search(text):
            found.append("github_token_pattern")
    return found


def scan_response_for_secrets(text: str) -> list[str]:
    found: list[str] = []
    for pattern in _GITHUB_TOKEN_PATTERNS:
        if pattern.search(text):
            found.append("github_token_pattern")
    if _JWT_PATTERN.search(text):
        found.append("jwt_pattern")
    if _PEM_KEY_PATTERN.search(text):
        found.append("pem_private_key_pattern")
    if _OAUTH_CLIENT_SECRET_PATTERN.search(text):
        found.append("oauth_client_secret_pattern")
    return found


_REDACTION_RULES: dict[str, list[str]] = {
    "github.repo.metadata.read": ["full_name", "owner.login", "owner.email", "owner"],
    "github.repo.commits.read": [
        "message",
        "commit.message",
        "author.email",
        "commit.author.email",
        "committer.email",
    ],
    "github.repo.issues.read": ["body", "user.email", "user.login"],
    "github.repo.pull_requests.read": [
        "body",
        "user.email",
        "user.login",
        "head.label",
        "base.label",
    ],
    "github.actions.runs.read": ["logs_url", "html_url", "url"],
}


def redact_github_response(response_data: dict, capability_id: str) -> dict:
    fields = _REDACTION_RULES.get(capability_id)
    if not fields:
        return response_data
    result = dict(response_data)
    for field in fields:
        if "." in field:
            parts = field.split(".")
            container = result
            for part in parts[:-1]:
                if isinstance(container, dict) and part in container:
                    nested = container[part]
                    if isinstance(nested, dict):
                        container = nested
                    else:
                        break
                else:
                    container = None
                    break
            if container is not None and isinstance(container, dict):
                leaf = parts[-1]
                if leaf in container and isinstance(container[leaf], str):
                    container[leaf] = "sha256:" + hash_identifier(container[leaf])
        else:
            result = hash_private_field(result, field)
    return result
