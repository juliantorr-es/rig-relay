"""GitHub operating picture integration tests."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from rig_relay.integrations.github_provider._operating_picture import (
    build_github_operating_picture,
    build_github_operating_picture_from_paths,
)
from scripts.rig_github_operating_picture import main as operating_picture_main

pytestmark = [pytest.mark.contract, pytest.mark.integration, pytest.mark.substrate]

REPO_ROOT = Path(__file__).resolve().parents[2]
LIVE_AUTH_PATH = (
    REPO_ROOT / "docs" / "json" / "governance" / "live_github_auth_result.v1.json"
)
INTAKE_PATH = (
    REPO_ROOT / "docs" / "json" / "governance" / "github_security_intake_result.v1.json"
)
CANDIDATES_PATH = (
    REPO_ROOT
    / "docs"
    / "json"
    / "governance"
    / "github_security_mission_candidates_v1.v1.json"
)
PACKETS_PATH = (
    REPO_ROOT
    / "docs"
    / "json"
    / "governance"
    / "github_security_mission_packets_v1.v1.json"
)
CI_PATH = (
    REPO_ROOT / "docs" / "json" / "governance" / "github_ci_cd_reliability_v1.v1.json"
)
SWIFT_PATH = (
    REPO_ROOT
    / "docs"
    / "json"
    / "governance"
    / "swift_codeql_advisory_parking_v1.v1.json"
)
SCHEMA_PATH = (
    REPO_ROOT / "docs" / "schemas" / "rig.github.operating_picture.v1.schema.json"
)


def _read(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _missing_descriptor(artifact_id: str, path: Path) -> dict[str, object]:
    return {
        "artifact_id": artifact_id,
        "path": str(path),
        "present": False,
        "status": "missing",
        "artifact_hash": None,
        "schema_version": None,
        "summary": None,
    }


def test_operating_picture_joins_real_artifacts_and_is_fresh():
    report = build_github_operating_picture_from_paths(
        owner="juliantorr-es", repo="rig-relay", generated_at_utc="2026-05-20T00:00:00Z"
    )

    assert report["content_light"] is True
    assert report["remote_mutation"] is False
    assert report["auth_summary"]["installation_access_proven"] is True
    assert report["auth_summary"]["token_present"] is True
    assert report["auth_summary"]["token_hash_present"] is True
    assert report["candidate_summary"]["candidate_count"] == 44
    assert report["candidate_summary"]["ready_for_investigation_count"] == 27
    assert report["packet_summary"]["packet_count"] == 27
    assert report["packet_summary"]["excluded_by_route"] == {
        "advisory_only": 15,
        "permission_required": 2,
    }
    assert report["packet_summary"]["packet_index_stale"] is False
    assert report["intake_summary"]["code_scanning"]["status"] == "present"
    assert report["intake_summary"]["dependabot"]["status"] == "refused"
    assert report["intake_summary"]["checks"]["status"] == "present"
    assert report["intake_summary"]["workflow_runs"]["status"] == "present"
    assert report["local_patch_lane_summary"]["codeql_security_fix_needed"] == 27
    assert report["local_patch_lane_summary"]["code_quality_fix_needed"] == 15
    assert report["local_patch_lane_summary"]["permission_blocked"] == 2
    assert report["next_recommended_actions"][0] == "run_packet_lane"
    assert "secret_scanning_alerts" in json.dumps(report)

    schema = _read(SCHEMA_PATH)
    jsonschema.validate(instance=report, schema=schema)


def test_missing_optional_artifacts_produce_structured_missing_status():
    live_auth = _read(LIVE_AUTH_PATH)
    report = build_github_operating_picture(
        context={
            "owner": "juliantorr-es",
            "repo": "rig-relay",
            "generated_at_utc": "2026-05-20T00:00:00Z",
            "branch": "main",
            "head": "0" * 40,
        },
        source_artifacts=[
            {
                "artifact_id": "live_auth",
                "path": str(LIVE_AUTH_PATH),
                "present": True,
                "status": "present",
                "artifact_hash": "a" * 64,
                "schema_version": "rig.github.live_auth_result.v1",
                "summary": {"permission_mode": "development_debug"},
            },
            _missing_descriptor("security_intake", INTAKE_PATH),
            _missing_descriptor("security_mission_candidates", CANDIDATES_PATH),
            _missing_descriptor("security_mission_packets", PACKETS_PATH),
            _missing_descriptor("github_ci_cd_reliability", CI_PATH),
            _missing_descriptor("swift_codeql_advisory_parking", SWIFT_PATH),
        ],
        artifacts={
            "live_auth": live_auth,
            "security_intake": None,
            "security_mission_candidates": None,
            "security_mission_packets": None,
            "github_ci_cd_reliability": None,
            "swift_codeql_advisory_parking": None,
        },
    )

    assert report["intake_summary"]["code_scanning"]["status"] == "missing"
    assert report["candidate_summary"]["candidate_count"] == 0
    assert report["packet_summary"]["packet_count"] == 0
    assert report["next_recommended_actions"][0] == "run_live_intake_dry_run"


def test_packet_index_stale_true_when_source_hash_mismatch():
    live_auth = _read(LIVE_AUTH_PATH)
    intake = _read(INTAKE_PATH)
    candidate_artifact = {
        "schema_version": "rig.github.security_mission_candidates.v1",
        "generated_at_utc": "2026-05-20T00:00:00Z",
        "source_artifact_path": str(CANDIDATES_PATH),
        "source_artifact_hash": "1" * 64,
        "content_light": True,
        "remote_mutation": False,
        "mission_candidate_count": 1,
        "blocked_candidate_count": 0,
        "advisory_candidate_count": 0,
        "ready_candidate_count": 1,
        "route_groups": [],
        "mission_candidates": [],
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
    packet_artifact = {
        "schema_version": "rig.github.security_mission_packets.v1",
        "generated_at_utc": "2026-05-20T00:00:00Z",
        "source_artifact_path": str(CANDIDATES_PATH),
        "source_artifact_hash": "2" * 64,
        "content_light": True,
        "remote_mutation": False,
        "packet_count": 1,
        "excluded_candidate_count": 0,
        "excluded_by_route": {},
        "route_summary": {
            "selection_mode": "ready_only",
            "input_by_route": {"ready_for_investigation": 1},
            "selected_by_route": {"ready_for_investigation": 1},
            "selected_route": "ready_for_investigation",
        },
        "summary": {
            "packet_count": 1,
            "excluded_candidate_count": 0,
            "excluded_by_route": {},
            "source_artifact_hash": "2" * 64,
            "remote_mutation": False,
        },
    }
    report = build_github_operating_picture(
        context={
            "owner": "juliantorr-es",
            "repo": "rig-relay",
            "generated_at_utc": "2026-05-20T00:00:00Z",
            "branch": "main",
            "head": "0" * 40,
        },
        source_artifacts=[
            {
                "artifact_id": "live_auth",
                "path": str(LIVE_AUTH_PATH),
                "present": True,
                "status": "present",
                "artifact_hash": "a" * 64,
                "schema_version": "rig.github.live_auth_result.v1",
                "summary": {"permission_mode": "development_debug"},
            },
            {
                "artifact_id": "security_intake",
                "path": str(INTAKE_PATH),
                "present": True,
                "status": "present",
                "artifact_hash": "b" * 64,
                "schema_version": "rig.github.security_intake.v1",
                "summary": {"code_scanning_total": 42},
            },
            {
                "artifact_id": "security_mission_candidates",
                "path": str(CANDIDATES_PATH),
                "present": True,
                "status": "present",
                "artifact_hash": "a" * 64,
                "schema_version": "rig.github.security_mission_candidates.v1",
                "summary": {"mission_candidate_count": 1},
            },
            {
                "artifact_id": "security_mission_packets",
                "path": str(PACKETS_PATH),
                "present": True,
                "status": "present",
                "artifact_hash": "c" * 64,
                "schema_version": "rig.github.security_mission_packets.v1",
                "summary": {"source_artifact_hash": "2" * 64},
            },
        ],
        artifacts={
            "live_auth": live_auth,
            "security_intake": intake,
            "security_mission_candidates": candidate_artifact,
            "security_mission_packets": packet_artifact,
            "github_ci_cd_reliability": _read(CI_PATH),
            "swift_codeql_advisory_parking": _read(SWIFT_PATH),
        },
    )

    assert report["packet_summary"]["packet_index_stale"] is True
    assert report["next_recommended_actions"][0] == "regenerate_packets"


def test_summary_cli_prints_compact_table(tmp_path, capsys):
    output = tmp_path / "operating-picture.json"
    exit_code = operating_picture_main([
        "--owner",
        "juliantorr-es",
        "--repo",
        "rig-relay",
        "--output-json",
        str(output),
        "--summary",
    ])

    captured = capsys.readouterr().out
    assert exit_code == 0
    assert output.exists()
    assert "packet_index_stale" in captured
    assert "packet_count" in captured
    assert (
        json.loads(output.read_text(encoding="utf-8"))["summary"][
            "next_recommended_action"
        ]
        == "run_packet_lane"
    )
