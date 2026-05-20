"""Meta permissions inventory integration tests."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from rig_relay.integrations.meta_provider._permissions_inventory import (
    build_meta_permissions_inventory,
)
from scripts.rig_meta_permissions_inventory import main as permissions_main

pytestmark = [pytest.mark.contract, pytest.mark.integration, pytest.mark.substrate]

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = (
    REPO_ROOT / "docs" / "schemas" / "rig.meta.permissions_inventory.v1.schema.json"
)


def _read(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_permissions_inventory_no_network_all_refused():
    report = build_meta_permissions_inventory(
        generated_at="2026-05-20T00:00:00Z", branch="main", head="0" * 40
    )

    assert report["content_light"] is True
    assert report["remote_mutation"] is False
    assert report["live_network"] is False
    assert report["capability_count"] > 0
    assert report["refused_count"] > 0
    assert report["deferred_count"] > 0
    assert len(report["surfaces"]) == 5

    schema = _read(SCHEMA_PATH)
    jsonschema.validate(instance=report, schema=schema)


def test_supported_readonly_count_positive():
    report = build_meta_permissions_inventory(
        generated_at="2026-05-20T00:00:00Z", branch="main", head="0" * 40
    )

    assert report["summary"]["supported_readonly_count"] > 0


def test_publishing_all_refused():
    report = build_meta_permissions_inventory(
        generated_at="2026-05-20T00:00:00Z", branch="main", head="0" * 40
    )

    publishing_surface = next(
        s for s in report["surfaces"] if s["surface_name"] == "Publishing Surfaces"
    )
    for cap in publishing_surface["capabilities"]:
        assert cap["v1_status"] == "refused"


def test_messaging_all_refused():
    report = build_meta_permissions_inventory(
        generated_at="2026-05-20T00:00:00Z", branch="main", head="0" * 40
    )

    whatsapp_surface = next(
        s for s in report["surfaces"] if s["surface_name"] == "WhatsApp Business Cloud"
    )
    send_cap = next(
        c
        for c in whatsapp_surface["capabilities"]
        if c["capability_id"] == "meta.whatsapp.send_message"
    )
    assert send_cap["v1_status"] == "refused"
    assert "all_messaging_refused" in send_cap["refusal_reason"]


def test_high_risk_count_positive():
    report = build_meta_permissions_inventory(
        generated_at="2026-05-20T00:00:00Z", branch="main", head="0" * 40
    )

    assert report["summary"]["high_risk_count"] > 0
    assert report["summary"]["app_review_likely_count"] > 0


def test_summary_cli_prints_compact_table(tmp_path, capsys):
    output = tmp_path / "permissions-inventory.json"
    exit_code = permissions_main(["--output-json", str(output), "--summary"])

    captured = capsys.readouterr().out
    assert exit_code == 0
    assert output.exists()
    assert "total_capabilities" in captured
    assert "refused" in captured


def test_deterministic_capability_ids():
    report1 = build_meta_permissions_inventory(
        generated_at="2026-05-20T00:00:00Z", branch="main", head="0" * 40
    )
    report2 = build_meta_permissions_inventory(
        generated_at="2026-05-20T00:00:00Z", branch="main", head="0" * 40
    )

    ids1 = [c["capability_id"] for s in report1["surfaces"] for c in s["capabilities"]]
    ids2 = [c["capability_id"] for s in report2["surfaces"] for c in s["capabilities"]]
    assert ids1 == ids2
