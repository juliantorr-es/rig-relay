from __future__ import annotations

import json

import pytest

from rig_relay.integrations.github_provider._redaction import (
    assert_content_light_mapping,
    safe_summary,
)

pytestmark = [pytest.mark.adversarial]


def test_execution_safe_summary_strips_forbidden_fields():
    payload = {
        "schema_version": "rig.github.security_packet_execution.v1",
        "token_prefix": "ghs_crumb",
        "authorization": "Bearer ghs_crumb",
        "raw_response": {"access_token": "ghs_crumb"},
        "raw_body": "raw body",
        "code_snippet": "print('vuln')",
        "patch": "--- a/file.py\n+++ b/file.py",
        "diff": "@@ -1 +1 @@",
        "contents": "file contents",
        "secret": "hidden",
        "nested": {"token_prefix": "ghs_nested", "authorization": "Bearer nested"},
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
        "ghs_crumb",
        "ghs_nested",
    ):
        assert forbidden not in serialized


def test_execution_content_light_guard_rejects_forbidden_fields():
    with pytest.raises(ValueError, match="token_prefix"):
        assert_content_light_mapping({"token_prefix": "crumb"})

    with pytest.raises(ValueError, match="raw_content_field_detected"):
        assert_content_light_mapping({"patch": "--- a/file.py"})

    with pytest.raises(ValueError, match="raw_content_field_detected"):
        assert_content_light_mapping({"code_snippet": "print('x')"})


def test_execution_result_item_rejects_raw_source():
    item = {
        "execution_id": "a" * 64,
        "packet_id": "b" * 64,
        "candidate_id": "c",
        "route": "ready",
        "source_surface": "code_scanning",
        "severity_summary": {"normalized_severity": "medium", "priority": "p2"},
        "local_lane_type": "code_scanning_investigation",
        "result_status": "inspected",
        "remediation_recommendation": "ok",
        "required_validation_commands": [],
        "evidence_refs": [],
        "source_artifact_hashes": {},
        "remote_mutation": False,
        "local_mutation": False,
        "content_light": True,
        "code_snippet": "should not be here",
        "patch": "malicious",
    }

    serialized = json.dumps(item, sort_keys=True)
    assert "code_snippet" in serialized

    summary = safe_summary(item)
    assert "code_snippet" not in json.dumps(summary, sort_keys=True)
    assert "patch" not in json.dumps(summary, sort_keys=True)
