from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
from typing import Any

from rig_relay.otel_dataset._redact import RedactedAttributes, redact_otel_attributes

SCHEMA_VERSION = "rig.otel.normalized_event.v1"
EXCESSIVE_ATTRIBUTE_THRESHOLD = 20

_SPAN_KIND_MAP = {
    0: "unspecified",
    1: "internal",
    2: "server",
    3: "client",
    4: "producer",
    5: "consumer",
}

_STATUS_CODE_MAP = {0: "UNSET", 1: "OK", 2: "ERROR"}


@dataclass(frozen=True, slots=True)
class NormalizationResult:
    events: list[dict[str, Any]]
    source_event_count: int
    normalized_event_count: int
    dropped_event_count: int
    redaction_summary: dict[str, Any]
    hardening_candidates: list[dict[str, Any]]
    missing_trace_id_count: int
    missing_parent_span_id_count: int
    signal_counts: dict[str, int]


@dataclass(frozen=True, slots=True)
class EventInput:
    source_signal: str
    source_system: str
    resource_attrs: dict[str, Any]
    raw_attrs: dict[str, Any]
    event_name: str
    trace_id: Any
    span_id: Any
    parent_span_id: Any
    span_kind: Any
    event_time: Any
    duration_ms: Any
    status_code: Any
    status_message: Any
    raw_repo_head_sha: Any
    normalized_at: str


@dataclass(slots=True)
class NormalizationState:
    events: list[dict[str, Any]]
    hardening_candidates: list[dict[str, Any]]
    signal_counts: dict[str, int]
    source_event_count: int = 0
    redacted_count: int = 0
    hashed_count: int = 0
    missing_trace_id_count: int = 0
    missing_parent_span_id_count: int = 0

    def add_candidate(self, *, kind: str, description: str, **details: Any) -> None:
        _add_hardening_candidate(
            self.hardening_candidates, kind=kind, description=description, **details
        )

    def append_event(self, event_input: EventInput) -> None:
        event, redaction = _build_event(event_input)
        if len(event["retained_attribute_keys"]) > EXCESSIVE_ATTRIBUTE_THRESHOLD:
            self.add_candidate(
                kind="excessive_event_attributes",
                description=f"{event_input.source_signal.capitalize()} retained too many attributes",
                count=len(event["retained_attribute_keys"]),
            )
        self.events.append(event)
        self.signal_counts[event_input.source_signal] += 1
        self.redacted_count += len(redaction.redacted_attribute_keys)
        self.hashed_count += len(redaction.hashed_attribute_keys)


def _now() -> str:
    return datetime.now(tz=UTC).isoformat()


