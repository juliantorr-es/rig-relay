from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

HIGH_LATENCY_P95_MS = 1000.0
RETRY_LOOP_MIN_COUNT = 3


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * (percentile / 100)
    lower = int(rank)
    upper = min(lower + 1, len(ordered) - 1)
    weight = rank - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def _normalize_status_code(value: Any) -> str:
    if isinstance(value, str):
        upper = value.upper()
        if upper in {"OK", "ERROR", "UNSET", "INFO", "CANCELLED", "TIMEOUT", "UNKNOWN"}:
            return upper
        return "UNKNOWN"
    if value in {0, 1, 2}:
        return {0: "UNSET", 1: "OK", 2: "ERROR"}[int(value)]
    return "UNKNOWN"


def _category_durations(events: list[dict[str, Any]], category: str) -> list[float]:
    return [
        float(event["duration_ms"])
        for event in events
        if (event.get("tool_category") or "unknown") == category
        and isinstance(event.get("duration_ms"), (int, float))
    ]


def build_tool_behavior_summary(
    events: list[dict[str, Any]],
    *,
    run_id: str,
    generated_at: str,
    source_event_count: int,
    normalized_event_count: int,
    dropped_event_count: int,
    redaction_summary: dict[str, int],
    hardening_candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    trace_events = [
        event for event in events if event.get("source_signal", "trace") == "trace"
    ]
    durations = [
        float(event["duration_ms"])
        for event in trace_events
        if isinstance(event.get("duration_ms"), (int, float))
    ]
    tool_events = [event for event in trace_events if event.get("tool_category")]

    tool_counts = Counter(
        event.get("tool_category", "unknown") or "unknown" for event in tool_events
    )
    error_by_tool_category = Counter(
        event.get("tool_category", "unknown") or "unknown"
        for event in tool_events
        if _normalize_status_code(event.get("status_code")) == "ERROR"
    )
    status_by_tool_category: dict[str, dict[str, int]] = defaultdict(
        lambda: defaultdict(int)
    )
    for event in tool_events:
        category = event.get("tool_category", "unknown") or "unknown"
        status = _normalize_status_code(event.get("status_code"))
        status_by_tool_category[category][status] += 1

    repeated_groups = Counter(
        (
            event.get("tool_category", "unknown") or "unknown",
            event.get("span_name", "unknown"),
            event.get("tool_name_hash"),
        )
        for event in tool_events
    )
    retry_count = sum(count - 1 for count in repeated_groups.values() if count > 1)

    hardening = list(hardening_candidates)
    if any(not event.get("trace_id") for event in trace_events):
        hardening.append({
            "kind": "missing_trace_id",
            "description": "One or more spans are missing trace ids",
            "count": sum(1 for event in trace_events if not event.get("trace_id")),
        })
    if any(not event.get("parent_span_id") for event in trace_events):
        hardening.append({
            "kind": "missing_parent_span_id",
            "description": "One or more spans are missing parent span ids",
            "count": sum(
                1 for event in trace_events if not event.get("parent_span_id")
            ),
        })
    for category, count in tool_counts.items():
        category_durations = _category_durations(tool_events, category)
        if (
            category_durations
            and _percentile(category_durations, 95) >= HIGH_LATENCY_P95_MS
        ):
            hardening.append({
                "kind": "high_latency_tool_category",
                "description": "Tool category shows high tail latency",
                "tool_category": category,
                "count": count,
                "p95_duration_ms": round(_percentile(category_durations, 95), 3),
            })
        if count >= RETRY_LOOP_MIN_COUNT and retry_count > 0:
            hardening.append({
                "kind": "retry_loop",
                "description": "Repeated spans suggest retries",
                "tool_category": category,
                "count": retry_count,
            })

    return {
        "schema_version": "rig.otel.tool_behavior_summary.v1",
        "run_id": run_id,
        "generated_at": generated_at,
        "source_event_count": source_event_count,
        "normalized_event_count": normalized_event_count,
        "dropped_event_count": dropped_event_count,
        "tool_call_count": len(tool_events),
        "error_count": sum(error_by_tool_category.values()),
        "timeout_count": sum(
            1
            for event in tool_events
            if _normalize_status_code(event.get("status_code")) == "TIMEOUT"
            or "timeout" in str(event.get("span_name", "")).lower()
        ),
        "retry_count": retry_count,
        "cancellation_count": sum(
            1
            for event in tool_events
            if _normalize_status_code(event.get("status_code")) == "CANCELLED"
            or "cancel" in str(event.get("span_name", "")).lower()
        ),
        "total_duration_ms": round(sum(durations), 3),
        "p50_duration_ms": round(_percentile(durations, 50), 3),
        "p95_duration_ms": round(_percentile(durations, 95), 3),
        "p99_duration_ms": round(_percentile(durations, 99), 3),
        "top_tool_categories": [
            {
                "tool_category": category,
                "count": count,
                "error_count": error_by_tool_category.get(category, 0),
                "p95_duration_ms": round(
                    _percentile(
                        [
                            float(event["duration_ms"])
                            for event in tool_events
                            if (event.get("tool_category") or "unknown") == category
                            and isinstance(event.get("duration_ms"), (int, float))
                        ],
                        95,
                    ),
                    3,
                ),
            }
            for category, count in tool_counts.most_common()
        ],
        "error_by_tool_category": dict(error_by_tool_category),
        "status_by_tool_category": {
            category: dict(status_counts)
            for category, status_counts in status_by_tool_category.items()
        },
        "redaction_summary": dict(redaction_summary),
        "hardening_candidates": hardening,
        "missing_trace_id_count": sum(
            1 for event in trace_events if not event.get("trace_id")
        ),
        "missing_parent_span_id_count": sum(
            1 for event in trace_events if not event.get("parent_span_id")
        ),
    }
