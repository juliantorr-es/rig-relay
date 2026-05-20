"""GitHub security mission candidate redaction adversarial tests."""

from __future__ import annotations

import pytest

from rig_relay.integrations.github_provider._security_mission_candidates import (
    route_github_security_work_items,
)

pytestmark = [pytest.mark.adversarial]


def test_router_rejects_forbidden_secret_like_input_content():
    report = {
        "schema_version": "rig.github.security_work_items.v1",
        "generated_at_utc": "2026-05-19T00:00:00Z",
        "source_artifact_path": "docs/json/governance/github_security_work_items_v1.v1.json",
        "source_artifact_hash": "f" * 64,
        "remote_mutation": False,
        "content_light": True,
        "work_item_count": 1,
        "refused_surface_count": 0,
        "candidate_group_count": 1,
        "candidate_groups": [
            {
                "group_id": "group-id",
                "group_kind": "code_scanning",
                "group_key": "code_scanning|1",
                "source_surface": "code_scanning",
                "candidate_count": 1,
                "recommended_lane": "security_patch",
                "recommended_action": "inspect_code_scanning_alert",
                "mutation_allowed": False,
                "remote_mutation_required": False,
                "severity_summary": {"high": 1},
                "candidates": [
                    {
                        "candidate_id": "candidate-id",
                        "source_surface": "code_scanning",
                        "source_finding_key": "code_scanning#1",
                        "normalized_severity": "high",
                        "state": "open",
                        "confidence": "medium",
                        "recommended_lane": "security_patch",
                        "recommended_action": "inspect_code_scanning_alert",
                        "mutation_allowed": False,
                        "remote_mutation_required": False,
                        "rationale": "ghs_should_not_escape",
                        "source_hashes": {
                            "candidate_id_hash": "candidate-hash",
                            "group_id_hash": "group-hash",
                            "group_key_hash": "group-key-hash",
                            "raw_response": "ghs_should_not_escape",
                            "token_prefix": "ghs_should_not_escape",
                        },
                    }
                ],
                "source_hashes": {
                    "group_key_hash": "group-hash",
                    "candidate_id_hashes": ["candidate-id"],
                },
                "rationale": "ghs_should_not_escape",
            }
        ],
        "refusals": [],
        "summary": {
            "work_item_count": 1,
            "candidate_group_count": 1,
            "refused_surface_count": 0,
            "by_surface": {"code_scanning": 1},
            "by_lane": {"security_patch": 1},
            "by_action": {"inspect_code_scanning_alert": 1},
        },
    }

    with pytest.raises(ValueError, match="forbidden"):
        route_github_security_work_items(
            report,
            source_artifact_path="docs/json/governance/github_security_work_items_v1.v1.json",
            generated_at_utc="2026-05-19T00:00:00Z",
        )
