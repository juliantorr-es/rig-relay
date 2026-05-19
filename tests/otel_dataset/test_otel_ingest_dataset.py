from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

pytestmark = [pytest.mark.contract, pytest.mark.integration, pytest.mark.real_artifact]

from rig_relay.otel_dataset._ingest import ingest_otel_dataset
from scripts.rig_otel_ingest_dataset import main as ingest_main


def _write_raw_capture(
    path: Path, *, trace_id: str = "0123456789abcdef0123456789abcdef"
) -> None:
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
                "scopeSpans": [
                    {
                        "scope": {"name": "opencode"},
                        "spans": [
                            {
                                "traceId": trace_id,
                                "spanId": "0123456789abcdef",
                                "parentSpanId": "fedcba9876543210",
                                "name": "tool.call",
                                "kind": 2,
                                "startTimeUnixNano": "1000000000",
                                "endTimeUnixNano": "2000000000",
                                "status": {"code": 2, "message": "failed"},
                                "attributes": [
                                    {
                                        "key": "tool.name",
                                        "value": {"stringValue": "bash"},
                                    },
                                    {
                                        "key": "tool.category",
                                        "value": {"stringValue": "shell"},
                                    },
                                    {
                                        "key": "gen_ai.request.model",
                                        "value": {"stringValue": "gpt-4.1"},
                                    },
                                    {
                                        "key": "prompt",
                                        "value": {"stringValue": "do private thing"},
                                    },
                                    {
                                        "key": "api_key",
                                        "value": {"stringValue": "sk-test-123"},
                                    },
                                ],
                            }
                        ],
                    }
                ],
            }
        ]
    }
    path.write_text(json.dumps(raw), encoding="utf-8")


def _write_raw_capture_with_metrics_and_logs(path: Path) -> None:
    raw = {
        "resourceLogs": [
            {
                "resource": {"attributes": []},
                "scopeLogs": [
                    {
                        "logRecords": [
                            {
                                "timeUnixNano": "3000000000",
                                "severityText": "INFO",
                                "body": {"stringValue": "hello"},
                                "attributes": [
                                    {
                                        "key": "tool.name",
                                        "value": {"stringValue": "bash"},
                                    },
                                    {
                                        "key": "tool.category",
                                        "value": {"stringValue": "shell"},
                                    },
                                ],
                            }
                        ]
                    }
                ],
            }
        ],
        "resourceMetrics": [
            {
                "resource": {"attributes": []},
                "scopeMetrics": [
                    {
                        "metrics": [
                            {
                                "name": "tool.duration",
                                "unit": "ms",
                                "gauge": {
                                    "dataPoints": [
                                        {
                                            "asDouble": 42.0,
                                            "attributes": [
                                                {
                                                    "key": "tool.category",
                                                    "value": {"stringValue": "shell"},
                                                }
                                            ],
                                        }
                                    ]
                                },
                            }
                        ]
                    }
                ],
            }
        ],
    }
    path.write_text(json.dumps(raw), encoding="utf-8")


def test_valid_minimal_trace_export_normalizes_into_jsonl(tmp_path: Path) -> None:
    raw_path = tmp_path / "otel_raw.json"
    _write_raw_capture(raw_path)

    result = ingest_otel_dataset(
        input_path=raw_path,
        run_id="run-1",
        output_root=tmp_path / "normalized",
        source_system="opencode",
    )

    assert result["ingest_verdict"] == "pass"
    normalized = Path(result["normalized_events_path_absolute"])
    assert normalized.is_file()
    rows = [
        json.loads(line) for line in normalized.read_text(encoding="utf-8").splitlines()
    ]
    assert rows
    assert rows[0]["schema_version"] == "rig.otel.normalized_event.v1"
    assert rows[0]["source_signal"] == "trace"


def test_malformed_raw_json_is_rejected(tmp_path: Path) -> None:
    raw_path = tmp_path / "bad.json"
    raw_path.write_text('{"unclosed": true', encoding="utf-8")

    with pytest.raises(ValueError):
        ingest_otel_dataset(
            input_path=raw_path,
            run_id="run-2",
            output_root=tmp_path / "normalized",
            source_system="opencode",
        )


def test_missing_trace_id_creates_hardening_candidate(tmp_path: Path) -> None:
    raw_path = tmp_path / "otel_raw.json"
    _write_raw_capture(raw_path, trace_id="")

    result = ingest_otel_dataset(
        input_path=raw_path,
        run_id="run-3",
        output_root=tmp_path / "normalized",
        source_system="opencode",
    )

    summary = json.loads(
        Path(result["tool_behavior_summary_path_absolute"]).read_text(encoding="utf-8")
    )
    assert any(
        candidate["kind"] == "missing_trace_id"
        for candidate in summary["hardening_candidates"]
    )


