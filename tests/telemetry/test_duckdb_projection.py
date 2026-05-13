from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch
import uuid

import pytest

from vibe.core.telemetry.constants import EventName
from vibe.core.telemetry.duckdb_projection import HAS_DUCKDB, DuckDBProjection


@pytest.fixture
def session_root(tmp_path):
    root = tmp_path / "sessions"
    root.mkdir()
    return root


def write_event(
    session_dir: Path, event_name: str, payload: dict, receipt: bool = False
):
    # Ensure payload has a stable-ish schema for DuckDB inference
    full_payload = {
        "context_accounting": {"model": "", "estimated_tokens": 0},
        "tool_name": "",
        "status": "",
        "raw_byte_size": 0,
        "prompt_visible_byte_size": 0,
        "total_estimated_tokens": 0,
        "stable_prefix_bytes": 0,
        "dynamic_suffix_bytes": 0,
        "cache_candidate_bytes": 0,
        "cacheability_ratio": 0.0,
        "prefix_stability_status": "",
        "optimization_hints": [],
    }
    full_payload.update(payload)

    log_file = session_dir / "observability.jsonl"
    event = {
        "schema_version": "rig.relay.observability.v1",
        "event_id": str(uuid.uuid4()),
        "session_id": session_dir.name,
        "sequence": 0,
        "created_at": "2024-01-01T00:00:00Z",
        "event_name": event_name,
        "payload": full_payload,
        "producer": {"name": "rig-relay", "version": "1.0.0"},
        "receipt_candidate": receipt,
        "event_hash": "sha256:abc",
    }
    with log_file.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event) + "\n")


@pytest.mark.skipif(not HAS_DUCKDB, reason="DuckDB not installed")
def test_analyzer_summarizes_correctly(session_root):
    s1 = session_root / "session-1"
    s1.mkdir()

    write_event(
        s1,
        EventName.REQUEST_ACCOUNTED,
        {"context_accounting": {"model": "gpt-4", "estimated_tokens": 1000}},
    )
    write_event(
        s1,
        EventName.TOOL_CALL_COMPLETED,
        {"tool_name": "ls", "status": "success"},
        receipt=True,
    )

    analyzer = DuckDBProjection(session_root)
    summary = analyzer.get_summary()

    assert summary.sessions_seen == 1
    assert summary.events_seen == 2
    assert not summary.errors


@pytest.mark.skipif(not HAS_DUCKDB, reason="DuckDB not installed")
def test_analyzer_handles_spaces_in_paths(session_root):
    s1 = session_root / "session with spaces"
    s1.mkdir()
    write_event(s1, "test.event", {"data": 1})

    analyzer = DuckDBProjection(session_root)
    summary = analyzer.get_summary()
    assert summary.sessions_seen == 1
    assert summary.events_seen == 1
    assert not summary.errors


@pytest.mark.skipif(not HAS_DUCKDB, reason="DuckDB not installed")
def test_analyzer_handles_malformed_lines(session_root):
    s1 = session_root / "session-1"
    s1.mkdir()
    log_file = s1 / "observability.jsonl"
    log_file.write_text('{"event_name": "valid"}\nNOT_JSON\n{"event_name": "valid2"}\n')

    analyzer = DuckDBProjection(session_root)
    summary = analyzer.get_summary()

    assert summary.malformed_line_count == 1
    # DuckDB will still report an error because read_json fails on bad lines by default
    assert any("DuckDB projection failed" in e for e in summary.errors)


@pytest.mark.skipif(not HAS_DUCKDB, reason="DuckDB not installed")
def test_analyzer_records_query_failures(session_root):
    s1 = session_root / "session-1"
    s1.mkdir()
    write_event(s1, "test.event", {"data": 1})

    analyzer = DuckDBProjection(session_root)
    # Mock aggregate to fail
    with patch("duckdb.DuckDBPyRelation.aggregate", side_effect=Exception("SQL Error")):
        summary = analyzer.get_summary()
        assert any("DuckDB projection failed: SQL Error" in e for e in summary.errors)


def test_analyzer_handles_empty_root(tmp_path):
    analyzer = DuckDBProjection(tmp_path / "nonexistent")
    summary = analyzer.get_summary()
    assert summary.sessions_seen == 0
    assert not summary.errors


def test_analyzer_handles_missing_duckdb_gracefully(session_root, monkeypatch):
    import vibe.core.telemetry.duckdb_projection

    monkeypatch.setattr(vibe.core.telemetry.duckdb_projection, "HAS_DUCKDB", False)

    analyzer = DuckDBProjection(session_root)
    with pytest.raises(ImportError, match="DuckDB is required"):
        analyzer.get_summary()
