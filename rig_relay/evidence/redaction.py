"""Content-light redaction helpers for remote/shareable artifacts."""

# ruff: noqa: PLR0915

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
import re
from typing import Any

_FORBIDDEN_FIELD_KEYS = {
    "raw_file_contents",
    "raw_prompt_text",
    "model_output_text",
    "stdout_bodies",
    "stderr_bodies",
    "raw_diff",
    "authorization_receipt",
    "secrets",
}

_SENSITIVE_NAME_PATTERNS = (
    "token",
    "secret",
    "password",
    "api_key",
    "client_secret",
    "private_key",
    "receipt",
    "prompt",
    "output",
    "stdout",
    "stderr",
    "diff",
)

_ABSOLUTE_PATH_RE = re.compile(r"^(?:/|[A-Za-z]:\\)")
_SECRET_VALUE_PATTERNS = (
    re.compile(
        r"(?i)-----BEGIN\s+(?:RSA\s+PRIVATE|EC\s+PRIVATE|OPENSSH\s+PRIVATE|PRIVATE)\s+KEY-----"
    ),
    re.compile(r"(?i)\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"(?i)\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    re.compile(r"(?i)\b(bearer\s+[A-Za-z0-9\-_.]{20,})\b"),
    re.compile(r"(?i)\b(api[_-]?key|api[_-]?token|secret[_-]?key|client[_-]?secret)\b"),
)


@dataclass(frozen=True, slots=True)
class RedactionPolicy:
    max_preview_chars: int = 160
    hash_private_paths: bool = True
    hash_sensitive_scalars: bool = True
    allow_relative_paths: bool = True


@dataclass(frozen=True, slots=True)
class RedactionResult:
    payload: Any
    warnings: tuple[str, ...] = field(default_factory=tuple)
    redacted_paths: tuple[str, ...] = field(default_factory=tuple)
    hashed_paths: tuple[str, ...] = field(default_factory=tuple)


def hash_sensitive_value(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, default=str, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _looks_sensitive_name(name: str) -> bool:
    lowered = name.lower()
    return any(pattern in lowered for pattern in _SENSITIVE_NAME_PATTERNS)


def _looks_sensitive_text(text: str) -> bool:
    return any(pattern.search(text) for pattern in _SECRET_VALUE_PATTERNS)


def classify_shareable_field(name: str, value: Any) -> str:
    lowered = name.lower()
    classification = "allow"
    if (
        lowered.endswith("_sha256")
        or lowered.endswith("_hash")
        or lowered
        in {
            "event_hash",
            "coord_event_hash",
            "artifact_record_sha256",
            "result_sha256",
            "receipt_sha256",
            "authorization_receipt_sha256",
            "bundle_sha256",
        }
    ):
        classification = "allow"
    elif name in _FORBIDDEN_FIELD_KEYS:
        classification = "forbid"
    elif _looks_sensitive_name(name):
        classification = "hash"
    elif isinstance(value, str):
        if value.startswith("sha256:"):
            classification = "allow"
        elif _looks_sensitive_text(value):
            classification = "forbid"
        elif _ABSOLUTE_PATH_RE.match(value):
            classification = "hash"
    elif isinstance(value, Path):
        classification = "hash"
    return classification


def _redact_scalar(
    name: str, value: Any, policy: RedactionPolicy
) -> tuple[Any, list[str], list[str], list[str]]:
    classification = classify_shareable_field(name, value)
    warnings: list[str] = []
    redacted_paths: list[str] = []
    hashed_paths: list[str] = []
    redacted_value = value

    if classification == "allow":
        pass
    elif classification == "hash" and policy.hash_sensitive_scalars:
        hashed_paths.append(name)
        redacted_value = hash_sensitive_value(value)
    else:
        redacted_paths.append(name)
        warnings.append(
            f"{name}: redacted sensitive string"
            if isinstance(value, str)
            else f"{name}: redacted sensitive value"
        )
        redacted_value = "[REDACTED]"

    return redacted_value, warnings, redacted_paths, hashed_paths


def _redact_value(
    value: Any, policy: RedactionPolicy, path: str
) -> tuple[Any, list[str], list[str], list[str]]:
    warnings: list[str] = []
    redacted_paths: list[str] = []
    hashed_paths: list[str] = []
    redacted_value: Any = value

    if isinstance(value, dict):
        redacted_dict: dict[str, Any] = {}
        for key, child in value.items():
            child_path = f"{path}.{key}" if path else key
            classification = classify_shareable_field(key, child)
            if classification == "allow":
                red_child, child_warnings, child_redacted, child_hashed = _redact_value(
                    child, policy, child_path
                )
                redacted_dict[key] = red_child
                warnings.extend(child_warnings)
                redacted_paths.extend(child_redacted)
                hashed_paths.extend(child_hashed)
                continue
            if classification == "hash" and policy.hash_sensitive_scalars:
                redacted_dict[key] = hash_sensitive_value(child)
                hashed_paths.append(child_path)
                continue
            redacted_dict[key] = "[REDACTED]"
            redacted_paths.append(child_path)
            warnings.append(f"{child_path}: redacted sensitive field")
        redacted_value = redacted_dict

    elif isinstance(value, list):
        redacted_list: list[Any] = []
        for index, child in enumerate(value):
            child_path = f"{path}[{index}]"
            red_child, child_warnings, child_redacted, child_hashed = _redact_value(
                child, policy, child_path
            )
            redacted_list.append(red_child)
            warnings.extend(child_warnings)
            redacted_paths.extend(child_redacted)
            hashed_paths.extend(child_hashed)
        redacted_value = redacted_list

    elif isinstance(value, tuple):
        redacted_list, child_warnings, child_redacted, child_hashed = _redact_value(
            list(value), policy, path
        )
        redacted_value = tuple(redacted_list)
        warnings.extend(child_warnings)
        redacted_paths.extend(child_redacted)
        hashed_paths.extend(child_hashed)

    elif isinstance(value, str):
        classification = classify_shareable_field(path.rsplit(".", 1)[-1], value)
        if classification == "allow":
            redacted_value = value
        elif classification == "hash" and policy.hash_sensitive_scalars:
            hashed_paths.append(path)
            redacted_value = hash_sensitive_value(value)
        else:
            redacted_paths.append(path)
            warnings.append(f"{path}: redacted sensitive string")
            redacted_value = "[REDACTED]"

    elif isinstance(value, Path):
        if policy.hash_private_paths:
            hashed_paths.append(path)
            redacted_value = hash_sensitive_value(str(value))
        else:
            redacted_paths.append(path)
            redacted_value = "[REDACTED]"

    else:
        redacted_value, scalar_warnings, scalar_redacted, scalar_hashed = (
            _redact_scalar(path, value, policy)
        )
        warnings.extend(scalar_warnings)
        redacted_paths.extend(scalar_redacted)
        hashed_paths.extend(scalar_hashed)

    return redacted_value, warnings, redacted_paths, hashed_paths


def redact_for_remote(
    payload: Any, policy: RedactionPolicy | None = None
) -> RedactionResult:
    active_policy = policy or RedactionPolicy()
    redacted_payload, warnings, redacted_paths, hashed_paths = _redact_value(
        payload, active_policy, ""
    )
    return RedactionResult(
        payload=redacted_payload,
        warnings=tuple(warnings),
        redacted_paths=tuple(redacted_paths),
        hashed_paths=tuple(hashed_paths),
    )


def assert_remote_safe(payload: Any, policy: RedactionPolicy | None = None) -> Any:
    result = redact_for_remote(payload, policy)
    return result.payload


def content_light_summary(
    payload: Any, policy: RedactionPolicy | None = None
) -> dict[str, Any]:
    result = redact_for_remote(payload, policy)
    summary: dict[str, Any] = {
        "schema_version": payload.get("schema_version", "")
        if isinstance(payload, dict)
        else "",
        "field_count": len(payload) if isinstance(payload, dict) else 1,
        "redacted_count": len(result.redacted_paths),
        "hashed_count": len(result.hashed_paths),
        "warnings": list(result.warnings)[:5],
    }
    if isinstance(payload, dict):
        summary["keys"] = sorted(str(key) for key in payload)
    return summary
