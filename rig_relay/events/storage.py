from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

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


def _has_raw_content(payload: dict[str, Any]) -> bool:
    for key in payload:
        if key in _REDACT_FIELDS:
            return True
        if isinstance(payload[key], dict) and _has_raw_content(payload[key]):
            return True
    return False


def _validate_entry(entry: dict[str, Any]) -> None:
    if "event_id" not in entry or not entry["event_id"]:
        raise StorageError("event_id required")
    payload = entry.get("payload")
    if isinstance(payload, dict) and _has_raw_content(payload):
        raise StorageError(
            "raw_content_field_detected: payload contains forbidden field"
        )
    content_light = entry.get("content_light")
    if not content_light:
        raise StorageError("content_light must be true")


class StorageError(Exception):
    pass


StorageBackendError = StorageError


@runtime_checkable
class StorageBackend(Protocol):
    def append(self, entry: dict[str, Any]) -> None: ...
    def read(self) -> list[dict[str, Any]]: ...
    def exists(self) -> bool: ...
    def checksum(self) -> str: ...
    def compact(
        self, max_entries: int | None = None, max_bytes: int | None = None
    ) -> int: ...
    def size_bytes(self) -> int: ...


@dataclass(slots=True)
class StorageConfig:
    path: Path
    max_entries: int | None = None
    max_bytes: int | None = None
    fsync: bool = True


class LocalFileBackend:
    def __init__(self, config: StorageConfig) -> None:
        self.config = config
        self._path = config.path

    def append(self, entry: dict[str, Any]) -> None:
        _validate_entry(entry)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(entry, sort_keys=True) + "\n"
        with open(self._path, "a") as f:
            f.write(line)
            if self.config.fsync:
                f.flush()
                os.fsync(f.fileno())

    def read(self) -> list[dict[str, Any]]:
        if not self._path.exists():
            return []
        results: list[dict[str, Any]] = []
        with open(self._path) as f:
            for line in f:
                stripped = line.strip()
                if stripped:
                    results.append(json.loads(stripped))
        return results

    def exists(self) -> bool:
        return self._path.exists() and self._path.stat().st_size > 0

    def checksum(self) -> str:
        entries = self.read()
        if not entries:
            return hashlib.sha256(b"").hexdigest()
        canonical = json.dumps(entries, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def compact(
        self, max_entries: int | None = None, max_bytes: int | None = None
    ) -> int:
        entries = self.read()
        original_count = len(entries)
        if original_count == 0:
            return 0

        max_e = max_entries if max_entries is not None else self.config.max_entries
        max_b = max_bytes if max_bytes is not None else self.config.max_bytes

        kept = list(entries)
        removed = 0

        if max_e is not None and len(kept) > max_e:
            removed += len(kept) - max_e
            kept = kept[-max_e:]

        if max_b is not None:
            while len(kept) > 1:
                data = "\n".join(json.dumps(e, sort_keys=True) for e in kept).encode(
                    "utf-8"
                )
                if len(data) <= max_b:
                    break
                kept = kept[1:]
                removed += 1

        if removed > 0:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._path, "w") as f:
                for entry in kept:
                    f.write(json.dumps(entry, sort_keys=True) + "\n")
                if self.config.fsync:
                    f.flush()
                    os.fsync(f.fileno())

        return removed

    def size_bytes(self) -> int:
        if not self._path.exists():
            return 0
        return self._path.stat().st_size


class MemoryBackend:
    def __init__(self) -> None:
        self._entries: list[dict[str, Any]] = []

    def append(self, entry: dict[str, Any]) -> None:
        _validate_entry(entry)
        self._entries.append(entry)

    def read(self) -> list[dict[str, Any]]:
        return list(self._entries)

    def exists(self) -> bool:
        return len(self._entries) > 0

    def checksum(self) -> str:
        if not self._entries:
            return hashlib.sha256(b"").hexdigest()
        canonical = json.dumps(self._entries, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def compact(
        self, max_entries: int | None = None, max_bytes: int | None = None
    ) -> int:
        original_count = len(self._entries)
        if original_count == 0:
            return 0

        kept = list(self._entries)
        removed = 0

        if max_entries is not None and len(kept) > max_entries:
            removed += len(kept) - max_entries
            kept = kept[-max_entries:]

        if max_bytes is not None:
            while len(kept) > 1:
                data = json.dumps(kept, sort_keys=True, separators=(",", ":")).encode(
                    "utf-8"
                )
                if len(data) <= max_bytes:
                    break
                kept = kept[1:]
                removed += 1

        if removed > 0:
            self._entries = kept

        return removed

    def size_bytes(self) -> int:
        return len(
            json.dumps(self._entries, sort_keys=True, separators=(",", ":")).encode(
                "utf-8"
            )
        )


__all__ = [
    "LocalFileBackend",
    "MemoryBackend",
    "StorageBackend",
    "StorageBackendError",
    "StorageConfig",
    "StorageError",
]
