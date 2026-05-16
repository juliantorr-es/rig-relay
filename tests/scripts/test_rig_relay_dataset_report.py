from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pytest import MonkeyPatch

from scripts.rig_relay_dataset_report import (
    DataSources,
    ReportGenerator,
    _count_lines,
    _fmt_table,
    _load_jsonl,
    main,
)

# ── Fixture helpers ──────────────────────────────────────────────────────


pytestmark = [pytest.mark.migration]


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")


_COORD_FIXTURE_LINES = [
    {
        "schema_version": "rig.relay.coordination.event.v1",
        "event_id": "evt-001",
        "event_name": "coord.task.claimed",
        "session_id": "sess-1",
        "task_id": "task-1",
        "sequence": 1,
        "payload": {
            "event_kind": "task_claimed",
            "claim_kind": "search_replace",
            "session_id": "sess-1",
            "task_id": "task-1",
            "status": "active",
            "ttl_seconds": 300,
        },
    },
    {
        "schema_version": "rig.relay.coordination.event.v1",
        "event_id": "evt-002",
        "event_name": "coord.path.reserved",
        "session_id": "sess-1",
        "task_id": "task-1",
        "sequence": 2,
        "payload": {
            "event_kind": "path_reserved",
            "reservation_mode": "write",
            "reservation_status": "active",
            "session_id": "sess-1",
            "task_id": "task-1",
            "path_count": 1,
        },
    },
    {
        "schema_version": "rig.relay.coordination.event.v1",
        "event_id": "evt-003",
        "event_name": "coord.path.reservation_refused",
        "session_id": "sess-2",
        "task_id": "task-2",
        "sequence": 3,
        "payload": {
            "event_kind": "reservation_refused",
            "reservation_status": "refused",
            "session_id": "sess-2",
            "task_id": "task-2",
        },
    },
    {
        "schema_version": "rig.relay.coordination.event.v1",
        "event_id": "evt-004",
        "event_name": "coord.conflict.reported",
        "session_id": "sess-2",
        "task_id": "task-2",
        "sequence": 4,
        "payload": {
            "event_kind": "conflict_reported",
            "conflict_kind": "path_write_overlap",
            "session_id": "sess-2",
            "task_id": "task-2",
        },
    },
]

_OBS_FIXTURE_LINES = [
    {
        "event_name": "rig.relay.tool.call_completed",
        "session_id": "sess-1",
        "payload": {
            "tool_name": "search_replace",
            "status": "success",
            "model": "deepseek-v4-flash",
        },
    },
    {
        "event_name": "rig.relay.tool.call_completed",
        "session_id": "sess-1",
        "payload": {
            "tool_name": "search_replace",
            "status": "success",
            "model": "deepseek-v4-flash",
        },
    },
    {
        "event_name": "rig.relay.tool.call_completed",
        "session_id": "sess-2",
        "payload": {
            "tool_name": "write_file",
            "status": "refused",
            "model": "deepseek-v4-flash",
        },
    },
    {
        "event_name": "rig.relay.context.request_accounted",
        "session_id": "sess-1",
        "payload": {
            "model": "deepseek-v4-flash",
            "context_accounting": {"model": "deepseek-v4-flash"},
        },
    },
    {
        "event_name": "rig.relay.checkpoint.committed",
        "session_id": "sess-1",
        "payload": {
            "commit_sha": "abc123def456",
            "branch": "main",
            "status": "committed",
        },
    },
    {
        "event_name": "rig.relay.checkpoint.refused",
        "session_id": "sess-2",
        "payload": {
            "refusal_code": "dirty_file_overlap",
            "status": "refused",
            "warnings": ["path is dirty"],
        },
    },
    {
        "event_name": "rig.relay.tool.reasoning_trace",
        "session_id": "sess-1",
        "payload": {"tool_name": "bash", "status": "success"},
    },
]

