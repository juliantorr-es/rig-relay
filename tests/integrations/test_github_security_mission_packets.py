"""GitHub security mission packet generation integration tests."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from rig_relay.integrations.github_provider._security_mission_packets import (
    project_github_security_mission_packets,
    project_github_security_mission_packets_from_path,
)

pytestmark = [pytest.mark.contract, pytest.mark.integration]

REPO_ROOT = Path(__file__).resolve().parents[2]
MISSION_CANDIDATES_PATH = (
    REPO_ROOT
    / "docs"
    / "json"
    / "governance"
    / "github_security_mission_candidates_v1.v1.json"
)
PACKETS_SCHEMA_PATH = (
    REPO_ROOT
    / "docs"
    / "schemas"
    / "rig.github.security_mission_packets.v1.schema.json"
)


def _candidate(
    *,
    mission_candidate_id: str,
    source_candidate_id: str,
    route: str,
    mission_type: str,
    priority: str,
    normalized_severity: str,
    source_surface: str = "code_scanning",
    recommended_action: str = "inspect_code_scanning_alert",
    proposed_next_action: str = "inspect_code_scanning_alert",
) -> dict[str, object]:
    return {
        "mission_candidate_id": mission_candidate_id,
        "source_candidate_id": source_candidate_id,
        "source_surface": source_surface,
        "recommended_lane": "security_patch",
        "route": route,
        "mission_type": mission_type,
        "priority": priority,
        "severity_basis": "normalized severity high -> p1",
        "mutation_allowed": False,
        "remote_mutation_required": False,
        "requires_human_review": True,
        "requires_permission_change": False,
        "proposed_next_action": proposed_next_action,
        "state": "open",
        "confidence": "medium",
        "rationale": "candidate",
        "source_hashes": {
            "candidate_id_hash": "candidate-hash",
            "group_id_hash": "group-hash",
            "group_key_hash": "group-key-hash",
            "source_surface_hash": "surface-hash",
            "recommended_lane_hash": "lane-hash",
            "route_hash": "route-hash",
            "mission_type_hash": "mission-type-hash",
            "priority_hash": "priority-hash",
            "severity_hash": "severity-hash",
            "state_hash": "state-hash",
            "confidence_hash": "confidence-hash",
        },
        "normalized_severity": normalized_severity,
        "recommended_action": recommended_action,
    }


def _route_group(candidate: dict[str, object]) -> dict[str, object]:
    return {
        "route_group_id": f"group-{candidate['mission_candidate_id']}",
        "route": candidate["route"],
        "mission_type": candidate["mission_type"],
        "priority": candidate["priority"],
        "candidate_count": 1,
        "candidate_ids": [candidate["mission_candidate_id"]],
        "source_candidate_ids": [candidate["source_candidate_id"]],
        "source_surfaces": {candidate["source_surface"]: 1},
        "severity_summary": {candidate["priority"]: 1},
        "mutation_allowed": False,
        "remote_mutation_required": False,
        "requires_human_review": True,
        "requires_permission_change": candidate["route"] == "permission_required",
        "proposed_next_action": candidate["proposed_next_action"],
        "rationale": candidate["rationale"],
        "source_hashes": {
            "route_hash": "route-hash",
            "mission_type_hash": "mission-type-hash",
            "priority_hash": "priority-hash",
            "candidate_id_hashes": [candidate["mission_candidate_id"]],
            "source_candidate_id_hashes": [candidate["source_candidate_id"]],
        },
    }


def _report(candidates: list[dict[str, object]]) -> dict[str, object]:
    route_groups = [_route_group(candidate) for candidate in candidates]
    route_counts: dict[str, int] = {}
    for candidate in candidates:
        route = str(candidate["route"])
        route_counts[route] = route_counts.get(route, 0) + 1
    blocked_candidate_count = route_counts.get("permission_required", 0)
    advisory_candidate_count = route_counts.get("advisory_only", 0)
    ready_candidate_count = route_counts.get("ready_for_investigation", 0)
    return {
        "schema_version": "rig.github.security_mission_candidates.v1",
        "generated_at_utc": "2026-05-19T00:00:00Z",
        "source_artifact_path": str(MISSION_CANDIDATES_PATH),
        "source_artifact_hash": "f" * 64,
        "content_light": True,
        "remote_mutation": False,
        "mission_candidate_count": len(candidates),
        "blocked_candidate_count": blocked_candidate_count,
        "advisory_candidate_count": advisory_candidate_count,
        "ready_candidate_count": ready_candidate_count,
        "route_group_count": len(route_groups),
        "route_groups": route_groups,
        "mission_candidates": candidates,
        "blocked_reasons": [],
        "summary": {
            "mission_candidate_count": len(candidates),
            "blocked_candidate_count": blocked_candidate_count,
            "advisory_candidate_count": advisory_candidate_count,
            "ready_candidate_count": ready_candidate_count,
            "route_group_count": len(route_groups),
            "by_route": dict(sorted(route_counts.items())),
            "by_mission_type": {},
            "by_priority": {},
        },
    }


def test_ready_candidates_generate_packets_and_emit_packet_files(tmp_path):
    ready = _candidate(
        mission_candidate_id="ready-candidate-1",
        source_candidate_id="source-candidate-1",
        route="ready_for_investigation",
        mission_type="investigate_security_alert",
        priority="p1",
        normalized_severity="high",
    )
    advisory = _candidate(
        mission_candidate_id="advisory-candidate-1",
        source_candidate_id="source-candidate-2",
        route="advisory_only",
        mission_type="advisory_record",
        priority="p4",
        normalized_severity="info",
        recommended_action="ignore_noop",
        proposed_next_action="ignore_noop",
    )
    permission_required = _candidate(
        mission_candidate_id="permission-candidate-1",
        source_candidate_id="source-candidate-3",
        route="permission_required",
        mission_type="permission_enablement_plan",
        priority="p3",
        normalized_severity="unknown",
        recommended_action="request_permission",
        proposed_next_action="request_permission",
    )
    report = _report([ready, advisory, permission_required])
    input_path = tmp_path / "mission-candidates.json"
    input_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    packet_dir = tmp_path / "packets"

    projected = project_github_security_mission_packets_from_path(
        input_path,
        source_artifact_path=str(MISSION_CANDIDATES_PATH),
        packet_dir=packet_dir,
        generated_at_utc="2026-05-19T00:00:00Z",
    )
    projected_again = project_github_security_mission_packets(
        report,
        source_artifact_path=str(MISSION_CANDIDATES_PATH),
        packet_dir=packet_dir,
        generated_at_utc="2026-05-19T00:00:00Z",
    )

    assert projected == projected_again
    assert projected["remote_mutation"] is False
    assert projected["content_light"] is True
    assert projected["packet_count"] == 1
    assert projected["excluded_candidate_count"] == 2
    assert projected["excluded_by_route"] == {
        "advisory_only": 1,
        "permission_required": 1,
    }
    assert projected["route_summary"]["selection_mode"] == "ready_only"
    assert projected["route_summary"]["selected_by_route"] == {
        "ready_for_investigation": 1
    }
    assert projected["packets"][0]["route"] == "ready_for_investigation"
    assert projected["packets"][0]["source_alert_count"] == 1
    assert projected["summary"]["packet_count"] == 1
    assert projected["summary"]["excluded_candidate_count"] == 2
    assert (packet_dir / "source-candidate-1.v1.json").exists()

    schema = json.loads(PACKETS_SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.validate(instance=projected, schema=schema)
    packet = json.loads(
        (packet_dir / "source-candidate-1.v1.json").read_text(encoding="utf-8")
    )
    jsonschema.validate(instance=packet, schema=schema)


def test_real_mission_candidates_generate_ready_only_packets(tmp_path):
    projected = project_github_security_mission_packets_from_path(
        MISSION_CANDIDATES_PATH,
        source_artifact_path=str(MISSION_CANDIDATES_PATH),
        packet_dir=tmp_path / "packets",
        generated_at_utc="2026-05-19T00:00:00Z",
    )

    assert projected["packet_count"] == 27
    assert projected["excluded_candidate_count"] == 17
    assert projected["excluded_by_route"] == {
        "advisory_only": 15,
        "permission_required": 2,
    }
    assert (
        projected["packet_count"]
        == projected["route_summary"]["selected_by_route"]["ready_for_investigation"]
    )
    assert projected["risk_summary"]["ready_candidate_count"] == 27
    assert len(projected["packets"]) == 27
    assert all(
        packet["route"] == "ready_for_investigation" for packet in projected["packets"]
    )


def test_source_artifact_hash_changes_when_input_changes(tmp_path):
    base = _report([
        _candidate(
            mission_candidate_id="ready-candidate-1",
            source_candidate_id="source-candidate-1",
            route="ready_for_investigation",
            mission_type="investigate_security_alert",
            priority="p1",
            normalized_severity="high",
        )
    ])
    mutated = json.loads(json.dumps(base))
    mutated["mission_candidates"][0]["priority"] = "p2"
    mutated["route_groups"][0]["priority"] = "p2"
    mutated["summary"]["by_route"] = {"ready_for_investigation": 1}
    mutated["summary"]["by_priority"] = {"p2": 1}

    first = project_github_security_mission_packets(
        base,
        source_artifact_path=str(MISSION_CANDIDATES_PATH),
        packet_dir=tmp_path / "packets-one",
        generated_at_utc="2026-05-19T00:00:00Z",
    )
    second = project_github_security_mission_packets(
        mutated,
        source_artifact_path=str(MISSION_CANDIDATES_PATH),
        packet_dir=tmp_path / "packets-two",
        generated_at_utc="2026-05-19T00:00:00Z",
    )

    assert first["source_artifact_hash"] != second["source_artifact_hash"]
