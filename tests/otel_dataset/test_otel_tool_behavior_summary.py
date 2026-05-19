from __future__ import annotations

from datetime import UTC, datetime

import pytest

pytestmark = [pytest.mark.contract, pytest.mark.integration]

from rig_relay.otel_dataset._summarize import build_tool_behavior_summary


def test_tool_duration_summary_computes_percentiles() -> None:
    summary = build_tool_behavior_summary(
        [
            {"tool_category": "bash", "duration_ms": 10, "status_code": "OK"},
            {"tool_category": "bash", "duration_ms": 20, "status_code": "ERROR"},
            {"tool_category": "bash", "duration_ms": 30, "status_code": "OK"},
            {"tool_category": "bash", "duration_ms": 40, "status_code": "OK"},
        ],
        run_id="run-1",
        generated_at=datetime.now(tz=UTC).isoformat(),
        source_event_count=4,
        normalized_event_count=4,
        dropped_event_count=0,
        redaction_summary={"redacted": 0, "hashed": 0},
        hardening_candidates=[],
    )

    assert summary["p50_duration_ms"] == 25
    assert summary["p95_duration_ms"] >= 30
    assert summary["p99_duration_ms"] >= 30


def test_error_spans_are_counted_by_tool_category() -> None:
    summary = build_tool_behavior_summary(
        [
            {"tool_category": "bash", "duration_ms": 10, "status_code": "ERROR"},
            {"tool_category": "python", "duration_ms": 20, "status_code": "OK"},
            {"tool_category": "bash", "duration_ms": 30, "status_code": "ERROR"},
        ],
        run_id="run-2",
        generated_at=datetime.now(tz=UTC).isoformat(),
        source_event_count=3,
        normalized_event_count=3,
        dropped_event_count=0,
        redaction_summary={"redacted": 0, "hashed": 0},
        hardening_candidates=[],
    )

    assert summary["error_by_tool_category"]["bash"] == 2
    assert summary["status_by_tool_category"]["bash"]["ERROR"] == 2


def test_retry_like_repeated_spans_are_summarized() -> None:
    summary = build_tool_behavior_summary(
        [
            {"tool_category": "bash", "span_name": "tool.call", "duration_ms": 10},
            {"tool_category": "bash", "span_name": "tool.call", "duration_ms": 11},
            {"tool_category": "bash", "span_name": "tool.call", "duration_ms": 12},
        ],
        run_id="run-3",
        generated_at=datetime.now(tz=UTC).isoformat(),
        source_event_count=3,
        normalized_event_count=3,
        dropped_event_count=0,
        redaction_summary={"redacted": 0, "hashed": 0},
        hardening_candidates=[],
    )

    assert summary["retry_count"] >= 2
