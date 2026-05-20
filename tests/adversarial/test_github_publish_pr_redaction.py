from __future__ import annotations

import json

import pytest

from rig_relay.integrations.github_provider._redaction import (
    assert_content_light_mapping,
    safe_summary,
)

pytestmark = [pytest.mark.adversarial]


def test_publish_pr_safe_summary_strips_forbidden_fields():
    payload = {
        "schema_version": "rig.github.publish_pr.v1",
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


def test_publish_pr_content_light_guard_rejects_forbidden_fields():
    with pytest.raises(ValueError, match="token_prefix"):
        assert_content_light_mapping({"token_prefix": "crumb"})

    with pytest.raises(ValueError, match="raw_content_field_detected"):
        assert_content_light_mapping({"patch": "--- a/file.py"})

    with pytest.raises(ValueError, match="raw_content_field_detected"):
        assert_content_light_mapping({"code_snippet": "print('x')"})

    with pytest.raises(ValueError, match="raw_content_field_detected"):
        assert_content_light_mapping({"diff": "@@ -1 +1 @@"})


def test_publish_pr_proposal_item_rejects_raw_source():
    item = {
        "schema_version": "rig.github.publish_pr.v1",
        "mode": "dry_run",
        "proposal": {
            "proposed_branch": "test-branch",
            "proposed_pr_title": "test title",
            "proposed_pr_summary": "test summary",
            "proposed_files": [],
            "proposed_base_branch": "main",
            "proposed_labels": [],
            "evidence_refs": [],
        },
        "code_snippet": "should not be here",
        "patch": "malicious",
        "diff": "rogue",
        "contents": "raw contents",
    }

    summary = safe_summary(item)
    serialized = json.dumps(summary, sort_keys=True)
    assert "code_snippet" not in serialized
    assert "patch" not in serialized
    assert "diff" not in serialized
    assert "contents" not in serialized


def test_publish_pr_forbidden_fields_never_in_result():
    for forbidden_field in (
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
        with pytest.raises(ValueError, match="raw_content_field_detected"):
            assert_content_light_mapping({forbidden_field: "test"})


def test_publish_pr_sensitive_fields_hashed():
    data = {
        "schema_version": "rig.github.publish_pr.v1",
        "access_token": "sensitive-token-value",
        "private_key": "-----BEGIN PRIVATE KEY-----sensitive-----END PRIVATE KEY-----",
        "safe_field": "public value",
    }

    summary = safe_summary(data)
    assert summary.get("access_token", "").startswith("sha256:")
    assert summary.get("private_key", "").startswith("sha256:")
    assert summary.get("safe_field") == "public value"
    assert "sensitive-token-value" not in json.dumps(summary)
    assert "-----BEGIN PRIVATE KEY-----" not in json.dumps(summary)
