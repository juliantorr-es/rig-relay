"""GitHub security mission packet redaction adversarial tests."""

from __future__ import annotations

import json

import pytest

from rig_relay.integrations.github_provider._security_mission_packets import (
    project_github_security_mission_packets,
)

pytestmark = [pytest.mark.adversarial]


def test_packet_generator_rejects_forbidden_secret_like_input_content():
    report = {
        "schema_version": "rig.github.security_mission_candidates.v1",
        "generated_at_utc": "2026-05-19T00:00:00Z",
        "source_artifact_path": "docs/json/governance/github_security_mission_candidates_v1.v1.json",
        "source_artifact_hash": "f" * 64,
        "content_light": True,
        "remote_mutation": False,
        "mission_candidate_count": 1,
        "blocked_candidate_count": 0,
        "advisory_candidate_count": 0,
        "ready_candidate_count": 1,
        "route_group_count": 1,
        "route_groups": [
            {
                "route_group_id": "group-id",
                "route": "ready_for_investigation",
                "mission_type": "investigate_security_alert",
                "priority": "p1",
                "candidate_count": 1,
                "candidate_ids": ["candidate-id"],
                "source_candidate_ids": ["source-candidate-id"],
                "source_surfaces": {"code_scanning": 1},
                "severity_summary": {"p1": 1},
                "mutation_allowed": False,
                "remote_mutation_required": False,
                "requires_human_review": True,
                "requires_permission_change": False,
                "proposed_next_action": "inspect_code_scanning_alert",
                "rationale": "candidate",
                "source_hashes": {
                    "route_hash": "route-hash",
                    "mission_type_hash": "mission-type-hash",
                    "priority_hash": "priority-hash",
                    "candidate_id_hashes": ["candidate-id"],
                    "source_candidate_id_hashes": ["source-candidate-id"],
                },
            }
        ],
        "mission_candidates": [
            {
                "mission_candidate_id": "candidate-id",
                "source_candidate_id": "source-candidate-id",
                "source_surface": "code_scanning",
                "recommended_lane": "security_patch",
                "route": "ready_for_investigation",
                "mission_type": "investigate_security_alert",
                "priority": "p1",
                "severity_basis": "normalized severity high -> p1",
                "mutation_allowed": False,
                "remote_mutation_required": False,
                "requires_human_review": True,
                "requires_permission_change": False,
                "proposed_next_action": "inspect_code_scanning_alert",
                "state": "open",
                "confidence": "medium",
                "rationale": "candidate",
                "source_hashes": {
                    "candidate_id_hash": "candidate-hash",
                    "group_id_hash": "group-hash",
                    "group_key_hash": "group-key-hash",
                    "raw_response": "ghs_should_not_escape",
                    "token_prefix": "ghs_should_not_escape",
                    "code_snippet": "ghs_should_not_escape",
                },
            }
        ],
        "blocked_reasons": [],
        "summary": {
            "mission_candidate_count": 1,
            "blocked_candidate_count": 0,
            "advisory_candidate_count": 0,
            "ready_candidate_count": 1,
            "route_group_count": 1,
            "by_route": {"ready_for_investigation": 1},
            "by_mission_type": {"investigate_security_alert": 1},
            "by_priority": {"p1": 1},
        },
    }

    projected = project_github_security_mission_packets(
        report,
        source_artifact_path="docs/json/governance/github_security_mission_candidates_v1.v1.json",
        packet_dir="tests/tmp/mission-packets",
        generated_at_utc="2026-05-19T00:00:00Z",
    )

    serialized = json.dumps(projected, sort_keys=True)
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
