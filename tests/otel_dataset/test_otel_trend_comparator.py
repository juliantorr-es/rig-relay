from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

pytestmark = [
    pytest.mark.contract,
    pytest.mark.integration,
    pytest.mark.real_artifact,
    pytest.mark.substrate,
]

from rig_relay.otel_dataset._aggregate import aggregate_otel_runs
from rig_relay.otel_dataset._ingest import ingest_otel_dataset
from rig_relay.otel_dataset._trend import compare_otel_aggregate_runs
from scripts.rig_otel_compare_trends import main as compare_main

REPO_ROOT = Path(__file__).resolve().parents[2]


def _schema(name: str) -> dict[str, object]:
    return json.loads(
        (REPO_ROOT / "docs" / "schemas" / f"{name}.schema.json").read_text(
            encoding="utf-8"
        )
    )


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
        "startTimeUnixNano": "1000000000",
        "endTimeUnixNano": str(1_000_000_000 + duration_ns),
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


def _build_aggregate_run(
    tmp_path: Path,
    *,
    aggregate_run_id: str,
    spans: list[dict[str, object]],
    run_id: str,
) -> dict[str, object]:
    normalized_root = tmp_path / f"normalized-{aggregate_run_id}"
    raw_path = tmp_path / f"{aggregate_run_id}.json"
    _write_raw_capture(raw_path, spans=spans)
    ingest_otel_dataset(
        input_path=raw_path,
        run_id=run_id,
        output_root=normalized_root,
        source_system="opencode",
    )
    return aggregate_otel_runs(
        input_root=normalized_root,
        aggregate_run_id=aggregate_run_id,
        output_root=tmp_path / "aggregate",
        min_runs=1,
        latency_p95_threshold_ms=1_000.0,
    )


def _read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_trend_artifacts(
    report: dict[str, object],
) -> tuple[dict[str, object], dict[str, object]]:
    trend_report = _read_json(Path(report["trend_report_path_absolute"]))
    deltas = _read_json(Path(report["hardening_deltas_path_absolute"]))
    return trend_report, deltas


def _delta_by_signal(deltas: dict[str, object], signal_kind: str) -> dict[str, object]:
    for delta in deltas["deltas"]:
        if delta["signal_kind"] == signal_kind:
            return delta
    raise AssertionError(f"Missing delta for signal_kind={signal_kind}")


def _make_low_latency_run(
    tmp_path: Path, aggregate_run_id: str, *, tool_category: str = "shell"
) -> dict[str, object]:
    return _build_aggregate_run(
        tmp_path,
        aggregate_run_id=aggregate_run_id,
        run_id=f"{aggregate_run_id}-run",
        spans=[_build_span(tool_category=tool_category, duration_ns=100_000_000)],
    )


def _make_high_latency_run(
    tmp_path: Path,
    aggregate_run_id: str,
    *,
    tool_category: str = "shell",
    duration_ns: int = 4_000_000_000,
) -> dict[str, object]:
    return _build_aggregate_run(
        tmp_path,
        aggregate_run_id=aggregate_run_id,
        run_id=f"{aggregate_run_id}-run",
        spans=[_build_span(tool_category=tool_category, duration_ns=duration_ns)],
    )


def _make_redaction_run(tmp_path: Path, aggregate_run_id: str) -> dict[str, object]:
    return _build_aggregate_run(
        tmp_path,
        aggregate_run_id=aggregate_run_id,
        run_id=f"{aggregate_run_id}-run",
        spans=[
            _build_span(prompt="do private thing", api_key="sk-test-123"),
            _build_span(
                name="tool.call-2", prompt="more private thing", api_key="sk-test-456"
            ),
            _build_span(
                name="tool.call-3",
                prompt="even more private thing",
                api_key="sk-test-789",
            ),
            _build_span(
                name="tool.call-4",
                prompt="sensitive content again",
                api_key="sk-test-abc",
            ),
            _build_span(
                name="tool.call-5",
                prompt="last sensitive content",
                api_key="sk-test-def",
            ),
        ],
    )


