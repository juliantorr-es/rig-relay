from __future__ import annotations

import json
from pathlib import Path

from scripts.rig_relay_trace_handshake import (
    _select_handshake_id,
    format_handshake_trace,
)


def test_format_handshake_trace_filters_correlated_events(tmp_path: Path) -> None:
    path = tmp_path / "trace_events.jsonl"
    rows = [
        {
            "timestamp": "2026-05-16T10:00:00.000Z",
            "name": "desktop.transport.connection_begin",
            "event_kind": "span.event",
            "attributes": {"handshake_id": "corr_1", "transport.session_id": "ts_1"},
        },
        {
            "timestamp": "2026-05-16T10:00:01.000Z",
            "name": "desktop.transport.handshake_succeeded",
            "event_kind": "span.event",
            "attributes": {
                "handshake_id": "corr_1",
                "transport.session_id": "ts_1",
                "token_present": True,
            },
        },
        {
            "timestamp": "2026-05-16T10:00:02.000Z",
            "name": "desktop.transport.connection_begin",
            "event_kind": "span.event",
            "attributes": {"handshake_id": "corr_2", "transport.session_id": "ts_2"},
        },
    ]
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")

    events = [json.loads(line) for line in path.read_text().splitlines()]
    text = format_handshake_trace(events, "corr_1")
    assert "Handshake trace: corr_1" in text
    assert "desktop.transport.connection_begin" in text
    assert "desktop.transport.handshake_succeeded" in text
    assert "corr_2" not in text


def test_select_handshake_id_prefers_runtime_match_then_latest() -> None:
    events = [
        {
            "timestamp": "2026-05-16T10:00:00.000Z",
            "attributes": {"handshake_id": "corr_1"},
        },
        {
            "timestamp": "2026-05-16T10:00:01.000Z",
            "attributes": {"handshake_id": "corr_2"},
        },
    ]

    assert _select_handshake_id(events, "corr_1") == "corr_1"
    assert _select_handshake_id(events, None) == "corr_2"
