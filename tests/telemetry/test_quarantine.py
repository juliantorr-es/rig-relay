from __future__ import annotations

import json
from pathlib import Path

from rig_relay.core.telemetry.quarantine import (
    get_quarantine_summary,
    is_debug_packet,
    list_quarantined_packets,
    quarantine_debug_export_allowed,
    write_debug_packet,
)

BUNDLE_MANIFEST_SCHEMA_PATH = (
    Path(__file__).parent.parent.parent
    / "docs"
    / "schemas"
    / "rig.relay.telemetry_bundle_manifest.v1.schema.json"
)

# ── Test classification ────────────────────────────────────────────────
# real-artifact: test_write_debug_packet_creates_file,
#                test_write_debug_packet_appends_jsonl,
#                test_list_quarantined_packets_returns_packets,
#                test_get_quarantine_summary_has_correct_counts
# contract:      test_is_debug_packet_true_for_debug_prefix,
#                test_is_debug_packet_false_for_normal_events,
#                test_quarantine_schema_validates,
#                test_debug_export_gating
# adversarial:   test_list_quarantined_packets_empty_when_no_file,
#                test_debug_packet_goes_to_quarantine_not_observability,
#                test_normal_event_goes_to_observability_not_quarantine,
#                test_quarantine_summary_has_hashes,
#                test_quarantine_summary_redaction_status


# ── real-artifact ──────────────────────────────────────────────────────


def test_write_debug_packet_creates_file(tmp_path: Path):
    quarantine_root = tmp_path / "quarantine"
    session_id = "test-session"
    packet = {"event": "debug.test", "data": 42}
    path = write_debug_packet(packet, quarantine_root, session_id)
    assert path.exists()
    assert path.name == "debug_quarantine.jsonl"


def test_write_debug_packet_appends_jsonl(tmp_path: Path):
    quarantine_root = tmp_path / "quarantine"
    session_id = "test-session"
    p1 = {"event": "debug.one", "x": 1}
    p2 = {"event": "debug.two", "x": 2}
    write_debug_packet(p1, quarantine_root, session_id)
    write_debug_packet(p2, quarantine_root, session_id)
    packs = list_quarantined_packets(quarantine_root, session_id)
    assert len(packs) == 2
    assert packs[0]["event"] == "debug.one"
    assert packs[1]["event"] == "debug.two"


def test_list_quarantined_packets_returns_packets(tmp_path: Path):
    quarantine_root = tmp_path / "quarantine"
    session_id = "test-session"
    p = {"event": "debug.test", "payload": {"k": "v"}}
    write_debug_packet(p, quarantine_root, session_id)
    packs = list_quarantined_packets(quarantine_root, session_id)
    assert len(packs) == 1
    assert packs[0] == p


def test_get_quarantine_summary_has_correct_counts(tmp_path: Path):
    quarantine_root = tmp_path / "quarantine"
    session_id = "test-session"
    write_debug_packet({"event": "debug.a"}, quarantine_root, session_id)
    write_debug_packet({"event": "debug.b"}, quarantine_root, session_id)
    write_debug_packet({"event": "debug.c"}, quarantine_root, session_id)
    summary = get_quarantine_summary(quarantine_root, session_id)
    assert summary["session_id"] == session_id
    assert summary["packet_count"] == 3
    assert summary["total_bytes"] > 0
    assert "debug_quarantine.jsonl" in summary["file_path"]


def test_get_quarantine_summary_has_packet_hashes(tmp_path: Path):
    quarantine_root = tmp_path / "quarantine"
    session_id = "test-session-hash"
    write_debug_packet(
        {"event": "debug.a", "payload": {"x": 1}}, quarantine_root, session_id
    )
    summary = get_quarantine_summary(quarantine_root, session_id)
    assert "packet_hashes" in summary
    assert len(summary["packet_hashes"]) == 1
    assert summary["packet_hashes"][0].startswith("sha256:")


def test_get_quarantine_summary_tracks_redaction_status(tmp_path: Path):
    quarantine_root = tmp_path / "quarantine"
    session_id = "test-session-redact"
    write_debug_packet(
        {"event": "debug.leak", "api_key": "[REDACTED]", "normal": "ok"},
        quarantine_root,
        session_id,
    )
    summary = get_quarantine_summary(quarantine_root, session_id)
    assert "redacted_field_count" in summary
    assert "redaction_status" in summary
    assert summary["redacted_field_count"] > 0


# ── contract ──────────────────────────────────────────────────────────


def test_is_debug_packet_true_for_debug_prefix():
    assert is_debug_packet("debug.something.happened") is True
    assert is_debug_packet("rig.relay.debug.latency") is True


