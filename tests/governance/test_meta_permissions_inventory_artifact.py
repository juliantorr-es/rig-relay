"""Governance artifact test for Meta permissions inventory."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

pytestmark = [pytest.mark.contract, pytest.mark.real_artifact]

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = (
    REPO_ROOT / "docs" / "schemas" / "rig.meta.permissions_inventory.v1.schema.json"
)
REPORT_PATH = (
    REPO_ROOT / "docs" / "json" / "governance" / "meta_permissions_inventory_v1.v1.json"
)

_FORBIDDEN_KEYS = frozenset({
    "access_token",
    "app_secret",
    "client_secret",
    "verify_token",
    "authorization",
    "bearer",
    "phone_number",
    "email",
    "raw_response",
    "raw_body",
    "webhook_payload",
    "message_text",
    "comment_text",
    "dm_text",
    "media_url",
    "image_url",
    "video_url",
    "post_caption",
})


def _assert_no_forbidden_keys(obj):
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key in _FORBIDDEN_KEYS:
                raise AssertionError(f"forbidden_key_found: {key}")
            _assert_no_forbidden_keys(value)
    elif isinstance(obj, list):
        for item in obj:
            _assert_no_forbidden_keys(item)


def test_meta_permissions_inventory_artifact_validates_and_is_content_light():
    assert SCHEMA_PATH.exists(), f"Schema file not found at {SCHEMA_PATH}"
    assert REPORT_PATH.exists(), f"Report file not found at {REPORT_PATH}"

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    jsonschema.validate(instance=report, schema=schema)

    _assert_no_forbidden_keys(report)

    serialized = json.dumps(report, sort_keys=True)
    assert "EAA" not in serialized
    assert "ghp_" not in serialized

    assert report["schema_version"] == "rig.meta.permissions_inventory.v1"
    assert report["content_light"] is True
    assert report["remote_mutation"] is False
    assert report["live_network"] is False
    assert report["capability_count"] > 0
    assert report["refused_count"] > 0


def test_meta_permissions_inventory_generation_succeeds():
    assert REPORT_PATH.exists()
    contents = REPORT_PATH.read_text(encoding="utf-8")
    assert contents.startswith("{")
    data = json.loads(contents)
    assert len(data["surfaces"]) == 5
    assert data["refused_count"] > 0
    assert data["deferred_count"] > 0
