"""GitHub App permission posture integration tests."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from rig_relay.integrations.github_provider._permission_posture import (
    build_github_permission_posture_report,
    build_github_permission_posture_report_from_paths,
)

pytestmark = [pytest.mark.contract, pytest.mark.integration]

REPO_ROOT = Path(__file__).resolve().parents[2]
LIVE_AUTH_PATH = (
    REPO_ROOT / "docs" / "json" / "governance" / "live_github_auth_result.v1.json"
)
INTAKE_PATH = (
    REPO_ROOT / "docs" / "json" / "governance" / "github_security_intake_result.v1.json"
)
WORK_ITEMS_PATH = (
    REPO_ROOT / "docs" / "json" / "governance" / "github_security_work_items_v1.v1.json"
)
MISSION_CANDIDATES_PATH = (
    REPO_ROOT
    / "docs"
    / "json"
    / "governance"
    / "github_security_mission_candidates_v1.v1.json"
)
SCHEMA_PATH = (
    REPO_ROOT / "docs" / "schemas" / "rig.github_app_permission_posture.v1.schema.json"
)


def _load(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_permission_posture_derives_mappings_from_real_artifacts(tmp_path):
    report = build_github_permission_posture_report_from_paths(
        live_auth_json=LIVE_AUTH_PATH,
        security_intake_json=INTAKE_PATH,
        work_items_json=WORK_ITEMS_PATH,
        mission_candidates_json=MISSION_CANDIDATES_PATH,
        generated_at_utc="2026-05-19T00:00:00Z",
    )
    repeat = build_github_permission_posture_report_from_paths(
        live_auth_json=LIVE_AUTH_PATH,
        security_intake_json=INTAKE_PATH,
        work_items_json=WORK_ITEMS_PATH,
        mission_candidates_json=MISSION_CANDIDATES_PATH,
        generated_at_utc="2026-05-19T00:00:00Z",
    )

    assert report == repeat
    assert report["remote_mutation"] is False
    assert report["content_light"] is True

    observed = {
        item["permission_name"]: item["level"]
        for item in report["observed_permissions"]
    }
    assert observed["actions"] == "read"
    assert observed["metadata"] == "read"

    required = {
        item["permission_name"]: item for item in report["required_permissions"]
    }
    assert required["security_events"]["status"] == "missing"
    assert required["secret_scanning_alerts"]["status"] == "missing"
    assert required["vulnerability_alerts"]["status"] == "missing"
    assert required["workflows"]["status"] == "non_goal"
    assert required["workflows"]["allowed_in_this_slice"] is False

    request_names = [
        item["permission_name"] for item in report["permission_request_plan"]
    ]
    assert request_names == [
        "secret_scanning_alerts",
        "security_events",
        "vulnerability_alerts",
    ]

    blocked = report["blocked_candidate_links"]
    assert len(blocked) == 3
    assert all(item["blocked_reason"] == "permission_required" for item in blocked)

    assert report["risk_summary"]["requested_read_permissions_count"] == 3
    assert report["risk_summary"]["requested_sensitive_read_permissions_count"] == 1
    assert report["risk_summary"]["requested_write_permissions_count"] == 0
    assert report["risk_summary"]["requested_admin_permissions_count"] == 0
    assert report["risk_summary"]["mutation_permissions_requested"] is False

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.validate(instance=report, schema=schema)


def test_permission_posture_handles_missing_optional_artifacts(tmp_path):
    missing_live_auth = tmp_path / "missing-live-auth.json"
    report = build_github_permission_posture_report_from_paths(
        live_auth_json=missing_live_auth,
        security_intake_json=INTAKE_PATH,
        work_items_json=WORK_ITEMS_PATH,
        mission_candidates_json=MISSION_CANDIDATES_PATH,
        generated_at_utc="2026-05-19T00:00:00Z",
    )

    unavailable = [
        item
        for item in report["source_artifacts"]
        if item["status"] == "input_unavailable"
    ]
    assert unavailable
    assert unavailable[0]["path"].endswith("missing-live-auth.json")
    assert report["summary"]["input_unavailable_count"] == len(unavailable)
    assert report["summary"]["permission_request_count"] == 3


def test_permission_posture_rejects_missing_meaningful_inputs():
    with pytest.raises(Exception, match="no meaningful input artifacts available"):
        build_github_permission_posture_report(
            live_auth=None,
            security_intake=None,
            work_items=None,
            mission_candidates=None,
            source_artifacts=[
                {
                    "artifact_role": "live_auth",
                    "path": "missing.json",
                    "present": False,
                    "status": "input_unavailable",
                    "artifact_hash": None,
                    "schema_version": None,
                    "reason": "missing_file",
                }
            ],
            generated_at_utc="2026-05-19T00:00:00Z",
        )
