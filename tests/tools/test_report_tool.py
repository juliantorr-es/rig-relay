"""Tests for rig.report tool — argument validation, persistence, deduplication,
receipt emission, and read-only guarantee on the canonical findings registry.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from rig_relay.core.tools.base import BaseToolState
from rig_relay.core.tools.builtins.report import (
    Report,
    ReportArgs,
    ReportResult,
    ReportToolConfig,
)
from rig_relay.reports.report_store import (
    REPORT_KINDS,
    compute_report_sha256,
    derive_dedupe_key,
    find_existing_report,
    generate_report_id,
    write_report_to_ledger,
)


class TestReportArgs:
    """Argument model validation."""

    def test_minimal_args(self) -> None:
        args = ReportArgs(
            kind="bug_report", title="Test bug", summary="Something broke"
        )
        assert args.kind == "bug_report"
        assert args.severity == "medium"
        assert args.status == "open"

    def test_all_kinds_valid(self) -> None:
        for kind in sorted(REPORT_KINDS):
            args = ReportArgs(kind=kind, title="t", summary="s")
            assert args.kind == kind

    def test_invalid_kind_rejected(self) -> None:
        with pytest.raises(ValueError, match="Invalid kind"):
            ReportArgs(kind="not_a_real_kind", title="t", summary="s")

    def test_invalid_severity_rejected(self) -> None:
        with pytest.raises(ValueError, match="Invalid severity"):
            ReportArgs(kind="bug_report", title="t", summary="s", severity="extreme")

    def test_extra_fields_rejected(self) -> None:
        with pytest.raises(ValueError):
            ReportArgs.model_validate({
                "kind": "bug_report",
                "title": "t",
                "summary": "s",
                "unknown": "x",
            })  # type: ignore

    def test_affected_paths(self) -> None:
        args = ReportArgs(
            kind="architecture_seam",
            title="Seam",
            summary="Boundary issue",
            affected_paths=["src/main.py", "src/utils.py"],
        )
        assert len(args.affected_paths) == 2

    def test_evidence_validation(self) -> None:
        args = ReportArgs(
            kind="data_race",
            title="Race",
            summary="Concurrent write",
            evidence=[
                {
                    "kind": "code_reference",
                    "path": "src/main.py",
                    "summary": "Race at line 42",
                }
            ],
        )
        assert len(args.evidence) == 1


class TestReportResult:
    def test_result_fields(self) -> None:
        r = ReportResult(ok=True, report_id="report_abc")
        assert r.ok is True
        assert r.dedupe_status == "new"
        assert r.report_sha256 == ""
        assert r.event_sha256 == ""

    def test_report_and_event_hashes_separate(self) -> None:
        """Prove report_sha256 and event_sha256 are different fields."""
        r = ReportResult(
            ok=True,
            report_id="r1",
            report_sha256="sha256:report",
            event_sha256="sha256:event",
        )
        assert r.report_sha256 == "sha256:report"
        assert r.event_sha256 == "sha256:event"
        assert r.report_sha256 != r.event_sha256

    def test_ledger_and_finding_counts_separate(self) -> None:
        """Prove raw report counts and canonical finding counts are distinct fields."""
        r = ReportResult(
            ok=True,
            report_id="r2",
            report_ledger_count=10,
            open_raw_report_count=4,
            open_finding_count=2,
            stale_finding_count=1,
        )
        assert r.report_ledger_count == 10
        assert r.open_raw_report_count == 4
        assert r.open_finding_count == 2
        assert r.stale_finding_count == 1

    def test_extra_fields_rejected(self) -> None:
        with pytest.raises(ValueError):
            ReportResult.model_validate({"ok": True, "report_id": "r", "unknown": "x"})  # type: ignore


class TestReportStore:
    """Pure functions for report persistence."""

    def test_generate_report_id(self) -> None:
        rid = generate_report_id()
        assert rid.startswith("report_")
        assert len(rid) > 20

    def test_derive_dedupe_key(self) -> None:
        key1 = derive_dedupe_key({
            "kind": "bug",
            "title": "Test",
            "affected_paths": ["a.py"],
        })
        key2 = derive_dedupe_key({
            "kind": "bug",
            "title": "Test",
            "affected_paths": ["a.py"],
        })
        assert key1 == key2

    def test_dedupe_key_different_for_different_content(self) -> None:
        key1 = derive_dedupe_key({
            "kind": "bug",
            "title": "One",
            "affected_paths": ["a.py"],
        })
        key2 = derive_dedupe_key({
            "kind": "bug",
            "title": "Two",
            "affected_paths": ["a.py"],
        })
        assert key1 != key2

    def test_compute_report_sha256(self) -> None:
        report = {"a": 1, "b": 2}
        sha = compute_report_sha256(report)
        assert len(sha) == 64
        assert sha == compute_report_sha256({"b": 2, "a": 1})  # stable JSON key order

    def test_write_and_find(self, tmp_path: Path) -> None:
        ledger = tmp_path / "reports.jsonl"
        report = {
            "report_id": "report_001",
            "dedupe_key": "key001",
            "kind": "test",
            "title": "Test",
            "summary": "A test report",
        }
        ledger_path = write_report_to_ledger(report, ledger)
        assert ledger_path == ledger
        assert ledger.is_file()

        found = find_existing_report("key001", ledger)
        assert found is not None
        assert found["report_id"] == "report_001"

    def test_find_nonexistent(self, tmp_path: Path) -> None:
        ledger = tmp_path / "reports.jsonl"
        found = find_existing_report("nonexistent", ledger)
        assert found is None

    def test_ledger_is_append_only(self, tmp_path: Path) -> None:
        """Prove that writing a second report doesn't destroy the first."""
        ledger = tmp_path / "reports.jsonl"
        write_report_to_ledger(
            {"report_id": "r1", "dedupe_key": "k1", "title": "First"}, ledger
        )
        write_report_to_ledger(
            {"report_id": "r2", "dedupe_key": "k2", "title": "Second"}, ledger
        )

        lines = ledger.read_text().strip().split("\n")
        assert len(lines) == 2
        assert json.loads(lines[0])["title"] == "First"
        assert json.loads(lines[1])["title"] == "Second"

    def test_dedupe_detects_exact_match(self, tmp_path: Path) -> None:
        """Prove that a report with the same dedupe_key is detected as duplicate."""
        ledger = tmp_path / "reports.jsonl"
        key = "dupe_key_123"
        write_report_to_ledger(
            {"report_id": "r1", "dedupe_key": key, "title": "Original"}, ledger
        )
        found = find_existing_report(key, ledger)
        assert found is not None
        assert found["title"] == "Original"

    def test_dedupe_no_false_positive(self, tmp_path: Path) -> None:
        ledger = tmp_path / "reports.jsonl"
        write_report_to_ledger(
            {"report_id": "r1", "dedupe_key": "key_a", "title": "A"}, ledger
        )
        found = find_existing_report("key_b", ledger)
        assert found is None