_FINDINGS_FIXTURE = [
    {
        "schema_version": "rig.relay.out_of_scope_finding.v1",
        "finding_id": "finding_test_001",
        "title": "Test finding",
        "severity": "medium",
        "status": "open",
        "repo_area": "vibe/core/test",
        "finding_kind": "architecture_debt",
        "suggested_slice": "Fix test finding",
    },
    {
        "schema_version": "rig.relay.out_of_scope_finding.v1",
        "finding_id": "finding_test_002",
        "title": "Low severity finding",
        "severity": "low",
        "status": "open",
        "repo_area": "vibe/core/other",
        "finding_kind": "lint_refactor",
        "suggested_slice": "Fix low finding",
    },
    {
        "schema_version": "rig.relay.out_of_scope_finding.v1",
        "finding_id": "finding_test_003",
        "title": "Resolved finding",
        "severity": "high",
        "status": "resolved",
        "repo_area": "vibe/core/resolved",
        "finding_kind": "safety_guard_gap",
        "suggested_slice": "Already done",
    },
]


# ── Tests ────────────────────────────────────────────────────────────────


def test_load_jsonl_empty_file(tmp_path: Path) -> None:
    path = tmp_path / "empty.jsonl"
    path.write_text("", encoding="utf-8")
    assert _load_jsonl(path) == []


def test_load_jsonl_missing_file(tmp_path: Path) -> None:
    path = tmp_path / "nonexistent.jsonl"
    assert _load_jsonl(path) == []


def test_load_jsonl_skips_malformed_lines(tmp_path: Path) -> None:
    path = tmp_path / "mixed.jsonl"
    path.write_text('{"valid": true}\nnot json\n{"also_valid": 42}\n', encoding="utf-8")
    result = _load_jsonl(path)
    assert len(result) == 2
    assert result[0] == {"valid": True}
    assert result[1] == {"also_valid": 42}


def test_count_lines(tmp_path: Path) -> None:
    path = tmp_path / "lines.jsonl"
    path.write_text("a\nb\nc\n", encoding="utf-8")
    assert _count_lines(path) == 3


def test_fmt_table_empty() -> None:
    result = _fmt_table(["Col"], [])
    assert "No data for" in result


def test_fmt_table_renders_correctly() -> None:
    headers = ["Name", "Count"]
    rows = [["foo", "1"], ["bar", "2"]]
    result = _fmt_table(headers, rows)
    assert "| Name | Count |" in result
    assert "| --- | --- |" in result
    assert "| foo | 1 |" in result
    assert "| bar | 2 |" in result


