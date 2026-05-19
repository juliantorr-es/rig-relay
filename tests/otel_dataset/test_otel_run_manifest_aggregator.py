from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

pytestmark = [pytest.mark.contract, pytest.mark.integration, pytest.mark.real_artifact]

from rig_relay.otel_dataset._aggregate import aggregate_otel_runs
from rig_relay.otel_dataset._ingest import ingest_otel_dataset
from scripts.rig_otel_aggregate_runs import main as aggregate_main

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


def _write_raw_capture(
    path: Path,
    *,
    spans: list[dict[str, object]],
    service_name: str = "opencode-rig-relay-dev",
    resource_attributes: list[dict[str, object]] | None = None,
) -> None:
    attributes = resource_attributes or [
        {"key": "service.name", "value": {"stringValue": service_name}},
        {"key": "session.id", "value": {"stringValue": "sess-123"}},
        {
            "key": "workspace.path",
            "value": {"stringValue": "/Users/user/Developer/GitHub/rig-relay"},
        },
        {"key": "git.branch", "value": {"stringValue": "main"}},
        {"key": "git.commit.sha", "value": {"stringValue": "a2684d79"}},
        {"key": "gen_ai.provider.name", "value": {"stringValue": "openai"}},
    ]
    raw = {
        "resourceSpans": [
            {
                "resource": {"attributes": attributes},
                "scopeSpans": [{"scope": {"name": "opencode"}, "spans": spans}],
            }
        ]
    }
    path.write_text(json.dumps(raw), encoding="utf-8")


