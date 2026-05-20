"""Integration tests for security remediation plan — top 3, planning-only."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from rig_relay.integrations.github_provider._security_remediation_plan import (
    _MAX_SELECTED,
    _SOURCE_STRATEGIES,
    _build_item_plan,
    _is_actionable,
    _select_top_items,
    build_security_remediation_plan,
)

pytestmark = [pytest.mark.contract]

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = (
    REPO_ROOT
    / "docs"
    / "schemas"
    / "rig.github.security_remediation_plan.v1.schema.json"
)


def _sample_queue_item(**overrides: object) -> dict:
    base = {
        "queue_item_id": "test001",
        "source_surface": "code_scanning",
        "source_kind": "alert",
        "severity": "high",
        "state": "open",
        "security_domain": "code_vulnerability",
        "remediation_lane": "codeql_security_fix_needed",
        "required_permissions": ["security_events:read", "metadata:read"],
        "remediation_permissions": [
            "security_events:write",
            "contents:write",
            "pull_requests:write",
        ],
        "mutation_required": False,
        "remote_mutation_status": "disabled",
        "local_mutation_status": "not_attempted",
        "content_light": True,
        "redaction_status": {"clean": True},
        "priority_score": 0,
        "priority_reason": "severity=high:w1;state=open",
        "blocked_reasons": [],
        "recommended_next_action": "inspect_in_intake_viewer",
        "rule_id_hash": "abc123",
    }
    base.update(overrides)
    return base


# ── Selection policy tests ──


def test_select_top_items_sorts_by_priority():
    items = [
        _sample_queue_item(queue_item_id="low", priority_score=5),
        _sample_queue_item(queue_item_id="high", priority_score=0),
        _sample_queue_item(queue_item_id="mid", priority_score=2),
    ]
    selected, rejected = _select_top_items(items, 3)
    assert len(selected) == 3
    assert selected[0]["queue_item_id"] == "high"
    assert selected[1]["queue_item_id"] == "mid"
    assert selected[2]["queue_item_id"] == "low"


def test_select_top_items_limits_to_max():
    items = [
        _sample_queue_item(queue_item_id=f"item{i}", priority_score=i)
        for i in range(10)
    ]
    selected, rejected = _select_top_items(items, 3)
    assert len(selected) == 3
    assert len(rejected) == 7


def test_select_top_items_excludes_not_available():
    items = [
        _sample_queue_item(queue_item_id="good", priority_score=0),
        _sample_queue_item(
            queue_item_id="na", source_kind="not_available", priority_score=0
        ),
    ]
    selected, _ = _select_top_items(items, 3)
    assert len(selected) == 1
    assert selected[0]["queue_item_id"] == "good"


def test_select_top_items_excludes_fixed():
    items = [
        _sample_queue_item(queue_item_id="good", priority_score=0),
        _sample_queue_item(queue_item_id="fixed", state="fixed", priority_score=0),
    ]
    selected, _ = _select_top_items(items, 3)
    assert len(selected) == 1


def test_select_top_items_excludes_refused():
    items = [
        _sample_queue_item(queue_item_id="good", priority_score=0),
        _sample_queue_item(
            queue_item_id="ref",
            source_kind="refusal",
            state="refused",
            priority_score=0,
        ),
    ]
    selected, _ = _select_top_items(items, 3)
    assert len(selected) == 1


def test_select_fewer_when_not_enough_actionable():
    items = [
        _sample_queue_item(queue_item_id="good", priority_score=0),
        _sample_queue_item(queue_item_id="fixed", state="fixed", priority_score=1),
    ]
    selected, rejected = _select_top_items(items, 3)
    assert len(selected) == 1
    assert len(rejected) == 1


# ── Plan building tests ──


def test_build_remediation_plan_from_queue():
    report = build_security_remediation_plan(generated_at_utc="2026-05-20T00:00:00Z")
    assert report["schema_version"] == "rig.github.security_remediation_plan.v1"
    assert report["content_light"] is True
    assert report["remote_mutation"] is False
    assert report["remote_mutation_status"] == "disabled"
    assert len(report["remediation_plans"]) <= _MAX_SELECTED


def test_selected_items_are_actionable():
    report = build_security_remediation_plan(generated_at_utc="2026-05-20T00:00:00Z")
    for plan in report["remediation_plans"]:
        assert plan["mutation_required"] is False
        assert plan["remote_mutation_status"] == "disabled"
        assert plan["human_review_required"] is True


def test_plan_includes_required_permissions_separated():
    report = build_security_remediation_plan(generated_at_utc="2026-05-20T00:00:00Z")
    for plan in report["remediation_plans"]:
        perms = plan.get("required_permissions")
        assert isinstance(perms, dict)
        assert "read" in perms
        assert "mutation" in perms


def test_plan_includes_strategy_for_each_source():
    for source in ("code_scanning", "secret_scanning", "security_policy_gap"):
        assert source in _SOURCE_STRATEGIES
        strategy = _SOURCE_STRATEGIES[source]
        assert "remediation_strategy" in strategy
        assert "allowed_next_actions" in strategy
        assert "forbidden_actions" in strategy


def test_secret_scanning_strategy_no_secret_values():
    strategy = _SOURCE_STRATEGIES["secret_scanning"]
    assert "persist_secret_value" in strategy["forbidden_actions"]


def test_code_scanning_plan_is_content_light():
    item = _sample_queue_item()
    plan = _build_item_plan(item, 1)
    assert plan["mutation_required"] is False
    assert plan["remote_mutation_status"] == "disabled"
    serialized = json.dumps(plan, sort_keys=True)
    for forbidden in ("code_snippet", "vulnerable_code", "raw_body", "secret_value"):
        assert f'"{forbidden}"' not in serialized


def test_not_available_advisory_is_blocked():
    item = _sample_queue_item(
        source_surface="repository_security_advisory",
        source_kind="not_available",
        state="not_available",
        priority_score=0,
    )
    assert not _is_actionable(item)


def test_policy_gap_produces_planning_only():
    strategy = _SOURCE_STRATEGIES["security_policy_gap"]
    assert strategy["mutation_required"] is False
    assert "auto_write_policy_file" in strategy["forbidden_actions"]


# ── Schema validation tests ──


def test_plan_validates_against_schema():
    assert SCHEMA_PATH.exists()
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    report = build_security_remediation_plan(generated_at_utc="2026-05-20T00:00:00Z")
    jsonschema.validate(instance=report, schema=schema)


def test_generated_artifact_validates():
    artifact_path = (
        REPO_ROOT
        / "docs"
        / "json"
        / "governance"
        / "github_security_remediation_plan_v1.v1.json"
    )
    if not artifact_path.exists():
        pytest.skip("Artifact not yet generated")
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    report = json.loads(artifact_path.read_text(encoding="utf-8"))
    jsonschema.validate(instance=report, schema=schema)
    assert report["remote_mutation"] is False


# ── Redaction tests ──


def test_plan_no_forbidden_fields():
    report = build_security_remediation_plan(generated_at_utc="2026-05-20T00:00:00Z")
    serialized = json.dumps(report, sort_keys=True)
    for forbidden in (
        '"access_token"',
        '"authorization"',
        '"client_secret"',
        '"private_key"',
        '"raw_response"',
        '"raw_body"',
        '"patch"',
        '"diff"',
        '"code_snippet"',
        '"vulnerable_code"',
        '"secret_value"',
    ):
        assert forbidden not in serialized


def test_plan_no_token_patterns():
    report = build_security_remediation_plan(generated_at_utc="2026-05-20T00:00:00Z")
    serialized = json.dumps(report, sort_keys=True)
    for pattern in ("ghp_", "gho_", "github_pat_", "BEGIN PRIVATE KEY"):
        assert pattern not in serialized


def test_generated_artifact_no_forbidden_content():
    artifact_path = (
        REPO_ROOT
        / "docs"
        / "json"
        / "governance"
        / "github_security_remediation_plan_v1.v1.json"
    )
    if not artifact_path.exists():
        pytest.skip("Artifact not yet generated")
    serialized = artifact_path.read_text(encoding="utf-8")
    for pattern in (
        "ghp_",
        "BEGIN PRIVATE KEY",
        '"access_token"',
        '"authorization"',
        '"code_snippet"',
    ):
        assert pattern not in serialized, f"'{pattern}' found"