def test_missing_parent_span_id_is_allowed_and_counted(tmp_path: Path) -> None:
    raw_path = tmp_path / "otel_raw.json"
    _write_raw_capture(raw_path)
    raw = json.loads(raw_path.read_text(encoding="utf-8"))
    raw["resourceSpans"][0]["scopeSpans"][0]["spans"][0].pop("parentSpanId")
    raw_path.write_text(json.dumps(raw), encoding="utf-8")

    result = ingest_otel_dataset(
        input_path=raw_path,
        run_id="run-4",
        output_root=tmp_path / "normalized",
        source_system="opencode",
    )

    summary = json.loads(
        Path(result["tool_behavior_summary_path_absolute"]).read_text(encoding="utf-8")
    )
    assert summary["missing_parent_span_id_count"] == 1


def test_cli_writes_all_expected_artifacts(tmp_path: Path) -> None:
    raw_path = tmp_path / "otel_raw.json"
    _write_raw_capture(raw_path)

    result = ingest_otel_dataset(
        input_path=raw_path,
        run_id="run-5",
        output_root=tmp_path / "normalized",
        source_system="opencode",
    )

    assert Path(result["raw_capture_manifest_path_absolute"]).is_file()
    assert Path(result["normalized_events_path_absolute"]).is_file()
    assert Path(result["tool_behavior_summary_path_absolute"]).is_file()
    assert Path(result["ingest_report_path_absolute"]).is_file()


def test_cli_rejects_malformed_input_without_writing_outputs(tmp_path: Path) -> None:
    raw_path = tmp_path / "bad.json"
    raw_path.write_text("{", encoding="utf-8")

    with pytest.raises(ValueError):
        ingest_otel_dataset(
            input_path=raw_path,
            run_id="run-6",
            output_root=tmp_path / "normalized",
            source_system="opencode",
        )

    assert not (tmp_path / "normalized").exists()


def test_cli_main_writes_all_expected_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw_path = tmp_path / "otel_raw.json"
    _write_raw_capture(raw_path)

    exit_code = ingest_main([
        "--input",
        str(raw_path),
        "--run-id",
        "run-12",
        "--output-root",
        str(tmp_path / "normalized"),
        "--source-system",
        "opencode",
    ])

    assert exit_code == 0
    assert (
        tmp_path / "normalized" / "run-12" / "otel_normalized_events.v1.jsonl"
    ).is_file()
    assert (tmp_path / "normalized" / "run-12" / "otel_ingest_report.v1.json").is_file()
    assert (tmp_path / "raw" / "run-12" / "otel_raw_capture_manifest.v1.json").is_file()


def test_cli_main_rejects_malformed_input(tmp_path: Path) -> None:
    raw_path = tmp_path / "bad.json"
    raw_path.write_text("{", encoding="utf-8")

    exit_code = ingest_main([
        "--input",
        str(raw_path),
        "--run-id",
        "run-13",
        "--output-root",
        str(tmp_path / "normalized"),
        "--source-system",
        "opencode",
    ])

    assert exit_code != 0


def test_dataset_does_not_write_to_coordination_ledger(tmp_path: Path) -> None:
    raw_path = tmp_path / "otel_raw.json"
    _write_raw_capture(raw_path)
    ingest_otel_dataset(
        input_path=raw_path,
        run_id="run-7",
        output_root=tmp_path / "normalized",
        source_system="opencode",
    )

    assert not (tmp_path / "normalized" / "coordination").exists()


def test_dataset_does_not_mutate_release_gate_evidence(tmp_path: Path) -> None:
    raw_path = tmp_path / "otel_raw.json"
    _write_raw_capture(raw_path)
    ingest_otel_dataset(
        input_path=raw_path,
        run_id="run-8",
        output_root=tmp_path / "normalized",
        source_system="opencode",
    )

    assert not (tmp_path / "normalized" / "release_gate").exists()


