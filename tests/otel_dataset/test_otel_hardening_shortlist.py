from __future__ import annotations

import json
from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.contract,
    pytest.mark.integration,
    pytest.mark.real_artifact,
    pytest.mark.substrate,
]

from rig_relay.otel_dataset._aggregate import aggregate_otel_runs
from rig_relay.otel_dataset._ingest import ingest_otel_dataset


def _build_span(
    *,
    name: str = "tool.call",
    trace_id: str = "0123456789abcdef0123456789abcdef",
    span_id: str = "0123456789abcdef",
    parent_span_id: str = "fedcba9876543210",
    tool_name: str = "bash",
    tool_category: str | None = "shell",
    status_code: int = 1,
    status_message: str = "ok",
    start_ns: int = 1_000_000_000,
    duration_ns: int = 1_000_000_000,
    prompt: str | None = None,
    api_key: str | None = None,
) -> dict[str, object]:
    attributes = [{"key": "tool.name", "value": {"stringValue": tool_name}}]
    if tool_category is not None:
        attributes.append({
            "key": "tool.category",
            "value": {"stringValue": tool_category},
        })
    if prompt is not None:
        attributes.append({"key": "prompt", "value": {"stringValue": prompt}})
    if api_key is not None:
        attributes.append({"key": "api_key", "value": {"stringValue": api_key}})
    span: dict[str, object] = {
        "spanId": span_id,
        "name": name,
        "kind": 2,
        "startTimeUnixNano": str(start_ns),
        "endTimeUnixNano": str(start_ns + duration_ns),
        "status": {"code": status_code, "message": status_message},
        "attributes": attributes,
    }
    if trace_id:
        span["traceId"] = trace_id
    if parent_span_id:
        span["parentSpanId"] = parent_span_id
    return span


def _write_raw_capture(path: Path, *, spans: list[dict[str, object]]) -> None:
    raw = {
        "resourceSpans": [
            {
                "resource": {
                    "attributes": [
                        {
                            "key": "service.name",
                            "value": {"stringValue": "opencode-rig-relay-dev"},
                        },
                        {"key": "session.id", "value": {"stringValue": "sess-123"}},
                        {
                            "key": "workspace.path",
                            "value": {
                                "stringValue": "/Users/user/Developer/GitHub/rig-relay"
                            },
                        },
                        {"key": "git.branch", "value": {"stringValue": "main"}},
                        {"key": "git.commit.sha", "value": {"stringValue": "a2684d79"}},
                        {
                            "key": "gen_ai.provider.name",
                            "value": {"stringValue": "openai"},
                        },
                    ]
                },
                "scopeSpans": [{"scope": {"name": "opencode"}, "spans": spans}],
            }
        ]
    }
    path.write_text(json.dumps(raw), encoding="utf-8")


def _ingest_run(
    tmp_path: Path, run_id: str, *, spans: list[dict[str, object]]
) -> dict[str, object]:
    raw_path = tmp_path / f"{run_id}.json"
    _write_raw_capture(raw_path, spans=spans)
    return ingest_otel_dataset(
        input_path=raw_path,
        run_id=run_id,
        output_root=tmp_path / "normalized",
        source_system="opencode",
    )


def _aggregate(tmp_path: Path, *, aggregate_run_id: str) -> dict[str, object]:
    return aggregate_otel_runs(
        input_root=tmp_path / "normalized",
        aggregate_run_id=aggregate_run_id,
        output_root=tmp_path / "aggregate",
        min_runs=1,
        latency_p95_threshold_ms=1_000.0,
    )


def _candidate(report: dict[str, object], signal_kind: str) -> dict[str, object]:
    shortlist = json.loads(
        Path(report["hardening_shortlist_path_absolute"]).read_text(encoding="utf-8")
    )
    for candidate in shortlist["candidates"]:
        if candidate["signal_kind"] == signal_kind:
            return candidate
    raise AssertionError(f"Missing candidate for signal_kind={signal_kind}")