def _make_missing_trace_run(tmp_path: Path, aggregate_run_id: str) -> dict[str, object]:
    return _build_aggregate_run(
        tmp_path,
        aggregate_run_id=aggregate_run_id,
        run_id=f"{aggregate_run_id}-run",
        spans=[_build_span(trace_id="", parent_span_id="")],
    )


def test_trend_report_schema_validates(tmp_path: Path) -> None:
    _make_high_latency_run(tmp_path, "agg-1")
    _make_low_latency_run(tmp_path, "agg-2")

    report = compare_otel_aggregate_runs(
        input_root=tmp_path / "aggregate",
        trend_run_id="trend-1",
        output_root=tmp_path / "trends",
    )
    trend_report, _ = _load_trend_artifacts(report)

    jsonschema.validate(trend_report, _schema("rig.otel.trend_report.v1"))
    assert trend_report["local_only"] is True
    assert trend_report["coordination_ledger_mutated"] is False
    assert trend_report["release_gate_mutated"] is False


def test_hardening_delta_schema_validates(tmp_path: Path) -> None:
    _make_high_latency_run(tmp_path, "agg-1")
    _make_low_latency_run(tmp_path, "agg-2")

    report = compare_otel_aggregate_runs(
        input_root=tmp_path / "aggregate",
        trend_run_id="trend-2",
        output_root=tmp_path / "trends",
    )
    _, deltas = _load_trend_artifacts(report)

    jsonschema.validate(deltas, _schema("rig.otel.hardening_delta.v1"))
    assert deltas["trend_run_id"] == "trend-2"


def test_comparator_reads_two_real_aggregate_run_directories(tmp_path: Path) -> None:
    _make_high_latency_run(tmp_path, "agg-1")
    _make_low_latency_run(tmp_path, "agg-2")

    report = compare_otel_aggregate_runs(
        input_root=tmp_path / "aggregate",
        trend_run_id="trend-3",
        output_root=tmp_path / "trends",
    )

    assert report["input_aggregate_count"] == 2
    assert report["trend_verdict"] == "pass"


def test_fewer_than_two_runs_produces_hold_and_insufficient_sample(
    tmp_path: Path,
) -> None:
    _make_high_latency_run(tmp_path, "agg-1")

    report = compare_otel_aggregate_runs(
        input_root=tmp_path / "aggregate",
        trend_run_id="trend-4",
        output_root=tmp_path / "trends",
    )

    trend_report, deltas = _load_trend_artifacts(report)
    assert report["trend_verdict"] == "hold"
    assert trend_report["trend_summary"]["insufficient_sample_count"] >= 1
    assert all(
        delta["trend_class"] == "insufficient_sample" for delta in deltas["deltas"]
    )


@pytest.mark.adversarial
def test_persistent_latency_in_repeated_runs_becomes_persistent_pain(
    tmp_path: Path,
) -> None:
    _make_high_latency_run(tmp_path, "agg-1")
    _make_high_latency_run(tmp_path, "agg-2")

    report = compare_otel_aggregate_runs(
        input_root=tmp_path / "aggregate",
        trend_run_id="trend-5",
        output_root=tmp_path / "trends",
    )
    deltas = _load_trend_artifacts(report)[1]
    delta = _delta_by_signal(deltas, "latency")

    assert delta["trend_class"] == "persistent_pain"
    assert delta["severity"] in {"medium", "high", "critical"}


@pytest.mark.adversarial
def test_newly_introduced_high_latency_category_becomes_new_regression(
    tmp_path: Path,
) -> None:
    _make_low_latency_run(tmp_path, "agg-1", tool_category="python")
    _make_high_latency_run(tmp_path, "agg-2", tool_category="python")

    report = compare_otel_aggregate_runs(
        input_root=tmp_path / "aggregate",
        trend_run_id="trend-6",
        output_root=tmp_path / "trends",
    )
    delta = _delta_by_signal(_load_trend_artifacts(report)[1], "latency")

    assert delta["trend_class"] == "new_regression"
    assert delta["affected_tool_category"] == "python"


