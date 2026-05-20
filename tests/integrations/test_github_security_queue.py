"""Integration tests for unified security queue."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from rig_relay.integrations.github_provider._security_queue import (
    _SOURCE_SURFACES,
    _SURFACE_PERMISSIONS,
    _calculate_priority,
    _normalize_advisory_to_queue_item,
    _normalize_code_scanning_to_queue_item,
    _normalize_dependabot_to_queue_item,
    _normalize_policy_gap_to_queue_item,
    _normalize_secret_scanning_to_queue_item,
    build_security_queue,
)

pytestmark = [pytest.mark.contract]

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = (
    REPO_ROOT / "docs" / "schemas" / "rig.github.security_queue.v1.schema.json"
)


def _sample_intake() -> dict:
    return {
        "alerts": {
            "code_scanning": [
                {
                    "alert_number": 1,
                    "state": "open",
                    "rule_severity": "high",
                    "rule_id_hash": "abc123",
                    "file_path_hash": "def456",
                    "suggested_group_kind": "codeql_security_fix_needed",
                },
                {
                    "alert_number": 2,
                    "state": "fixed",
                    "rule_severity": "medium",
                    "rule_id_hash": "ghi789",
                    "file_path_hash": "jkl012",
                    "suggested_group_kind": "code_quality_fix_needed",
                },
            ],
            "dependabot": [
                {
                    "alert_number": 1,
                    "state": "open",
                    "severity": "critical",
                    "package_ecosystem": "pip",
                    "package_name_hash": "pkg123",
                    "ghsa_id_hash": "ghsa456",
                    "fixed_version_available": True,
                }
            ],
        },
        "source_surfaces": [
            {"surface": "code_scanning", "status": "collected"},
            {"surface": "dependabot", "status": "collected"},
        ],
        "refusals": [
            {
                "surface": "secret_scanning",
                "reason": "missing_permission_or_not_enabled",
                "required_permission": "security_events:read",
            }
        ],
    }


# ── Priority tests ──


def test_priority_critical_open():
    score, reason = _calculate_priority("critical", "open")
    assert score == 0
    assert "severity=critical" in reason
    assert "state=open" in reason


def test_priority_low_fixed():
    score, _ = _calculate_priority("low", "fixed")
    assert score >= 3


def test_priority_permission_unavailable_boosts():
    score, reason = _calculate_priority("medium", "open", permission_available=False)
    assert "permission_unavailable" in reason
    assert score <= 2


def test_priority_unknown_deprioritizes():
    sc1, _ = _calculate_priority("high", "open", confidence="high")
    sc2, _ = _calculate_priority("high", "open", confidence="low")
    assert sc1 <= sc2


def test_priority_deterministic():
    sc1, r1 = _calculate_priority("high", "open", "high", True, False)
    sc2, r2 = _calculate_priority("high", "open", "high", True, False)
    assert sc1 == sc2
    assert r1 == r2


# ── Normalization tests ──


def test_normalize_cs_alert():
    alert = {
        "alert_number": 1,
        "state": "open",
        "rule_severity": "high",
        "rule_id_hash": "abc",
        "file_path_hash": "def",
        "suggested_group_kind": "codeql_security_fix_needed",
    }
    item = _normalize_code_scanning_to_queue_item(alert, 0)
    assert item["source_surface"] == "code_scanning"
    assert item["severity"] == "high"
    assert item["state"] == "open"
    assert item["remote_mutation_status"] == "disabled"
    assert item["content_light"] is True
    assert "queue_item_id" in item


def test_normalize_db_alert():
    alert = {
        "alert_number": 1,
        "state": "open",
        "severity": "critical",
        "package_ecosystem": "pip",
        "package_name_hash": "pkg",
        "ghsa_id_hash": "ghsa",
        "fixed_version_available": True,
    }
    item = _normalize_dependabot_to_queue_item(alert, 0)
    assert item["source_surface"] == "dependabot"
    assert item["severity"] == "critical"
    assert item["remediation_lane"] == "dependency_update_needed"


def test_normalize_ss_refusal():
    item = _normalize_secret_scanning_to_queue_item({}, 0)
    assert item["source_surface"] == "secret_scanning"
    assert item["source_kind"] == "refusal"
    assert item["state"] == "refused"
    assert "source_surface_refused" in item["blocked_reasons"]


def test_normalize_advisory_missing():
    item = _normalize_advisory_to_queue_item(None, 0)
    assert item["source_surface"] == "repository_security_advisory"
    assert item["source_kind"] == "not_available"
    assert "source_artifact_missing" in item["blocked_reasons"]


def test_normalize_policy_gap():
    item = _normalize_policy_gap_to_queue_item()
    assert item["source_surface"] == "security_policy_gap"
    assert item["security_domain"] == "security_policy"


# ── Queue build tests ──


def test_build_queue_from_intake():
    report = build_security_queue(generated_at_utc="2026-05-20T00:00:00Z")
    assert report["schema_version"] == "rig.github.security_queue.v1"
    assert report["content_light"] is True
    assert report["remote_mutation"] is False
    assert report["queue_summary"]["total_queue_items"] >= 5


def test_build_queue_includes_all_five_surfaces():
    report = build_security_queue(generated_at_utc="2026-05-20T00:00:00Z")
    surfaces = {s["surface"] for s in report["input_surfaces"]}
    assert "code_scanning" in surfaces
    assert "dependabot" in surfaces
    assert "secret_scanning" in surfaces
    assert "repository_security_advisory" in surfaces
    assert "security_policy_gap" in surfaces


def test_build_queue_has_permission_model():
    report = build_security_queue(generated_at_utc="2026-05-20T00:00:00Z")
    perms = report["permission_summary"]
    assert "read_permissions" in perms
    assert "remediation_permissions" in perms
    assert len(perms["read_permissions"]) > 0


def test_build_queue_remediation_not_active():
    report = build_security_queue(generated_at_utc="2026-05-20T00:00:00Z")
    rem = report["remediation_readiness_summary"]
    assert rem["remediation_possible"] is False
    assert rem["remote_mutation_required"] is False


def test_queue_items_sorted_by_priority():
    report = build_security_queue(generated_at_utc="2026-05-20T00:00:00Z")
    items = report["queue_items"]
    scores = [qi["priority_score"] for qi in items if "priority_score" in qi]
    assert scores == sorted(scores)


def test_queue_has_severity_breakdown():
    report = build_security_queue(generated_at_utc="2026-05-20T00:00:00Z")
    breakdown = report["queue_summary"]["severity_breakdown"]
    assert isinstance(breakdown, dict)
    assert sum(breakdown.values()) == report["queue_summary"]["total_queue_items"]


def test_queue_has_surface_breakdown():
    report = build_security_queue(generated_at_utc="2026-05-20T00:00:00Z")
    breakdown = report["queue_summary"]["surface_breakdown"]
    assert isinstance(breakdown, dict)


# ── Schema validation ──


def test_queue_validates_against_schema():
    assert SCHEMA_PATH.exists()
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    report = build_security_queue(generated_at_utc="2026-05-20T00:00:00Z")
    jsonschema.validate(instance=report, schema=schema)


def test_generated_artifact_validates():
    artifact_path = (
        REPO_ROOT / "docs" / "json" / "governance" / "github_security_queue_v1.v1.json"
    )
    if not artifact_path.exists():
        pytest.skip("Queue artifact not yet generated")
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    report = json.loads(artifact_path.read_text(encoding="utf-8"))
    jsonschema.validate(instance=report, schema=schema)
    assert report["remote_mutation"] is False
    assert report["content_light"] is True


# ── Redaction tests ──


def test_queue_no_forbidden_fields():
    report = build_security_queue(generated_at_utc="2026-05-20T00:00:00Z")
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
        '"bearer"',
    ):
        assert forbidden not in serialized


def test_queue_no_token_patterns():
    report = build_security_queue(generated_at_utc="2026-05-20T00:00:00Z")
    serialized = json.dumps(report, sort_keys=True)
    for pattern in ("ghp_", "gho_", "ghu_", "github_pat_", "BEGIN PRIVATE KEY"):
        assert pattern not in serialized


def test_generated_artifact_no_forbidden_content():
    artifact_path = (
        REPO_ROOT / "docs" / "json" / "governance" / "github_security_queue_v1.v1.json"
    )
    if not artifact_path.exists():
        pytest.skip("Queue artifact not yet generated")
    serialized = artifact_path.read_text(encoding="utf-8")
    for pattern in (
        "ghp_",
        "gho_",
        "BEGIN PRIVATE KEY",
        '"access_token"',
        '"authorization"',
        '"raw_body"',
    ):
        assert pattern not in serialized, f"'{pattern}' found in queue artifact"


# ── Permission separation tests ──


def test_read_permissions_separated_from_remediation():
    assert "code_scanning" in _SURFACE_PERMISSIONS
    cs = _SURFACE_PERMISSIONS["code_scanning"]
    assert "read" in cs
    assert "remediation" in cs
    assert cs["read"] != cs["remediation"]


def test_remediation_not_required_for_queue_items():
    report = build_security_queue(generated_at_utc="2026-05-20T00:00:00Z")
    for item in report["queue_items"]:
        assert item["mutation_required"] is False
        assert item["remote_mutation_status"] == "disabled"


def test_all_five_source_surfaces_defined():
    assert len(_SOURCE_SURFACES) == 5
    assert "code_scanning" in _SOURCE_SURFACES
    assert "security_policy_gap" in _SOURCE_SURFACES
