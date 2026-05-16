from __future__ import annotations

import gzip
import json
from pathlib import Path

import pytest

from scripts.analyze_relay_tool_usage import (
    analyze_relay,
    infer_risk_tier,
    main,
    normalize_tool_name,
)

pytestmark = [pytest.mark.migration]

def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")


def test_parses_jsonl_tool_events(tmp_path: Path) -> None:
    root = tmp_path / "relay"
    _write_jsonl(
        root / "sessions" / "s1" / "observability.jsonl",
        [
            {
                "event_name": "rig.relay.tool.call_completed",
                "payload": {
                    "tool_name": "search_replace",
                    "status": "success",
                    "duration_ms": 10,
                },
            },
            {
                "event_name": "rig.relay.tool.call_completed",
                "payload": {
                    "tool_name": "search_replace",
                    "status": "error",
                    "duration_ms": 20,
                },
            },
        ],
    )
    aggregate = analyze_relay(root)
    tool = next(
        row for row in aggregate["tools"] if row["tool_name"] == "search_replace"
    )
    assert tool["count"] == 2
    assert tool["success_count"] == 1
    assert tool["failure_count"] == 1


def test_parses_json_receipts(tmp_path: Path) -> None:
    root = tmp_path / "relay"
    _write_jsonl(
        root / "sessions" / "s1" / "receipts.jsonl",
        [{"tool_name": "write_file", "status": "success", "output_bytes": 99}],
    )
    aggregate = analyze_relay(root)
    assert any(row["tool_name"] == "write_file" for row in aggregate["tools"])


def test_tolerates_malformed_records(tmp_path: Path) -> None:
    root = tmp_path / "relay"
    path = root / "sessions" / "s1" / "observability.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        '{"tool_name":"bash","status":"success"}\nnot json\n', encoding="utf-8"
    )
    aggregate = analyze_relay(root)
    assert aggregate["parseable_records"] == 1
    assert aggregate["malformed_records"] >= 1


def test_content_light_aggregate_json(tmp_path: Path) -> None:
    root = tmp_path / "relay"
    _write_jsonl(
        root / "sessions" / "s1" / "observability.jsonl",
        [
            {
                "tool_name": "browser",
                "status": "success",
                "args": {"secret": "x"},
                "output": "raw",
            }
        ],
    )
    aggregate = analyze_relay(root)
    assert "args" not in aggregate["tools"][0]
    assert aggregate["schema_gaps"]["raw_content_keys_seen"]["args"] == 1


def test_risk_tier_classification() -> None:
    assert infer_risk_tier("search_replace") == 1
    assert infer_risk_tier("write_file") == 2
    assert infer_risk_tier("bash") == 3
    assert infer_risk_tier("git_commit") == 4
    assert infer_risk_tier("google_drive_upload") == 5
    assert infer_risk_tier("gc_artifacts") == 6


def test_jsonl_gz_support(tmp_path: Path) -> None:
    root = tmp_path / "relay"
    path = root / "sessions" / "s1" / "observability.jsonl.gz"
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        handle.write(
            json.dumps({"tool_name": "search_replace", "status": "success"}) + "\n"
        )
    aggregate = analyze_relay(root, include_gz=True)
    assert aggregate["tool_event_records"] == 1


def test_normalize_tool_name_from_event_payload() -> None:
    row = {
        "event_name": "rig.relay.tool.call_completed",
        "payload": {"tool_name": "search_replace"},
    }
    assert normalize_tool_name(row) == "search_replace"


def test_main_writes_reports(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "relay"
    out = tmp_path / "out"
    _write_jsonl(
        root / "sessions" / "s1" / "observability.jsonl",
        [{"tool_name": "bash", "status": "success"}],
    )
    exit_code = main(["--relay-root", str(root), "--out", str(out)])
    assert exit_code == 0
    assert (out / "tool-usage-summary.md").is_file()
    assert (out / "tool-usage-aggregates.json").is_file()