@pytest.mark.adversarial
def test_improved_p95_latency_becomes_improved(tmp_path: Path) -> None:
    _make_high_latency_run(tmp_path, "agg-1")
    _build_aggregate_run(
        tmp_path,
        aggregate_run_id="agg-2",
        run_id="agg-2-run",
        spans=[_build_span(duration_ns=1_500_000_000)],
    )

    report = compare_otel_aggregate_runs(
        input_root=tmp_path / "aggregate",
        trend_run_id="trend-7",
        output_root=tmp_path / "trends",
    )
    delta = _delta_by_signal(_load_trend_artifacts(report)[1], "latency")

    assert delta["trend_class"] == "improved"
    assert delta["latest_metrics"]["p95_duration_ms"] == 1_500.0


@pytest.mark.adversarial
def test_one_run_candidate_that_disappears_becomes_one_off_noise(
    tmp_path: Path,
) -> None:
    _make_high_latency_run(tmp_path, "agg-1")
    _make_low_latency_run(tmp_path, "agg-2")

    report = compare_otel_aggregate_runs(
        input_root=tmp_path / "aggregate",
        trend_run_id="trend-8",
        output_root=tmp_path / "trends",
    )
    delta = _delta_by_signal(_load_trend_artifacts(report)[1], "latency")

    assert delta["trend_class"] == "one_off_noise"


@pytest.mark.adversarial
def test_redaction_drop_increase_becomes_redaction_pressure_trend(
    tmp_path: Path,
) -> None:
    _make_low_latency_run(tmp_path, "agg-1")
    _make_redaction_run(tmp_path, "agg-2")
    _make_redaction_run(tmp_path, "agg-3")

    report = compare_otel_aggregate_runs(
        input_root=tmp_path / "aggregate",
        trend_run_id="trend-9",
        output_root=tmp_path / "trends",
    )
    trend_report, deltas = _load_trend_artifacts(report)

    assert trend_report["trend_summary"]["redaction_pressure_trend"] == "worsening"
    assert _delta_by_signal(deltas, "redaction_pressure")["trend_class"] in {
        "new_regression",
        "persistent_pain",
    }


@pytest.mark.adversarial
def test_missing_trace_context_trend_is_counted(tmp_path: Path) -> None:
    _make_missing_trace_run(tmp_path, "agg-1")
    _make_missing_trace_run(tmp_path, "agg-2")

    report = compare_otel_aggregate_runs(
        input_root=tmp_path / "aggregate",
        trend_run_id="trend-10",
        output_root=tmp_path / "trends",
    )
    trend_report, deltas = _load_trend_artifacts(report)

    assert trend_report["trend_summary"]["trace_context_quality_trend"] == "worsening"
    assert trend_report["trend_summary"]["insufficient_sample_count"] == 0
    assert (
        _delta_by_signal(deltas, "missing_trace_context")["latest_metrics"][
            "affected_event_count"
        ]
        >= 1
    )


def test_malformed_aggregate_report_is_rejected(tmp_path: Path) -> None:
    _make_high_latency_run(tmp_path, "agg-1")
    bad_run = _make_low_latency_run(tmp_path, "agg-2")
    Path(bad_run["aggregate_report_path_absolute"]).write_text("{", encoding="utf-8")

    with pytest.raises(ValueError):
        compare_otel_aggregate_runs(
            input_root=tmp_path / "aggregate",
            trend_run_id="trend-11",
            output_root=tmp_path / "trends",
        )


