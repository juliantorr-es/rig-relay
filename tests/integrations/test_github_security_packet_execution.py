from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from rig_relay.integrations.github_provider._security_packet_execution import (
    build_github_security_packet_execution,
)

pytestmark = [pytest.mark.contract, pytest.mark.integration]

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = (
    REPO_ROOT
    / "docs"
    / "schemas"
    / "rig.github.security_packet_execution.v1.schema.json"
)
PLAN_PATH = (
    REPO_ROOT
    / "docs"
    / "json"
    / "governance"
    / "github_security_packet_runner_plan_v1.v1.json"
)


def test_execution_selects_exactly_limit_items():
    result = build_github_security_packet_execution(limit=1)

    assert result["schema_version"] == "rig.github.security_packet_execution.v1"
    assert result["content_light"] is True
    assert result["remote_mutation"] is False
    assert result["local_mutation"] is False
    assert result["selected_count"] == 1
    assert result["executed_count"] == 1
    assert result["limit"] == 1
    assert len(result["execution_results"]) == 1


def test_execution_selects_by_packet_id():
    target = "00172fc90c7b61137f68c8df8d31306e539515772cf39f266ed4d7233983c319"

    result = build_github_security_packet_execution(packet_ids=[target])

    assert result["selected_count"] == 1
    assert len(result["execution_results"]) == 1
    assert result["execution_results"][0]["packet_id"] == target


def test_execution_refuses_local_apply_by_default():
    result = build_github_security_packet_execution(limit=1, refuse_local_apply=True)
    assert result["refuse_local_apply"] is True
    assert result["local_mutation"] is False


def test_execution_refuses_missing_plan():
    result = build_github_security_packet_execution(
        plan_path=REPO_ROOT / "nonexistent.json"
    )
    assert result["selected_count"] == 0
    assert result["executed_count"] == 0


def test_execution_is_schema_valid():
    result = build_github_security_packet_execution(limit=1)

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.validate(instance=result, schema=schema)


def test_execution_is_content_light():
    result = build_github_security_packet_execution(limit=1)

    serialized = json.dumps(result, sort_keys=True)
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


def test_execution_result_has_required_fields():
    result = build_github_security_packet_execution(limit=1)

    item = result["execution_results"][0]
    assert len(item["execution_id"]) == 64
    assert len(item["packet_id"]) == 64
    assert isinstance(item["candidate_id"], str)
    assert item["remote_mutation"] is False
    assert item["local_mutation"] is False
    assert item["content_light"] is True
    assert "remediation_recommendation" in item
    assert "result_status" in item
    assert isinstance(item["evidence_refs"], list)


def test_execution_results_are_deterministic():
    result = build_github_security_packet_execution(limit=2)

    ids = [item["packet_id"] for item in result["execution_results"]]
    assert ids == sorted(ids)


def test_execution_summary_has_all_fields():
    result = build_github_security_packet_execution(limit=1)

    summary = result["summary"]
    assert "selected_count" in summary
    assert "executed_count" in summary
    assert "needs_local_remediation_count" in summary
    assert "needs_human_review_count" in summary
    assert "permission_blocked_count" in summary
    assert "advisory_only_count" in summary
    assert "skipped_count" in summary
    assert "next_recommended_action" in summary


def test_execution_limit_max_three():
    result = build_github_security_packet_execution(limit=2)

    assert result["selected_count"] <= 3
    assert result["selected_count"] == 2
