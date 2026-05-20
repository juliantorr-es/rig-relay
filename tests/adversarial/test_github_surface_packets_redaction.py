from __future__ import annotations

import json

import pytest

from rig_relay.integrations.github_provider._redaction import (
    assert_content_light_mapping,
    safe_summary,
)

pytestmark = [pytest.mark.adversarial]


def test_surface_packets_safe_summary_strips_forbidden_fields():
    payload = {
        "schema_version": "rig.github.surface_packets.v1",
        "token_prefix": "ghs_crumb",
        "code_snippet": "print('hello')",
        "patch": "--- a/file.py\n+++ b/file.py",
        "diff": "@@ -1 +1 @@",
        "contents": "file contents",
        "secret": "my-secret",
        "packets": [
            {
                "packet_id": "a" * 64,
                "packet_type": "no_action_packet",
                "authorization": "Bearer crumb",
                "raw_body": "response",
                "proposed_change_summary": "raw change",
            }
        ],
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


def test_surface_packets_content_light_guard_rejects_forbidden_fields():
    with pytest.raises(ValueError, match="token_prefix"):
        assert_content_light_mapping({"token_prefix": "crumb"})

    with pytest.raises(ValueError, match="raw_content_field_detected"):
        assert_content_light_mapping({"patch": "--- a/file.py"})

    with pytest.raises(ValueError, match="raw_content_field_detected"):
        assert_content_light_mapping({"code_snippet": "def foo(): pass"})


def test_surface_packets_packet_item_rejects_raw_source():
    item = {
        "packet_id": "a" * 64,
        "packet_type": "project_readme_packet",
        "source_findings": [],
        "source_claims": [],
        "target_surface_role": "project_readme",
        "proposed_change_summary": "Review project README.",
        "generated_public_text_allowed": False,
        "evidence_refs": [],
        "validation_commands": [],
        "apply_ready": False,
        "preview_ready": True,
        "human_review_required": False,
        "local_mutation": False,
        "remote_mutation": False,
        "remaining_seams": [],
        "code_snippet": "should not be here",
    }

    serialized = json.dumps(item, sort_keys=True)
    assert "code_snippet" in serialized

    summary = safe_summary(item)
    assert "code_snippet" not in json.dumps(summary, sort_keys=True)