def test_raw_prompt_and_credentials_are_not_retained(tmp_path: Path) -> None:
    raw_path = tmp_path / "otel_raw.json"
    _write_raw_capture(raw_path)

    result = ingest_otel_dataset(
        input_path=raw_path,
        run_id="run-9",
        output_root=tmp_path / "normalized",
        source_system="opencode",
    )
    rows = [
        json.loads(line)
        for line in Path(result["normalized_events_path_absolute"])
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    event = rows[0]
    assert event["redaction_status"] in {"redacted", "hashed", "content_light"}
    assert "prompt" not in event["retained_attribute_keys"]
    assert "api_key" not in event["retained_attribute_keys"]


def test_absolute_paths_are_not_retained_in_normalized_events(tmp_path: Path) -> None:
    raw_path = tmp_path / "otel_raw.json"
    _write_raw_capture(raw_path)
    result = ingest_otel_dataset(
        input_path=raw_path,
        run_id="run-10",
        output_root=tmp_path / "normalized",
        source_system="opencode",
    )
    rows = [
        json.loads(line)
        for line in Path(result["normalized_events_path_absolute"])
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    event = rows[0]
    assert all(
        not str(value).startswith("/Users/user")
        for value in event.values()
        if isinstance(value, str)
    )


def test_normalized_events_validate_against_schema(tmp_path: Path) -> None:
    raw_path = tmp_path / "otel_raw.json"
    _write_raw_capture(raw_path)
    result = ingest_otel_dataset(
        input_path=raw_path,
        run_id="run-14",
        output_root=tmp_path / "normalized",
        source_system="opencode",
    )

    schema = json.loads(
        (
            Path(__file__).resolve().parents[2]
            / "docs/schemas/rig.otel.normalized_event.v1.schema.json"
        ).read_text(encoding="utf-8")
    )
    for line in (
        Path(result["normalized_events_path_absolute"])
        .read_text(encoding="utf-8")
        .splitlines()
    ):
        jsonschema.validate(json.loads(line), schema)


def test_ingest_report_validates_against_schema(tmp_path: Path) -> None:
    raw_path = tmp_path / "otel_raw.json"
    _write_raw_capture(raw_path)
    result = ingest_otel_dataset(
        input_path=raw_path,
        run_id="run-15",
        output_root=tmp_path / "normalized",
        source_system="opencode",
    )

    schema = json.loads(
        (
            Path(__file__).resolve().parents[2]
            / "docs/schemas/rig.otel.ingest_report.v1.schema.json"
        ).read_text(encoding="utf-8")
    )
    jsonschema.validate(
        json.loads(
            Path(result["ingest_report_path_absolute"]).read_text(encoding="utf-8")
        ),
        schema,
    )


def test_tool_behavior_summary_validates_against_schema(tmp_path: Path) -> None:
    raw_path = tmp_path / "otel_raw.json"
    _write_raw_capture(raw_path)
    result = ingest_otel_dataset(
        input_path=raw_path,
        run_id="run-16",
        output_root=tmp_path / "normalized",
        source_system="opencode",
    )

    schema = json.loads(
        (
            Path(__file__).resolve().parents[2]
            / "docs/schemas/rig.otel.tool_behavior_summary.v1.schema.json"
        ).read_text(encoding="utf-8")
    )
    jsonschema.validate(
        json.loads(
            Path(result["tool_behavior_summary_path_absolute"]).read_text(
                encoding="utf-8"
            )
        ),
        schema,
    )


def test_raw_capture_manifest_validates_against_schema(tmp_path: Path) -> None:
    raw_path = tmp_path / "otel_raw.json"
    _write_raw_capture(raw_path)
    result = ingest_otel_dataset(
        input_path=raw_path,
        run_id="run-17",
        output_root=tmp_path / "normalized",
        source_system="opencode",
    )

    schema = json.loads(
        (
            Path(__file__).resolve().parents[2]
            / "docs/schemas/rig.otel.raw_capture_manifest.v1.schema.json"
        ).read_text(encoding="utf-8")
    )
    jsonschema.validate(
        json.loads(
            Path(result["raw_capture_manifest_path_absolute"]).read_text(
                encoding="utf-8"
            )
        ),
        schema,
    )


def test_logs_and_metrics_are_tolerated(tmp_path: Path) -> None:
    raw_path = tmp_path / "otel_raw.json"
    _write_raw_capture_with_metrics_and_logs(raw_path)

    result = ingest_otel_dataset(
        input_path=raw_path,
        run_id="run-11",
        output_root=tmp_path / "normalized",
        source_system="opencode",
    )

    rows = [
        json.loads(line)
        for line in Path(result["normalized_events_path_absolute"])
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert any(row["source_signal"] == "log" for row in rows)
    assert any(row["source_signal"] == "metric" for row in rows)
