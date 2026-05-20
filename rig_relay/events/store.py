from __future__ import annotations

import json
from pathlib import Path

_DEFAULT_STORE_PATH = Path(".build/rig-relay/events/event_fabric_v1.jsonl")

_REDACT_FIELDS: frozenset[str] = frozenset({
    "token_prefix",
    "access_token",
    "authorization",
    "raw_response",
    "raw_body",
    "code_snippet",
    "patch",
    "diff",
    "contents",
    "secret",
    "vulnerable_code",
    "file_body",
    "auth_header",
    "bearer",
    "raw_token",
    "raw_repository_content",
    "raw_private_file_content",
    "raw_prompt",
    "raw_credential",
    "raw_absolute_path",
    "oauth_code",
    "client_secret",
    "private_key",
    "jwt_assertion",
    "token",
    "code",
    "refresh_token",
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
})


def _has_raw_content(payload: dict) -> bool:
    for key in payload:
        if key in _REDACT_FIELDS:
            return True
        if isinstance(payload[key], dict) and _has_raw_content(payload[key]):
            return True
    return False


def _validate_event(event: dict) -> None:
    if "event_id" not in event or not event["event_id"]:
        raise ValueError("event_id required")
    payload = event.get("payload")
    if isinstance(payload, dict) and _has_raw_content(payload):
        raise ValueError("raw_content_field_detected: payload contains forbidden field")
    content_light = event.get("content_light")
    if not content_light:
        raise ValueError("content_light must be true")


class EventStoreError(Exception):
    pass


class EventStore:
    """Append-only JSONL event log. Writes one canonical JSON object per line."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path or _DEFAULT_STORE_PATH

    def append(self, event: dict) -> None:
        try:
            _validate_event(event)
        except ValueError as e:
            raise EventStoreError(str(e)) from e
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            line = json.dumps(event, sort_keys=True) + "\n"
            with open(self._path, "a") as f:
                f.write(line)
                f.flush()
        except (OSError, TypeError) as e:
            raise EventStoreError(str(e)) from e

    def read(self) -> list[dict]:
        if not self._path.exists():
            return []
        results: list[dict] = []
        with open(self._path) as f:
            for line in f:
                stripped = line.strip()
                if stripped:
                    results.append(json.loads(stripped))
        return results

    def exists(self) -> bool:
        return self._path.exists()


__all__ = ["EventStore", "EventStoreError"]
