from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from rig_relay.integrations.github_provider._surface_audit import (
    build_github_surface_audit,
)

pytestmark = [pytest.mark.contract, pytest.mark.integration]

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = REPO_ROOT / "docs" / "schemas" / "rig.github.surface_audit.v1.schema.json"


def test_surface_audit_is_content_light():
    audit = build_github_surface_audit()

    assert audit["schema_version"] == "rig.github.surface_audit.v1"
    assert audit["content_light"] is True
    assert audit["remote_mutation"] is False


def test_surface_audit_has_all_required_surfaces():
    audit = build_github_surface_audit()

    surface_names = {s["surface_name"] for s in audit["audited_surfaces"]}
    assert "project_readme" in surface_names
    assert "profile_readme" in surface_names
    assert "static_site_pages" in surface_names
    assert "badge_status_block" in surface_names
    assert "public_claims" in surface_names
    assert "changelog" in surface_names
    assert "license" in surface_names
    assert "contributing" in surface_names
    assert "security_policy" in surface_names
    assert "code_of_conduct" in surface_names


def test_surface_audit_has_proposal_packets_for_missing_surfaces():
    audit = build_github_surface_audit()

    missing_names = {m["surface_name"] for m in audit["missing_surfaces"]}
    proposal_targets = {p["target_surface"] for p in audit["proposal_packets"]}

    for name in missing_names:
        assert name in proposal_targets, f"No proposal for missing surface {name}"


def test_surface_audit_profile_readme_needs_live_check():
    audit = build_github_surface_audit()

    profile = next(
        s for s in audit["audited_surfaces"] if s["surface_name"] == "profile_readme"
    )
    assert profile["status"] == "needs_live_check"
    assert profile["present"] is False


def test_surface_audit_project_readme_detected():
    audit = build_github_surface_audit()

    readme = next(
        s for s in audit["audited_surfaces"] if s["surface_name"] == "project_readme"
    )
    assert readme["present"] is True
    assert readme["status"] == "present"


def test_surface_audit_is_schema_valid():
    audit = build_github_surface_audit()

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.validate(instance=audit, schema=schema)


def test_surface_audit_has_summary():
    audit = build_github_surface_audit()

    summary = audit["summary"]
    assert isinstance(summary, dict)
    assert "total_surfaces_audited" in summary
    assert summary["total_surfaces_audited"] == 10
    assert "present_surface_count" in summary
    assert "missing_surface_count" in summary


def test_surface_audit_proposals_are_deterministic():
    audit = build_github_surface_audit()

    proposal_ids = [p["proposal_id"] for p in audit["proposal_packets"]]
    assert proposal_ids == sorted(proposal_ids)


def test_surface_audit_no_remote_mutation_ever():
    audit = build_github_surface_audit()

    serialized = json.dumps(audit, sort_keys=True)
    assert audit["remote_mutation"] is False
    for forbidden in (
        "token_prefix",
        "access_token",
        "authorization",
        "raw_response",
        "raw_body",
    ):
        assert forbidden not in serialized
