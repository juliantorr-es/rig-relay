"""CLI seam tests for the release evidence gate — test the actual `python -m rig_relay.release_gate` entrypoint.

These tests invoke the real CLI via subprocess to validate argument parsing,
exit codes, output format, and file I/O. They complement the existing
GateRunner/registry/check unit tests by exercising the argparse + _main()
boundary.
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess

REPO_ROOT = Path(__file__).resolve().parents[2]

# A check known to pass in the real repo: visibility matrix has 0 release blockers,
# and the one "missing" path has release_blocker=false with a non-"None" recommended_fix.
_KNOWN_PASSING_CHECK = "runtime.visibility_matrix.release_paths"


def _run_gate(
    *args: str, cwd: Path | None = None, timeout: int = 60
) -> subprocess.CompletedProcess[str]:
    """Run the release gate CLI via uv subprocess."""
    cmd = ["uv", "run", "python", "-m", "rig_relay.release_gate", *args]
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=str(cwd) if cwd is not None else str(REPO_ROOT),
        timeout=timeout,
    )


class TestCliExitCodes:
    def test_runs_and_exits_zero(self):
        """Gate passes when run with a known-passing check."""
        result = _run_gate("--include-check", _KNOWN_PASSING_CHECK)
        assert result.returncode == 0, (
            f"Expected exit 0, got {result.returncode}\n"
            f"stdout: {result.stdout}\n"
            f"stderr: {result.stderr}"
        )

    def test_include_check_unknown_reports_deferred(self):
        """Unknown --include-check is deferred with warning, exits 0."""
        result = _run_gate("--include-check", "definitely.nonexistent.check")
        # Unknown check IDs are deferred, not errors — gate exits 0
        assert result.returncode == 0, (
            f"Unknown check should not crash; got {result.returncode}\n"
            f"stdout: {result.stdout}\n"
            f"stderr: {result.stderr}"
        )
        assert "gate:" in result.stdout, "Should print gate summary"


class TestCliOutput:
    def test_output_is_valid_json(self, tmp_path: Path):
        """--output writes a file containing valid JSON."""
        output_file = tmp_path / "gate_result.json"
        result = _run_gate(
            "--include-check", _KNOWN_PASSING_CHECK, "--output", str(output_file)
        )
        assert result.returncode == 0, f"CLI failed: {result.stderr}"
        assert output_file.is_file(), f"Output file not written: {output_file}"
        raw = output_file.read_text(encoding="utf-8")
        parsed = json.loads(raw)
        assert isinstance(parsed, dict)

    def test_output_has_required_fields(self, tmp_path: Path):
        """CLI JSON output contains all fields that __main__.py produces."""
        output_file = tmp_path / "gate_result.json"
        result = _run_gate(
            "--include-check", _KNOWN_PASSING_CHECK, "--output", str(output_file)
        )
        assert result.returncode == 0, f"CLI failed: {result.stderr}"
        parsed = json.loads(output_file.read_text(encoding="utf-8"))

        # Top-level keys produced by _main() at __main__.py:68-79
        required_top = [
            "schema_version",
            "gate_id",
            "overall_status",
            "summary",
            "checks",
            "findings",
            "lifecycle",
        ]
        for key in required_top:
            assert key in parsed, f"Missing top-level key: {key}"

        # summary sub-fields (from GateSummary dataclass + asdict)
        summary = parsed["summary"]
        assert isinstance(summary, dict)
        for key in (
            "total_checks",
            "passed",
            "failed",
            "warning",
            "skipped",
            "total_findings",
            "findings_by_severity",
        ):
            assert key in summary, f"Missing summary key: {key}"

        # checks list items (from GateRunner._check_dict at runner.py:207-214)
        checks = parsed["checks"]
        assert isinstance(checks, list)
        assert len(checks) >= 1, f"Expected at least 1 check, got {len(checks)}"
        for chk in checks:
            for key in (
                "check_id",
                "title",
                "status",
                "severity",
                "summary",
                "evidence",
            ):
                assert key in chk, f"Missing check key: {key}"

        # findings list items (from GateRunner._flatten_findings at runner.py:119-131)
        findings = parsed["findings"]
        assert isinstance(findings, list)
        for f in findings:
            for key in (
                "finding_id",
                "check_id",
                "category",
                "description",
                "severity",
                "source",
                "recommendation",
            ):
                assert key in f, f"Missing finding key: {key}"

    def test_output_file_written_to_nested_path(self, tmp_path: Path):
        """--output creates parent directories and writes to nested path."""
        output_file = tmp_path / "deep" / "nested" / "result.json"
        result = _run_gate(
            "--include-check", _KNOWN_PASSING_CHECK, "--output", str(output_file)
        )
        assert result.returncode == 0, f"CLI failed: {result.stderr}"
        assert output_file.is_file(), f"Output file not written at {output_file}"
        parsed = json.loads(output_file.read_text(encoding="utf-8"))
        assert parsed["gate_id"] == "release_evidence_v1"

    def test_stdout_reports_summary_line(self):
        """CLI prints a summary line to stdout with check counts."""
        result = _run_gate("--include-check", _KNOWN_PASSING_CHECK)
        assert result.returncode == 0
        assert "gate:" in result.stdout
        assert "checks" in result.stdout


class TestCliFiltering:
    def test_include_check_filters_to_single_check(self, tmp_path: Path):
        """--include-check restricts output to only that check."""
        output_file = tmp_path / "filtered.json"
        target_check = "runtime.visibility_matrix.release_paths"
        result = _run_gate(
            "--include-check", target_check, "--output", str(output_file)
        )
        assert result.returncode == 0, f"CLI failed: {result.stderr}"
        parsed = json.loads(output_file.read_text(encoding="utf-8"))
        check_ids = [c["check_id"] for c in parsed["checks"]]
        assert check_ids == [target_check], (
            f"Expected only [{target_check}], got {check_ids}"
        )

    def test_include_multiple_checks(self, tmp_path: Path):
        """Multiple --include-check flags run all specified checks."""
        output_file = tmp_path / "multi.json"
        checks = [
            "runtime.visibility_matrix.release_paths",
            "runtime.websocket.security_invariants",
        ]
        result = _run_gate(
            "--include-check",
            checks[0],
            "--include-check",
            checks[1],
            "--output",
            str(output_file),
        )
        assert result.returncode == 0, f"CLI failed: {result.stderr}"
        parsed = json.loads(output_file.read_text(encoding="utf-8"))
        check_ids = [c["check_id"] for c in parsed["checks"]]
        assert set(check_ids) == set(checks), (
            f"Expected {set(checks)}, got {set(check_ids)}"
        )

    def test_exclude_check_defers_it(self, tmp_path: Path):
        """--exclude-check marks the check as deferred in output."""
        output_file = tmp_path / "excluded.json"
        excluded = "runtime.websocket.security_invariants"
        result = _run_gate(
            "--include-check",
            "runtime.visibility_matrix.release_paths",
            "--include-check",
            excluded,
            "--exclude-check",
            excluded,
            "--output",
            str(output_file),
        )
        assert result.returncode == 0, f"CLI failed: {result.stderr}"
        parsed = json.loads(output_file.read_text(encoding="utf-8"))
        check_ids = [c["check_id"] for c in parsed["checks"]]
        assert "runtime.visibility_matrix.release_paths" in check_ids
        excluded_entries = [c for c in parsed["checks"] if c["check_id"] == excluded]
        assert len(excluded_entries) >= 1
        for entry in excluded_entries:
            assert entry["status"] == "deferred", (
                f"Excluded check {excluded} should be deferred, got {entry['status']}"
            )


class TestCliNonMutation:
    def test_does_not_mutate_repo(self, tmp_path: Path):
        """Running the gate does not modify tracked files or git status."""
        output_file = tmp_path / "no_mutate.json"

        before_files = subprocess.run(
            ["git", "ls-files", "--cached"],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        tracked_before = (
            set(before_files.stdout.strip().split("\n"))
            if before_files.stdout.strip()
            else set()
        )

        status_before = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )

        result = _run_gate(
            "--include-check", _KNOWN_PASSING_CHECK, "--output", str(output_file)
        )
        assert result.returncode == 0, f"CLI failed: {result.stderr}"

        after_files = subprocess.run(
            ["git", "ls-files", "--cached"],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        tracked_after = (
            set(after_files.stdout.strip().split("\n"))
            if after_files.stdout.strip()
            else set()
        )

        status_after = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )

        assert tracked_before == tracked_after, (
            f"Tracked files changed!\n"
            f"Removed: {tracked_before - tracked_after}\n"
            f"Added: {tracked_after - tracked_before}"
        )
        assert status_before.stdout == status_after.stdout, (
            f"Git status changed!\n"
            f"Before:\n{status_before.stdout}\n"
            f"After:\n{status_after.stdout}"
        )
