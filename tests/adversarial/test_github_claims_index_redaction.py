from __future__ import annotations

import json

import pytest

from rig_relay.integrations.github_provider._redaction import (
    assert_content_light_mapping,
    safe_summary,
)

pytestmark = [pytest.mark.adversarial]


_FORBIDDEN_KEYS = frozenset({
    "token_prefix",
    "access_token",
    "authorization",
    "raw_response",
    "raw_body",
    "code_snippet",
    "patch",
    "diff",
    "contents",
    "secret",
})


def _has_forbidden_key(obj: object) -> bool:
    if isinstance(obj, dict):
        for key in obj:
            if key in _FORBIDDEN_KEYS:
                return True
            if _has_forbidden_key(obj[key]):
                return True
    elif isinstance(obj, list):
        for item in obj:
            if _has_forbidden_key(item):
                return True
    return False


def test_claims_index_safe_summary_strips_forbidden_fields():
    payload = {
        "schema_version": "rig.github.evidence_backed_claims_index.v1",
        "token_prefix": "ghs_crumb",
        "code_snippet": "print('hello')",
        "patch": "--- a/file.py\n+++ b/file.py",
        "diff": "@@ -1 +1 @@",
        "contents": "file contents",
        "secret": "my-secret",
        "claims": [
            {
                "claim_id": "a" * 64,
                "claim_category": "functionality_claim",
                "source_surface_ref": "README.md#test",
                "normalized_claim_summary": "Test claim text",
                "evidence_refs": [],
                "support_status": "unknown",
                "confidence": "low",
                "public_wording_risk": "low",
                "suggested_action": "keep",
                "human_review_required": False,
                "local_mutation": False,
                "remote_mutation": False,
                "remaining_seams": [],
                "raw_body": "should be stripped",
                "authorization": "Bearer crumb",
            }
        ],
    }

    summary = safe_summary(payload)

    assert not _has_forbidden_key(summary)

    serialized = json.dumps(summary, sort_keys=True)
    for token_pattern in ("ghp_", "gho_", "ghu_", "ghs_", "github_pat_"):
        assert token_pattern not in serialized


def test_claims_index_content_light_guard_rejects_forbidden_fields():
    with pytest.raises(ValueError, match="token_prefix"):
        assert_content_light_mapping({"token_prefix": "crumb"})

    with pytest.raises(ValueError, match="raw_content_field_detected"):
        assert_content_light_mapping({"patch": "--- a/file.py"})
