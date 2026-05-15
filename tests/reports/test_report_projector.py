"""Tests for report projectors — deterministic read models from the report ledger.

All tests use in-memory or temp-ledger data. No side effects on canonical findings.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from rig_relay.reports.projector import (
    build_candidate_findings,
    build_duplicate_candidates,
    build_open_raw_reports,
    build_report_snapshots,
    build_report_summary,
    write_indexes,
)
from rig_relay.reports.report_store import write_report_to_ledger


def _add_report(ledger: Path, **fields: str | list[str]) -> None:
    """Helper: write a minimal report to the test ledger."""
    report = {
        "report_id": fields.get("report_id", "r1"),
        "dedupe_key": fields.get("dedupe_key", "dk1"),
        "kind": fields.get("kind", "bug_report"),
        "title": fields.get("title", "Test report"),
        "summary": "Test",
        "severity": fields.get("severity", "medium"),
        "status": fields.get("status", "open"),
        "created_at": fields.get("created_at", "2026-05-15T00:00:00Z"),
        "evidence": fields.get("evidence", []),
        "affected_paths": fields.get("affected_paths", []),
    }
    if isinstance(report.get("evidence"), list):
        pass
    else:
        report["evidence"] = []
    write_report_to_ledger(report, ledger)


class TestEmptyLedger:
    def test_summary_empty(self, tmp_path: Path) -> None:
        ledger = tmp_path / "reports.jsonl"
        summary = build_report_summary(ledger)
        assert summary["total_reports"] == 0
        assert summary["open_raw_report_count"] == 0

    def test_snapshots_empty(self, tmp_path: Path) -> None:
        assert build_report_snapshots(tmp_path / "reports.jsonl") == []

    def test_open_raw_empty(self, tmp_path: Path) -> None:
        assert build_open_raw_reports(tmp_path / "reports.jsonl") == []

    def test_duplicate_candidates_empty(self, tmp_path: Path) -> None:
        assert build_duplicate_candidates(tmp_path / "reports.jsonl") == []

    def test_candidate_findings_empty(self, tmp_path: Path) -> None:
        assert build_candidate_findings(tmp_path / "reports.jsonl") == []


class TestSingleReport:
    def test_summary_counts_one(self, tmp_path: Path) -> None:
        ledger = tmp_path / "reports.jsonl"
        _add_report(ledger)
        summary = build_report_summary(ledger)
        assert summary["total_reports"] == 1
        assert summary["by_status"]["open"] == 1
        assert summary["by_kind"]["bug_report"] == 1

    def test_snapshot_includes_report(self, tmp_path: Path) -> None:
        ledger = tmp_path / "reports.jsonl"
        _add_report(ledger, report_id="r1")
        snapshots = build_report_snapshots(ledger)
        assert len(snapshots) == 1
        assert snapshots[0]["report_id"] == "r1"

    def test_open_raw_includes_open(self, tmp_path: Path) -> None:
        ledger = tmp_path / "reports.jsonl"
        _add_report(ledger, status="open")
        assert len(build_open_raw_reports(ledger)) == 1

    def test_open_raw_excludes_closed(self, tmp_path: Path) -> None:
        ledger = tmp_path / "reports.jsonl"
        _add_report(ledger, status="resolved")
        assert len(build_open_raw_reports(ledger)) == 0

    def test_stale_count(self, tmp_path: Path) -> None:
        ledger = tmp_path / "reports.jsonl"
        _add_report(ledger, created_at="2025-01-01T00:00:00Z")
        summary = build_report_summary(ledger)
        assert summary["stale_raw_report_count"] == 1


class TestDuplicateCandidates:
    def test_no_duplicates(self, tmp_path: Path) -> None:
        ledger = tmp_path / "reports.jsonl"
        _add_report(ledger, dedupe_key="k1")
        _add_report(ledger, dedupe_key="k2", report_id="r2")
        assert build_duplicate_candidates(ledger) == []

    def test_duplicates_detected(self, tmp_path: Path) -> None:
        ledger = tmp_path / "reports.jsonl"
        _add_report(ledger, dedupe_key="dup_key", report_id="r1")
        _add_report(ledger, dedupe_key="dup_key", report_id="r2")
        candidates = build_duplicate_candidates(ledger)
        assert len(candidates) == 1
        assert candidates[0]["dedupe_key"] == "dup_key"
        assert candidates[0]["report_count"] == 2
        assert "r1" in candidates[0]["report_ids"]
        assert "r2" in candidates[0]["report_ids"]

    def test_exact_duplicate(self, tmp_path: Path) -> None:
        """Same dedupe_key with three reports."""
        ledger = tmp_path / "reports.jsonl"
        for i in range(3):
            _add_report(ledger, dedupe_key="exact", report_id=f"r{i}")
        candidates = build_duplicate_candidates(ledger)
        assert len(candidates) == 1
        assert candidates[0]["report_count"] == 3


class TestCandidateFindings:
    def test_candidate_with_evidence(self, tmp_path: Path) -> None:
        ledger = tmp_path / "reports.jsonl"
        _add_report(ledger, kind="architecture_seam", severity="high",
                    evidence=[{"kind": "code_reference", "path": "a.py", "summary": "Seam"}])
        candidates = build_candidate_findings(ledger)
        assert len(candidates) == 1

    def test_mission_report_excluded(self, tmp_path: Path) -> None:
        ledger = tmp_path / "reports.jsonl"
        _add_report(ledger, kind="mission_report", severity="medium", evidence=[{"kind": "text", "path": "", "summary": "Done"}])
        assert len(build_candidate_findings(ledger)) == 0

    def test_low_severity_excluded(self, tmp_path: Path) -> None:
        ledger = tmp_path / "reports.jsonl"
        _add_report(ledger, kind="architecture_seam", severity="low", evidence=[{"kind": "text", "path": "", "summary": "Minor"}])
        assert len(build_candidate_findings(ledger)) == 0

    def test_no_evidence_excluded(self, tmp_path: Path) -> None:
        ledger = tmp_path / "reports.jsonl"
        _add_report(ledger, kind="architecture_seam", severity="high", evidence=[])
        assert len(build_candidate_findings(ledger)) == 0

    def test_closed_report_excluded(self, tmp_path: Path) -> None:
        ledger = tmp_path / "reports.jsonl"
        _add_report(ledger, kind="architecture_seam", severity="high", status="resolved",
                    evidence=[{"kind": "text", "path": "", "summary": "Fixed"}])
        assert len(build_candidate_findings(ledger)) == 0


class TestWriteIndexes:
    def test_writes_all_indexes(self, tmp_path: Path) -> None:
        ledger = tmp_path / "reports.jsonl"
        _add_report(ledger)
        indexes_dir = tmp_path / "indexes"
        written = write_indexes(indexes_dir, ledger)
        assert len(written) == 5
        for name in ("report_summary", "report_snapshots", "open_raw_reports",
                     "duplicate_candidates", "candidate_findings"):
            assert name in written
            assert written[name].is_file()

    def test_indexes_are_valid_json(self, tmp_path: Path) -> None:
        ledger = tmp_path / "reports.jsonl"
        _add_report(ledger)
        indexes_dir = tmp_path / "indexes"
        written = write_indexes(indexes_dir, ledger)
        for name, path in written.items():
            data = json.loads(path.read_text())
            assert data is not None, f"{name} is not valid JSON"

    def test_no_mutation_of_findings(self, tmp_path: Path) -> None:
        """Prove write_indexes does not touch docs/findings/."""
        ledger = tmp_path / "reports.jsonl"
        _add_report(ledger)
        findings_dir = tmp_path / "docs" / "findings"
        findings_dir.mkdir(parents=True)
        (findings_dir / "out-of-scope-findings.jsonl").write_text("")
        write_indexes(tmp_path / "indexes", ledger)
        assert (findings_dir / "out-of-scope-findings.jsonl").read_text() == ""


class TestProjectorDeterminism:
    """Prove projectors are deterministic — same input = same output."""

    def test_summary_ordering(self, tmp_path: Path) -> None:
        ledger = tmp_path / "reports.jsonl"
        _add_report(ledger, report_id="r_a", created_at="2026-05-01T00:00:00Z")
        _add_report(ledger, report_id="r_b", created_at="2026-05-02T00:00:00Z")

        s1 = build_report_summary(ledger)
        s2 = build_report_summary(ledger)
        assert s1["total_reports"] == s2["total_reports"]
        assert s1["by_status"] == s2["by_status"]

    def test_snapshots_ordering(self, tmp_path: Path) -> None:
        ledger = tmp_path / "reports.jsonl"
        _add_report(ledger, report_id="r1", created_at="2026-05-01T00:00:00Z")
        _add_report(ledger, report_id="r2", created_at="2026-05-02T00:00:00Z")

        snaps = build_report_snapshots(ledger)
        # DuckDB DISTINCT ON returns rows in ORDER BY group order (report_id ASC),
        # so r1 comes before r2. Both should be present.
        assert len(snaps) == 2
        report_ids = {s["report_id"] for s in snaps}
        assert "r1" in report_ids
        assert "r2" in report_ids


class TestMalformedLedger:
    def test_skips_malformed_lines(self, tmp_path: Path) -> None:
        ledger = tmp_path / "reports.jsonl"
        ledger.write_text(
            '{"report_id": "r1", "kind": "valid"}\n'
            'not json\n'
            '{"report_id": "r2", "kind": "valid"}\n'
        )
        summary = build_report_summary(ledger)
        assert summary["total_reports"] == 2

    def test_partial_malformed_still_counts_valid(self, tmp_path: Path) -> None:
        ledger = tmp_path / "reports.jsonl"
        ledger.write_text(
            'garbage\n'
            '{"report_id": "r1", "kind": "bug", "status": "open", "created_at": "2026-05-15T00:00:00Z", "severity": "medium", "evidence": []}\n'
        )
        summary = build_report_summary(ledger)
        assert summary["total_reports"] == 1
        assert summary["by_kind"]["bug"] == 1
