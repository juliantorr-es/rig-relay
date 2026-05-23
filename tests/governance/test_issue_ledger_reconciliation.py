from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

from rig_relay.cli._steward._issues import read_issue_work_items


def _init_git(root: Path) -> None:
    subprocess.run(["git", "init"], cwd=root, capture_output=True, timeout=10)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=root,
        capture_output=True,
        timeout=10,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"], cwd=root, capture_output=True, timeout=10
    )
    (root / "placeholder.txt").write_text("initial", encoding="utf-8")
    subprocess.run(
        ["git", "add", "placeholder.txt"], cwd=root, capture_output=True, timeout=10
    )
    subprocess.run(
        ["git", "commit", "-m", "init"], cwd=root, capture_output=True, timeout=10
    )


def _write_issue_ledger(root: Path, rows: list[dict]) -> Path:
    ledger_dir = root / "docs" / "json" / "issues"
    ledger_dir.mkdir(parents=True, exist_ok=True)
    ledger_path = ledger_dir / "issue_ledger.v1.jsonl"
    with ledger_path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")
    return ledger_path


def _base_issue(issue_id: str, **overrides: object) -> dict:
    issue = {
        "schema_version": "rig.relay.issue.v1",
        "issue_id": issue_id,
        "tracker_id": "archive-3-review-tracker",
        "area": "tests/coordination",
        "title": "Strict schema validator still lacks regression tests",
        "summary": "Open. The validator is fixed, but strict-mode still lacks dedicated regression coverage.",
        "issue_kind": "testing_gap",
        "severity": "medium",
        "priority": "p2",
        "status": "open",
        "verification_state": "verified",
        "source_kind": "transcript",
        "source_label": "Archive 3 review transcript",
        "evidence": "The archive does not contain a regression test for the repaired strict-mode behavior.",
        "why_it_matters": "Without coverage, the bad behavior can regress silently.",
        "recommended_action": "Add tests for valid schema pass, invalid schema fail, and inventory-wide strict validation.",
        "related_files": [
            "scripts/rig_relay_validate_schemas.py",
            "tests/coordination/test_schema_validation.py",
        ],
        "validation_commands": [
            "uv run pytest tests/coordination/test_schema_validation.py -q"
        ],
        "created_at": "2026-05-22T10:56:02Z",
        "updated_at": "2026-05-22T10:56:02Z",
    }
    issue.update(overrides)
    return issue


def _run_issue_reconcile(root: Path, validation_run: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "rig_relay.cli.entrypoint",
            "issues",
            "reconcile",
            "--project-root",
            str(root),
            "--validation-run",
            str(validation_run),
        ],
        capture_output=True,
        text=True,
        cwd=root,
        timeout=30,
    )


def _write_validation_run(root: Path, **overrides: object) -> Path:
    validation_dir = root / ".build" / "rig-relay" / "derived"
    validation_dir.mkdir(parents=True, exist_ok=True)
    path = validation_dir / "issue_validation_run.v1.json"
    payload = {
        "validation_run_id": "vr_issue_1",
        "phase_ids": ["issue_20260522_schema_validator_strict_regression_tests_missing"],
        "command": "uv run pytest tests/coordination/test_schema_validation.py -q",
        "result": "passed",
        "tests_run": 3,
        "tests_intentionally_skipped": 0,
        "test_classifications": {"contract": 1},
        "schema_validation_results": {},
        "evidence_paths": ["tests/coordination/test_schema_validation.py"],
        "source_commit": "abc123",
        "created_at": "2026-05-22T12:00:00Z",
    }
    payload.update(overrides)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


class TestIssueLedgerLatestState:
    def test_latest_resolved_row_suppresses_work_item(self, tmp_path: Path) -> None:
        _init_git(tmp_path)
        issue_id = "issue_1"
        _write_issue_ledger(
            tmp_path,
            [
                _base_issue(issue_id),
                _base_issue(
                    issue_id,
                    status="resolved",
                    summary="Resolved. The strict validator regression test now exists.",
                    resolution="Validation run vr_issue_1 passed.",
                    resolved_at="2026-05-22T12:00:00Z",
                ),
            ],
        )

        items = read_issue_work_items(tmp_path)

        assert items == []


class TestIssueLedgerReconcileCommand:
    def test_passed_validation_run_appends_resolved_issue_row(
        self, tmp_path: Path
    ) -> None:
        _init_git(tmp_path)
        ledger_path = _write_issue_ledger(
            tmp_path,
            [
                _base_issue(
                    "issue_20260522_schema_validator_strict_regression_tests_missing"
                )
            ],
        )
        validation_run = _write_validation_run(tmp_path)

        result = _run_issue_reconcile(tmp_path, validation_run)

        assert result.returncode == 0
        assert "resolved" in result.stdout.lower()

        rows = [
            json.loads(line)
            for line in ledger_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        assert len(rows) == 2
        latest = rows[-1]
        assert latest["status"] == "resolved"
        assert latest["issue_id"] == (
            "issue_20260522_schema_validator_strict_regression_tests_missing"
        )
        assert latest["resolution"]
        assert latest["resolved_at"] == "2026-05-22T12:00:00Z"

        items = read_issue_work_items(tmp_path)
        assert items == []
