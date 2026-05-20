from __future__ import annotations

import json

import pytest

from rig_relay.integrations.github_provider._redaction import (
    assert_content_light_mapping,
    safe_summary,
)

pytestmark = [pytest.mark.adversarial]


def test_audit_payload_strips_forbidden_fields():
    payload = {
        "schema_version": "rig.event_propagation_resource_allocation_audit.v1",
        "token_prefix": "ghs_crumb",
        "code_snippet": "print('vuln')",
        "patch": "--- a/file.py",
        "diff": "@@ -1 +1 @@",
        "contents": "file contents",
        "authorization": "Bearer xyz",
        "nested": {"raw_response": {}, "secret": "hidden"},
    }

    summary = safe_summary(payload)
    serialized = json.dumps(summary, sort_keys=True)

    for forbidden in (
        "token_prefix",
        "authorization",
        "raw_response",
        "code_snippet",
        "patch",
        "diff",
        "contents",
        "secret",
    ):
        assert forbidden not in serialized


def test_audit_content_light_guard_rejects_forbidden():
    with pytest.raises(ValueError, match="raw_content_field_detected"):
        assert_content_light_mapping({"raw_response": {}})

    with pytest.raises(ValueError, match="raw_content_field_detected"):
        assert_content_light_mapping({"code_snippet": "x"})


def test_audit_control_loop_payload_is_content_light():
    loop = {
        "name": "test loop",
        "input_events": ["test.event"],
        "derived_signal": "test signal",
        "decision": "test decision",
        "affected_subsystem": "test",
        "resource_conserved": "CPU",
        "failure_mode_avoided": "none",
        "safety_gate": "test gate",
        "telemetry_implication": "emit event",
        "reaction_timing": "immediate",
        "ux_visibility": "test visibility",
        "code_snippet": "should be stripped",
    }

    summary = safe_summary(loop)
    assert "code_snippet" not in json.dumps(summary, sort_keys=True)
