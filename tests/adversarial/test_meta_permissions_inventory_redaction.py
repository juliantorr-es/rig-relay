"""Meta permissions inventory redaction adversarial tests."""

from __future__ import annotations

import json

import pytest

from rig_relay.integrations.meta_provider._permissions_inventory import (
    build_meta_permissions_inventory,
)

pytestmark = [pytest.mark.adversarial]


def test_permissions_inventory_never_leaks_raw_tokens():
    report = build_meta_permissions_inventory(
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
    assert "EAA" not in serialized


def test_permissions_inventory_all_requires_doc_verification():
    report = build_meta_permissions_inventory(
        generated_at="2026-05-20T00:00:00Z", branch="main", head="0" * 40
    )

    for surface in report["surfaces"]:
        for cap in surface["capabilities"]:
            assert cap["requires_doc_verification"] is True


def test_permissions_inventory_no_raw_permission_names_contain_secrets():
    report = build_meta_permissions_inventory(
        generated_at="2026-05-20T00:00:00Z", branch="main", head="0" * 40
    )

    for surface in report["surfaces"]:
        for cap in surface["capabilities"]:
            for perm_name in cap["required_permission_names"]:
                assert "token" not in perm_name.lower()
                assert "secret" not in perm_name.lower()
                assert "key" not in perm_name.lower()