def _ingest_run(
    tmp_path: Path,
    run_id: str,
    *,
    spans: list[dict[str, object]],
    resource_attributes: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    raw_path = tmp_path / f"{run_id}.json"
    _write_raw_capture(raw_path, spans=spans, resource_attributes=resource_attributes)
    return ingest_otel_dataset(
        input_path=raw_path,
        run_id=run_id,
        output_root=tmp_path / "normalized",
        source_system="opencode",
    )


def _aggregate(
    tmp_path: Path,
    *,
    aggregate_run_id: str = "aggregate-run",
    min_runs: int = 1,
    fail_on_schema_error: bool = False,
) -> dict[str, object]:
    return aggregate_otel_runs(
        input_root=tmp_path / "normalized",
        aggregate_run_id=aggregate_run_id,
        output_root=tmp_path / "aggregate",
        min_runs=min_runs,
        latency_p95_threshold_ms=1_000.0,
        fail_on_schema_error=fail_on_schema_error,
    )


def _read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _assert_no_raw_absolute_paths(value: object, forbidden: str) -> None:
    match value:
        case dict():
            for item in value.values():
                _assert_no_raw_absolute_paths(item, forbidden)
        case list():
            for item in value:
                _assert_no_raw_absolute_paths(item, forbidden)
        case str():
            assert forbidden not in value


def test_run_manifest_schema_validates(tmp_path: Path) -> None:
    _ingest_run(tmp_path, "run-1", spans=[_build_span()])
    _ingest_run(
        tmp_path, "run-2", spans=[_build_span(name="tool.other", tool_name="python")]
    )

    report = _aggregate(tmp_path, aggregate_run_id="agg-1")
    manifest = _read_json(Path(report["run_manifest_path_absolute"]))

    jsonschema.validate(manifest, _schema("rig.otel.run_manifest.v1"))
    assert manifest["input_run_count"] == 2
    assert manifest["content_light"] is True
    assert manifest["local_only"] is True


def test_hardening_shortlist_schema_validates(tmp_path: Path) -> None:
    _ingest_run(tmp_path, "run-1", spans=[_build_span()])
    _ingest_run(
        tmp_path, "run-2", spans=[_build_span(name="tool.other", tool_name="python")]
    )

    report = _aggregate(tmp_path, aggregate_run_id="agg-2")
    shortlist = _read_json(Path(report["hardening_shortlist_path_absolute"]))

    jsonschema.validate(shortlist, _schema("rig.otel.hardening_shortlist.v1"))
    assert shortlist["aggregate_run_id"] == "agg-2"


def test_aggregate_report_schema_validates(tmp_path: Path) -> None:
    _ingest_run(tmp_path, "run-1", spans=[_build_span()])
    _ingest_run(
        tmp_path, "run-2", spans=[_build_span(name="tool.other", tool_name="python")]
    )

    report = _aggregate(tmp_path, aggregate_run_id="agg-3")
    jsonschema.validate(
        _read_json(Path(report["aggregate_report_path_absolute"])),
        _schema("rig.otel.aggregate_report.v1"),
    )
    assert report["local_only"] is True
    assert report["coordination_ledger_mutated"] is False
    assert report["release_gate_mutated"] is False


def test_aggregator_reads_two_real_temp_run_directories(tmp_path: Path) -> None:
    run_a = _ingest_run(tmp_path, "run-a", spans=[_build_span()])
    run_b = _ingest_run(
        tmp_path, "run-b", spans=[_build_span(name="tool.other", tool_name="python")]
    )

    report = _aggregate(tmp_path, aggregate_run_id="agg-4")
    manifest = _read_json(Path(report["run_manifest_path_absolute"]))

    assert len(manifest["input_runs"]) == 2
    assert manifest["input_runs"][0]["event_count"] == 1
    assert run_a["ingest_report_path_absolute"]
    assert run_b["ingest_report_path_absolute"]


def test_aggregator_computes_sha256_for_all_input_artifacts(tmp_path: Path) -> None:
    _ingest_run(tmp_path, "run-1", spans=[_build_span()])
    _ingest_run(
        tmp_path, "run-2", spans=[_build_span(name="tool.other", tool_name="python")]
    )

    report = _aggregate(tmp_path, aggregate_run_id="agg-5")
    manifest = _read_json(Path(report["run_manifest_path_absolute"]))

    for item in manifest["input_runs"]:
        assert str(item["normalized_events_sha256"]).startswith("sha256:")
        assert str(item["ingest_report_sha256"]).startswith("sha256:")
        assert str(item["tool_behavior_summary_sha256"]).startswith("sha256:")


def test_missing_normalized_events_file_causes_hold_or_fail(tmp_path: Path) -> None:
    _ingest_run(tmp_path, "run-1", spans=[_build_span()])
    run_two = _ingest_run(
        tmp_path, "run-2", spans=[_build_span(name="tool.other", tool_name="python")]
    )
    Path(run_two["normalized_events_path_absolute"]).unlink()

    report = _aggregate(tmp_path, aggregate_run_id="agg-6")

    assert report["aggregate_verdict"] in {"hold", "fail"}


def test_malformed_ingest_report_is_rejected(tmp_path: Path) -> None:
    _ingest_run(tmp_path, "run-1", spans=[_build_span()])
    bad_run = _ingest_run(
        tmp_path, "run-2", spans=[_build_span(name="tool.other", tool_name="python")]
    )
    Path(bad_run["ingest_report_path_absolute"]).write_text("{", encoding="utf-8")

    with pytest.raises(ValueError):
        _aggregate(tmp_path, aggregate_run_id="agg-7")


def test_cli_writes_run_manifest_shortlist_and_report(tmp_path: Path) -> None:
    _ingest_run(tmp_path, "run-1", spans=[_build_span()])
    _ingest_run(
        tmp_path, "run-2", spans=[_build_span(name="tool.other", tool_name="python")]
    )

    exit_code = aggregate_main([
        "--input-root",
        str(tmp_path / "normalized"),
        "--run-id",
        "agg-8",
        "--output-root",
        str(tmp_path / "aggregate"),
    ])

    assert exit_code == 0
    assert (tmp_path / "aggregate" / "agg-8" / "otel_run_manifest.v1.json").is_file()
    assert (
        tmp_path / "aggregate" / "agg-8" / "otel_hardening_shortlist.v1.json"
    ).is_file()
    assert (
        tmp_path / "aggregate" / "agg-8" / "otel_aggregate_report.v1.json"
    ).is_file()


def test_cli_exits_non_zero_on_malformed_input(tmp_path: Path) -> None:
    _ingest_run(tmp_path, "run-1", spans=[_build_span()])
    bad_run = _ingest_run(
        tmp_path, "run-2", spans=[_build_span(name="tool.other", tool_name="python")]
    )
    Path(bad_run["ingest_report_path_absolute"]).write_text("{", encoding="utf-8")

    exit_code = aggregate_main([
        "--input-root",
        str(tmp_path / "normalized"),
        "--run-id",
        "agg-9",
        "--output-root",
        str(tmp_path / "aggregate"),
    ])

    assert exit_code != 0


def test_aggregator_does_not_write_to_coordination_ledger(tmp_path: Path) -> None:
    _ingest_run(tmp_path, "run-1", spans=[_build_span()])
    _ingest_run(
        tmp_path, "run-2", spans=[_build_span(name="tool.other", tool_name="python")]
    )

    _aggregate(tmp_path, aggregate_run_id="agg-10")

    assert not (tmp_path / "aggregate" / "agg-10" / "coordination").exists()


def test_aggregator_does_not_mutate_release_gate_evidence(tmp_path: Path) -> None:
    _ingest_run(tmp_path, "run-1", spans=[_build_span()])
    _ingest_run(
        tmp_path, "run-2", spans=[_build_span(name="tool.other", tool_name="python")]
    )

    _aggregate(tmp_path, aggregate_run_id="agg-11")

    assert not (tmp_path / "aggregate" / "agg-11" / "release_gate").exists()


def test_no_raw_absolute_paths_or_secret_values_in_outputs(tmp_path: Path) -> None:
    _ingest_run(
        tmp_path,
        "run-1",
        spans=[_build_span(prompt="do private thing", api_key="sk-test-123")],
    )
    _ingest_run(
        tmp_path, "run-2", spans=[_build_span(name="tool.other", tool_name="python")]
    )

    report = _aggregate(tmp_path, aggregate_run_id="agg-12")

    for key in (
        "run_manifest_path_absolute",
        "hardening_shortlist_path_absolute",
        "aggregate_report_path_absolute",
    ):
        payload = _read_json(Path(report[key]))
        _assert_no_raw_absolute_paths(payload, str(tmp_path))
        _assert_no_raw_absolute_paths(payload, "/Users/user")
        _assert_no_raw_absolute_paths(payload, "do private thing")
        _assert_no_raw_absolute_paths(payload, "sk-test-123")
