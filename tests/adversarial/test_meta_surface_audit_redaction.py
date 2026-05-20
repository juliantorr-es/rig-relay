"""Meta surface audit redaction adversarial tests."""

from __future__ import annotations

import json

import pytest

from rig_relay.integrations.meta_provider._surface_audit import build_meta_surface_audit

pytestmark = [pytest.mark.adversarial]


def test_surface_audit_never_leaks_raw_tokens():
    report = build_meta_surface_audit(
        generated_at="2026-05-20T00:00:00Z", branch="main", head="0" * 40
    )

    serialized = json.dumps(report, sort_keys=True)
    assert '"access_token"' not in serialized
    assert '"app_secret"' not in serialized
    assert '"client_secret"' not in serialized
    assert '"verify_token"' not in serialized
    assert '"bearer"' not in serialized
    assert '"phone_number"' not in serialized
    assert '"raw_response"' not in serialized
    assert '"raw_body"' not in serialized
    assert '"webhook_payload"' not in serialized
    assert '"message_text"' not in serialized
    assert '"comment_text"' not in serialized
    assert '"dm_text"' not in serialized
    assert '"media_url"' not in serialized
    assert '"image_url"' not in serialized
    assert '"video_url"' not in serialized
    assert '"post_caption"' not in serialized
    assert "EAA" not in serialized


def test_surface_audit_no_user_content_keys_in_packets():
    report = build_meta_surface_audit(
        generated_at="2026-05-20T00:00:00Z", branch="main", head="0" * 40
    )

    for packet in report["packets"]:
        packet_serialized = json.dumps(packet, sort_keys=True)
        assert '"raw posts"' not in packet_serialized.lower()
        assert '"raw comments"' not in packet_serialized.lower()
        assert '"raw DMs"' not in packet_serialized.lower()
        assert '"webhook_payload"' not in packet_serialized.lower()
        assert '"phone_number"' not in packet_serialized.lower()


def test_surface_audit_packets_blocked_by_documented_reasons():
    report = build_meta_surface_audit(
        generated_at="2026-05-20T00:00:00Z", branch="main", head="0" * 40
    )

    for packet in report["packets"]:
        assert len(packet["blocked_by"]) > 0
        if packet["current_status"] == "refused":
            assert (
                "permanently_refused" in packet["blocked_by"][0]
                or "refused" in packet["blocked_by"][0]
            )
