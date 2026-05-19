from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
import re
import secrets
from typing import Any

_LIFECYCLE_SCHEMA_VERSION = "rig.relay.bridge_lifecycle_event.v1"
_SCHEMA_VERSION = "rig.relay.bridge_envelope.v1"

_REFUSAL_KINDS: frozenset[str] = frozenset({
    "unknown_intent_kind",
    "invalid_schema_version",
    "missing_trace_id",
    "duplicate_message_id",
    "oversized_payload",
    "missing_capability",
    "mutation_class_refused",
    "credentialed_provider_mutation_refused",
    "release_affecting_mutation_refused",
    "external_network_mutation_refused",
    "unsafe_payload_refused",
    "raw_secret_refused",
    "raw_path_refused",
    "internal_error",
})

_MAX_INTENT_BYTES = 64 * 1024

_MIN_SECRET_LENGTH = 5

_TOKEN_PATTERNS: list[tuple[str, str]] = [
    ("ghp_", "github_personal_access_token"),
    ("gho_", "github_oauth_token"),
    ("ghu_", "github_user_server_token"),
    ("ghs_", "github_server_token"),
    ("ghr_", "github_refresh_token"),
    ("github_pat_", "github_pat_prefix"),
]

_SECRET_FIELD_PATTERNS = [
    "api_key",
    "api_secret",
    "secret_key",
    "access_token",
    "client_secret",
    "private_key",
    "refresh_token",
    "oauth_token",
    "oauth_code",
    "authorization_code",
]

_PATH_PATTERNS = [r"^/Users/", r"^/home/", r"^[A-Z]:\\"]

_RAW_CONTENT_FIELDS = [
    "raw_prompt",
    "raw_completion",
    "raw_file_contents",
    "private_repo_contents",
]


# ── Refusal envelope builder ────────────────────────────────────────────


def build_bridge_refusal_envelope(
    *,
    refusal_kind: str,
    reason_code: str,
    human_safe_message: str,
    trace_id: str = "",
    frontend_session_id: str = "",
    backend_session_id: str = "",
    parent_message_id: str = "",
    refused_intent_kind: str = "",
    mutation_class: str = "",
    capability_required: list[str] | None = None,
    payload_hash: str = "",
    projection_sequence: int = 0,
) -> dict[str, Any]:
    if refusal_kind not in _REFUSAL_KINDS:
        refusal_kind = "internal_error"

    refusal = {
        "refusal_code": reason_code,
        "refusal_reason": human_safe_message,
        "refusal_kind": refusal_kind,
    }

    safe_summary: dict[str, str] = {
        "refused_intent_kind": refused_intent_kind,
        "mutation_class": mutation_class,
    }

    payload: dict[str, Any] = {
        "schema_version": _SCHEMA_VERSION,
        "message_id": _new_message_id(),
        "trace_id": trace_id or _new_trace_id(),
        "frontend_session_id": frontend_session_id,
        "backend_session_id": backend_session_id,
        "protocol_version": "v1",
        "direction": "backend_to_frontend",
        "kind": "error",
        "sequence": 0,
        "created_at": datetime.now(UTC).isoformat(),
        "redaction_status": "content_light",
        "refusal": refusal,
        "safe_summary": safe_summary,
    }

    if parent_message_id:
        payload["parent_message_id"] = parent_message_id
    if projection_sequence > 0:
        payload["projection_sequence"] = projection_sequence

    return payload


def _new_message_id() -> str:
    return f"msg_{secrets.token_hex(12)}"


def _new_trace_id() -> str:
    return f"trace_{secrets.token_hex(12)}"


def _new_event_id() -> str:
    return f"evt_{secrets.token_hex(8)}"


def _hash_reason(reason: str) -> str:
    return hashlib.sha256(reason.encode("utf-8")).hexdigest()[:16]


def build_bridge_refusal_trace_event(
    *,
    refusal_kind: str,
    refused_intent_kind: str,
    refusal_message_id: str,
    inbound_message_id: str,
    refusal_reason: str = "",
    mutation_class: str = "",
    capability_required: list[str] | None = None,
    trace_id: str = "",
    frontend_session_id: str = "",
    backend_session_id: str = "",
    handshake_id: str = "",
    payload_hash: str = "",
    source: str = "bridge_refusal_builder",
) -> dict[str, Any]:
    event: dict[str, Any] = {
        "schema_version": _LIFECYCLE_SCHEMA_VERSION,
        "event_id": _new_event_id(),
        "trace_id": trace_id or _new_trace_id(),
        "handshake_id": handshake_id,
        "frontend_session_id": frontend_session_id,
        "backend_session_id": backend_session_id,
        "event": "refusal_emitted",
        "created_at": datetime.now(UTC).isoformat(),
        "redaction_status": "content_light",
        "content_light": True,
        "inbound_message_id": inbound_message_id,
        "refusal_message_id": refusal_message_id,
        "refusal_kind": refusal_kind,
        "refused_intent_kind": refused_intent_kind,
        "source": source,
    }

    if mutation_class:
        event["mutation_class"] = mutation_class
    if capability_required:
        event["capability_required"] = capability_required
    if payload_hash:
        event["payload_hash"] = payload_hash
    if refusal_reason:
        event["refusal_reason_hash"] = _hash_reason(refusal_reason)

    return event


# ── Content-light scanner ───────────────────────────────────────────────


class ContentLightScanResult:
    __slots__ = ("safe", "finding_kind", "detail")

    def __init__(self, safe: bool, finding_kind: str = "", detail: str = "") -> None:
        self.safe = safe
        self.finding_kind = finding_kind
        self.detail = detail

    def __bool__(self) -> bool:
        return self.safe


SCAN_SAFE = ContentLightScanResult(True)


