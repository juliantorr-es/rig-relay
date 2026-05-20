"""Meta operating picture redaction adversarial tests."""

from __future__ import annotations

import json
import os
from unittest.mock import patch

import pytest

from rig_relay.integrations.meta_provider._operating_picture import (
    build_meta_operating_picture,
)

pytestmark = [pytest.mark.adversarial]


def test_operating_picture_rejects_forbidden_token_keys():
    report = build_meta_operating_picture(
        generated_at="2026-05-20T00:00:00Z", branch="main", head="0" * 40
    )

    serialized = json.dumps(report, sort_keys=True)
    assert '"access_token"' not in serialized
    assert '"app_secret"' not in serialized
    assert '"client_secret"' not in serialized
    assert '"verify_token"' not in serialized
    assert '"bearer"' not in serialized
    assert '"phone_number"' not in serialized
    assert '"raw_response"' not in serialized
    assert '"raw_body"' not in serialized
    assert '"webhook_payload"' not in serialized
    assert '"message_text"' not in serialized
    assert '"comment_text"' not in serialized
    assert '"dm_text"' not in serialized
    assert '"media_url"' not in serialized
    assert '"image_url"' not in serialized
    assert '"video_url"' not in serialized
    assert '"post_caption"' not in serialized


def test_operating_picture_rejects_forbidden_value_patterns():
    report = build_meta_operating_picture(
        generated_at="2026-05-20T00:00:00Z", branch="main", head="0" * 40
    )

    serialized = json.dumps(report, sort_keys=True)
    assert "EAA" not in serialized


def test_operating_picture_env_values_never_leak_raw():
    env_vars = {
        "RIG_META_APP_ID": "test-app-123",
        "RIG_META_ACCESS_TOKEN": "EAAfakeaccesstoken12345",
        "RIG_META_APP_SECRET": "test-secret-should-not-leak",
    }
    with patch.dict(os.environ, env_vars, clear=True):
        report = build_meta_operating_picture(
            generated_at="2026-05-20T00:00:00Z", branch="main", head="0" * 40
        )

    serialized = json.dumps(report, sort_keys=True)
    assert "test-app-123" not in serialized
    assert "EAAfakeaccesstoken" not in serialized
    assert "test-secret-should-not-leak" not in serialized
    assert report["configured_summary"]["app_id_configured"] is True
    assert report["configured_summary"]["access_token_configured"] is True
    assert report["configured_summary"]["app_secret_configured"] is True
