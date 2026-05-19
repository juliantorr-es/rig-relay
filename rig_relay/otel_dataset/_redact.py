from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from typing import Any

_HASH_KEY_HINTS = (
    "path",
    "tool.name",
    "tool_name",
    "gen_ai.request.model",
    "gen_ai.response.model",
    "gen_ai.provider.name",
    "model",
    "provider",
    "session",
    "conversation.id",
    "git.branch",
    "git.commit.sha",
    "workspace",
    "repo",
    "traceid",
    "spanid",
)

_DROP_KEY_HINTS = (
    "raw_prompt",
    "prompt",
    "raw_completion",
    "completion",
    "model_output",
    "body",
    "content",
    "text",
    "message",
    "input",
    "output",
    "arguments",
    "result",
    "stdout",
    "stderr",
    "diff",
    "authorization",
    "bearer",
    "token",
    "secret",
    "password",
    "api_key",
    "credential",
    "cookie",
)

_ABSOLUTE_PATH_RE = re.compile(r"^(?:/|[A-Za-z]:\\)")
_SECRET_VALUE_RE = re.compile(
    r"(?i)(?:-----BEGIN\s+.*PRIVATE\s+KEY-----|sk-[A-Za-z0-9_-]{12,}|gh[pousr]_[A-Za-z0-9]{10,}|Bearer\s+[A-Za-z0-9\-_.]{10,})"
)


@dataclass(frozen=True, slots=True)
class RedactedAttributes:
    attributes: dict[str, Any]
    warnings: tuple[str, ...]
    redacted_attribute_keys: tuple[str, ...]
    hashed_attribute_keys: tuple[str, ...]


def _sha256(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, default=str, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _key_path(key: str, path: str) -> str:
    return f"{path}.{key}" if path else key


def _top_level_key(path: str) -> str:
    return path.split(".", 1)[0].split("[", 1)[0]


def _should_hash(key_path: str, value: Any) -> bool:
    lowered = key_path.lower()
    if isinstance(value, str) and _ABSOLUTE_PATH_RE.match(value):
        return True
    return any(hint in lowered for hint in _HASH_KEY_HINTS)


def _should_drop(key_path: str, value: Any) -> bool:
    lowered = key_path.lower()
    if isinstance(value, str) and _SECRET_VALUE_RE.search(value):
        return True
    return any(hint in lowered for hint in _DROP_KEY_HINTS)


def _redact_value(
    value: Any, path: str
) -> tuple[Any, tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    warnings: list[str] = []
    redacted: list[str] = []
    hashed: list[str] = []

    if isinstance(value, dict):
        redacted_dict: dict[str, Any] = {}
        for key, child in value.items():
            child_path = _key_path(str(key), path)
            child_value, child_warnings, child_redacted, child_hashed = _redact_value(
                child, child_path
            )
            redacted_dict[str(key)] = child_value
            warnings.extend(child_warnings)
            redacted.extend(child_redacted)
            hashed.extend(child_hashed)
        return redacted_dict, tuple(warnings), tuple(redacted), tuple(hashed)

    if isinstance(value, list):
        redacted_list: list[Any] = []
        for index, child in enumerate(value):
            child_value, child_warnings, child_redacted, child_hashed = _redact_value(
                child, f"{path}[{index}]"
            )
            redacted_list.append(child_value)
            warnings.extend(child_warnings)
            redacted.extend(child_redacted)
            hashed.extend(child_hashed)
        return redacted_list, tuple(warnings), tuple(redacted), tuple(hashed)

    if isinstance(value, tuple):
        child_value, child_warnings, child_redacted, child_hashed = _redact_value(
            list(value), path
        )
        return (
            tuple(child_value),
            tuple(child_warnings),
            tuple(child_redacted),
            tuple(child_hashed),
        )

    if _should_hash(path, value):
        hashed.append(path)
        return _sha256(value), tuple(warnings), tuple(redacted), tuple(hashed)

    if _should_drop(path, value):
        redacted.append(path)
        warnings.append(f"{path}: redacted sensitive value")
        return "[REDACTED]", tuple(warnings), tuple(redacted), tuple(hashed)

    return value, tuple(warnings), tuple(redacted), tuple(hashed)


def redact_otel_attributes(attributes: dict[str, Any]) -> RedactedAttributes:
    redacted_payload, warnings, redacted_paths, hashed_paths = _redact_value(
        attributes, ""
    )
    if not isinstance(redacted_payload, dict):
        redacted_payload = dict(attributes)
    return RedactedAttributes(
        attributes=redacted_payload,
        warnings=tuple(warnings),
        redacted_attribute_keys=tuple(
            sorted({_top_level_key(path) for path in redacted_paths})
        ),
        hashed_attribute_keys=tuple(
            sorted({_top_level_key(path) for path in hashed_paths})
        ),
    )