def scan_bridge_payload(data: dict[str, Any]) -> ContentLightScanResult:
    raw = json.dumps(data, sort_keys=True)

    for pattern, label in _TOKEN_PATTERNS:
        if pattern in raw:
            return ContentLightScanResult(False, "raw_secret_refused", label)

    for field in _RAW_CONTENT_FIELDS:
        if data.get(field):
            return ContentLightScanResult(False, "unsafe_payload_refused", field)

    for field in _SECRET_FIELD_PATTERNS:
        value = _deep_get(data, field)
        if value and isinstance(value, str) and len(value) > _MIN_SECRET_LENGTH:
            return ContentLightScanResult(False, "raw_secret_refused", field)

    for field_pattern in _PATH_PATTERNS:
        if _scan_paths(data, {re.compile(field_pattern)}):
            return ContentLightScanResult(
                False, "raw_path_refused", "absolute_local_path"
            )

    return SCAN_SAFE


def scan_payload_size(data: dict[str, Any]) -> int:
    return len(json.dumps(data, sort_keys=True).encode("utf-8"))


def is_oversized_payload(data: dict[str, Any]) -> bool:
    return scan_payload_size(data) > _MAX_INTENT_BYTES


def _deep_get(data: dict[str, Any], key: str) -> Any:
    if key in data:
        return data[key]
    for v in data.values():
        if isinstance(v, dict):
            result = _deep_get(v, key)
            if result:
                return result
    return None


def _scan_paths(data: dict[str, Any], patterns: set[re.Pattern]) -> bool:
    for v in data.values():
        if isinstance(v, str):
            if _any_pattern_match(v, patterns):
                return True
        elif isinstance(v, dict) and _scan_paths(v, patterns):
            return True
        elif isinstance(v, list):
            if _any_list_path_match(v, patterns):
                return True
    return False


def _any_pattern_match(value: str, patterns: set[re.Pattern]) -> bool:
    return any(pat.match(value) for pat in patterns)


def _any_list_path_match(items: list[Any], patterns: set[re.Pattern]) -> bool:
    for item in items:
        if isinstance(item, str) and _any_pattern_match(item, patterns):
            return True
        if isinstance(item, dict) and _scan_paths(item, patterns):
            return True
    return False


# ── Dispatcher enforcement ──────────────────────────────────────────────


_MUTATION_CLASSES: frozenset[str] = frozenset({
    "read_only",
    "safe_local_mutation",
    "dangerous_local_mutation",
    "external_network_mutation",
    "credentialed_provider_mutation",
    "release_affecting_mutation",
})

_REFUSED_MUTATION_CLASSES: frozenset[str] = frozenset({
    "external_network_mutation",
    "credentialed_provider_mutation",
    "release_affecting_mutation",
    "dangerous_local_mutation",
})


class DispatcherEnforcementResult:
    __slots__ = ("allowed", "refusal_kind", "reason_code", "message")

    def __init__(
        self,
        allowed: bool,
        refusal_kind: str = "",
        reason_code: str = "",
        message: str = "",
    ) -> None:
        self.allowed = allowed
        self.refusal_kind = refusal_kind
        self.reason_code = reason_code
        self.message = message

    def __bool__(self) -> bool:
        return self.allowed


ENFORCEMENT_ALLOWED = DispatcherEnforcementResult(True)


def enforce_intent(
    *,
    intent_kind: str,
    schema_version: str = "",
    mutation_class: str = "",
    capability_required: list[str] | None = None,
    trace_id: str = "",
    payload: dict[str, Any] | None = None,
    allowed_intents: frozenset[str] | None = None,
) -> DispatcherEnforcementResult:
    if schema_version and schema_version != "rig.relay.frontend_intent.v1":
        return DispatcherEnforcementResult(
            False,
            "invalid_schema_version",
            "invalid_schema_version",
            f"Schema version '{schema_version}' not supported.",
        )

    if not trace_id:
        return DispatcherEnforcementResult(
            False,
            "missing_trace_id",
            "missing_trace_id",
            "trace_id is required for all bridge intents.",
        )

    if allowed_intents is not None and intent_kind not in allowed_intents:
        return DispatcherEnforcementResult(
            False,
            "unknown_intent_kind",
            "unknown_intent_kind",
            f"Intent '{intent_kind}' is not recognised.",
        )

    if payload is not None:
        size = scan_payload_size(payload)
        if size > _MAX_INTENT_BYTES:
            return DispatcherEnforcementResult(
                False,
                "oversized_payload",
                "oversized_payload",
                f"Payload size {size} exceeds maximum {_MAX_INTENT_BYTES} bytes.",
            )

        scan_result = scan_bridge_payload(payload)
        if not scan_result.safe:
            return DispatcherEnforcementResult(
                False,
                scan_result.finding_kind,
                scan_result.finding_kind,
                "Content-light violation detected.",
            )

    caps = capability_required or []

    if mutation_class and mutation_class not in _MUTATION_CLASSES:
        return DispatcherEnforcementResult(
            False,
            "mutation_class_refused",
            "mutation_class_refused",
            f"Mutation class '{mutation_class}' not recognised.",
        )

    if mutation_class in _REFUSED_MUTATION_CLASSES:
        refusal_kind = f"{mutation_class}_refused"
        if refusal_kind not in _REFUSAL_KINDS:
            refusal_kind = "mutation_class_refused"
        return DispatcherEnforcementResult(
            False,
            refusal_kind,
            refusal_kind,
            f"Mutation class '{mutation_class}' is refused in this lane.",
        )

    if mutation_class and mutation_class != "read_only" and not caps:
        return DispatcherEnforcementResult(
            False,
            "missing_capability",
            "missing_capability",
            f"Mutation intent '{intent_kind}' requires capability.",
        )

    return ENFORCEMENT_ALLOWED
