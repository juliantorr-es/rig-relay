from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from rig_relay.integrations.github_provider._surface_packets import (
    build_github_surface_packets,
)

pytestmark = [pytest.mark.contract, pytest.mark.integration]

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = (
    REPO_ROOT / "docs" / "schemas" / "rig.github.surface_packets.v1.schema.json"
)


def test_surface_packets_generates_for_all_audited_surfaces():
    result = build_github_surface_packets()

    assert result["schema_version"] == "rig.github.surface_packets.v1"
    assert result["content_light"] is True
    assert result["remote_mutation"] is False
    assert result["local_mutation"] is False
    assert len(result["packets"]) == 10
    assert result["summary"]["total_packets"] == 10


def test_surface_packets_has_correct_packet_types():
    result = build_github_surface_packets()

    packet_types = {p["packet_type"] for p in result["packets"]}
    assert "project_readme_packet" in packet_types
    assert "profile_readme_packet" in packet_types
    assert "github_pages_packet" in packet_types
    assert "badge_status_packet" in packet_types
    assert "claim_cleanup_packet" in packet_types
    assert "release_notes_packet" in packet_types
    assert "security_posture_packet" in packet_types
    assert "contribution_surface_packet" in packet_types
    assert "no_action_packet" in packet_types


def test_surface_packets_no_packets_apply_changes():
    result = build_github_surface_packets()

    for packet in result["packets"]:
        assert packet["apply_ready"] is False
        assert packet["local_mutation"] is False
        assert packet["remote_mutation"] is False
        assert packet["generated_public_text_allowed"] is False


def test_surface_packets_is_schema_valid():
    result = build_github_surface_packets()

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.validate(instance=result, schema=schema)


def test_surface_packets_is_content_light():
    result = build_github_surface_packets()

    serialized = json.dumps(result, sort_keys=True)
    for forbidden in (
        "ghp_",
        "gho_",
        "ghu_",
        "ghs_",
        "github_pat_",
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
    ):
        assert forbidden not in serialized


def test_surface_packets_are_deterministically_ordered():
    result = build_github_surface_packets()

    packet_ids = [p["packet_id"] for p in result["packets"]]
    assert packet_ids == sorted(packet_ids)


def test_profile_readme_packet_requires_human_review():
    result = build_github_surface_packets()

    profile_packet = next(
        p for p in result["packets"] if p["packet_type"] == "profile_readme_packet"
    )
    assert profile_packet["human_review_required"] is True
    assert profile_packet["preview_ready"] is False


def test_claim_cleanup_packet_has_source_findings():
    result = build_github_surface_packets()

    claim_packet = next(
        p for p in result["packets"] if p["packet_type"] == "claim_cleanup_packet"
    )
    assert len(claim_packet["source_findings"]) > 0
    assert "public_claims" in claim_packet["target_surface_role"]


def test_no_action_packets_have_preview_ready():
    result = build_github_surface_packets()

    no_action_packets = [
        p for p in result["packets"] if p["packet_type"] == "no_action_packet"
    ]
    assert len(no_action_packets) >= 1
    for packet in no_action_packets:
        assert packet["preview_ready"] is True
        assert packet["human_review_required"] is False


def test_summary_has_required_fields():
    result = build_github_surface_packets()

    summary = result["summary"]
    assert isinstance(summary["total_packets"], int)
    assert isinstance(summary["packet_type_counts"], dict)
    assert isinstance(summary["next_recommended_action"], str)
    assert summary["total_packets"] == len(result["packets"])
    total_by_type = sum(summary["packet_type_counts"].values())
    assert total_by_type == summary["total_packets"]
