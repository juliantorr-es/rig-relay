"""GitHub security mission candidate routing integration tests."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from rig_relay.integrations.github_provider._security_mission_candidates import (
    route_github_security_work_items,
    route_github_security_work_items_from_path,
)

pytestmark = [pytest.mark.contract, pytest.mark.integration]

REPO_ROOT = Path(__file__).resolve().parents[2]
WORK_ITEMS_PATH = (
    REPO_ROOT / "docs" / "json" / "governance" / "github_security_work_items_v1.v1.json"
)
MISSION_CANDIDATES_SCHEMA_PATH = (
    REPO_ROOT
    / "docs"
    / "schemas"
    / "rig.github.security_mission_candidates.v1.schema.json"
)


def _work_item(
    *,
    candidate_id: str,
    source_surface: str,
    recommended_lane: str,
    normalized_severity: str,
    state: str,
    confidence: str = "medium",
    source_hashes: dict[str, str] | None = None,
) -> dict[str, object]:
    return {
        "candidate_id": candidate_id,
        "source_surface": source_surface,
        "source_finding_key": f"{source_surface}#{candidate_id}",
        "normalized_severity": normalized_severity,
        "state": state,
        "confidence": confidence,
        "recommended_lane": recommended_lane,
        "recommended_action": "noop",
        "mutation_allowed": False,
        "remote_mutation_required": False,
        "rationale": f"{source_surface} candidate",
        "source_hashes": source_hashes
        or {
            "candidate_id_hash": "candidate-hash",
            "group_id_hash": "group-hash",
            "group_key_hash": "group-key-hash",
        },
    }


def _work_items_report(candidates: list[dict[str, object]]) -> dict[str, object]:
    candidate_groups: list[dict[str, object]] = []
    for candidate in candidates:
        candidate_groups.append({
            "group_id": f"group-{candidate['candidate_id']}",
            "group_kind": candidate["source_surface"],
            "group_key": f"{candidate['source_surface']}|{candidate['candidate_id']}",
            "source_surface": candidate["source_surface"],
            "candidate_count": 1,
            "recommended_lane": candidate["recommended_lane"],
            "recommended_action": candidate["recommended_action"],
            "mutation_allowed": False,
            "remote_mutation_required": False,
            "severity_summary": {str(candidate["normalized_severity"]): 1},
            "candidates": [candidate],
            "source_hashes": {
                "group_key_hash": f"hash-{candidate['candidate_id']}",
                "candidate_id_hashes": [candidate["candidate_id"]],
            },
            "rationale": candidate["rationale"],
        })

    refused_surface_count = sum(
        1 for candidate in candidates if candidate["source_surface"] == "refusal"
    )
    return {
        "schema_version": "rig.github.security_work_items.v1",
        "generated_at_utc": "2026-05-19T00:00:00Z",
        "source_artifact_path": str(WORK_ITEMS_PATH),
        "source_artifact_hash": "f" * 64,
        "remote_mutation": False,
        "content_light": True,
        "work_item_count": len(candidates),
        "refused_surface_count": refused_surface_count,
        "candidate_group_count": len(candidate_groups),
        "candidate_groups": candidate_groups,
        "refusals": [],
        "summary": {
            "work_item_count": len(candidates),
            "candidate_group_count": len(candidate_groups),
            "refused_surface_count": refused_surface_count,
            "by_surface": {},
            "by_lane": {},
            "by_action": {},
        },
    }


def test_routes_dependabot_and_code_scanning_and_refusal_and_unknown(tmp_path):
    report = _work_items_report([
        _work_item(
            candidate_id="dependabot-1",
            source_surface="dependabot",
            recommended_lane="dependency_update",
            normalized_severity="high",
            state="open",
            source_hashes={
                "candidate_id_hash": "dependabot-hash",
                "group_id_hash": "group-hash",
                "group_key_hash": "group-key-hash",
                "package_name_hash": "package-hash",
            },
        ),
        _work_item(
            candidate_id="code-1",
            source_surface="code_scanning",
            recommended_lane="investigation",
            normalized_severity="medium",
            state="open",
            source_hashes={
                "candidate_id_hash": "code-hash",
                "group_id_hash": "group-hash",
                "group_key_hash": "group-key-hash",
                "rule_id_hash": "rule-hash",
            },
        ),
        _work_item(
            candidate_id="refusal-1",
            source_surface="refusal",
            recommended_lane="permission_required",
            normalized_severity="unknown",
            state="refused",
            source_hashes={
                "candidate_id_hash": "refusal-hash",
                "group_id_hash": "group-hash",
                "group_key_hash": "group-key-hash",
                "required_permission_hash": "perm-hash",
            },
        ),
        _work_item(
            candidate_id="unknown-1",
            source_surface="unknown",
            recommended_lane="unknown",
            normalized_severity="unknown",
            state="unknown",
            source_hashes={},
        ),
    ])
    input_path = tmp_path / "work-items.json"
    input_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    projected = route_github_security_work_items_from_path(
        input_path,
        source_artifact_path=str(WORK_ITEMS_PATH),
        generated_at_utc="2026-05-19T00:00:00Z",
    )
    projected_again = route_github_security_work_items(
        report,
        source_artifact_path=str(WORK_ITEMS_PATH),
        generated_at_utc="2026-05-19T00:00:00Z",
    )

    assert projected == projected_again
    assert projected["remote_mutation"] is False
    assert projected["content_light"] is True
    assert projected["mission_candidate_count"] == 4
    assert projected["route_group_count"] == 4
    assert projected["ready_candidate_count"] == 2
    assert projected["blocked_candidate_count"] == 2
    assert projected["advisory_candidate_count"] == 0
    assert projected["summary"]["by_priority"] == {"p1": 1, "p2": 1, "p3": 1, "p4": 1}

    routes = [candidate["route"] for candidate in projected["mission_candidates"]]
    assert routes == [
        "ready_for_dependency_update",
        "ready_for_investigation",
        "permission_required",
        "blocked_insufficient_evidence",
    ]
    priorities = [
        candidate["priority"] for candidate in projected["mission_candidates"]
    ]
    assert priorities == ["p1", "p2", "p3", "p4"]

    permission_candidate = next(
        candidate
        for candidate in projected["mission_candidates"]
        if candidate["route"] == "permission_required"
    )
    assert permission_candidate["mission_type"] == "permission_enablement_plan"
    assert permission_candidate["requires_permission_change"] is True
    assert permission_candidate["requires_human_review"] is True

    unknown_candidate = next(
        candidate
        for candidate in projected["mission_candidates"]
        if candidate["route"] == "blocked_insufficient_evidence"
    )
    assert unknown_candidate["mission_type"] == "unknown_security_work"

    schema = json.loads(MISSION_CANDIDATES_SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.validate(instance=projected, schema=schema)


def test_repeated_runs_keep_identical_ids_and_ordering():
    report = _work_items_report([
        _work_item(
            candidate_id="dependabot-1",
            source_surface="dependabot",
            recommended_lane="dependency_update",
            normalized_severity="high",
            state="open",
        )
    ])

    first = route_github_security_work_items(
        report,
        source_artifact_path=str(WORK_ITEMS_PATH),
        generated_at_utc="2026-05-19T00:00:00Z",
    )
    second = route_github_security_work_items(
        report,
        source_artifact_path=str(WORK_ITEMS_PATH),
        generated_at_utc="2026-05-19T00:00:00Z",
    )

    assert first == second
    assert (
        first["mission_candidates"][0]["mission_candidate_id"]
        == second["mission_candidates"][0]["mission_candidate_id"]
    )
