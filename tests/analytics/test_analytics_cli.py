from __future__ import annotations

from importlib.util import find_spec
import json
from pathlib import Path
from typing import Any

import pytest

from scripts.rig_relay_analytics import (
    cmd_correlate,
    cmd_query,
    cmd_scan_sessions,
    cmd_view,
    main,
    parse_args,
)

HAS_DUCKD = find_spec("duckdb") is not None


def _make_obs_file(path: Path, events: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for e in events:
            f.write(json.dumps(e) + "\n")


def _make_trace_file(path: Path, events: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for e in events:
            f.write(json.dumps(e) + "\n")


class TestParseArgs:
    def test_scan_sessions_defaults(self) -> None:
        args = parse_args(["scan-sessions"])
        assert args.command == "scan-sessions"

    def test_ingest_all(self) -> None:
        args = parse_args(["ingest-all"])
        assert args.command == "ingest-all"

    def test_view_with_name(self) -> None:
        args = parse_args(["view", "--name", "session-health"])
        assert args.command == "view"
        assert args.name == "session-health"

    def test_view_with_json(self) -> None:
        args = parse_args(["view", "--name", "session-health", "--json"])
        assert args.json is True

    def test_view_with_csv(self) -> None:
        args = parse_args(["view", "--name", "session-health", "--csv"])
        assert args.csv is True

    def test_query(self) -> None:
        args = parse_args(["query", "--sql", "SELECT 1"])
        assert args.command == "query"
        assert args.sql == "SELECT 1"

    def test_correlate(self) -> None:
        args = parse_args(["correlate"])
        assert args.command == "correlate"

    def test_export(self) -> None:
        args = parse_args(["export", "--format", "csv", "--output-dir", "/tmp/out"])
        assert args.command == "export"
        assert args.format == "csv"
        assert str(args.output_dir) == "/tmp/out"

    def test_default_to_help(self) -> None:
        args = parse_args([])
        assert args.command is None


class TestScanSessions:
    def test_scan_empty_root(self, tmp_path: Path) -> None:
        ns = parse_args(["scan-sessions", "--sessions-root", str(tmp_path), "--json"])
        result = cmd_scan_sessions(ns)
        assert result == 0

    def test_scan_with_sessions(self, tmp_path: Path, capsys: Any) -> None:
        sess = tmp_path / "sess-001"
        sess.mkdir(parents=True)
        _make_obs_file(sess / "observability.jsonl", [{"event_name": "test"}])

        ns = parse_args(["scan-sessions", "--sessions-root", str(tmp_path), "--json"])
        result = cmd_scan_sessions(ns)
        assert result == 0
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["session_count"] == 1
        assert data["sessions"][0]["session_id"] == "sess-001"
        assert data["sessions"][0]["observability_present"] is True
        assert data["sessions"][0]["receipts_present"] is False

    def test_scan_with_receipts(self, tmp_path: Path, capsys: Any) -> None:
        sess = tmp_path / "sess-002"
        sess.mkdir(parents=True)
        _make_obs_file(sess / "receipts.jsonl", [{"event_name": "receipt"}])

        ns = parse_args(["scan-sessions", "--sessions-root", str(tmp_path), "--json"])
        result = cmd_scan_sessions(ns)
        assert result == 0
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["sessions"][0]["receipts_present"] is True

    def test_scan_text_output(self, tmp_path: Path, capsys: Any) -> None:
        sess = tmp_path / "sess-003"
        sess.mkdir(parents=True)

        ns = parse_args(["scan-sessions", "--sessions-root", str(tmp_path)])
        result = cmd_scan_sessions(ns)
        assert result == 0
        captured = capsys.readouterr()
        assert "sess-003" in captured.out


@pytest.mark.skipif(not HAS_DUCKD, reason="DuckDB not installed")
class TestViewCommand:
    def test_view_session_health_json(self, tmp_path: Path, capsys: Any) -> None:
        sess = tmp_path / "sess-001"
        sess.mkdir(parents=True)
        _make_obs_file(
            sess / "observability.jsonl",
            [{"event_name": "test.event", "session_id": "sess-001", "payload": "{}"}],
        )
        _make_obs_file(
            sess / "receipts.jsonl",
            [{"event_name": "test.receipt", "session_id": "sess-001", "payload": "{}"}],
        )
        _make_trace_file(tmp_path / "trace_events.jsonl", [])

        ns = parse_args([
            "view",
            "--name",
            "session-health",
            "--json",
            "--sessions-root",
            str(tmp_path),
        ])
        result = cmd_view(ns)
        assert result == 0
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert isinstance(data, list)

    def test_view_unknown_view(self, tmp_path: Path) -> None:
        ns = parse_args(["view", "--name", "nonexistent"])
        result = cmd_view(ns)
        assert result == 1

    def test_view_governance_gate_health(self, tmp_path: Path, capsys: Any) -> None:
        sess = tmp_path / "sess-001"
        sess.mkdir(parents=True)
        _make_obs_file(
            sess / "observability.jsonl",
            [
                {
                    "event_name": "rig.relay.governance_gate.decision",
                    "session_id": "sess-001",
                    "payload": json.dumps({"decision": "allowed"}),
                }
            ],
        )
        _make_obs_file(sess / "receipts.jsonl", [])
        _make_trace_file(tmp_path / "trace_events.jsonl", [])

        ns = parse_args([
            "view",
            "--name",
            "governance-gate-health",
            "--json",
            "--sessions-root",
            str(tmp_path),
        ])
        result = cmd_view(ns)
        assert result == 0
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert isinstance(data, list)


@pytest.mark.skipif(not HAS_DUCKD, reason="DuckDB not installed")
class TestQueryCommand:
    def test_query_select_one(self, capsys: Any) -> None:
        ns = parse_args(["query", "--sql", "SELECT 1 AS x"])
        result = cmd_query(ns)
        assert result == 0

    def test_query_with_session_data(self, tmp_path: Path, capsys: Any) -> None:
        sess = tmp_path / "sess-001"
        sess.mkdir(parents=True)
        _make_obs_file(
            sess / "observability.jsonl",
            [{"event_name": "test.event", "session_id": "sess-001"}],
        )
        _make_obs_file(sess / "receipts.jsonl", [])
        _make_trace_file(tmp_path / "trace_events.jsonl", [])

        ns = parse_args([
            "query",
            "--sql",
            "SELECT count(*) AS cnt FROM observability",
            "--json",
            "--sessions-root",
            str(tmp_path),
        ])
        result = cmd_query(ns)
        assert result == 0
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert isinstance(data, list)


@pytest.mark.skipif(not HAS_DUCKD, reason="DuckDB not installed")
class TestCorrelateCommand:
    def test_correlate_json(self, tmp_path: Path, capsys: Any) -> None:
        sess = tmp_path / "sess-001"
        sess.mkdir(parents=True)
        _make_obs_file(
            sess / "observability.jsonl",
            [{"event_name": "test.event", "session_id": "sess-001"}],
        )
        _make_obs_file(sess / "receipts.jsonl", [])
        _make_trace_file(tmp_path / "trace_events.jsonl", [])

        ns = parse_args(["correlate", "--json", "--sessions-root", str(tmp_path)])
        result = cmd_correlate(ns)
        assert result == 0
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert "trace_to_session" in data
        assert "receipt_to_event" in data
        assert "session_to_parent" in data

    def test_correlate_text(self, tmp_path: Path, capsys: Any) -> None:
        sess = tmp_path / "sess-001"
        sess.mkdir(parents=True)
        _make_obs_file(sess / "observability.jsonl", [])
        _make_obs_file(sess / "receipts.jsonl", [])
        _make_trace_file(tmp_path / "trace_events.jsonl", [])

        ns = parse_args(["correlate", "--sessions-root", str(tmp_path)])
        result = cmd_correlate(ns)
        assert result == 0
        captured = capsys.readouterr()
        assert "Correlation Report" in captured.out


class TestJsonOutputValid:
    def test_scan_sessions_json_is_valid(self, tmp_path: Path, capsys: Any) -> None:
        sess = tmp_path / "sess-001"
        sess.mkdir(parents=True)

        ns = parse_args(["scan-sessions", "--sessions-root", str(tmp_path), "--json"])
        result = cmd_scan_sessions(ns)
        assert result == 0
        captured = capsys.readouterr()
        json.loads(captured.out)


def test_main_no_args() -> None:
    with pytest.raises(SystemExit) as exc_info:
        main([])
    assert exc_info.value.code == 0


def test_main_scan_sessions_help() -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["scan-sessions", "--help"])
    assert exc_info.value.code == 0
