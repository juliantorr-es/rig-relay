from __future__ import annotations

import json

import pytest

from rig_relay.integrations.github_provider._redaction import (
    assert_content_light_mapping,
    safe_summary,
)

pytestmark = [pytest.mark.adversarial]


def test_surface_audit_safe_summary_strips_forbidden_fields():
    payload = {
        "schema_version": "rig.github.surface_audit.v1",
        "owner": "test-owner",
        "token_prefix": "ghs_crumb",
        "raw_body": "response body",
        "code_snippet": "print('x')",
        "patch": "--- a/README.md",
        "diff": "@@ -1 +1 @@",
        "contents": "raw contents",
        "secret": "hidden",
        "nested": {
            "authorization": "Bearer ghs_crumb",
            "raw_response": {"data": "sensitive"},
        },
    }

    summary = safe_summary(payload)
    serialized = json.dumps(summary, sort_keys=True)

    for forbidden in (
        "token_prefix",
        "authorization",
        "raw_response",
        "raw_body",
        "code_snippet",
        "patch",
        "diff",
        "contents",
        "secret",
    ):
        assert forbidden not in serialized


def test_surface_audit_content_light_guard_rejects_forbidden_fields():
    with pytest.raises(ValueError, match="raw_content_field_detected"):
        assert_content_light_mapping({"raw_response": {}})

    with pytest.raises(ValueError, match="raw_content_field_detected"):
        assert_content_light_mapping({"code_snippet": "print('hello')"})


def test_surface_audit_result_has_no_raw_urls_or_paths():
    audit = {
        "schema_version": "rig.github.surface_audit.v1",
        "generated_at": "2026-01-01T00:00:00Z",
        "owner": "test-owner",
        "repo": "test-repo",
        "content_light": True,
        "remote_mutation": False,
        "audited_surfaces": [],
        "missing_surfaces": [],
        "stale_surfaces": [],
        "proposal_packets": [],
        "required_permissions_for_future_publish": [],
        "next_recommended_action": "none",
        "summary": {},
    }

    summary = safe_summary(audit)
    serialized = json.dumps(summary, sort_keys=True)
    assert "github.com" not in serialized or "html_url" not in serialized