@pytest.mark.adversarial
def test_missing_trace_ids_produce_missing_trace_context_candidate(
    tmp_path: Path,
) -> None:
    _ingest_run(tmp_path, "run-1", spans=[_build_span(trace_id="", parent_span_id="")])
    _ingest_run(tmp_path, "run-2", spans=[_build_span()])

    report = _aggregate(tmp_path, aggregate_run_id="agg-missing-trace")
    candidate = _candidate(report, "missing_trace_context")

    assert candidate["affected_event_count"] >= 1
    assert candidate["missing_trace_id_count"] >= 1
    assert candidate["content_light_evidence_hashes"]


@pytest.mark.adversarial
def test_high_latency_produces_latency_candidate(tmp_path: Path) -> None:
    _ingest_run(tmp_path, "run-1", spans=[_build_span(duration_ns=4_000_000_000)])
    _ingest_run(tmp_path, "run-2", spans=[_build_span()])

    report = _aggregate(tmp_path, aggregate_run_id="agg-latency")
    candidate = _candidate(report, "latency")

    assert candidate["p95_duration_ms"] >= 1_000
    assert candidate["severity"] in {"medium", "high", "critical"}


@pytest.mark.adversarial
def test_repeated_error_events_produce_error_rate_candidate(tmp_path: Path) -> None:
    _ingest_run(
        tmp_path,
        "run-1",
        spans=[
            _build_span(status_code=2, status_message="failed"),
            _build_span(name="tool.call-2", status_code=2, status_message="failed"),
            _build_span(name="tool.call-3", status_code=2, status_message="failed"),
        ],
    )
    _ingest_run(tmp_path, "run-2", spans=[_build_span()])

    report = _aggregate(tmp_path, aggregate_run_id="agg-errors")
    candidate = _candidate(report, "error_rate")

    assert candidate["error_count"] >= 2
    assert candidate["affected_tool_category"] == "shell"


@pytest.mark.adversarial
def test_repeated_similar_spans_produce_retry_loop_candidate(tmp_path: Path) -> None:
    _ingest_run(
        tmp_path,
        "run-1",
        spans=[
            _build_span(name="tool.call", status_code=1),
            _build_span(name="tool.call", span_id="0123456789abcdee", status_code=1),
            _build_span(name="tool.call", span_id="0123456789abcdff", status_code=1),
        ],
    )
    _ingest_run(tmp_path, "run-2", spans=[_build_span()])

    report = _aggregate(tmp_path, aggregate_run_id="agg-retry")
    candidate = _candidate(report, "retry_loop")

    assert candidate["retry_count"] >= 2
    assert candidate["recommended_hardening_action"]


@pytest.mark.adversarial
def test_redaction_heavy_runs_produce_redaction_pressure_candidate(
    tmp_path: Path,
) -> None:
    _ingest_run(
        tmp_path,
        "run-1",
        spans=[
            _build_span(prompt="do private thing", api_key="sk-test-123"),
            _build_span(
                name="tool.call-2", prompt="more private text", api_key="sk-test-456"
            ),
        ],
    )
    _ingest_run(tmp_path, "run-2", spans=[_build_span()])

    report = _aggregate(tmp_path, aggregate_run_id="agg-redaction")
    candidate = _candidate(report, "redaction_pressure")

    assert candidate["redaction_drop_count"] >= 1
    assert candidate["content_light_evidence_hashes"]


@pytest.mark.adversarial
def test_unknown_tool_categories_produce_unknown_tool_category_candidate(
    tmp_path: Path,
) -> None:
    _ingest_run(
        tmp_path,
        "run-1",
        spans=[_build_span(tool_category=None, tool_name="custom-tool")],
    )
    _ingest_run(tmp_path, "run-2", spans=[_build_span()])

    report = _aggregate(tmp_path, aggregate_run_id="agg-unknown")
    candidate = _candidate(report, "unknown_tool_category")

    assert candidate["affected_tool_category"] == "unknown"
    assert candidate["affected_event_count"] >= 1
