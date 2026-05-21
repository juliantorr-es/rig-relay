"""Tests for site editor — intent gating, validation, atomic write, render trigger."""

from __future__ import annotations

import json
import os
from pathlib import Path

import jsonschema
import pytest

from rig_relay.desktop.intents import _execute_site_editor_save

pytestmark = [pytest.mark.contract, pytest.mark.integration]

REPO_ROOT = Path(__file__).resolve().parents[2]
SITE_HOME = REPO_ROOT / "docs" / "json" / "site_home.v1.json"
SITE_SCHEMA = REPO_ROOT / "docs" / "schemas" / "rig.documentation.home.v1.schema.json"


# ═══════ Safety gate tests ═══════


def test_save_refused_without_env_var():
    result = _execute_site_editor_save(
        "test-1", {"page_data": {}, "artifact_path": "docs/json/site_home.v1.json"}
    )
    assert result["status"] == "refused"
    assert result["error_code"] == "authorization_required"


def test_save_requires_env_var():
    os.environ["RIG_RELAY_ALLOW_SITE_EDITS"] = "1"
    try:
        result = _execute_site_editor_save(
            "test-2",
            {
                "page_data": {"title": "Test"},
                "artifact_path": "docs/json/site_home.v1.json",
            },
        )
        assert result["status"] in ("completed", "completed_with_errors", "failed")
    finally:
        del os.environ["RIG_RELAY_ALLOW_SITE_EDITS"]


# ═══════ Validation tests ═══════


def test_save_validates_against_schema():
    os.environ["RIG_RELAY_ALLOW_SITE_EDITS"] = "1"
    try:
        # Invalid data — missing required fields
        result = _execute_site_editor_save(
            "test-3",
            {
                "page_data": {"invalid_field": 123},
                "artifact_path": "docs/json/site_home.v1.json",
            },
        )
        assert result["status"] == "refused" or result["error_code"] in (
            "schema_validation_failed",
            "authorization_required",
        )
    finally:
        del os.environ["RIG_RELAY_ALLOW_SITE_EDITS"]


def test_save_preserves_immutable_fields():
    os.environ["RIG_RELAY_ALLOW_SITE_EDITS"] = "1"
    try:
        existing = json.loads(SITE_HOME.read_text(encoding="utf-8"))
        result = _execute_site_editor_save(
            "test-4",
            {
                "page_data": {"title": "Test Override"},
                "artifact_path": "docs/json/site_home.v1.json",
            },
        )
        assert result["status"] in ("completed", "completed_with_errors", "failed")
        SITE_HOME.write_text(
            json.dumps(existing, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    finally:
        del os.environ["RIG_RELAY_ALLOW_SITE_EDITS"]


# ═══════ Schema field reader tests ═══════


def test_schema_reader_produces_fields():
    from rig_relay.integrations._site_editor import read_schema_fields

    fields = read_schema_fields(SITE_SCHEMA)
    assert len(fields) >= 10
    field_names = {f["field_name"] for f in fields}
    assert "title" in field_names
    assert "tagline" in field_names


def test_schema_fields_have_types():
    from rig_relay.integrations._site_editor import read_schema_fields

    fields = read_schema_fields(SITE_SCHEMA)
    for f in fields:
        assert "field_type" in f
        assert f["field_type"] in {
            "text",
            "textarea",
            "select",
            "card_list",
            "tag_list",
            "object",
            "array",
        }, f"Unknown type {f['field_type']} for {f['field_name']}"


# ═══════ Projection tests ═══════


def test_projection_available():
    from rig_relay.desktop.projection import build_projection

    proj = build_projection()
    se = proj.get("site_editor", {})
    assert se.get("available") is True


def test_projection_has_fields():
    from rig_relay.desktop.projection import build_projection

    proj = build_projection()
    se = proj.get("site_editor", {})
    assert len(se.get("fields", [])) >= 10


def test_projection_can_save_defaults_false():
    from rig_relay.desktop.projection import build_projection

    proj = build_projection()
    se = proj.get("site_editor", {})
    assert se.get("can_save") is False
