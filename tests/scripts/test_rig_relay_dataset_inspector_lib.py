from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from scripts.rig_relay_dataset_inspector_lib import (
    compute_summary,
    count_by_field,
    count_by_field_pair,
    filter_by_event_name,
    filter_by_model,
    filter_by_session_id,
    filter_by_task_id,
    filter_by_tool_name,
    load_all,
    unique_values,
)

# ── Fixture helpers ──────────────────────────────────────────────────────


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")


def _write_json(path: Path, obj: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(obj, f, sort_keys=True)


_COORD_ROW = {
    "session_id": "sess-1",
    "task_id": "task-1",
    "event_name": "coord.task.claimed",
    "claim_kind": "search_replace",
    "status": "active",
    "event_id": "evt-001",
}

_CONFLICT_ROW = {
    "session_id": "sess-1",
    "task_id": "task-1",
    "event_name": "coord.path.reservation_refused",
    "conflict_id": "conflict-1",
    "other_session_id": "sess-2",
    "path_hashes": ["sha256:abc"],
}

_ARTIFACT_ROW = {
    "session_id": "sess-1",
    "task_id": "task-1",
    "artifact_kind": "file_read",
    "artifact_uri": "sha256:fff",
    "producer_session_id": "sess-1",
}

_CHECKPOINT_ROW = {
    "session_id": "sess-1",
    "checkpoint_outcome": "committed",
    "files_committed": 3,
    "task_id": "task-1",
}

_TOOL_FAILURE_ROW = {
    "session_id": "sess-1",
    "tool_name": "read_file",
    "status": "failure",
    "error_message": "Not found",
}

_PROVIDER_PERF_ROW = {
    "session_id": "sess-1",
    "model": "gpt-4",
    "provider": "openai",
    "total_tokens": 150,
    "task_id": "task-1",
}

_FINDING_ROW = {
    "id": "F001",
    "severity": "medium",
    "kind": "design_gap",
    "affected_files": ["src/main.py"],
    "description": "Missing error handling",
}


def _make_minimal_fixture(root: Path) -> None:
    """Write tiny datasets into root/derived."""
    d = root / "derived"
    _write_jsonl(d / "cross_session_coordination_dataset.jsonl", [_COORD_ROW])
    _write_jsonl(d / "coordination_conflict_dataset.jsonl", [_CONFLICT_ROW])
    _write_jsonl(d / "artifact_reuse_dataset.jsonl", [_ARTIFACT_ROW])
    _write_jsonl(d / "checkpoint_eval_dataset.jsonl", [_CHECKPOINT_ROW])
    _write_jsonl(d / "tool_failure_patterns_dataset.jsonl", [_TOOL_FAILURE_ROW])
    _write_jsonl(d / "provider_task_performance_dataset.jsonl", [_PROVIDER_PERF_ROW])
    _write_jsonl(d / "findings_dataset.jsonl", [_FINDING_ROW])
    manifest = {
        "exported_at": "2026-05-13T12:00:00Z",
        "warnings": ["Some warning"],
        "validation_results": {"cross_session_coordination_dataset": {"valid": 1}},
    }
    _write_json(d / "export_manifest.json", manifest)


# ── load_all ─────────────────────────────────────────────────────────────


def test_load_all_with_fixtures(tmp_path: Path) -> None:
    _make_minimal_fixture(tmp_path)
    datasets = load_all(tmp_path / "derived")
    assert len(datasets.coordination) == 1
    assert len(datasets.conflicts) == 1
    assert len(datasets.artifact_reuse) == 1
    assert len(datasets.checkpoints) == 1
    assert len(datasets.tool_failures) == 1
    assert len(datasets.provider_perf) == 1
    assert len(datasets.findings) == 1
    assert datasets.manifest is not None
    assert datasets.manifest["exported_at"] == "2026-05-13T12:00:00Z"
    assert datasets.missing_files == []
    assert datasets.load_warnings == []


def test_load_all_missing_dir(tmp_path: Path) -> None:
    """Non-existent dir returns empty datasets with a warning."""
    missing = tmp_path / "nope"
    datasets = load_all(missing)
    assert datasets.total_rows == 0
    assert len(datasets.load_warnings) == 1
    assert "not found" in datasets.load_warnings[0]


def test_load_all_partial_missing_files(tmp_path: Path) -> None:
    """Missing individual files produce warnings but not failures."""
    d = tmp_path / "derived"
    d.mkdir(parents=True)
    _write_jsonl(d / "cross_session_coordination_dataset.jsonl", [_COORD_ROW])
    # Only write coordination + manifest
    _write_json(
        d / "export_manifest.json",
        {"exported_at": "2026-01-01T00:00:00Z", "warnings": []},
    )
    datasets = load_all(d)
    assert len(datasets.coordination) == 1
    assert len(datasets.conflicts) == 0
    assert len(datasets.artifact_reuse) == 0
    assert len(datasets.checkpoints) == 0
    assert len(datasets.tool_failures) == 0
    assert len(datasets.provider_perf) == 0
    assert len(datasets.findings) == 0
    assert datasets.manifest is not None
    assert len(datasets.missing_files) == 6
    assert len(datasets.load_warnings) == 6


def test_load_all_skips_malformed_jsonl(tmp_path: Path) -> None:
    """Malformed lines in JSONL are skipped."""
    d = tmp_path / "derived"
    d.mkdir(parents=True)
    path = d / "cross_session_coordination_dataset.jsonl"
    with path.open("w", encoding="utf-8") as f:
        f.write('{"valid": true}\n')
        f.write("not json\n")
        f.write('{"also_valid": 2}\n')
    _write_json(
        d / "export_manifest.json",
        {"exported_at": "2026-01-01T00:00:00Z", "warnings": []},
    )
    datasets = load_all(d)
    assert len(datasets.coordination) == 2


def test_load_all_total_rows(tmp_path: Path) -> None:
    """total_rows property sums all datasets."""
    _make_minimal_fixture(tmp_path)
    datasets = load_all(tmp_path / "derived")
    assert datasets.total_rows == 7


# ── compute_summary ──────────────────────────────────────────────────────


def test_compute_summary_counts(tmp_path: Path) -> None:
    _make_minimal_fixture(tmp_path)
    datasets = load_all(tmp_path / "derived")
    summary = compute_summary(datasets)

    assert summary.total_sessions == 1
    assert summary.total_coordination_rows == 1
    assert summary.total_conflict_rows == 1
    assert summary.total_artifact_reuse_rows == 1
    assert summary.total_checkpoint_rows == 1
    assert summary.total_tool_failure_rows == 1
    assert summary.total_provider_perf_rows == 1
    assert summary.total_finding_rows == 1


def test_compute_summary_metadata(tmp_path: Path) -> None:
    _make_minimal_fixture(tmp_path)
    datasets = load_all(tmp_path / "derived")
    summary = compute_summary(datasets)

    assert summary.export_timestamp == "2026-05-13T12:00:00Z"
    assert summary.export_warnings == ["Some warning"]
    assert summary.schema_validation_results == {
        "cross_session_coordination_dataset": {"valid": 1}
    }


def test_compute_summary_empty_datasets(tmp_path: Path) -> None:
    """Datasets with zero rows are listed in empty_datasets."""
    d = tmp_path / "derived"
    d.mkdir(parents=True)
    _write_jsonl(d / "cross_session_coordination_dataset.jsonl", [_COORD_ROW])
    _write_json(
        d / "export_manifest.json",
        {"exported_at": "2026-01-01T00:00:00Z", "warnings": []},
    )
    datasets = load_all(d)
    summary = compute_summary(datasets)

    assert "coordination_conflict_dataset" in summary.empty_datasets
    assert "artifact_reuse_dataset" in summary.empty_datasets
    assert "checkpoint_eval_dataset" in summary.empty_datasets
    assert "tool_failure_patterns_dataset" in summary.empty_datasets
    assert "provider_task_performance_dataset" in summary.empty_datasets
    assert "findings_dataset" in summary.empty_datasets
    assert "cross_session_coordination_dataset" not in summary.empty_datasets


def test_compute_summary_no_manifest(tmp_path: Path) -> None:
    """No manifest results in empty metadata."""
    d = tmp_path / "derived"
    d.mkdir(parents=True)
    datasets = load_all(d)
    summary = compute_summary(datasets)
    assert summary.export_timestamp == ""
    assert summary.export_warnings == []
    assert summary.schema_validation_results == {}


def test_compute_summary_distinct_sessions(tmp_path: Path) -> None:
    """Multiple sessions across datasets are counted distinctly."""
    d = tmp_path / "derived"
    d.mkdir(parents=True)
    _write_jsonl(
        d / "cross_session_coordination_dataset.jsonl",
        [
            {"session_id": "sess-1", "event_name": "coord.task.claimed"},
            {"session_id": "sess-2", "event_name": "coord.task.claimed"},
            {"session_id": "sess-1", "event_name": "coord.task.claimed"},
        ],
    )
    _write_jsonl(
        d / "tool_failure_patterns_dataset.jsonl",
        [{"session_id": "sess-3", "tool_name": "read_file", "status": "failure"}],
    )
    _write_json(
        d / "export_manifest.json",
        {"exported_at": "2026-01-01T00:00:00Z", "warnings": []},
    )
    datasets = load_all(d)
    summary = compute_summary(datasets)
    assert summary.total_sessions == 3


# ── Filter helpers ───────────────────────────────────────────────────────


class TestFilterBySessionId:
    def test_match(self):
        rows = [{"session_id": "abc-123"}, {"session_id": "xyz-456"}]
        assert len(filter_by_session_id(rows, "abc")) == 1
        assert len(filter_by_session_id(rows, "xyz")) == 1

    def test_no_match(self):
        rows = [{"session_id": "abc-123"}]
        assert filter_by_session_id(rows, "zzz") == []

    def test_none_filter(self):
        rows = [{"session_id": "abc-123"}]
        assert filter_by_session_id(rows, None) == rows

    def test_empty_rows(self):
        assert filter_by_session_id([], "abc") == []

    def test_missing_field(self):
        rows = [{"other": "val"}]
        assert filter_by_session_id(rows, "abc") == []


class TestFilterByTaskId:
    def test_match(self):
        rows = [{"task_id": "task-1"}, {"task_id": "task-2"}]
        assert len(filter_by_task_id(rows, "task-1")) == 1

    def test_none_filter(self):
        rows = [{"task_id": "task-1"}]
        assert filter_by_task_id(rows, None) == rows


class TestFilterByEventName:
    def test_match(self):
        rows = [
            {"event_name": "coord.task.claimed"},
            {"event_name": "coord.task.completed"},
        ]
        assert len(filter_by_event_name(rows, "claimed")) == 1

    def test_none_filter(self):
        rows = [{"event_name": "coord.task.claimed"}]
        assert filter_by_event_name(rows, None) == rows


class TestFilterByToolName:
    def test_match(self):
        rows = [{"tool_name": "read_file"}, {"tool_name": "write_file"}]
        assert len(filter_by_tool_name(rows, "read")) == 1

    def test_none_filter(self):
        rows = [{"tool_name": "read_file"}]
        assert filter_by_tool_name(rows, None) == rows


class TestFilterByModel:
    def test_match(self):
        rows = [{"model": "gpt-4"}, {"model": "claude-3"}]
        assert len(filter_by_model(rows, "gpt")) == 1

    def test_none_filter(self):
        rows = [{"model": "gpt-4"}]
        assert filter_by_model(rows, None) == rows


# ── Aggregation helpers ──────────────────────────────────────────────────


class TestCountByField:
    def test_counts(self):
        rows = [{"status": "active"}, {"status": "active"}, {"status": "completed"}]
        result = count_by_field(rows, "status")
        assert result == [("active", 2), ("completed", 1)]

    def test_empty(self):
        assert count_by_field([], "status") == []

    def test_none_values_skipped(self):
        rows = [{"status": None}, {"status": "active"}]
        result = count_by_field(rows, "status")
        assert result == [("active", 1)]

    def test_sorted_high_to_low(self):
        rows = [{"x": "a"}, {"x": "a"}, {"x": "a"}, {"x": "b"}, {"x": "b"}, {"x": "c"}]
        result = count_by_field(rows, "x")
        assert result == [("a", 3), ("b", 2), ("c", 1)]


class TestCountByFieldPair:
    def test_counts(self):
        rows = [
            {"tool": "read_file", "status": "ok"},
            {"tool": "read_file", "status": "ok"},
            {"tool": "write_file", "status": "ok"},
            {"tool": "write_file", "status": "fail"},
        ]
        result = count_by_field_pair(rows, "tool", "status")
        assert ("read_file", "ok", 2) in result
        assert ("write_file", "ok", 1) in result
        assert ("write_file", "fail", 1) in result

    def test_empty(self):
        assert count_by_field_pair([], "a", "b") == []

    def test_none_values_skipped(self):
        rows = [{"a": None, "b": "y"}, {"a": "x", "b": None}, {"a": "x", "b": "y"}]
        result = count_by_field_pair(rows, "a", "b")
        assert result == [("x", "y", 1)]


class TestUniqueValues:
    def test_unique(self):
        rows = [{"color": "red"}, {"color": "blue"}, {"color": "red"}]
        assert unique_values(rows, "color") == ["blue", "red"]

    def test_empty(self):
        assert unique_values([], "color") == []

    def test_none_values_skipped(self):
        rows = [{"color": None}, {"color": "red"}]
        assert unique_values(rows, "color") == ["red"]


# ── Privacy safeguard ────────────────────────────────────────────────────


FORBIDDEN_RAW_FIELDS = {
    "prompt",
    "raw_prompt",
    "model_output",
    "completion",
    "file_content",
    "file_contents",
    "stdout",
    "stderr",
    "body",
    "raw_body",
    "output_text",
    "response_text",
    "code",
    "source_code",
}


def _all_field_names(rows: list[dict[str, Any]]) -> set[str]:
    fields: set[str] = set()
    for row in rows:
        fields.update(row.keys())
    return fields


def test_load_all_no_raw_fields_in_datasets(tmp_path: Path) -> None:
    """Verifies content-light property: no raw content fields."""
    _make_minimal_fixture(tmp_path)
    datasets = load_all(tmp_path / "derived")
    for attr in [
        "coordination",
        "conflicts",
        "artifact_reuse",
        "checkpoints",
        "tool_failures",
        "provider_perf",
        "findings",
    ]:
        rows = getattr(datasets, attr)
        fields = _all_field_names(rows)
        forbidden = fields & FORBIDDEN_RAW_FIELDS
        assert not forbidden, f"{attr} has forbidden fields: {forbidden}"


# ── Chart-ready summary helpers ──────────────────────────────────────────


class TestEventCountsForChart:
    def test_returns_expected_counts(self):
        from scripts.rig_relay_dataset_inspector_lib import (
            DerivedDatasets,
            event_counts_for_chart,
        )

        ds = DerivedDatasets()
        ds.coordination = [
            {"event_name": "coord.task.claimed"},
            {"event_name": "coord.task.claimed"},
            {"event_name": "coord.path.reserved"},
        ]
        result = event_counts_for_chart(ds)
        assert len(result) == 2
        assert {"event_name": "coord.task.claimed", "count": 2} in result

    def test_empty_dataset(self):
        from scripts.rig_relay_dataset_inspector_lib import (
            DerivedDatasets,
            event_counts_for_chart,
        )

        ds = DerivedDatasets()
        assert event_counts_for_chart(ds) == []

    def test_no_forbidden_raw_fields(self):
        from scripts.rig_relay_dataset_inspector_lib import (
            DerivedDatasets,
            event_counts_for_chart,
        )

        ds = DerivedDatasets()
        ds.coordination = [{"event_name": "test"}]
        for item in event_counts_for_chart(ds):
            assert not set(item.keys()) & {
                "prompt",
                "raw_prompt",
                "model_output",
                "completion",
                "file_content",
                "stdout",
                "stderr",
                "body",
            }


class TestToolStatusCountsForChart:
    def test_returns_expected_counts(self):
        from scripts.rig_relay_dataset_inspector_lib import (
            DerivedDatasets,
            tool_status_counts_for_chart,
        )

        ds = DerivedDatasets()
        ds.tool_failures = [
            {"tool_name": "read_file", "status": "failure"},
            {"tool_name": "read_file", "status": "failure"},
            {"tool_name": "write_file", "status": "failure"},
            {"tool_name": "grep", "status": "success"},
        ]
        result = tool_status_counts_for_chart(ds)
        assert len(result) == 3
        assert {"tool_name": "read_file", "status": "failure", "count": 2} in result

    def test_empty_dataset(self):
        from scripts.rig_relay_dataset_inspector_lib import (
            DerivedDatasets,
            tool_status_counts_for_chart,
        )

        ds = DerivedDatasets()
        assert tool_status_counts_for_chart(ds) == []


class TestModelCountsForChart:
    def test_returns_expected_counts(self):
        from scripts.rig_relay_dataset_inspector_lib import (
            DerivedDatasets,
            model_counts_for_chart,
        )

        ds = DerivedDatasets()
        ds.provider_perf = [
            {"model": "gpt-4"},
            {"model": "gpt-4"},
            {"model": "claude-3"},
        ]
        result = model_counts_for_chart(ds)
        assert len(result) == 2
        assert {"model": "gpt-4", "requests": 2} in result

    def test_empty_dataset(self):
        from scripts.rig_relay_dataset_inspector_lib import (
            DerivedDatasets,
            model_counts_for_chart,
        )

        ds = DerivedDatasets()
        assert model_counts_for_chart(ds) == []


class TestFindingsSeverityCountsForChart:
    def test_returns_expected_counts(self):
        from scripts.rig_relay_dataset_inspector_lib import (
            DerivedDatasets,
            findings_severity_counts_for_chart,
        )

        ds = DerivedDatasets()
        ds.findings = [
            {"severity": "high"},
            {"severity": "medium"},
            {"severity": "medium"},
        ]
        result = findings_severity_counts_for_chart(ds)
        assert len(result) == 2
        assert {"severity": "high", "count": 1} in result

    def test_empty_dataset(self):
        from scripts.rig_relay_dataset_inspector_lib import (
            DerivedDatasets,
            findings_severity_counts_for_chart,
        )

        ds = DerivedDatasets()
        assert findings_severity_counts_for_chart(ds) == []


class TestArtifactKindCountsForChart:
    def test_returns_expected_counts(self):
        from scripts.rig_relay_dataset_inspector_lib import (
            DerivedDatasets,
            artifact_kind_counts_for_chart,
        )

        ds = DerivedDatasets()
        ds.artifact_reuse = [
            {"artifact_kind": "file_read"},
            {"artifact_kind": "file_read"},
            {"artifact_kind": "search_replace"},
        ]
        result = artifact_kind_counts_for_chart(ds)
        assert len(result) == 2
        assert {"artifact_kind": "file_read", "count": 2} in result

    def test_empty_dataset(self):
        from scripts.rig_relay_dataset_inspector_lib import (
            DerivedDatasets,
            artifact_kind_counts_for_chart,
        )

        ds = DerivedDatasets()
        assert artifact_kind_counts_for_chart(ds) == []


class TestCheckpointStatusCountsForChart:
    def test_returns_expected_counts(self):
        from scripts.rig_relay_dataset_inspector_lib import (
            DerivedDatasets,
            checkpoint_status_counts_for_chart,
        )

        ds = DerivedDatasets()
        ds.checkpoints = [
            {"checkpoint_outcome": "committed"},
            {"checkpoint_outcome": "committed"},
            {"checkpoint_outcome": "refused"},
        ]
        result = checkpoint_status_counts_for_chart(ds)
        assert len(result) == 2
        assert {"status": "committed", "count": 2} in result

    def test_empty_dataset(self):
        from scripts.rig_relay_dataset_inspector_lib import (
            DerivedDatasets,
            checkpoint_status_counts_for_chart,
        )

        ds = DerivedDatasets()
        assert checkpoint_status_counts_for_chart(ds) == []


# ── DuckDB helper tests ─────────────────────────────────────────────────


def test_create_derived_connection_no_duckdb(monkeypatch):
    monkeypatch.setattr("scripts.rig_relay_dataset_inspector_lib.HAS_DUCKDB", False)
    from scripts.rig_relay_dataset_inspector_lib import create_derived_connection

    con, views = create_derived_connection()
    assert con is None
    assert views == []


def test_create_derived_connection_missing_dir(tmp_path, monkeypatch):
    monkeypatch.setattr("scripts.rig_relay_dataset_inspector_lib.HAS_DUCKDB", True)
    from scripts.rig_relay_dataset_inspector_lib import create_derived_connection

    con, views = create_derived_connection(tmp_path / "nope")
    assert con is None
    assert views == []


def test_create_derived_connection_with_fixtures(tmp_path, monkeypatch):
    monkeypatch.setattr("scripts.rig_relay_dataset_inspector_lib.HAS_DUCKDB", True)
    from scripts.rig_relay_dataset_inspector_lib import create_derived_connection

    d = tmp_path / "derived"
    d.mkdir(parents=True)
    (d / "cross_session_coordination_dataset.jsonl").write_text(
        '{"event_name": "x", "session_id": "s-1"}\n'
    )
    (d / "tool_failure_patterns_dataset.jsonl").write_text(
        '{"tool_name": "bash", "status": "failure"}\n'
    )
    (d / "provider_task_performance_dataset.jsonl").write_text('{"model": "gpt-4"}\n')
    con, views = create_derived_connection(d)
    assert con is not None
    assert "cross_session_coordination" in views
    con.close()


def test_run_canned_query_with_fixtures(tmp_path, monkeypatch):
    monkeypatch.setattr("scripts.rig_relay_dataset_inspector_lib.HAS_DUCKDB", True)
    from scripts.rig_relay_dataset_inspector_lib import (
        create_derived_connection,
        run_canned_query,
    )

    d = tmp_path / "derived"
    d.mkdir(parents=True)
    p = d / "cross_session_coordination_dataset.jsonl"
    p.write_text(
        '{"event_name": "coord.task.claimed"}\n'
        '{"event_name": "coord.task.claimed"}\n'
        '{"event_name": "coord.path.reserved"}\n'
    )
    con, _ = create_derived_connection(d)
    assert con is not None
    result = run_canned_query(con, "top_event_names")
    assert result is not None and len(result) == 2
    assert run_canned_query(con, "nonexistent") is None
    con.close()


def test_canned_queries_have_names():
    from scripts.rig_relay_dataset_inspector_lib import CANNED_QUERIES

    assert len(CANNED_QUERIES) >= 6
    for name in [
        "top_event_names",
        "tool_failures_by_status",
        "provider_model_counts",
        "artifact_kinds",
        "findings_by_severity_and_kind",
        "checkpoint_outcomes",
    ]:
        assert name in CANNED_QUERIES


def test_find_derived_jsonl_files_partial(tmp_path):
    from scripts.rig_relay_dataset_inspector_lib import _find_derived_jsonl_files

    d = tmp_path / "derived"
    d.mkdir(parents=True)
    (d / "cross_session_coordination_dataset.jsonl").write_text(
        '{"event_name": "test"}\n'
    )
    result = _find_derived_jsonl_files(d)
    assert "cross_session_coordination" in result and len(result) == 1


def test_find_derived_jsonl_files_missing_dir(tmp_path):
    from scripts.rig_relay_dataset_inspector_lib import _find_derived_jsonl_files

    assert _find_derived_jsonl_files(tmp_path / "nope") == {}
