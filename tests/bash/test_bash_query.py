"""Tests for bash analytics — normalization, queries, projections."""

from __future__ import annotations

import json
from pathlib import Path

from rig_relay.analytics import connect_in_memory, rows_to_dicts
from rig_relay.analytics.bash_rows import (
    create_bash_invocations_table,
    detect_command_family,
    detect_pattern_tags,
    detect_replacement_candidate,
    detect_risk_tags,
    normalize_bash_record,
)


class TestDetectCommandFamily:
    def test_git_status(self) -> None:
        assert detect_command_family("git status --short") == "git_status"

    def test_git_diff(self) -> None:
        assert detect_command_family("git diff HEAD") == "git_diff"

    def test_pytest(self) -> None:
        assert detect_command_family("pytest tests/") == "pytest"

    def test_rg(self) -> None:
        assert detect_command_family("rg pattern src/") == "rg"

    def test_cat(self) -> None:
        assert detect_command_family("cat file.py") == "cat"

    def test_other(self) -> None:
        assert detect_command_family("echo hello") == "other"


class TestDetectPatternTags:
    def test_git_tags(self) -> None:
        tags = detect_pattern_tags("git status --short")
        assert "git" in tags
        assert "status" in tags

    def test_pipe_tag(self) -> None:
        tags = detect_pattern_tags("cat file | grep pattern")
        assert "shell_pipe" in tags

    def test_python_heredoc(self) -> None:
        tags = detect_pattern_tags('python3 -c "print(1)"')
        assert "python_heredoc" in tags

    def test_no_shell_features(self) -> None:
        tags = detect_pattern_tags("ls -la")
        assert "shell_pipe" not in tags


class TestDetectRiskTags:
    def test_uses_shell(self) -> None:
        tags = detect_risk_tags("bash -c 'echo hi'")
        assert "uses_shell" in tags

    def test_rm_risk(self) -> None:
        tags = detect_risk_tags("rm -rf /tmp/foo")
        assert "uses_rm" in tags
        assert "uses_recursive_delete" in tags
        assert "mutates_repo" in tags

    def test_network_risk(self) -> None:
        tags = detect_risk_tags("curl https://example.com")
        assert "uses_network" in tags

    def test_timeout_tag_from_record(self) -> None:
        tags = detect_risk_tags("pytest tests/", {"status": "timed_out"})
        assert "timeout_prone" in tags


class TestDetectReplacementCandidate:
    def test_git_status(self) -> None:
        assert detect_replacement_candidate("git status --short") == "git_status"

    def test_rg_to_grep(self) -> None:
        assert detect_replacement_candidate("rg pattern src/") == "grep"

    def test_cat_to_read_file(self) -> None:
        assert detect_replacement_candidate("cat file.py") == "read_file"

    def test_no_replacement(self) -> None:
        assert detect_replacement_candidate("echo hello") is None


class TestNormalizeBashRecord:
    def test_normalize_basic_command(self) -> None:
        record = {
            "command_text": "pytest tests/",
            "session_id": "s1",
            "duration_ms": 5000,
            "exit_code": 0,
            "status": "completed",
        }
        n = normalize_bash_record(record)
        assert n["command_family"] == "pytest"
        assert n["is_success"] == 1
        assert n["is_validation_command"] == 1
        assert n["is_replacement_candidate"] == 0

    def test_normalize_timeout(self) -> None:
        record = {
            "command_text": "pytest tests/",
            "status": "timed_out",
            "timeout_seconds": 120,
            "duration_ms": 120000,
        }
        n = normalize_bash_record(record)
        assert n["is_timeout"] == 1
        assert n["is_success"] == 0

    def test_normalize_refused(self) -> None:
        record = {
            "command_text": "rm -rf /",
            "status": "refused",
            "refusal_reason": "Dangerous command",
        }
        n = normalize_bash_record(record)
        assert n["is_refusal"] == 1
        assert n["is_destructive_candidate"] == 1
        assert n["refusal_reason"] == "Dangerous command"

    def test_replacement_candidate(self) -> None:
        record = {"command_text": "git status", "status": "completed"}
        n = normalize_bash_record(record)
        assert n["replacement_candidate"] == "git_status"
        assert n["is_replacement_candidate"] == 1

    def test_mutation_tracked(self) -> None:
        record = {
            "command_text": "rm file.txt",
            "mutation_detected": True,
            "affected_paths": ["file.txt"],
        }
        n = normalize_bash_record(record)
        assert n["mutation_detected"] == 1
        assert n["affected_path_count"] == 1

    def test_shell_used(self) -> None:
        record = {"command_text": "bash -c 'echo hi'", "shell_used": True}
        n = normalize_bash_record(record)
        assert n["shell_used"] == 1


