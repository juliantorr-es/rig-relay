"""GitHub App permission posture redaction adversarial tests."""

from __future__ import annotations

import json

import pytest

from rig_relay.integrations.github_provider._permission_posture import (
    build_github_permission_posture_report,
)

pytestmark = [pytest.mark.adversarial]


def test_permission_posture_allows_safe_secret_scanning_permission_name_but_rejects_secret_material():
    report = build_github_permission_posture_report(
        live_auth={
            "live_results": {
                "token_exchange": {
                    "permissions": {
                        "secret_scanning_alerts": "read",
                        "security_events": "read",
                    }
                }
            }
        },
        security_intake={"schema_version": "rig.github.security_intake.v1"},
        work_items={
            "schema_version": "rig.github.security_work_items.v1",
            "candidate_groups": [],
            "refusals": [],
            "summary": {},
        },
        mission_candidates={
            "schema_version": "rig.github.security_mission_candidates.v1",
            "mission_candidates": [],
            "blocked_reasons": [],
        },
        source_artifacts=[
            {
                "artifact_role": "live_auth",
                "path": "docs/json/governance/live_github_auth_result.v1.json",
                "present": True,
                "status": "available",
                "artifact_hash": "f" * 64,
                "schema_version": "rig.github.live_auth_result.v1",
                "reason": None,
            }
        ],
        generated_at_utc="2026-05-19T00:00:00Z",
    )

    serialized = json.dumps(report, sort_keys=True)
    assert "secret_scanning_alerts" in serialized
    for forbidden in (
        "ghp_",
        "gho_",
        "ghu_",
        "ghs_",
        "ghr_",
        "github_pat_",
        "BEGIN PRIVATE KEY",
        '"access_token"',
        '"token_prefix"',
        '"authorization"',
        '"client_secret"',
        '"private_key"',
        '"raw_response"',
        '"raw_body"',
        '"patch"',
        '"diff"',
        '"contents"',
        '"code_snippet"',
    ):
        assert forbidden not in serialized


def test_permission_posture_rejects_malicious_secret_material():
    with pytest.raises(ValueError, match="forbidden"):
        build_github_permission_posture_report(
            live_auth={
                "live_results": {
                    "token_exchange": {
                        "permissions": {"security_events": "read"},
                        "raw_response": "ghs_should_not_escape",
                    }
                }
            },
            security_intake={"schema_version": "rig.github.security_intake.v1"},
            work_items={
                "schema_version": "rig.github.security_work_items.v1",
                "candidate_groups": [],
                "refusals": [],
                "summary": {},
            },
            mission_candidates={
                "schema_version": "rig.github.security_mission_candidates.v1",
                "mission_candidates": [],
                "blocked_reasons": [],
            },
            source_artifacts=[
                {
                    "artifact_role": "live_auth",
                    "path": "docs/json/governance/live_github_auth_result.v1.json",
                    "present": True,
                    "status": "available",
                    "artifact_hash": "f" * 64,
                    "schema_version": "rig.github.live_auth_result.v1",
                    "reason": None,
                }
            ],
            generated_at_utc="2026-05-19T00:00:00Z",
        )