def _sha256_json(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, default=str, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _parse_otel_value(value: Any) -> Any:
    result = value
    if isinstance(value, dict):
        if "stringValue" in value:
            result = value["stringValue"]
        elif "intValue" in value:
            result = value["intValue"]
        elif "doubleValue" in value:
            result = value["doubleValue"]
        elif "boolValue" in value:
            result = value["boolValue"]
        elif "arrayValue" in value:
            result = [
                _parse_otel_value(item)
                for item in value["arrayValue"].get("values", [])
            ]
        elif "kvlistValue" in value:
            items = value["kvlistValue"].get("values", [])
            result = {
                str(item.get("key", "")): _parse_otel_value(item.get("value"))
                for item in items
            }
    return result


def _flatten_attributes(
    items: list[dict[str, Any]] | dict[str, Any] | None,
) -> dict[str, Any]:
    if items is None:
        return {}
    if isinstance(items, dict):
        return {str(key): _parse_otel_value(value) for key, value in items.items()}
    flattened: dict[str, Any] = {}
    for item in items:
        key = str(item.get("key", ""))
        if not key:
            continue
        flattened[key] = _parse_otel_value(item.get("value"))
    return flattened


def _merge_attrs(*sources: dict[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for source in sources:
        merged.update({
            key: value for key, value in source.items() if value is not None
        })
    return merged


def _nanoseconds_to_iso(value: Any) -> str:
    if value in {None, ""}:
        return _now()
    try:
        nanos = int(value)
    except (TypeError, ValueError):
        return _now()
    return datetime.fromtimestamp(nanos / 1_000_000_000, tz=UTC).isoformat()


def _duration_ms(start_ns: Any, end_ns: Any) -> float | None:
    try:
        start = int(start_ns)
        end = int(end_ns)
    except (TypeError, ValueError):
        return None
    if end < start:
        return None
    return (end - start) / 1_000_000


def _duration_from_datapoint(datapoint: dict[str, Any]) -> float | None:
    if datapoint.get("asDouble") is not None:
        return float(datapoint["asDouble"])
    if datapoint.get("asInt") is not None:
        return float(datapoint["asInt"])
    return None


def _pick(*values: Any) -> Any:
    for value in values:
        if value not in {None, ""}:
            return value
    return None


def _span_kind_name(value: Any) -> str:
    try:
        return _SPAN_KIND_MAP[int(value)]
    except (TypeError, ValueError, KeyError):
        return "unknown"


def _status_code_name(value: Any) -> str:
    if isinstance(value, str):
        upper = value.upper()
        if upper in {"OK", "ERROR", "UNSET", "INFO", "CANCELLED", "TIMEOUT"}:
            return upper
        return "UNKNOWN"
    try:
        return _STATUS_CODE_MAP[int(value)]
    except (TypeError, ValueError, KeyError):
        return "UNKNOWN"


def _attr_key_lookup(attributes: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in attributes:
            return attributes[key]
    return None


def _build_event(event: EventInput) -> tuple[dict[str, Any], RedactedAttributes]:
    merged_attrs = _merge_attrs(event.resource_attrs, event.raw_attrs)
    redaction = redact_otel_attributes(merged_attrs)

    tool_name = _pick(
        _attr_key_lookup(event.raw_attrs, "tool.name", "tool_name", "gen_ai.tool.name"),
        _attr_key_lookup(event.resource_attrs, "tool.name", "tool_name"),
    )
    tool_category = _pick(
        _attr_key_lookup(event.raw_attrs, "tool.category", "tool_category"),
        _attr_key_lookup(event.resource_attrs, "tool.category", "tool_category"),
        "unknown",
    )
    model_name = _pick(
        _attr_key_lookup(
            event.raw_attrs, "gen_ai.request.model", "gen_ai.response.model", "model"
        ),
        _attr_key_lookup(event.resource_attrs, "gen_ai.request.model", "model"),
    )
    provider_name = _pick(
        _attr_key_lookup(event.raw_attrs, "gen_ai.provider.name", "provider"),
        _attr_key_lookup(event.resource_attrs, "gen_ai.provider.name", "provider"),
    )
    session_id = _pick(
        _attr_key_lookup(
            event.raw_attrs, "session.id", "gen_ai.conversation.id", "conversation.id"
        ),
        _attr_key_lookup(event.resource_attrs, "session.id", "gen_ai.conversation.id"),
    )
    workspace = _pick(
        _attr_key_lookup(event.raw_attrs, "workspace.path", "workspace"),
        _attr_key_lookup(event.resource_attrs, "workspace.path", "workspace"),
    )
    git_branch = _pick(
        _attr_key_lookup(event.raw_attrs, "git.branch"),
        _attr_key_lookup(event.resource_attrs, "git.branch"),
    )
    status = (
        "content_light"
        if not redaction.redacted_attribute_keys and not redaction.hashed_attribute_keys
        else (
            "hashed"
            if redaction.hashed_attribute_keys and not redaction.redacted_attribute_keys
            else "redacted"
        )
    )
    return (
        {
            "schema_version": SCHEMA_VERSION,
            "event_id": _sha256_json({
                "signal": event.source_signal,
                "name": event.event_name,
                "trace_id": event.trace_id,
                "span_id": event.span_id,
                "event_time": event.event_time,
                "source_system": event.source_system,
            }),
            "source_signal": event.source_signal,
            "source_system": event.source_system,
            "service_name": str(event.resource_attrs.get("service.name") or "unknown"),
            "trace_id": event.trace_id or None,
            "span_id": event.span_id or None,
            "parent_span_id": event.parent_span_id or None,
            "span_name": event.event_name,
            "span_kind": _span_kind_name(event.span_kind),
            "event_time": _nanoseconds_to_iso(event.event_time),
            "duration_ms": event.duration_ms,
            "status_code": _status_code_name(event.status_code),
            "status_message_hash": _sha256_json(event.status_message)
            if event.status_message
            else None,
            "tool_name_hash": _sha256_json(tool_name) if tool_name else None,
            "tool_category": str(tool_category or "unknown"),
            "model_name_hash": _sha256_json(model_name) if model_name else None,
            "provider_hash": _sha256_json(provider_name) if provider_name else None,
            "session_id_hash": _sha256_json(session_id) if session_id else None,
            "workspace_hash": _sha256_json(workspace) if workspace else None,
            "repo_head_sha": event.raw_repo_head_sha
            if event.raw_repo_head_sha
            else None,
            "git_branch_hash": _sha256_json(git_branch) if git_branch else None,
            "attributes_hash": _sha256_json(redaction.attributes),
            "redaction_status": status,
            "dropped_attribute_keys": list(redaction.redacted_attribute_keys),
            "retained_attribute_keys": [
                key
                for key, value in redaction.attributes.items()
                if value != "[REDACTED]"
            ],
            "content_light": True,
            "normalized_at": event.normalized_at,
        },
        redaction,
    )


def _add_hardening_candidate(
    candidates: list[dict[str, Any]], *, kind: str, description: str, **details: Any
) -> None:
    candidates.append({
        "kind": kind,
        "description": description,
        "details": {key: value for key, value in details.items() if value is not None},
    })


def _normalize_trace_spans(
    resource_spans: list[dict[str, Any]],
    *,
    source_system: str,
    normalized_at: str,
    state: NormalizationState,
) -> int:
    source_event_count = 0

    for resource_span in resource_spans:
        resource_attrs = _flatten_attributes(
            resource_span.get("resource", {}).get("attributes")
        )
        raw_repo_head_sha = resource_attrs.get("git.commit.sha")
        for scope_span in resource_span.get("scopeSpans", []):
            for span in scope_span.get("spans", []):
                source_event_count += 1
                trace_id = span.get("traceId") or span.get("trace_id")
                span_id = span.get("spanId") or span.get("span_id")
                parent_span_id = span.get("parentSpanId") or span.get("parent_span_id")
                if not trace_id:
                    state.missing_trace_id_count += 1
                    state.add_candidate(
                        kind="missing_trace_id",
                        description="Span missing trace id",
                        span_name=span.get("name"),
                    )
                if not parent_span_id:
                    state.missing_parent_span_id_count += 1
                    state.add_candidate(
                        kind="missing_parent_span_id",
                        description="Span missing parent span id",
                        span_name=span.get("name"),
                    )
                status = span.get("status") or {}
                raw_attrs = _flatten_attributes(span.get("attributes"))
                state.append_event(
                    EventInput(
                        source_signal="trace",
                        source_system=source_system,
                        resource_attrs=resource_attrs,
                        raw_attrs=raw_attrs,
                        event_name=str(span.get("name") or "unknown"),
                        trace_id=trace_id,
                        span_id=span_id,
                        parent_span_id=parent_span_id,
                        span_kind=span.get("kind"),
                        event_time=span.get("startTimeUnixNano")
                        or span.get("start_time_unix_nano"),
                        duration_ms=_duration_ms(
                            span.get("startTimeUnixNano")
                            or span.get("start_time_unix_nano"),
                            span.get("endTimeUnixNano")
                            or span.get("end_time_unix_nano"),
                        ),
                        status_code=(
                            status.get("code") if isinstance(status, dict) else None
                        ),
                        status_message=(
                            status.get("message") if isinstance(status, dict) else None
                        ),
                        raw_repo_head_sha=raw_repo_head_sha,
                        normalized_at=normalized_at,
                    )
                )

    return source_event_count


def _normalize_log_records(
    resource_logs: list[dict[str, Any]],
    *,
    source_system: str,
    normalized_at: str,
    state: NormalizationState,
) -> int:
    source_event_count = 0

    for resource_log in resource_logs:
        resource_attrs = _flatten_attributes(
            resource_log.get("resource", {}).get("attributes")
        )
        for scope_log in resource_log.get("scopeLogs", []):
            for log_record in scope_log.get("logRecords", []):
                source_event_count += 1
                raw_attrs = _flatten_attributes(log_record.get("attributes"))
                body = _parse_otel_value(log_record.get("body"))
                raw_attrs = _merge_attrs(
                    raw_attrs, {"body": body} if body is not None else {}
                )
                state.append_event(
                    EventInput(
                        source_signal="log",
                        source_system=source_system,
                        resource_attrs=resource_attrs,
                        raw_attrs=raw_attrs,
                        event_name="log.record",
                        trace_id=log_record.get("traceId")
                        or log_record.get("trace_id"),
                        span_id=log_record.get("spanId") or log_record.get("span_id"),
                        parent_span_id=log_record.get("parentSpanId")
                        or log_record.get("parent_span_id"),
                        span_kind=None,
                        event_time=log_record.get("timeUnixNano")
                        or log_record.get("time_unix_nano"),
                        duration_ms=0.0,
                        status_code=log_record.get("severityText")
                        or log_record.get("severity_text"),
                        status_message=body,
                        raw_repo_head_sha=resource_attrs.get("git.commit.sha"),
                        normalized_at=normalized_at,
                    )
                )

    return source_event_count


def _metric_datapoints(metric: dict[str, Any]) -> list[dict[str, Any]]:
    datapoints: list[dict[str, Any]] = []
    for key in ("gauge", "sum", "histogram", "exponentialHistogram"):
        block = metric.get(key)
        if isinstance(block, dict):
            datapoints.extend(block.get("dataPoints", []))
    return datapoints


def _normalize_metric_datapoints(
    resource_metrics: list[dict[str, Any]],
    *,
    source_system: str,
    normalized_at: str,
    state: NormalizationState,
) -> int:
    source_event_count = 0

    for resource_metric in resource_metrics:
        resource_attrs = _flatten_attributes(
            resource_metric.get("resource", {}).get("attributes")
        )
        for scope_metric in resource_metric.get("scopeMetrics", []):
            for metric in scope_metric.get("metrics", []):
                metric_name = metric.get("name", "metric")
                for datapoint in _metric_datapoints(metric):
                    source_event_count += 1
                    raw_attrs = _flatten_attributes(datapoint.get("attributes"))
                    raw_attrs = _merge_attrs(
                        raw_attrs,
                        {"metric.name": metric_name, "metric.unit": metric.get("unit")},
                    )
                    state.append_event(
                        EventInput(
                            source_signal="metric",
                            source_system=source_system,
                            resource_attrs=resource_attrs,
                            raw_attrs=raw_attrs,
                            event_name=str(metric_name),
                            trace_id=datapoint.get("traceId")
                            or datapoint.get("trace_id"),
                            span_id=datapoint.get("spanId") or datapoint.get("span_id"),
                            parent_span_id=datapoint.get("parentSpanId")
                            or datapoint.get("parent_span_id"),
                            span_kind=None,
                            event_time=datapoint.get("timeUnixNano")
                            or datapoint.get("time_unix_nano"),
                            duration_ms=_duration_from_datapoint(datapoint),
                            status_code=datapoint.get("flags"),
                            status_message=None,
                            raw_repo_head_sha=resource_attrs.get("git.commit.sha"),
                            normalized_at=normalized_at,
                        )
                    )

    return source_event_count


def normalize_otel_capture(
    raw_capture: Any, *, source_system: str, normalized_at: str | None = None
) -> NormalizationResult:
    state = NormalizationState(
        events=[],
        hardening_candidates=[],
        signal_counts={"trace": 0, "log": 0, "metric": 0},
    )
    normalized_at_value = normalized_at or _now()
    source_system_value = (
        source_system
        if source_system in {"opencode", "otel_collector", "unknown"}
        else "unknown"
    )

    if isinstance(raw_capture, list):
        raw_capture = {"resourceSpans": raw_capture}

    if not isinstance(raw_capture, dict):
        raw_capture = {}

    trace_count = _normalize_trace_spans(
        raw_capture.get("resourceSpans", []),
        source_system=source_system_value,
        normalized_at=normalized_at_value,
        state=state,
    )
    log_count = _normalize_log_records(
        raw_capture.get("resourceLogs", []),
        source_system=source_system_value,
        normalized_at=normalized_at_value,
        state=state,
    )
    metric_count = _normalize_metric_datapoints(
        raw_capture.get("resourceMetrics", []),
        source_system=source_system_value,
        normalized_at=normalized_at_value,
        state=state,
    )

    state.source_event_count += trace_count + log_count + metric_count
    dropped_count = state.source_event_count - len(state.events)

    return NormalizationResult(
        events=state.events,
        source_event_count=state.source_event_count,
        normalized_event_count=len(state.events),
        dropped_event_count=dropped_count,
        redaction_summary={
            "redacted_count": state.redacted_count,
            "hashed_count": state.hashed_count,
            "dropped_count": dropped_count,
        },
        hardening_candidates=state.hardening_candidates,
        missing_trace_id_count=state.missing_trace_id_count,
        missing_parent_span_id_count=state.missing_parent_span_id_count,
        signal_counts=state.signal_counts,
    )