def test_is_debug_packet_false_for_normal_events():
    assert is_debug_packet("rig.relay.session.started") is False
    assert is_debug_packet("rig.relay.tool.call_completed") is False
    assert is_debug_packet("coord.session.registered") is False
    assert is_debug_packet("info.debug.something") is False


def test_quarantine_schema_validates():
    schema = json.loads(BUNDLE_MANIFEST_SCHEMA_PATH.read_text())
    props = schema.get("properties", {})
    assert "debug_packet_count" in props
    assert "quarantined_debug_packet_count" in props
    assert "quarantine_file_path" in props
    assert "quarantine_note" in props
    assert props["debug_packet_count"]["type"] == "integer"
    assert props["debug_packet_count"]["default"] == 0
    assert props["quarantined_debug_packet_count"]["type"] == "integer"
    assert props["quarantined_debug_packet_count"]["default"] == 0
    assert props["quarantine_file_path"]["type"] == ["string", "null"]
    assert props["quarantine_note"]["type"] == "string"


def test_debug_export_only_allowed_with_debug_opt_in():
    assert quarantine_debug_export_allowed("debug_opt_in") is True
    assert quarantine_debug_export_allowed("off") is False
    assert quarantine_debug_export_allowed("derived_only") is False
    assert quarantine_debug_export_allowed("evidence_hashes") is False
    assert quarantine_debug_export_allowed("debug_local_only") is False


# ── adversarial ───────────────────────────────────────────────────────


def test_list_quarantined_packets_empty_when_no_file(tmp_path: Path):
    quarantine_root = tmp_path / "nonexistent_dir"
    session_id = "no-session"
    packs = list_quarantined_packets(quarantine_root, session_id)
    assert packs == []


def test_debug_packet_goes_to_quarantine_not_observability(tmp_path: Path):
    import rig_relay.core.paths._vibe_home as vh
    from rig_relay.core.telemetry.local import log_local_event

    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    original_resolver = vh.SESSIONS_ROOT._resolver
    vh.SESSIONS_ROOT._resolver = lambda: sessions_dir

    try:
        session_id = "q-test-session"
        log_local_event(session_id, "debug.memory.leak", {"mb": 512})

        quarantine_file = sessions_dir / session_id / "debug_quarantine.jsonl"
        observability_file = sessions_dir / session_id / "observability.jsonl"

        assert quarantine_file.exists(), "debug packet should be in quarantine"
        assert not observability_file.exists(), (
            "debug packet should NOT be in observability"
        )

        packs = list_quarantined_packets(sessions_dir, session_id)
        assert len(packs) == 1
        assert packs[0]["event_name"] == "rig.relay.debug.memory.leak"
        assert packs[0]["payload"] == {"mb": 512}
    finally:
        vh.SESSIONS_ROOT._resolver = original_resolver


def test_no_quarantine_leakage_for_normal_events(tmp_path: Path):
    import rig_relay.core.paths._vibe_home as vh
    from rig_relay.core.telemetry.local import log_local_event

    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    original_resolver = vh.SESSIONS_ROOT._resolver
    vh.SESSIONS_ROOT._resolver = lambda: sessions_dir

    try:
        session_id = "q-normal-session"
        log_local_event(session_id, "rig.relay.session.started", {"v": 1})

        quarantine_file = sessions_dir / session_id / "debug_quarantine.jsonl"
        observability_file = sessions_dir / session_id / "observability.jsonl"

        assert not quarantine_file.exists(), "normal event should NOT be in quarantine"
        assert observability_file.exists(), "normal event should be in observability"
    finally:
        vh.SESSIONS_ROOT._resolver = original_resolver


def test_debug_packets_excluded_from_production_when_disabled(tmp_path: Path):
    import rig_relay.core.paths._vibe_home as vh
    from rig_relay.core.telemetry.local import log_local_event, set_telemetry_enabled

    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    original_resolver = vh.SESSIONS_ROOT._resolver
    vh.SESSIONS_ROOT._resolver = lambda: sessions_dir

    try:
        set_telemetry_enabled(False)
        session_id = "qa-disabled-1"
        log_local_event(session_id, "debug.memory.leak", {"mb": 512})
        log_local_event(session_id, "rig.relay.tool.call_completed", {"tool": "x"})

        quarantine_file = sessions_dir / session_id / "debug_quarantine.jsonl"
        observability_file = sessions_dir / session_id / "observability.jsonl"

        assert not observability_file.exists(), "no observability when disabled"
        assert not quarantine_file.exists(), (
            "debug packets also blocked when telemetry disabled"
        )
    finally:
        set_telemetry_enabled(True)
        vh.SESSIONS_ROOT._resolver = original_resolver
