"""Meta surface audit integration tests."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from rig_relay.integrations.meta_provider._surface_audit import build_meta_surface_audit
from scripts.rig_meta_surface_audit import main as surface_audit_main

pytestmark = [pytest.mark.contract, pytest.mark.integration, pytest.mark.substrate]

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = REPO_ROOT / "docs" / "schemas" / "rig.meta.surface_audit.v1.schema.json"


def _read(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_surface_audit_all_packets_present():
    report = build_meta_surface_audit(
        generated_at="2026-05-20T00:00:00Z", branch="main", head="0" * 40
    )

    assert report["content_light"] is True
    assert report["remote_mutation"] is False
    assert report["live_network"] is False
    assert report["packet_count"] == 9
    assert report["refused_packet_count"] == 2

    schema = _read(SCHEMA_PATH)
    jsonschema.validate(instance=report, schema=schema)


def test_publishing_refusal_packet_exists():
    report = build_meta_surface_audit(
        generated_at="2026-05-20T00:00:00Z", branch="main", head="0" * 40
    )

    refusal_packet = next(
        p
        for p in report["packets"]
        if p["proposed_future_action"].startswith(
            "Document the permanent v1 refusal of all publishing"
        )
    )
    assert refusal_packet["current_status"] == "refused"
    assert refusal_packet["remote_mutation"] is False
    assert refusal_packet["content_light"] is True


def test_messaging_refusal_packet_exists():
    report = build_meta_surface_audit(
        generated_at="2026-05-20T00:00:00Z", branch="main", head="0" * 40
    )

    refusal_packet = next(
        p
        for p in report["packets"]
        if "messaging" in p["surface"] and p["current_status"] == "refused"
    )
    assert refusal_packet["current_status"] == "refused"
    assert "ingest" in refusal_packet["safety_notes"].lower()


def test_all_packets_content_light_and_no_mutation():
    report = build_meta_surface_audit(
        generated_at="2026-05-20T00:00:00Z", branch="main", head="0" * 40
    )

    for packet in report["packets"]:
        assert packet["content_light"] is True
        assert packet["remote_mutation"] is False


def test_deterministic_packet_ids():
    report1 = build_meta_surface_audit(
        generated_at="2026-05-20T00:00:00Z", branch="main", head="0" * 40
    )
    report2 = build_meta_surface_audit(
        generated_at="2026-05-20T00:00:00Z", branch="main", head="0" * 40
    )

    ids1 = [p["packet_id"] for p in report1["packets"]]
    ids2 = [p["packet_id"] for p in report2["packets"]]
    assert ids1 == ids2
    for pid in ids1:
        assert pid.startswith("meta-surface-audit:")
        assert len(pid) == len("meta-surface-audit:") + 12


def test_summary_has_correct_counts():
    report = build_meta_surface_audit(
        generated_at="2026-05-20T00:00:00Z", branch="main", head="0" * 40
    )

    assert report["summary"]["total_packets"] == 9
    assert report["summary"]["refused_packets"] == 2
    assert report["summary"]["deferred_packets"] >= 1
    assert report["summary"]["blocked_packets"] >= 1


def test_summary_cli_prints_compact_table(tmp_path, capsys):
    output = tmp_path / "surface-audit.json"
    exit_code = surface_audit_main(["--output-json", str(output), "--summary"])

    captured = capsys.readouterr().out
    assert exit_code == 0
    assert output.exists()
    assert "total_packets" in captured
    assert "refused" in captured
