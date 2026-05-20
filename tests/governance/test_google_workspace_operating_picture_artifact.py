"""Governance artifact test for Google Workspace operating picture."""

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
    / "rig.google_workspace.operating_picture.v1.schema.json"
)
REPORT_PATH = (
    REPO_ROOT
    / "docs"
    / "json"
    / "governance"
    / "google_workspace_operating_picture_v1.v1.json"
)


def test_google_workspace_operating_picture_schema_exists():
    assert SCHEMA_PATH.exists(), f"Schema file not found at {SCHEMA_PATH}"


def test_google_workspace_operating_picture_artifact_validates_and_is_content_light():
    assert SCHEMA_PATH.exists(), f"Schema file not found at {SCHEMA_PATH}"

    if not REPORT_PATH.exists():
        pytest.skip("Operating picture artifact not yet generated")

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    jsonschema.validate(instance=report, schema=schema)

    serialized = json.dumps(report, sort_keys=True)
    for forbidden in (
        "ya29.",
        "1//",
        "BEGIN PRIVATE KEY",
        '"access_token"',
        '"refresh_token"',
        '"token_prefix"',
        '"authorization"',
        '"client_secret"',
        '"private_key"',
        '"raw_response"',
        '"raw_body"',
        '"email_body"',
        '"subject"',
        '"snippet"',
        '"calendar_description"',
        '"drive_file_contents"',
        '"contact_email"',
    ):
        assert forbidden not in serialized, f"Forbidden '{forbidden}' found"

    assert report["schema_version"] == "rig.google_workspace.operating_picture.v1"
    assert report["content_light"] is True
    assert report["remote_mutation"] is False
    assert report["scope_posture"]["public_release_ready"] is False
    assert report["scope_posture"]["restricted_scopes_refused_or_deferred"] is True
