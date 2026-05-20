"""Integration tests for Google Workspace surface packets."""

from __future__ import annotations

import json

import pytest

from rig_relay.integrations.google_workspace._surface_packets import (
    _PACKET_TEMPLATES,
    _resolve_packet_status,
    project_google_workspace_surface_packets,
)

pytestmark = [pytest.mark.contract]


def test_packet_templates_well_formed():
    assert len(_PACKET_TEMPLATES) > 0
    for packet in _PACKET_TEMPLATES:
        assert "packet_id" in packet
        assert "packet_type" in packet
        assert "source_surface" in packet
        assert "status" in packet
        assert "recommended_local_action" in packet
        assert "blocked_by" in packet
        assert "public_release_relevance" in packet


def test_packets_deterministic_ids():
    packet_ids = [p["packet_id"] for p in _PACKET_TEMPLATES]
    assert len(packet_ids) == len(set(packet_ids))


def test_project_packets_from_nothing():
    report = project_google_workspace_surface_packets(
        operating_picture=None,
        read_intake=None,
        generated_at_utc="2026-05-20T00:00:00Z",
    )
    assert report["schema_version"] == "rig.google_workspace.surface_packets.v1"
    assert report["content_light"] is True
    assert report["remote_mutation"] is False
    assert report["packet_count"] == len(_PACKET_TEMPLATES)


def test_all_packets_have_remote_mutation_false():
    report = project_google_workspace_surface_packets(
        operating_picture=None,
        read_intake=None,
        generated_at_utc="2026-05-20T00:00:00Z",
    )
    for packet in report["packets"]:
        assert packet["remote_mutation"] is False


def test_all_packets_have_content_light_true():
    report = project_google_workspace_surface_packets(
        operating_picture=None,
        read_intake=None,
        generated_at_utc="2026-05-20T00:00:00Z",
    )
    for packet in report["packets"]:
        assert packet["content_light"] is True


def test_packet_types_match_spec():
    valid_types = {
        "oauth_setup_packet",
        "scope_request_packet",
        "verification_required_packet",
        "gmail_metadata_packet",
        "calendar_metadata_packet",
        "drive_metadata_packet",
        "tasks_metadata_packet",
        "contacts_metadata_packet",
        "domain_wide_delegation_deferred_packet",
        "public_scope_profile_split_packet",
    }
    for packet in _PACKET_TEMPLATES:
        assert packet["packet_type"] in valid_types


def test_no_raw_tokens_in_packets():
    report = project_google_workspace_surface_packets(
        operating_picture=None,
        read_intake=None,
        generated_at_utc="2026-05-20T00:00:00Z",
    )
    serialized = json.dumps(report, sort_keys=True)
    for forbidden in ("ya29.", "1//", "BEGIN PRIVATE KEY"):
        assert forbidden not in serialized


def test_resolve_packet_status_no_op_picture():
    packet = dict(_PACKET_TEMPLATES[0])
    resolved = _resolve_packet_status(packet, None, None)
    assert "operating_picture_missing" in resolved["blocked_by"]


def test_summary_counts():
    report = project_google_workspace_surface_packets(
        operating_picture=None,
        read_intake=None,
        generated_at_utc="2026-05-20T00:00:00Z",
    )
    summary = report["summary"]
    assert summary["total_packets"] == len(_PACKET_TEMPLATES)
    assert (
        summary["ready_packets"]
        + summary["blocked_packets"]
        + summary["deferred_packets"]
        == summary["total_packets"]
    )


def test_dwd_packet_is_deferred():
    report = project_google_workspace_surface_packets(
        operating_picture=None,
        read_intake=None,
        generated_at_utc="2026-05-20T00:00:00Z",
    )
    dwd = [
        p
        for p in report["packets"]
        if p["packet_type"] == "domain_wide_delegation_deferred_packet"
    ]
    assert len(dwd) == 1
    assert dwd[0]["status"] == "deferred"
    assert dwd[0]["remote_mutation"] is False
