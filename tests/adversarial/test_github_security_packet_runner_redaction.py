from __future__ import annotations

import json

import pytest

from rig_relay.integrations.github_provider._redaction import (
    assert_content_light_mapping,
    safe_summary,
)

pytestmark = [pytest.mark.adversarial]


def test_packet_runner_safe_summary_strips_forbidden_fields():
    payload = {
        "schema_version": "rig.github.security_packet_runner_plan.v1",
        "token_prefix": "ghs_crumb",
        "code_snippet": "print('hello')",
        "patch": "--- a/file.py\n+++ b/file.py",
        "diff": "@@ -1 +1 @@",
        "contents": "file contents",
        "secret": "my-secret",
        "nested": {"authorization": "Bearer crumb", "raw_body": "response"},
    }

    summary = safe_summary(payload)
    serialized = json.dumps(summary, sort_keys=True)

    for forbidden in (
        "token_prefix",
        "authorization",
        "raw_body",
        "code_snippet",
        "patch",
        "diff",
        "contents",
        "secret",
    ):
        assert forbidden not in serialized


def test_packet_runner_content_light_guard_rejects_forbidden_fields():
    with pytest.raises(ValueError, match="token_prefix"):
        assert_content_light_mapping({"token_prefix": "crumb"})

    with pytest.raises(ValueError, match="raw_content_field_detected"):
        assert_content_light_mapping({"patch": "--- a/file.py"})


def test_packet_runner_plan_item_rejects_raw_source():
    item = {
        "plan_item_id": "a" * 64,
        "packet_id": "b" * 64,
        "candidate_id": "c",
        "route": "ready",
        "source_surface": "code_scanning",
        "severity_summary": {},
        "local_lane_type": "test",
        "expected_local_categories": [],
        "required_validation_commands": [],
        "remote_mutation": False,
        "apply_local": False,
        "status": "planned",
        "code_snippet": "should not be here",
    }

    serialized = json.dumps(item, sort_keys=True)
    assert "code_snippet" in serialized

    summary = safe_summary(item)
    assert "code_snippet" not in json.dumps(summary, sort_keys=True)
