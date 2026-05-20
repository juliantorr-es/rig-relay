"""Governance artifact test for GitHub operating picture."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

pytestmark = [pytest.mark.contract, pytest.mark.real_artifact]

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = (
    REPO_ROOT / "docs" / "schemas" / "rig.github.operating_picture.v1.schema.json"
)
REPORT_PATH = (
    REPO_ROOT / "docs" / "json" / "governance" / "github_operating_picture_v1.v1.json"
)


def test_github_operating_picture_artifact_validates_and_is_content_light():
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
    ):
        assert forbidden not in serialized

    assert report["schema_version"] == "rig.github.operating_picture.v1"
    assert report["content_light"] is True
    assert report["remote_mutation"] is False
    assert report["auth_summary"]["installation_access_proven"] is True
    assert report["candidate_summary"]["candidate_count"] == 44
    assert report["packet_summary"]["packet_count"] == 27
    assert report["packet_summary"]["packet_index_stale"] is False
    assert report["summary"]["next_recommended_action"] == "run_packet_lane"
