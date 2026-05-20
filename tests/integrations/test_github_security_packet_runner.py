from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from rig_relay.integrations.github_provider._security_packet_runner import (
    build_github_security_packet_runner_plan,
)

pytestmark = [pytest.mark.contract, pytest.mark.integration]

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = (
    REPO_ROOT
    / "docs"
    / "schemas"
    / "rig.github.security_packet_runner_plan.v1.schema.json"
)


def test_plan_selects_exactly_limit_packets():
    plan = build_github_security_packet_runner_plan(limit=3)

    assert plan["schema_version"] == "rig.github.security_packet_runner_plan.v1"
    assert plan["content_light"] is True
    assert plan["remote_mutation"] is False
    assert plan["apply_local"] is False
    assert plan["selected_packet_count"] == 3
    assert plan["limit"] == 3
    assert plan["selection_mode"] == "default_limit"
    assert len(plan["plan_items"]) == 3
    assert plan["refusals"] == []

    for item in plan["plan_items"]:
        assert len(item["plan_item_id"]) == 64
        assert len(item["packet_id"]) == 64
        assert item["remote_mutation"] is False
        assert item["apply_local"] is False
        assert item["status"] == "planned"
        assert isinstance(item["severity_summary"], dict)
        assert isinstance(item["expected_local_categories"], list)
        assert isinstance(item["required_validation_commands"], list)


def test_plan_selects_by_packet_id():
    target_id = "00172fc90c7b61137f68c8df8d31306e539515772cf39f266ed4d7233983c319"

    plan = build_github_security_packet_runner_plan(packet_ids=[target_id])

    assert plan["selected_packet_count"] == 1
    assert plan["selection_mode"] == "by_packet_id"
    assert len(plan["plan_items"]) == 1
    assert plan["plan_items"][0]["packet_id"] == target_id


def test_plan_refuses_when_packets_missing():
    plan = build_github_security_packet_runner_plan(
        packet_index_path=REPO_ROOT / "nonexistent.json"
    )
    assert plan["refusals"]


def test_plan_is_schema_valid():
    plan = build_github_security_packet_runner_plan(limit=3)

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.validate(instance=plan, schema=schema)


def test_plan_is_content_light():
    plan = build_github_security_packet_runner_plan(limit=3)

    serialized = json.dumps(plan, sort_keys=True)
    for forbidden in (
        "token_prefix",
        "access_token",
        "authorization",
        "raw_response",
        "raw_body",
        "code_snippet",
        "patch",
        "diff",
        "contents",
        "secret",
    ):
        assert forbidden not in serialized


def test_plan_items_are_deterministically_ordered():
    plan = build_github_security_packet_runner_plan(limit=5)
    item_ids = [item["packet_id"] for item in plan["plan_items"]]
    assert item_ids == sorted(item_ids)


def test_plan_item_has_complete_severity_summary():
    plan = build_github_security_packet_runner_plan(limit=1)

    item = plan["plan_items"][0]
    severity = item["severity_summary"]
    assert "normalized_severity" in severity
    assert "priority" in severity
    assert "source_alert_count" in severity


def test_plan_item_has_expected_categories():
    plan = build_github_security_packet_runner_plan(limit=1)

    item = plan["plan_items"][0]
    assert len(item["expected_local_categories"]) > 0
