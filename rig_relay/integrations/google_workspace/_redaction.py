"""Google Workspace redaction helpers — credential detection, content-light assertions."""

from __future__ import annotations

import hashlib
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

_EMAIL_PATTERN = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
_PHONE_PATTERN = re.compile(
    r"\+?[1-9]\d{1,14}(\s*\(?\d{1,4}\)?[\s\-.]?\d{1,4}[\s\-.]?\d{1,9})"
)
_ADDRESS_PATTERN = re.compile(
    r"\d{1,6}\s+[A-Za-z]+(?:\s+[A-Za-z]+)*(?:\s+(?:Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Drive|Dr|Lane|Ln|Court|Ct|Place|Pl|Way|Terrace|Ter|Circle|Cir))",
    re.IGNORECASE,
)
_NAME_PATTERN = re.compile(
    r"\b(?:[A-Z][a-z]+\s+){1,2}(?:van\s+|de\s+|del\s+)?[A-Z][a-z]+\b"
)

_REDACTION_RULES_WORKSPACE: dict[str, list[str]] = {
    "google_workspace.gmail.profile.get": ["emailAddress"],
    "google_workspace.gmail.labels.list": [],
    "google_workspace.calendar.calendarList.list": ["id", "summary"],
    "google_workspace.drive.files.list": ["id", "name", "owner.email", "owners"],
    "google_workspace.tasks.tasklists.list": ["id", "title"],
    "google_workspace.contacts.list": [
        "resourceName",
        "emailAddresses",
        "names",
        "emailAddress",
        "phoneNumbers",
    ],
}


def _hash_identifier(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _hash_field(data: dict, field: str) -> dict:
    result = dict(data)
    if field in result and isinstance(result[field], str):
        result[field] = "sha256:" + _hash_identifier(result[field])
    return result


def assert_no_raw_secret_patterns(text: str) -> None:
    for pat in _SECRET_PATTERNS:
        if pat.search(text):
            raise ValueError("raw_secret_pattern_detected")


def assert_no_workspace_content_fields(data: dict[str, object]) -> None:
    for key in _FORBIDDEN_OUTPUT_FIELDS:
        if key in data:
            raise ValueError(f"raw_workspace_content_rejected: field '{key}'")


def assert_response_content_light(
    response_data: dict, forbidden_fields: list[str]
) -> None:
    for field in forbidden_fields:
        if field in response_data:
            raise ValueError(f"forbidden_response_field_detected: field '{field}'")


def redact_workspace_response(response_data: dict, capability_id: str) -> dict:
    fields = _REDACTION_RULES_WORKSPACE.get(capability_id)
    if fields is None:
        return response_data
    result = dict(response_data)
    for field in fields:
        result = _hash_field(result, field)
    return result


def detect_pii_in_response(data: dict, _prefix: str = "") -> list[str]:
    found: list[str] = []
    for key, value in data.items():
        path = f"{_prefix}.{key}" if _prefix else key
        if isinstance(value, str):
            if _EMAIL_PATTERN.search(value):
                found.append(f"pii_email:{path}")
            if _PHONE_PATTERN.search(value):
                found.append(f"pii_phone:{path}")
            if _ADDRESS_PATTERN.search(value):
                found.append(f"pii_address:{path}")
            if _NAME_PATTERN.search(value):
                found.append(f"pii_name_heuristic:{path}")
        elif isinstance(value, dict):
            found.extend(detect_pii_in_response(value, path))
        elif isinstance(value, list):
            for i, item in enumerate(value):
                if isinstance(item, dict):
                    found.extend(detect_pii_in_response(item, f"{path}[{i}]"))
                elif isinstance(item, str):
                    item_path = f"{path}[{i}]"
                    if _EMAIL_PATTERN.search(item):
                        found.append(f"pii_email:{item_path}")
                    if _PHONE_PATTERN.search(item):
                        found.append(f"pii_phone:{item_path}")
                    if _ADDRESS_PATTERN.search(item):
                        found.append(f"pii_address:{item_path}")
    return found
