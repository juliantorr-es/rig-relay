"""GitHub security intake redaction adversarial tests."""

from __future__ import annotations

import json

import pytest

from rig_relay.integrations.github_provider._redaction import (
    assert_content_light_mapping,
    safe_summary,
)

pytestmark = [pytest.mark.adversarial]


def test_intake_safe_summary_strips_token_and_body_crumbs():
    payload = {
        "schema_version": "rig.github.security_intake.v1",
        "token_prefix": "ghs_tokencrumb",
        "authorization": "Bearer ghs_tokencrumb",
        "raw_response": {"access_token": "ghs_tokencrumb"},
        "raw_body": "response body",
        "code_snippet": "print('secret')",
        "patch": "diff --git a/file b/file",
        "diff": "@@ -1 +1 @@",
        "contents": "raw file contents",
        "secret": "hidden",
        "nested": {
            "token_prefix": "ghs_nestedcrumb",
            "authorization": "Bearer ghs_nestedcrumb",
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
        "ghs_tokencrumb",
        "ghs_nestedcrumb",
    ):
        assert forbidden not in serialized


def test_intake_content_light_guard_rejects_forbidden_top_level_fields():
    with pytest.raises(ValueError, match="token_prefix"):
        assert_content_light_mapping({"token_prefix": "ghs_tokencrumb"})

    with pytest.raises(ValueError, match="raw_content_field_detected"):
        assert_content_light_mapping({"raw_response": {}})