def test_data_sources_missing_all(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    fake_dir = tmp_path / "sessions"
    fake_dir.mkdir(parents=True)
    monkeypatch.setattr("scripts.rig_relay_dataset_report.SESSIONS_ROOT", fake_dir)
    monkeypatch.setattr(
        "scripts.rig_relay_dataset_report.COORD_EVENTS", tmp_path / "no_events.jsonl"
    )
    monkeypatch.setattr(
        "scripts.rig_relay_dataset_report.FINDINGS_PATH", tmp_path / "no_findings.jsonl"
    )

    ds = DataSources()
    assert not ds.coord_events_present
    assert not ds.obs_present
    assert not ds.findings_present
    assert len(ds.warnings()) == 3


def test_data_sources_with_fixtures(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    sessions_dir = tmp_path / "sessions" / "sess-1"
    sessions_dir.mkdir(parents=True)
    _write_jsonl(sessions_dir / "observability.jsonl", _OBS_FIXTURE_LINES[:3])

    coord_path = tmp_path / "events.jsonl"
    _write_jsonl(coord_path, _COORD_FIXTURE_LINES)

    findings_path = tmp_path / "findings.jsonl"
    _write_jsonl(findings_path, _FINDINGS_FIXTURE)

    monkeypatch.setattr(
        "scripts.rig_relay_dataset_report.SESSIONS_ROOT", tmp_path / "sessions"
    )
    monkeypatch.setattr("scripts.rig_relay_dataset_report.COORD_EVENTS", coord_path)
    monkeypatch.setattr("scripts.rig_relay_dataset_report.FINDINGS_PATH", findings_path)

    ds = DataSources()
    assert ds.coord_events_present
    assert ds.obs_present
    assert ds.findings_present
    assert ds.coord_event_count == 4
    assert ds.findings_count == 3
    assert len(ds.warnings()) == 0


def test_report_generation_with_missing_inputs(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    fake_dir = tmp_path / "sessions"
    fake_dir.mkdir(parents=True)
    monkeypatch.setattr("scripts.rig_relay_dataset_report.SESSIONS_ROOT", fake_dir)
    monkeypatch.setattr(
        "scripts.rig_relay_dataset_report.COORD_EVENTS", tmp_path / "no_events.jsonl"
    )
    monkeypatch.setattr(
        "scripts.rig_relay_dataset_report.FINDINGS_PATH", tmp_path / "no_findings.jsonl"
    )

    ds = DataSources()
    report = ReportGenerator(ds)
    markdown = report.generate()

    assert "# Rig Relay Dataset Report" in markdown
    assert "## Executive Summary" in markdown
    assert "## Event Volume" in markdown
    assert "## Tool Behavior" in markdown
    assert "## Guard and Safety" in markdown
    assert "## Coordination" in markdown
    assert "## Checkpoints" in markdown
    assert "## Provider / Model Use" in markdown
    assert "## Findings" in markdown
    assert "## Warnings / Missing Inputs" in markdown
    assert "## Recommended Next Slices" in markdown
    assert "## Data Sources Used" in markdown


def test_report_generation_with_coordination_fixture(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    sessions_dir = tmp_path / "sessions" / "sess-1"
    sessions_dir.mkdir(parents=True)
    _write_jsonl(sessions_dir / "observability.jsonl", _OBS_FIXTURE_LINES)

    coord_path = tmp_path / "events.jsonl"
    _write_jsonl(coord_path, _COORD_FIXTURE_LINES)

    findings_path = tmp_path / "findings.jsonl"
    _write_jsonl(findings_path, _FINDINGS_FIXTURE)

    monkeypatch.setattr(
        "scripts.rig_relay_dataset_report.SESSIONS_ROOT", tmp_path / "sessions"
    )
    monkeypatch.setattr("scripts.rig_relay_dataset_report.COORD_EVENTS", coord_path)
    monkeypatch.setattr("scripts.rig_relay_dataset_report.FINDINGS_PATH", findings_path)

    ds = DataSources()
    report = ReportGenerator(ds)
    markdown = report.generate()

    # Executive summary values
    assert "| Sessions observed | 1 |" in markdown
    assert "| Observability events | 7 |" in markdown
    assert "| Coordination events | 4 |" in markdown
    assert "| Tool calls | 3 |" in markdown
    assert "| Mutations allowed | 2 |" in markdown
    assert "| Mutations refused | 1 |" in markdown
    assert "| Open findings | 2 |" in markdown

    # Event volume
    assert "| coord.task.claimed | 1 |" in markdown
    assert "| coord.path.reserved | 1 |" in markdown
    assert "| coord.path.reservation_refused | 1 |" in markdown
    assert "| coord.conflict.reported | 1 |" in markdown

    # Tool behavior
    assert "| search_replace | 2 | 2 | 0 | 0 |" in markdown
    assert "| write_file | 1 | 0 | 1 | 0 |" in markdown

    # Coordination breakdown
    assert "| Task claims | 1" in markdown
    assert "| Path reservations | 1" in markdown
    assert "| Reservation refusals | 1" in markdown
    assert "| Conflicts reported | 1" in markdown

    # Checkpoints
    assert "| Committed | 1 |" in markdown
    assert "| Refused | 1 |" in markdown
    assert "abc123def456..." in markdown
    assert "dirty_file_overlap (1)" in markdown

    # Findings
    assert "| Severity | Count |" in markdown
    assert "| low | 1 |" in markdown
    assert "| medium | 1 |" in markdown
    assert "| high | 1 |" in markdown
    assert "| finding_test_001" in markdown
    assert "| finding_test_003" in markdown

    # No warnings section when all sources present
    assert "## Warnings / Missing Inputs" not in markdown

    # Recommended next slices
    assert "## Recommended Next Slices" in markdown
    assert "Fix test finding" in markdown
    assert "Fix low finding" in markdown

    # Data sources
    assert "## Data Sources Used" in markdown


def test_report_no_raw_fields_in_payload(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """Privacy safeguard: report must not include raw prompt/model output fields."""
    sessions_dir = tmp_path / "sessions" / "sess-1"
    sessions_dir.mkdir(parents=True)

    # Create observability events with raw fields in payload (simulate what might be there)
    obs_lines = _OBS_FIXTURE_LINES + [
        {
            "event_name": "rig.relay.tool.call_completed",
            "session_id": "sess-1",
            "payload": {
                "tool_name": "bash",
                "status": "success",
                "raw_stdout": "secret output",
                "raw_stderr": "secret error",
                "raw_prompt": "secret prompt",
            },
        }
    ]
    _write_jsonl(sessions_dir / "observability.jsonl", obs_lines)

    coord_path = tmp_path / "events.jsonl"
    _write_jsonl(coord_path, _COORD_FIXTURE_LINES)

    monkeypatch.setattr(
        "scripts.rig_relay_dataset_report.SESSIONS_ROOT", tmp_path / "sessions"
    )
    monkeypatch.setattr("scripts.rig_relay_dataset_report.COORD_EVENTS", coord_path)
    monkeypatch.setattr(
        "scripts.rig_relay_dataset_report.FINDINGS_PATH", tmp_path / "no_findings.jsonl"
    )

    ds = DataSources()
    report = ReportGenerator(ds)
    markdown = report.generate()

    # These raw field values must not appear in the report
    assert "secret output" not in markdown
    assert "secret error" not in markdown
    assert "secret prompt" not in markdown
    # Raw field names should not appear as values in the report
    # (they do appear in the event name table which is acceptable;
    #  the safeguard is about the values, not the structural field names)


def test_report_generation_via_main(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """Test that main() runs and produces output file."""
    sessions_dir = tmp_path / "sessions" / "sess-1"
    sessions_dir.mkdir(parents=True)
    _write_jsonl(sessions_dir / "observability.jsonl", _OBS_FIXTURE_LINES[:1])

    coord_path = tmp_path / "events.jsonl"
    _write_jsonl(coord_path, _COORD_FIXTURE_LINES[:1])

    output_path = tmp_path / "output" / "report.md"

    monkeypatch.setattr(
        "scripts.rig_relay_dataset_report.SESSIONS_ROOT", tmp_path / "sessions"
    )
    monkeypatch.setattr("scripts.rig_relay_dataset_report.COORD_EVENTS", coord_path)
    monkeypatch.setattr(
        "scripts.rig_relay_dataset_report.FINDINGS_PATH", tmp_path / "no_findings.jsonl"
    )

    exit_code = main([
        "--output",
        str(output_path),
        "--coord-events",
        str(coord_path),
        "--findings",
        str(tmp_path / "no_findings.jsonl"),
        "--sessions-root",
        str(tmp_path / "sessions"),
    ])
    assert exit_code == 0
    assert output_path.is_file()
    content = output_path.read_text(encoding="utf-8")
    assert "# Rig Relay Dataset Report" in content


def test_provider_model_reporting(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """Verify provider/model use section handles request accounting events."""
    sessions_dir = tmp_path / "sessions" / "sess-1"
    sessions_dir.mkdir(parents=True)

    obs = [
        {
            "event_name": "rig.relay.context.request_accounted",
            "session_id": "sess-1",
            "payload": {"model": "gpt-4o", "context_accounting": {"model": "gpt-4o"}},
        },
        {
            "event_name": "rig.relay.context.request_accounted",
            "session_id": "sess-2",
            "payload": {
                "model": "claude-3-opus",
                "context_accounting": {"model": "claude-3-opus"},
            },
        },
    ]
    _write_jsonl(sessions_dir / "observability.jsonl", obs)

    monkeypatch.setattr(
        "scripts.rig_relay_dataset_report.SESSIONS_ROOT", tmp_path / "sessions"
    )
    monkeypatch.setattr(
        "scripts.rig_relay_dataset_report.COORD_EVENTS", tmp_path / "no_events.jsonl"
    )
    monkeypatch.setattr(
        "scripts.rig_relay_dataset_report.FINDINGS_PATH", tmp_path / "no_findings.jsonl"
    )

    ds = DataSources()
    report = ReportGenerator(ds)
    markdown = report.generate()

    assert "## Provider / Model Use" in markdown
    assert "gpt-4o" in markdown
    assert "claude-3-opus" in markdown
