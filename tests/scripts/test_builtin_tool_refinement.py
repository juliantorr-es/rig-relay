from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import jsonschema
import pytest

from scripts.rig_relay_builtin_tool_refinement import (
    SCHEMA_PATH,
    _build_item,
    _build_summary_rows,
    run,
)


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")


def test_schema_validates_sample_item():
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    sample = {
        "schema_version": "rig.relay.builtin_tool_refinement_item.v1",
        "item_id": "refine_123",
        "created_at": "2026-05-13T00:00:00Z",
        "tool_name": "bash",
        "tool_family": "bash",
        "refinement_kind": "replace_shell_pattern",
        "priority": "P0",
        "confidence": 0.9,
        "evidence_window": "latest derived datasets present in .build/rig-relay/derived",
        "evidence_sources": ["tool_failure_patterns_dataset"],
        "event_count": 10,
        "failure_count": 2,
        "refusal_count": 1,
        "timeout_count": 0,
        "fallback_to_bash_count": 8,
        "truncation_count": 0,
        "artifact_size_bytes": 123,
        "storage_pressure_score": 0.0,
        "coordination_pressure_score": 0.0,
        "suggested_replacement_tool": "typed built-in",
        "recommended_action": "Create typed built-in.",
        "rationale": "Repeated fallback to bash indicates a typed surface would remove brittle shell parsing.",
        "safety_notes": "Content-light.",
        "warnings": [],
    }
    jsonschema.validate(instance=sample, schema=schema)


def test_missing_derived_dir_generates_partial_report_with_warnings(tmp_path: Path):
    output = tmp_path / "report.md"
    jsonl_output = tmp_path / "backlog.jsonl"
    rc = run(tmp_path / "missing", tmp_path, output, jsonl_output, strict=False)
    assert rc == 0
    text = output.read_text(encoding="utf-8")
    assert "Warnings" in text
    assert "Missing dataset" in text


def test_report_ranks_high_failure_tool_above_low_pressure_tool(tmp_path: Path):
    derived = tmp_path / "derived"
    _write_jsonl(
        derived / "tool_failure_patterns_dataset.jsonl",
        [{"tool_name": "bash", "status": "error"} for _ in range(5)]
        + [{"tool_name": "skill", "status": "ok"}],
    )
    rows, warnings = _build_summary_rows(derived)
    assert rows
    assert warnings
    items = [_build_item(row, "2026-05-13T00:00:00Z", derived) for row in rows]
    ranked = sorted(items, key=lambda r: (-r["_score"], r["tool_name"]))
    assert ranked[0]["tool_name"] == "bash"
    assert ranked[0]["priority"] in {"P0", "P1"}


def test_fallback_to_bash_creates_replace_shell_pattern_item(tmp_path: Path):
    derived = tmp_path / "derived"
    _write_jsonl(
        derived / "command_tool_opportunity_dataset.jsonl",
        [{"tool_name": "bash", "event_name": "shell fallback"} for _ in range(4)],
    )
    rows, _ = _build_summary_rows(derived)
    item = _build_item(rows[0], "2026-05-13T00:00:00Z", derived)
    assert item["refinement_kind"] == "replace_shell_pattern"


def test_storage_pressure_creates_reduce_artifact_weight_item(tmp_path: Path):
    derived = tmp_path / "derived"
    _write_jsonl(
        derived / "storage_audit.json",
        [{"tool_name": "reports", "storage_pressure_score": 5}],
    )
    rows, _ = _build_summary_rows(derived)
    item = _build_item(rows[0], "2026-05-13T00:00:00Z", derived)
    assert item["refinement_kind"] == "reduce_artifact_weight"


def test_semantic_change_pattern_creates_promote_or_harden_item(tmp_path: Path):
    derived = tmp_path / "derived"
    _write_jsonl(
        derived / "semantic_change_snippets.jsonl",
        [{"tool_name": "task", "change_kind": "coordination_event_added"}],
    )
    rows, _ = _build_summary_rows(derived)
    item = _build_item(rows[0], "2026-05-13T00:00:00Z", derived)
    assert item["refinement_kind"] in {
        "add_coordination_hook",
        "promote_to_builtin",
        "harden_existing_tool",
    }


def test_output_jsonl_validates_against_schema(tmp_path: Path):
    derived = tmp_path / "derived"
    reports = tmp_path / "reports"
    _write_jsonl(
        derived / "tool_failure_patterns_dataset.jsonl",
        [{"tool_name": "bash", "status": "error"}],
    )
    output = reports / "report.md"
    jsonl_output = derived / "backlog.jsonl"
    run(derived, reports, output, jsonl_output, strict=False)
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    for line in jsonl_output.read_text(encoding="utf-8").splitlines():
        jsonschema.validate(instance=json.loads(line), schema=schema)


def test_report_contains_no_forbidden_raw_fields(tmp_path: Path):
    derived = tmp_path / "derived"
    _write_jsonl(
        derived / "tool_failure_patterns_dataset.jsonl",
        [{"tool_name": "bash", "status": "error"}],
    )
    output = tmp_path / "report.md"
    jsonl_output = tmp_path / "backlog.jsonl"
    run(derived, tmp_path, output, jsonl_output, strict=False)
    text = output.read_text(encoding="utf-8")
    assert "stdout" not in text
    assert "stderr" not in text
    assert "prompt" not in text


def test_strict_mode_fails_when_required_files_missing(tmp_path: Path):
    with pytest.raises(SystemExit):
        run(
            tmp_path / "missing",
            tmp_path,
            tmp_path / "report.md",
            tmp_path / "backlog.jsonl",
            strict=True,
        )
