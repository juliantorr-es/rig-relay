"""Tests for the shared analytical compiler substrate.

Tests the shared JSONL loading, malformed-line diagnostics, DuckDB
relation registration, projection metadata, and projection writing.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from rig_relay.analytics import (
    LedgerLoadResult,
    build_projection_metadata,
    create_reports_table,
    load_jsonl,
    normalize_report_record,
    rows_to_dicts,
    write_projection,
)


class TestLoadJsonl:
    def test_missing_file(self, tmp_path: Path) -> None:
        result = load_jsonl(tmp_path / "nonexistent.jsonl")
        assert result.valid_records == []
        assert result.diagnostics["valid_record_count"] == 0
        assert result.diagnostics["malformed_line_count"] == 0
        assert result.diagnostics["source_ledger_sha256"] == ""

    def test_valid_single_record(self, tmp_path: Path) -> None:
        ledger = tmp_path / "test.jsonl"
        ledger.write_text('{"report_id": "r1", "kind": "test"}\n')
        result = load_jsonl(ledger)
        assert len(result.valid_records) == 1
        assert result.valid_records[0]["report_id"] == "r1"
        assert result.diagnostics["valid_record_count"] == 1
        assert result.diagnostics["malformed_line_count"] == 0
        assert result.diagnostics["source_ledger_sha256"] != ""

    def test_malformed_line_counted(self, tmp_path: Path) -> None:
        ledger = tmp_path / "test.jsonl"
        ledger.write_text(
            '{"report_id": "r1"}\n'
            'not json\n'
            '{"report_id": "r2"}\n'
        )
        result = load_jsonl(ledger)
        assert len(result.valid_records) == 2
        assert result.diagnostics["valid_record_count"] == 2
        assert result.diagnostics["malformed_line_count"] == 1
        assert result.diagnostics["malformed_line_numbers"] == [2]

    def test_all_malformed(self, tmp_path: Path) -> None:
        ledger = tmp_path / "test.jsonl"
        ledger.write_text("not json\nstill not json\n")
        result = load_jsonl(ledger)
        assert result.valid_records == []
        assert result.diagnostics["malformed_line_count"] == 2

    def test_empty_lines_skipped(self, tmp_path: Path) -> None:
        ledger = tmp_path / "test.jsonl"
        ledger.write_text('{"r": 1}\n\n  \n{"r": 2}\n')
        result = load_jsonl(ledger)
        assert len(result.valid_records) == 2

    def test_source_sha256_changes_on_edit(self, tmp_path: Path) -> None:
        ledger = tmp_path / "test.jsonl"
        ledger.write_text('{"a": 1}\n')
        sha1 = load_jsonl(ledger).diagnostics["source_ledger_sha256"]
        ledger.write_text('{"a": 2}\n')
        sha2 = load_jsonl(ledger).diagnostics["source_ledger_sha256"]
        assert sha1 != sha2


class TestNormalizeReportRecord:
    def test_normalize_minimal(self) -> None:
        record = {"report_id": "r1", "kind": "bug"}
        n = normalize_report_record(record)
        assert n["report_id"] == "r1"
        assert n["evidence_count"] == 0
        assert n["affected_path_count"] == 0

    def test_normalize_with_counts(self) -> None:
        record = {
            "report_id": "r1",
            "evidence": [{"kind": "code"}],
            "affected_paths": ["a.py", "b.py"],
            "blockers": ["dep1"],
            "details": {"key": "val"},
        }
        n = normalize_report_record(record)
        assert n["evidence_count"] == 1
        assert n["affected_path_count"] == 2
        assert n["blocker_count"] == 1
        assert "key" in n["details_json"]


class TestCreateReportsTable:
    def test_empty_table(self) -> None:
        from rig_relay.analytics import connect_in_memory

        con = connect_in_memory()
        create_reports_table(con, [])
        rows = rows_to_dicts(con, "SELECT count(*) AS cnt FROM reports")
        assert rows[0]["cnt"] == 0

    def test_table_with_records(self) -> None:
        from rig_relay.analytics import connect_in_memory

        con = connect_in_memory()
        records = [normalize_report_record({"report_id": "r1", "kind": "test", "severity": "low"})]
        create_reports_table(con, records)
        rows = rows_to_dicts(con, "SELECT count(*) AS cnt FROM reports")
        assert rows[0]["cnt"] == 1
        rows = rows_to_dicts(con, "SELECT report_id FROM reports")
        assert rows[0]["report_id"] == "r1"


class TestProjectionMetadata:
    def test_build_metadata(self) -> None:
        meta = build_projection_metadata(
            "report_summary",
            Path("/tmp/ledger.jsonl"),
            {
                "valid_record_count": 5,
                "malformed_line_count": 1,
                "source_ledger_sha256": "abc123",
            },
            generated_at="2026-05-15T00:00:00Z",
        )
        assert meta["schema_version"] == "rig.report_projection.v1"
        assert meta["projection_kind"] == "report_summary"
        assert meta["valid_record_count"] == 5
        assert meta["malformed_line_count"] == 1
        assert meta["source_ledger_sha256"] == "abc123"

    def test_invalid_kind_produces_metadata(self) -> None:
        """Any string is now accepted as projection_kind."""
        meta = build_projection_metadata(
            "any_kind", Path("/tmp/x.jsonl"), {},
        )
        assert meta["projection_kind"] == "any_kind"


class TestWriteProjection:
    def test_writes_dict(self, tmp_path: Path) -> None:
        path = write_projection(tmp_path / "test.json", {"count": 5})
        assert path.is_file()
        data = json.loads(path.read_text())
        assert data["count"] == 5

    def test_writes_list(self, tmp_path: Path) -> None:
        path = write_projection(tmp_path / "test.json", [1, 2, 3])
        assert path.is_file()
        data = json.loads(path.read_text())
        assert data == [1, 2, 3]

    def test_writes_with_metadata(self, tmp_path: Path) -> None:
        path = write_projection(
            tmp_path / "test.json",
            {"items": ["a"]},
            metadata={"schema_version": "v1", "projection_kind": "test"},
        )
        data = json.loads(path.read_text())
        assert data["schema_version"] == "v1"
        assert data["items"] == ["a"]

    def test_deterministic_output(self, tmp_path: Path) -> None:
        p1 = write_projection(tmp_path / "a.json", {"k": 1}, metadata={"m": "1"})
        p2 = write_projection(tmp_path / "b.json", {"k": 1}, metadata={"m": "1"})
        assert p1.read_text() == p2.read_text()


class TestRowsToDicts:
    def test_no_pandas_needed(self) -> None:
        """Prove that rows_to_dicts works without pandas/numpy."""
        from rig_relay.analytics import connect_in_memory

        con = connect_in_memory()
        con.execute("CREATE TABLE t AS SELECT * FROM (VALUES (1, 'a'), (2, 'b')) AS t(x, y)")
        rows = rows_to_dicts(con, "SELECT * FROM t ORDER BY x")
        assert len(rows) == 2
        assert rows[0]["x"] == 1
        assert rows[0]["y"] == "a"
        assert rows[1]["x"] == 2
        assert rows[1]["y"] == "b"
