from __future__ import annotations

from rig_relay.investigation_timeline._models import InvestigationTimelineEvent

FORBIDDEN_FIELD_NAMES: set[str] = {
    "raw_file_contents",
    "file_contents",
    "raw_prompt",
    "prompt",
    "raw_model_output",
    "model_output",
    "raw_stdout",
    "stdout",
    "raw_stderr",
    "stderr",
    "secret",
    "api_key",
    "token",
    "access_token",
    "private_key",
    "diff_body",
    "diff",
    "snippet",
    "content",
    "mutation_content",
    "validation_log",
}


def enforce_content_light(events: list[InvestigationTimelineEvent]) -> list[str]:
    violations: list[str] = []
    for event in events:
        event_dict = event.model_dump(exclude_none=True)
        violations.extend(_scan_for_forbidden_fields(event_dict, event.event_id))
    return violations


def enforce_content_light_dict(records: list[dict[str, object]]) -> list[str]:
    violations: list[str] = []
    for i, record in enumerate(records):
        record_id = str(record.get("event_id", f"record_{i}"))
        violations.extend(_scan_forbidden_keys(record, record_id))
    return violations


def _scan_for_forbidden_fields(data: dict[str, object], label: str) -> list[str]:
    violations: list[str] = []

    def _walk(obj: object, path: str) -> None:
        if isinstance(obj, dict):
            for key in obj:
                if key.lower() in FORBIDDEN_FIELD_NAMES:
                    violations.append(
                        f"forbidden field '{key}' at {path}.{key} in {label}"
                    )
                _walk(obj[key], f"{path}.{key}")
        elif isinstance(obj, list):
            for i, item in enumerate(obj):
                _walk(item, f"{path}[{i}]")

    _walk(data, label)
    return violations


def _scan_forbidden_keys(data: dict[str, object], label: str) -> list[str]:
    violations: list[str] = []
    for key in data:
        if key.lower() in FORBIDDEN_FIELD_NAMES:
            violations.append(f"forbidden field '{key}' in {label}")
    return violations
