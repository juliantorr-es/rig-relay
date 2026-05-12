from __future__ import annotations

import json
from pathlib import Path
import pytest
from vibe.core.telemetry.duckdb_projection import DuckDBProjection, HAS_DUCKDB
from vibe.core.telemetry.constants import EventName

@pytest.fixture
def session_root(tmp_path):
    root = tmp_path / "sessions"
    root.mkdir()
    return root

def write_event(session_dir: Path, event_name: str, payload: dict, receipt: bool = False):
    log_file = session_dir / "observability.jsonl"
    event = {
        "schema_version": "rig.relay.observability.v1",
        "event_id": "test-id",
        "session_id": session_dir.name,
        "sequence": 0,
        "created_at": "2024-01-01T00:00:00Z",
        "event_name": event_name,
        "payload": payload,
        "producer": {"name": "rig-relay", "version": "1.0.0"},
        "receipt_candidate": receipt,
        "event_hash": "sha256:abc"
    }
    with log_file.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event) + "\n")

@pytest.mark.skipif(not HAS_DUCKDB, reason="DuckDB not installed")
def test_analyzer_summarizes_correctly(session_root):
    s1 = session_root / "session-1"
    s1.mkdir()
    
    # 1. Request accounted
    write_event(s1, EventName.REQUEST_ACCOUNTED, {
        "context_accounting": {
            "model": "gpt-4",
            "estimated_tokens": 1000
        }
    })
    write_event(s1, EventName.REQUEST_ACCOUNTED, {
        "context_accounting": {
            "model": "gpt-4",
            "estimated_tokens": 2000
        }
    })
    
    # 2. Tool calls
    write_event(s1, EventName.TOOL_CALL_COMPLETED, {
        "tool_name": "ls",
        "status": "success"
    }, receipt=True)
    write_event(s1, EventName.TOOL_CALL_COMPLETED, {
        "tool_name": "bash",
        "status": "failure"
    }, receipt=True)

    analyzer = DuckDBProjection(session_root)
    summary = analyzer.get_summary()
    
    assert summary.sessions_seen == 1
    assert summary.events_seen == 4
    assert summary.request_count == 2
    assert summary.max_estimated_tokens == 2000
    assert summary.avg_estimated_tokens == 1500.0
    assert summary.receipt_candidate_count == 2
    assert summary.tool_calls_by_name["ls"] == 1
    assert summary.tool_calls_by_status["success"] == 1
    assert summary.tool_calls_by_status["failure"] == 1

@pytest.mark.skipif(not HAS_DUCKDB, reason="DuckDB not installed")
def test_analyzer_handles_malformed_lines(session_root):
    s1 = session_root / "session-1"
    s1.mkdir()
    log_file = s1 / "observability.jsonl"
    log_file.write_text('{"event_name": "valid"}\nNOT_JSON\n{"event_name": "valid2"}\n')
    
    analyzer = DuckDBProjection(session_root)
    summary = analyzer.get_summary()
    
    assert summary.malformed_line_count == 1
    # DuckDB read_json_auto might ignore the bad line depending on settings, 
    # but our manual pass catches it.

def test_analyzer_handles_missing_duckdb_gracefully(session_root, monkeypatch):
    import vibe.core.telemetry.duckdb_projection
    monkeypatch.setattr(vibe.core.telemetry.duckdb_projection, "HAS_DUCKDB", False)
    
    analyzer = DuckDBProjection(session_root)
    with pytest.raises(ImportError, match="DuckDB is required"):
        analyzer.get_summary()
