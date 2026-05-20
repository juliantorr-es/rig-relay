"""GitHub security work item projection integration tests."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from rig_relay.integrations.github_provider._security_intake import (
    _normalize_code_scanning_alert,
    _normalize_dependabot_alert,
)
from rig_relay.integrations.github_provider._security_work_items import (
    project_github_security_work_items,
    project_github_security_work_items_from_path,
)

pytestmark = [pytest.mark.contract, pytest.mark.integration]

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_DIR = (
    Path(__file__).resolve().parent.parent / "fixtures" / "github_security_intake"
)
INTAKE_PATH = (
    REPO_ROOT / "docs" / "json" / "governance" / "github_security_intake_result.v1.json"
)
WORK_ITEMS_SCHEMA_PATH = (
    REPO_ROOT / "docs" / "schemas" / "rig.github.security_work_items.v1.schema.json"
)


def _load_fixture(name: str) -> list[dict[str, object]]:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def _build_intake_report() -> dict[str, object]:
    code_scanning_alerts = _load_fixture("code_scanning_alerts.page1.json")
    dependabot_alerts = _load_fixture("dependabot_alerts.page1.json")
    return {
        "schema_version": "rig.github.security_intake.v1",
        "generated_at": "2026-05-19T00:00:00Z",
        "auth_mode": "app_installation",
        "owner_hash": "owner-hash",
        "repo_hash": "repo-hash",
        "installation_id_hash": "installation-hash",
        "trace_id": "trace-id",
        "receipt_id": "receipt-id",
        "dry_run": False,
        "content_light": True,
        "remote_mutation": False,
        "source_surfaces": [
            {
                "surface": "code_scanning",
                "status": "collected",
                "required_permission": "Code scanning alerts read",
                "remote_mutation": False,
                "details": "2 alerts",
            },
            {
                "surface": "dependabot",
                "status": "collected",
                "required_permission": "Dependabot alerts read",
                "remote_mutation": False,
                "details": "2 alerts",
            },
            {
                "surface": "secret_scanning",
                "status": "refused",
                "required_permission": "Secret scanning alerts read",
                "remote_mutation": False,
                "reason": "missing_permission_or_not_enabled",
            },
        ],
        "counts": {
            "code_scanning_open": 1,
            "code_scanning_total": 2,
            "dependabot_open": 1,
            "dependabot_total": 2,
            "refused_surfaces": 1,
        },
        "alerts": {
            "code_scanning": [
                _normalize_code_scanning_alert(code_scanning_alerts[0]),
                _normalize_code_scanning_alert(code_scanning_alerts[1]),
            ],
            "dependabot": [
                _normalize_dependabot_alert(dependabot_alerts[0]),
                _normalize_dependabot_alert(dependabot_alerts[1]),
            ],
        },
        "patch_candidate_groups": [],
        "refusals": [
            {
                "surface": "secret_scanning",
                "status": "refused",
                "reason": "missing_permission_or_not_enabled",
                "required_permission": "Secret scanning alerts read",
                "remote_mutation": False,
            }
        ],
        "installation_access": {
            "schema_version": "rig.github.live_auth_result.v1",
            "auth_mode": "app_installation",
            "installation_id_hash": "installation-hash",
            "installation_access": "success",
            "accessible_repo_count": 4,
            "accessible_repo_name_hashes": ["a", "b", "c", "d"],
            "permission_keys": ["code_scanning_alerts", "dependabot_alerts"],
            "repository_selection": "all",
        },
    }


def test_projection_from_existing_alert_fixtures_is_deterministic(tmp_path):
    intake = _build_intake_report()
    input_path = tmp_path / "intake.json"
    input_path.write_text(json.dumps(intake, indent=2) + "\n", encoding="utf-8")

    first = project_github_security_work_items_from_path(
        input_path,
        source_artifact_path=str(INTAKE_PATH),
        generated_at_utc="2026-05-19T00:00:00Z",
    )
    second = project_github_security_work_items(
        intake,
        source_artifact_path=str(INTAKE_PATH),
        generated_at_utc="2026-05-19T00:00:00Z",
    )

    assert first == second
    assert first["remote_mutation"] is False
    assert first["content_light"] is True
    assert first["source_alert_count"] == 4
    assert first["work_item_count"] == 5
    assert first["refused_surface_count"] == 1
    assert first["candidate_group_count"] == 5

    group_kinds = [group["group_kind"] for group in first["candidate_groups"]]
    assert group_kinds == [
        "code_scanning",
        "code_scanning",
        "dependabot",
        "dependabot",
        "refusal",
    ]

    work_item_ids = [
        candidate["candidate_id"]
        for group in first["candidate_groups"]
        for candidate in group["candidates"]
    ]
    assert len(work_item_ids) == len(set(work_item_ids))
    assert all(len(candidate_id) == 64 for candidate_id in work_item_ids)

    schema = json.loads(WORK_ITEMS_SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.validate(instance=first, schema=schema)


def test_real_intake_projects_code_scanning_alerts_into_work_items():
    report = project_github_security_work_items_from_path(
        INTAKE_PATH,
        source_artifact_path=str(INTAKE_PATH),
        generated_at_utc="2026-05-19T00:00:00Z",
    )

    assert report["source_alert_count"] == 42
    assert report["work_item_count"] == 44
    assert report["candidate_group_count"] == 10
    assert report["refused_surface_count"] == 2
    assert report["summary"]["source_alert_count"] == 42
    assert report["summary"]["by_surface"]["code_scanning"] == 42
    assert any(
        group["group_kind"] == "code_scanning"
        for group in report["candidate_groups"]
    )


def test_projection_refusal_becomes_permission_required_candidate():
    intake = {
        "schema_version": "rig.github.security_intake.v1",
        "generated_at": "2026-05-19T00:00:00Z",
        "auth_mode": "app_installation",
        "owner_hash": "owner-hash",
        "repo_hash": "repo-hash",
        "installation_id_hash": "installation-hash",
        "trace_id": "trace-id",
        "receipt_id": "receipt-id",
        "dry_run": False,
        "content_light": True,
        "remote_mutation": False,
        "source_surfaces": [
            {
                "surface": "secret_scanning",
                "status": "refused",
                "required_permission": "Secret scanning alerts read",
                "remote_mutation": False,
                "reason": "missing_permission_or_not_enabled",
            }
        ],
        "counts": {
            "code_scanning_open": 0,
            "code_scanning_total": 0,
            "dependabot_open": 0,
            "dependabot_total": 0,
            "refused_surfaces": 1,
        },
        "alerts": {"code_scanning": [], "dependabot": []},
        "patch_candidate_groups": [],
        "refusals": [
            {
                "surface": "secret_scanning",
                "status": "refused",
                "reason": "missing_permission_or_not_enabled",
                "required_permission": "Secret scanning alerts read",
                "remote_mutation": False,
            }
        ],
    }

    report = project_github_security_work_items(
        intake,
        source_artifact_path=str(INTAKE_PATH),
        generated_at_utc="2026-05-19T00:00:00Z",
    )

    refusal_groups = [
        group
        for group in report["candidate_groups"]
        if group["group_kind"] == "refusal"
    ]
    assert refusal_groups
    candidate = refusal_groups[0]["candidates"][0]
    assert candidate["source_surface"] == "refusal"
    assert candidate["recommended_lane"] == "permission_required"
    assert candidate["recommended_action"] == "request_permission"
    assert candidate["mutation_allowed"] is False
    assert candidate["remote_mutation_required"] is False