class TestReportToolRegistration:
    def test_tool_name(self) -> None:
        assert Report.get_name() == "report"

    def test_tool_is_writes_evidence_only(self) -> None:
        assert Report.mutation_class.value == "writes_evidence_only"

    def test_tool_is_not_abstract(self) -> None:
        import inspect

        assert not inspect.isabstract(Report)
        config = ReportToolConfig()
        state = BaseToolState()
        tool = Report(config_getter=lambda: config, state=state)
        assert tool is not None

    def test_has_description(self) -> None:
        assert len(Report.description) > 50


class TestReportToolDoesNotMutateFindings:
    """Prove rig.report does not touch the canonical findings registry."""

    @pytest.mark.asyncio
    async def test_no_modification_to_findings_registry(self, tmp_path: Path) -> None:
        import os

        orig_cwd = Path.cwd()
        os.chdir(str(tmp_path))

        try:
            findings_dir = tmp_path / "docs" / "findings"
            findings_dir.mkdir(parents=True)
            findings_jsonl = findings_dir / "out-of-scope-findings.jsonl"
            findings_jsonl.write_text("", encoding="utf-8")
            findings_md = findings_dir / "out-of-scope-findings.md"
            findings_md.write_text("# Empty", encoding="utf-8")

            config = ReportToolConfig()
            state = BaseState()
            tool = Report(config_getter=lambda: config, state=state)

            args = ReportArgs(
                kind="architecture_seam",
                title="Test seam",
                summary="A test report for testing",
            )
            async for event in tool.run(args):
                if isinstance(event, ReportResult):
                    assert event.ok is True

            # Canonical findings must be untouched
            assert findings_jsonl.read_text() == ""
            assert findings_md.read_text() == "# Empty"
        finally:
            os.chdir(str(orig_cwd))


class BaseState(BaseToolState):
    pass


class TestReportDataRaceDetails:
    """Verifies data_race report kind with kind-specific details."""

    def test_data_race_report_args(self) -> None:
        args = ReportArgs(
            kind="data_race",
            title="Concurrent store writers",
            summary="Two agents writing the same coordination store key without advisory lock",
            severity="high",
            confidence="confirmed",
            affected_paths=["rig_relay/coordination/store.py"],
            evidence=[
                {
                    "kind": "code_reference",
                    "path": "rig_relay/coordination/store.py",
                    "summary": "No advisory lock before put",
                }
            ],
            details={
                "shared_resource": ".build/rig-relay/coordination/",
                "race_condition": "Concurrent writers can overwrite job state without advisory lock",
                "reproduction": "Run two agents writing the same job id concurrently",
                "observed_failure_mode": "Lost update on job state",
                "lock_expectation": "Advisory file lock or coordination lease before write",
            },
        )
        assert args.kind == "data_race"
        assert args.details["shared_resource"] == ".build/rig-relay/coordination/"
        assert args.severity == "high"
