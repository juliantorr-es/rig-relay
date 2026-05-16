from __future__ import annotations

from rig_relay.analytics.model_rows import (
    build_model_behavior_summary,
    normalize_model_turn,
)


def test_normalize_empty_record():
    row = normalize_model_turn({})
    assert row["model_turn_id"] == ""
    assert row["latency_ms"] == 0
    assert row["tool_call_count"] == 0


def test_normalize_full_record():
    row = normalize_model_turn({
        "turn_id": "turn-1",
        "session_id": "s1",
        "provider": "openai",
        "model": "gpt-4",
        "input_token_count": 1000,
        "output_token_count": 200,
        "latency_ms": 1500,
        "tool_call_count": 3,
        "malformed_tool_call_count": 1,
        "retry_count": 0,
        "finish_reason": "stop",
        "error_kind": "",
    })
    assert row["model_turn_id"] == "turn-1"
    assert row["input_token_count"] == 1000
    assert row["tool_call_count"] == 3
    assert row["malformed_tool_call_count"] == 1


def test_model_behavior_summary_empty():
    summary = build_model_behavior_summary([])
    assert summary["total_turns"] == 0
    assert summary["by_provider"] == {}


def test_model_behavior_summary_with_data():
    records = [
        {"provider": "openai", "model": "gpt-4", "input_token_count": 100, "output_token_count": 50, "latency_ms": 100, "tool_call_count": 2, "malformed_tool_call_count": 0, "retry_count": 0, "error_kind": ""},
        {"provider": "openai", "model": "gpt-4", "input_token_count": 200, "output_token_count": 100, "latency_ms": 200, "tool_call_count": 3, "malformed_tool_call_count": 1, "retry_count": 0, "error_kind": ""},
        {"provider": "anthropic", "model": "claude-3", "input_token_count": 300, "output_token_count": 150, "latency_ms": 300, "tool_call_count": 1, "malformed_tool_call_count": 0, "retry_count": 0, "error_kind": ""},
    ]
    summary = build_model_behavior_summary(records)

    assert summary["total_turns"] == 3
    assert summary["by_provider"]["openai"]["turns"] == 2
    assert summary["by_provider"]["anthropic"]["turns"] == 1
    assert summary["malformed_tool_call_rate"] == 1 / 3
    assert summary["total_tokens"] == 900


def test_context_limit_events_counted():
    records = [
        {"provider": "openai", "model": "gpt-4", "error_kind": "context_limit", "input_token_count": 100, "output_token_count": 50, "latency_ms": 100, "tool_call_count": 0, "malformed_tool_call_count": 0, "retry_count": 0},
        {"provider": "openai", "model": "gpt-4", "error_kind": "", "input_token_count": 100, "output_token_count": 50, "latency_ms": 100, "tool_call_count": 0, "malformed_tool_call_count": 0, "retry_count": 0},
    ]
    summary = build_model_behavior_summary(records)
    assert summary["context_limit_events"] == 1


def test_no_pandas_numpy():
    import rig_relay.analytics.model_rows as mr
    source = open(mr.__file__).read()
    assert "import pandas" not in source
    assert "import numpy" not in source
    assert "from pandas" not in source
    assert "from numpy" not in source
