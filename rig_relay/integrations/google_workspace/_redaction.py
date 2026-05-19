"""Google Workspace redaction helpers — credential detection, content-light assertions."""

from __future__ import annotations

import re

_SECRET_PATTERNS: list[re.Pattern] = [
    re.compile(r"ya29\.[a-zA-Z0-9\-_]+"),
    re.compile(r"1//[a-zA-Z0-9\-_]+"),
    re.compile(r"-----BEGIN PRIVATE KEY-----"),
    re.compile(r"-----BEGIN RSA PRIVATE KEY-----"),
    re.compile(r"eyJ[A-Za-z0-9\-_]+\.(?:[A-Za-z0-9\-_]+)?\.[A-Za-z0-9\-_]+"),
    re.compile(r"[A-Za-z0-9+/]{100,}={0,2}"),
]

_FORBIDDEN_OUTPUT_FIELDS = frozenset({
    "raw_token",
    "access_token",
    "refresh_token",
    "client_secret",
    "private_key",
    "raw_email",
    "raw_domain",
    "raw_gmail_subject",
    "raw_gmail_body",
    "raw_drive_filename",
    "raw_drive_content",
    "raw_calendar_title",
    "raw_calendar_description",
    "raw_docs_text",
    "raw_sheets_cells",
    "raw_admin_user_email",
    "raw_chat_space_name",
    "raw_contacts",
    "raw_prompt",
    "raw_credential",
})


def assert_no_raw_secret_patterns(text: str) -> None:
    for pat in _SECRET_PATTERNS:
        if pat.search(text):
            raise ValueError("raw_secret_pattern_detected")


def assert_no_workspace_content_fields(data: dict[str, object]) -> None:
    for key in _FORBIDDEN_OUTPUT_FIELDS:
        if key in data:
            raise ValueError(f"raw_workspace_content_rejected: field '{key}'")