def test_missing_shortlist_file_produces_hold_or_fail(tmp_path: Path) -> None:
    _make_high_latency_run(tmp_path, "agg-1")
    bad_run = _make_low_latency_run(tmp_path, "agg-2")
    Path(bad_run["hardening_shortlist_path_absolute"]).unlink()

    report = compare_otel_aggregate_runs(
        input_root=tmp_path / "aggregate",
        trend_run_id="trend-12",
        output_root=tmp_path / "trends",
    )

    assert report["trend_verdict"] in {"hold", "fail"}


def test_output_artifacts_validate_against_schemas(tmp_path: Path) -> None:
    _make_high_latency_run(tmp_path, "agg-1")
    _make_low_latency_run(tmp_path, "agg-2")

    report = compare_otel_aggregate_runs(
        input_root=tmp_path / "aggregate",
        trend_run_id="trend-13",
        output_root=tmp_path / "trends",
    )
    trend_report, deltas = _load_trend_artifacts(report)

    jsonschema.validate(trend_report, _schema("rig.otel.trend_report.v1"))
    jsonschema.validate(deltas, _schema("rig.otel.hardening_delta.v1"))


def test_cli_writes_trend_report_and_delta_file(tmp_path: Path) -> None:
    _make_high_latency_run(tmp_path, "agg-1")
    _make_low_latency_run(tmp_path, "agg-2")

    exit_code = compare_main([
        "--input-root",
        str(tmp_path / "aggregate"),
        "--run-id",
        "trend-14",
        "--output-root",
        str(tmp_path / "trends"),
    ])

    assert exit_code == 0
    assert (tmp_path / "trends" / "trend-14" / "otel_trend_report.v1.json").is_file()
    assert (
        tmp_path / "trends" / "trend-14" / "otel_hardening_deltas.v1.json"
    ).is_file()


def test_cli_exits_2_on_insufficient_sample(tmp_path: Path) -> None:
    _make_high_latency_run(tmp_path, "agg-1")

    exit_code = compare_main([
        "--input-root",
        str(tmp_path / "aggregate"),
        "--run-id",
        "trend-15",
        "--output-root",
        str(tmp_path / "trends"),
    ])

    assert exit_code == 2


def test_comparator_does_not_write_to_coordination_ledger(tmp_path: Path) -> None:
    _make_high_latency_run(tmp_path, "agg-1")
    _make_low_latency_run(tmp_path, "agg-2")

    compare_otel_aggregate_runs(
        input_root=tmp_path / "aggregate",
        trend_run_id="trend-16",
        output_root=tmp_path / "trends",
    )

    assert not (tmp_path / "trends" / "trend-16" / "coordination").exists()


def test_comparator_does_not_mutate_release_gate(tmp_path: Path) -> None:
    _make_high_latency_run(tmp_path, "agg-1")
    _make_low_latency_run(tmp_path, "agg-2")

    compare_otel_aggregate_runs(
        input_root=tmp_path / "aggregate",
        trend_run_id="trend-17",
        output_root=tmp_path / "trends",
    )

    assert not (tmp_path / "trends" / "trend-17" / "release_gate").exists()


def test_no_raw_absolute_paths_or_secret_values_in_trend_outputs(
    tmp_path: Path,
) -> None:
    _build_aggregate_run(
        tmp_path,
        aggregate_run_id="agg-1",
        run_id="agg-1-run",
        spans=[_build_span(prompt="do private thing", api_key="sk-test-123")],
    )
    _make_low_latency_run(tmp_path, "agg-2")

    report = compare_otel_aggregate_runs(
        input_root=tmp_path / "aggregate",
        trend_run_id="trend-18",
        output_root=tmp_path / "trends",
    )
    trend_report, deltas = _load_trend_artifacts(report)
    raw_payload = json.dumps(trend_report) + json.dumps(deltas)

    assert str(tmp_path) not in raw_payload
    assert "/Users/user" not in raw_payload
    assert "do private thing" not in raw_payload
    assert "sk-test-123" not in raw_payload
