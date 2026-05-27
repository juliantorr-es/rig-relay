"""Secret-bearing content scanner for local runtime context.

Scans submitted messages for credential/token patterns before admission.
Overrides caller-provided ContextPrivacyClass when secrets are detected
in content labeled PRIVATE_LOCAL or PUBLIC_SAFE.

Never records the raw secret — only a content-light scan result.
"""

from __future__ import annotations

import re

_SECRET_PATTERNS: list[tuple[str, str]] = [
    (r"sk-[a-zA-Z0-9]{32,}", "openai_api_key"),
    (r"sk-ant-[a-zA-Z0-9]{32,}", "anthropic_api_key"),
    (r"AIza[0-9A-Za-z\-_]{35}", "google_api_key"),
    (r"ghp_[a-zA-Z0-9]{36}", "github_personal_token"),
    (r"gho_[a-zA-Z0-9]{36}", "github_oauth_token"),
    (r"ghu_[a-zA-Z0-9]{36}", "github_user_token"),
    (r"ghs_[a-zA-Z0-9]{36}", "github_server_token"),
    (r"ghr_[a-zA-Z0-9]{36}", "github_refresh_token"),
    (r"xox[bpras]-[a-zA-Z0-9-]{10,}", "slack_token"),
    (r"hf_[a-zA-Z0-9]{34}", "huggingface_token"),
    (r"AKIA[0-9A-Z]{16}", "aws_access_key"),
    (r"[\w\-]{24}\.[\w\-]{6}\.[\w\-]{27}", "jwt_token"),
    (r"Bearer\s+[A-Za-z0-9\-._~+/]+=*", "auth_header_bearer"),
    (r"eyJ[a-zA-Z0-9\-_]{20,}\.[a-zA-Z0-9\-_]{20,}\.[a-zA-Z0-9\-_]{20,}", "jwt_body"),
    (r"[\w\.\-]+@[\w\-]+\.\w+\s*:\s*\S{8,}", "email_password_pair"),
    (r'api[_-]?key\s*[=:]\s*["\']?\S{16,}', "api_key_assignment"),
    (r'access[_-]?token\s*[=:]\s*["\']?\S{16,}', "access_token_assignment"),
    (r'client[_-]?secret\s*[=:]\s*["\']?\S{16,}', "client_secret_assignment"),
    (r"private[_-]?key\s*[-:]\s*BEGIN", "private_key_pem"),
    (r'connect[_-]?sid\s*[=:]\s*["\']?\S{16,}', "connect_sid"),
]

_PRIVATE_KEY_TAGS: list[str] = [
    "PRIVATE KEY",
    "RSA PRIVATE",
    "DSA PRIVATE",
    "EC PRIVATE",
    "OPENSSH PRIVATE",
]


def scan_messages_for_secrets(messages: list[dict]) -> dict:
    """Scan messages for credential/secret patterns.

    Returns a content-light dict:
      { "secrets_detected": bool, "patterns_matched": [...],
        "secrets_detected_count": int, "content_light": true }

    Never returns the matched secret text — only pattern labels.
    """
    matches: list[str] = []
    total_finds = 0

    for msg in messages:
        content = _extract_content(msg)
        if not content:
            continue

        for pattern, label in _SECRET_PATTERNS:
            found = re.findall(pattern, content, re.IGNORECASE)
            if found:
                matches.append(label)
                total_finds += len(found)

        for tag in _PRIVATE_KEY_TAGS:
            if tag in content:
                matches.append("private_key_body")
                total_finds += 1

    unique = sorted(set(matches))
    return {
        "secrets_detected": len(unique) > 0,
        "patterns_matched": unique,
        "secrets_detected_count": total_finds,
        "content_light": True,
    }


def _extract_content(msg: dict) -> str:
    content = msg.get("content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                parts.append(str(item.get("text", item.get("content", ""))))
            elif isinstance(item, str):
                parts.append(item)
        return " ".join(parts)
    return str(content) if content else ""
