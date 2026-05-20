from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

pytestmark = [pytest.mark.contract, pytest.mark.real_artifact]

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = (
    REPO_ROOT / "docs" / "schemas" / "rig.github.surface_preview.v1.schema.json"
)
REPORT_PATH = (
    REPO_ROOT / "docs" / "json" / "governance" / "github_surface_preview_v1.v1.json"
)


def test_surface_preview_artifact_validates_and_stays_content_light():
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
        "github_pat_",
        "token_prefix",
        "access_token",
        "authorization",
        "raw_response",
        "raw_body",
    ):
        assert forbidden not in serialized

    assert report["schema_version"] == "rig.github.surface_preview.v1"
    assert report["content_light"] is True
    assert report["remote_mutation"] is False
    assert report["local_mutation"] is False
    assert isinstance(report["preview_entries"], list)
    assert isinstance(report["summary"], dict)


def test_surface_preview_artifact_all_entries_have_no_mutation():
    assert REPORT_PATH.exists()

    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    for entry in report["preview_entries"]:
        assert entry["local_mutation"] is False
        assert entry["remote_mutation"] is False
        assert entry["preview_artifact_path"] is None


def test_surface_preview_artifact_has_seven_entries():
    assert REPORT_PATH.exists()

    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    assert len(report["preview_entries"]) == 7