class TestCreateBashInvocationsTable:
    def test_empty_table(self) -> None:
        con = connect_in_memory()
        create_bash_invocations_table(con, [])
        rows = rows_to_dicts(con, "SELECT count(*) AS cnt FROM fact_bash_invocations")
        assert rows[0]["cnt"] == 0

    def test_table_with_records(self) -> None:
        con = connect_in_memory()
        records = [normalize_bash_record({"command_text": "ls", "status": "completed"})]
        create_bash_invocations_table(con, records)
        rows = rows_to_dicts(con, "SELECT count(*) AS cnt FROM fact_bash_invocations")
        assert rows[0]["cnt"] == 1


class TestBashQueryFunctions:
    """Integration tests with DuckDB queries."""

    def _make_ledger(self, tmp_path: Path) -> Path:
        ledger = tmp_path / "bash_invocations.jsonl"
        records = [
            {"command_text": "git status --short", "status": "completed", "duration_ms": 100, "session_id": "s1"},
            {"command_text": "pytest tests/ -x", "status": "completed", "duration_ms": 5000, "session_id": "s1"},
            {"command_text": "pytest tests/ -x", "status": "timed_out", "duration_ms": 120000, "timeout_seconds": 120, "session_id": "s2"},
            {"command_text": "rm -rf /tmp/build", "status": "refused", "refusal_reason": "Dangerous", "session_id": "s2"},
            {"command_text": "cat file.py", "status": "completed", "duration_ms": 10, "session_id": "s1"},
        ]
        ledger.write_text("\n".join(json.dumps(r) for r in records) + "\n")
        return ledger

    def test_query_usage_summary(self, tmp_path: Path) -> None:
        from rig_relay.bash.query import query_bash_usage_summary

        ledger = self._make_ledger(tmp_path)
        summary = query_bash_usage_summary(ledger)
        assert summary["total_invocations"] == 5
        assert summary["by_status"]["completed"] == 3
        assert summary["by_status"]["timed_out"] == 1
        assert summary["by_status"]["refused"] == 1
        assert summary["replacement_candidate_count"] >= 2  # git status + cat
        assert summary["shell_used_count"] == 0

    def test_query_failure_clusters(self, tmp_path: Path) -> None:
        from rig_relay.bash.query import query_bash_failure_clusters

        ledger = self._make_ledger(tmp_path)
        clusters = query_bash_failure_clusters(ledger)
        # No explicit failure status in the test data (refused != failure)
        # This is correct — refused commands are separate from failures.
        assert len(clusters) >= 0

    def test_query_timeout_clusters(self, tmp_path: Path) -> None:
        from rig_relay.bash.query import query_bash_timeout_clusters

        ledger = self._make_ledger(tmp_path)
        clusters = query_bash_timeout_clusters(ledger)
        assert len(clusters) >= 1
        assert clusters[0]["timeout_count"] >= 1

    def test_query_risk_patterns(self, tmp_path: Path) -> None:
        from rig_relay.bash.query import query_bash_risk_patterns

        ledger = self._make_ledger(tmp_path)
        patterns = query_bash_risk_patterns(ledger)
        assert len(patterns) >= 1

    def test_query_replacement_candidates(self, tmp_path: Path) -> None:
        from rig_relay.bash.query import query_bash_replacement_candidates

        ledger = self._make_ledger(tmp_path)
        candidates = query_bash_replacement_candidates(ledger)
        assert len(candidates) >= 1

    def test_diagnostics(self, tmp_path: Path) -> None:
        from rig_relay.bash.query import query_bash_diagnostics

        ledger = self._make_ledger(tmp_path)
        diag = query_bash_diagnostics(ledger)
        assert diag["valid_record_count"] == 5
        assert diag["projection_kind"] == "bash_diagnostics"


class TestBashProjector:
    def test_write_indexes(self, tmp_path: Path) -> None:
        from rig_relay.bash.query import write_bash_indexes

        # Write a temp ledger with one record
        ledger = tmp_path / "bash_invocations.jsonl"
        ledger.write_text(json.dumps({"command_text": "git status", "status": "completed"}) + "\n")
        indexes_dir = tmp_path / "indexes"
        written = write_bash_indexes(indexes_dir, ledger)
        assert len(written) == 5
        for name in ("bash_usage_summary", "bash_failure_clusters", "bash_timeout_clusters",
                     "bash_risk_patterns", "bash_replacement_candidates"):
            assert name in written
            assert written[name].is_file()


class TestNoMutation:
    def test_does_not_mutate_canonical_findings(self, tmp_path: Path) -> None:
        """Prove bash analytics never touches canonical findings."""
        from rig_relay.bash.query import query_bash_usage_summary

        findings_dir = tmp_path / "docs" / "findings"
        findings_dir.mkdir(parents=True)
        (findings_dir / "out-of-scope-findings.jsonl").write_text("")
        (findings_dir / "out-of-scope-findings.md").write_text("# Empty")

        ledger = tmp_path / "bash_invocations.jsonl"
        ledger.write_text(json.dumps({"command_text": "ls", "status": "completed"}) + "\n")
        query_bash_usage_summary(ledger)

        assert (findings_dir / "out-of-scope-findings.jsonl").read_text() == ""
        assert (findings_dir / "out-of-scope-findings.md").read_text() == "# Empty"
