"""Meta operating picture integration tests."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import jsonschema
import pytest

from rig_relay.integrations.meta_provider._operating_picture import (
    build_meta_operating_picture,
    build_meta_operating_picture_from_paths,
)
from scripts.rig_meta_operating_picture import main as operating_picture_main

pytestmark = [pytest.mark.contract, pytest.mark.integration, pytest.mark.substrate]

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = (
    REPO_ROOT / "docs" / "schemas" / "rig.meta.operating_picture.v1.schema.json"
)


def _read(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_operating_picture_no_config_no_network():
    with patch.dict(os.environ, {}, clear=True):
        report = build_meta_operating_picture(
            generated_at="2026-05-20T00:00:00Z", branch="main", head="0" * 40
        )

    assert report["content_light"] is True
    assert report["remote_mutation"] is False
    assert report["live_network"] is False
    assert report["configured_summary"]["app_id_configured"] is False
    assert report["configured_summary"]["access_token_configured"] is False
    assert report["surface_summary"]["publishing"] == "refused"
    assert report["surface_summary"]["messaging"] == "refused"
    assert report["surface_summary"]["comments_replies"] == "refused"
    assert report["safety_posture"]["public_release_ready"] is False
    assert report["safety_posture"]["publishing_allowed"] is False
    assert report["safety_posture"]["messaging_allowed"] is False
    assert report["safety_posture"]["app_review_required"] is True
    assert "build_permissions_inventory" not in report["next_recommended_action"]
    assert "no_action" in report["next_recommended_action"]

    schema = _read(SCHEMA_PATH)
    jsonschema.validate(instance=report, schema=schema)


def test_operating_picture_partial_config_sets_surface_status():
    env_vars = {
        "RIG_META_APP_ID": "1",
        "RIG_META_ACCESS_TOKEN": "1",
        "RIG_META_PAGE_ID": "1",
    }
    with patch.dict(os.environ, env_vars, clear=True):
        report = build_meta_operating_picture(
            generated_at="2026-05-20T00:00:00Z", branch="main", head="0" * 40
        )

    assert report["configured_summary"]["app_id_configured"] is True
    assert report["configured_summary"]["access_token_configured"] is True
    assert report["configured_summary"]["page_id_configured"] is True
    assert report["configured_summary"]["app_secret_configured"] is False
    assert report["surface_summary"]["facebook_pages"] == "configured"
    assert report["surface_summary"]["instagram_graph"] == "refused"
    assert report["surface_summary"]["whatsapp_business_cloud"] == "refused"
    assert report["surface_summary"]["publishing"] == "refused"
    assert report["surface_summary"]["messaging"] == "refused"


def test_operating_picture_instagram_configured():
    env_vars = {
        "RIG_META_APP_ID": "1",
        "RIG_META_ACCESS_TOKEN": "1",
        "RIG_META_INSTAGRAM_BUSINESS_ACCOUNT_ID": "1",
    }
    with patch.dict(os.environ, env_vars, clear=True):
        report = build_meta_operating_picture(
            generated_at="2026-05-20T00:00:00Z", branch="main", head="0" * 40
        )

    assert report["surface_summary"]["instagram_graph"] == "configured"
    assert report["surface_summary"]["facebook_pages"] == "refused"


def test_operating_picture_whatsapp_configured():
    env_vars = {
        "RIG_META_APP_ID": "1",
        "RIG_META_ACCESS_TOKEN": "1",
        "RIG_META_WHATSAPP_BUSINESS_ACCOUNT_ID": "1",
    }
    with patch.dict(os.environ, env_vars, clear=True):
        report = build_meta_operating_picture(
            generated_at="2026-05-20T00:00:00Z", branch="main", head="0" * 40
        )

    assert report["surface_summary"]["whatsapp_business_cloud"] == "configured"
    assert report["surface_summary"]["messaging"] == "refused"


def test_operating_picture_webhook_configured():
    env_vars = {"RIG_META_APP_ID": "1", "RIG_META_VERIFY_TOKEN": "1"}
    with patch.dict(os.environ, env_vars, clear=True):
        report = build_meta_operating_picture(
            generated_at="2026-05-20T00:00:00Z", branch="main", head="0" * 40
        )

    assert report["configured_summary"]["webhook_verify_token_configured"] is True
    assert report["surface_summary"]["webhooks"] == "configured"


def test_operating_picture_config_health_unconfigured():
    with patch.dict(os.environ, {}, clear=True):
        report = build_meta_operating_picture(
            generated_at="2026-05-20T00:00:00Z", branch="main", head="0" * 40
        )

    assert report["summary"]["config_health"] == "unconfigured"
    assert report["summary"]["surface_health"] == "all_unconfigured"
    assert report["summary"]["safety_health"] == "refusal_first"


def test_summary_cli_prints_compact_table(tmp_path, capsys):
    env_vars = {"RIG_META_APP_ID": "1", "RIG_META_ACCESS_TOKEN": "1"}
    with patch.dict(os.environ, env_vars, clear=True):
        output = tmp_path / "operating-picture.json"
        exit_code = operating_picture_main(["--output-json", str(output), "--summary"])

    captured = capsys.readouterr().out
    assert exit_code == 0
    assert output.exists()
    assert "app_id_configured" in captured
    assert "publishing" in captured
    assert "messaging" in captured


def test_build_from_paths_no_network():
    with patch.dict(os.environ, {}, clear=True):
        report = build_meta_operating_picture_from_paths(
            generated_at="2026-05-20T00:00:00Z"
        )

    assert report["content_light"] is True
    assert report["live_network"] is False
    assert report["remote_mutation"] is False
    schema = _read(SCHEMA_PATH)
    jsonschema.validate(instance=report, schema=schema)
