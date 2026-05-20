from __future__ import annotations

import json

import pytest

from rig_relay.integrations.github_provider._redaction import (
    assert_content_light_mapping,
    safe_summary,
)
from rig_relay.integrations.github_provider._surface_preview import (
    _build_preview_entry,
    _validate_packets,
)

pytestmark = [pytest.mark.adversarial]


def test_surface_preview_safe_summary_strips_forbidden_fields():
    payload = {
        "schema_version": "rig.github.surface_preview.v1",
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


def test_surface_preview_content_light_guard_rejects_forbidden_fields():
    with pytest.raises(ValueError, match="raw_content_field_detected"):
        assert_content_light_mapping({"raw_response": {}})

    with pytest.raises(ValueError, match="raw_content_field_detected"):
        assert_content_light_mapping({"code_snippet": "print('hello')"})

    with pytest.raises(ValueError, match="raw_content_field_detected"):
        assert_content_light_mapping({"patch": "--- a/README.md"})


def test_surface_preview_entry_is_content_light():
    packet = {
        "packet_id": "abc123packet",
        "target_surface_role": "project_readme",
        "packet_type": "project_readme_packet",
        "proposed_change_summary": "Review project README.",
        "apply_ready": False,
        "preview_ready": True,
        "human_review_required": False,
        "remote_mutation": False,
        "evidence_refs": ["README.md"],
    }

    entry = _build_preview_entry(packet)

    assert_content_light_mapping(entry)
    serialized = json.dumps(entry, sort_keys=True)
    for forbidden in (
        "token_prefix",
        "raw_body",
        "code_snippet",
        "patch",
        "diff",
        "contents",
        "secret",
        "authorization",
        "raw_response",
    ):
        assert forbidden not in serialized


def test_surface_preview_no_github_tokens_in_entries():
    packet = {
        "packet_id": "abc456packet",
        "target_surface_role": "badge_status_block",
        "packet_type": "badge_status_packet",
        "proposed_change_summary": "Validate badge freshness.",
        "apply_ready": False,
        "preview_ready": True,
        "human_review_required": False,
        "remote_mutation": False,
        "evidence_refs": ["README.md"],
    }

    entry = _build_preview_entry(packet)
    serialized = json.dumps(entry, sort_keys=True)

    for token_prefix in ("ghp_", "gho_", "ghu_", "ghs_", "ghr_", "github_pat_"):
        assert token_prefix not in serialized


def test_surface_preview_validate_packets_accepts_mapped_role():
    packets = [
        {
            "packet_id": "packet:a:v1",
            "target_surface_role": "project_readme",
            "packet_type": "project_readme_packet",
        }
    ]
    errors = _validate_packets(packets)
    assert not errors


def test_surface_preview_validate_packets_skips_unmapped_role():
    packets = [
        {
            "packet_id": "packet:a:v1",
            "target_surface_role": "license",
            "packet_type": "no_action_packet",
        },
        {
            "packet_id": "packet:b:v1",
            "target_surface_role": "project_readme",
            "packet_type": "project_readme_packet",
        },
    ]
    errors = _validate_packets(packets)
    assert not errors


def test_surface_preview_validate_packets_rejects_duplicate_target():
    packets = [
        {
            "packet_id": "packet:a:v1",
            "target_surface_role": "project_readme",
            "packet_type": "project_readme_packet",
        },
        {
            "packet_id": "packet:b:v1",
            "target_surface_role": "project_readme",
            "packet_type": "project_readme_packet",
        },
    ]
    errors = _validate_packets(packets)
    assert any("duplicate preview target" in e for e in errors)


def test_surface_preview_validate_packets_rejects_dup_id():
    packets = [
        {
            "packet_id": "dup:id:v1",
            "target_surface_role": "project_readme",
            "packet_type": "project_readme_packet",
        },
        {
            "packet_id": "dup:id:v1",
            "target_surface_role": "changelog",
            "packet_type": "release_notes_packet",
        },
    ]
    errors = _validate_packets(packets)
    assert any("duplicate packet_id" in e for e in errors)


def test_surface_preview_entry_hashes_are_deterministic():
    packet = {
        "packet_id": "hash:test:v1",
        "target_surface_role": "public_claims",
        "packet_type": "claim_cleanup_packet",
        "proposed_change_summary": "Reconcile claims.",
        "apply_ready": False,
        "preview_ready": True,
        "human_review_required": False,
        "remote_mutation": False,
        "evidence_refs": ["README.md"],
    }

    entry1 = _build_preview_entry(packet)
    entry2 = _build_preview_entry(packet)

    assert entry1["preview_id"] == entry2["preview_id"]
    assert entry1["preview_hash"] == entry2["preview_hash"]


def test_surface_preview_entry_maps_target_correctly():
    packet = {
        "packet_id": "map:test:v1",
        "target_surface_role": "public_claims",
        "packet_type": "claim_cleanup_packet",
        "proposed_change_summary": "Reconcile claims.",
        "apply_ready": False,
        "preview_ready": True,
        "human_review_required": False,
        "remote_mutation": False,
        "evidence_refs": [],
    }

    entry = _build_preview_entry(packet)
    assert entry["target_surface_role"] == "claim_cleanup_preview"
