"""Governance artifact test for GitHub security mission packets."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

pytestmark = [pytest.mark.contract, pytest.mark.real_artifact]

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = (
    REPO_ROOT
    / "docs"
    / "schemas"
    / "rig.github.security_mission_packets.v1.schema.json"
)
REPORT_PATH = (
    REPO_ROOT
    / "docs"
    / "json"
    / "governance"
    / "github_security_mission_packets_v1.v1.json"
)


def test_github_security_mission_packets_artifact_validates_and_stays_content_light():
    assert SCHEMA_PATH.exists(), f"Schema file not found at {SCHEMA_PATH}"
    assert REPORT_PATH.exists(), f"Report file not found at {REPORT_PATH}"

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))

    jsonschema.validate(instance=report, schema=schema)

    serialized = json.dumps(report, sort_keys=True)
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
        "diff --git",
    ):
        assert forbidden not in serialized

    assert report["schema_version"] == "rig.github.security_mission_packets.v1"
    assert report["content_light"] is True
    assert report["remote_mutation"] is False
    assert report["packet_count"] == 27
    assert report["excluded_candidate_count"] == 17
    assert report["excluded_by_route"] == {
        "advisory_only": 15,
        "permission_required": 2,
    }
    assert (
        report["packet_count"]
        == report["route_summary"]["selected_by_route"]["ready_for_investigation"]
    )
    assert report["risk_summary"]["ready_candidate_count"] == 27
    assert report["packets"][0]["content_light"] is True
    assert report["packets"][0]["remote_mutation"] is False
