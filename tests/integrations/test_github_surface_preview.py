from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from rig_relay.integrations.github_provider._surface_preview import (
    build_github_surface_preview,
)

pytestmark = [pytest.mark.contract, pytest.mark.integration]

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = (
    REPO_ROOT / "docs" / "schemas" / "rig.github.surface_preview.v1.schema.json"
)
PACKETS_PATH = (
    REPO_ROOT / "docs" / "json" / "governance" / "github_surface_packets_v1.v1.json"
)


def test_surface_preview_is_content_light():
    preview = build_github_surface_preview()

    assert preview["schema_version"] == "rig.github.surface_preview.v1"
    assert preview["content_light"] is True
    assert preview["remote_mutation"] is False
    assert preview["local_mutation"] is False


def test_surface_preview_has_all_preview_targets():
    preview = build_github_surface_preview()

    targets = {e["target_surface_role"] for e in preview["preview_entries"]}
    assert "project_readme_preview" in targets
    assert "profile_readme_preview" in targets
    assert "github_pages_preview" in targets
    assert "badge_status_preview" in targets
    assert "release_notes_preview" in targets
    assert "security_posture_preview" in targets
    assert "claim_cleanup_preview" in targets


def test_surface_preview_entries_have_required_fields():
    preview = build_github_surface_preview()

    for entry in preview["preview_entries"]:
        assert "preview_id" in entry
        assert entry["preview_id"].startswith("sha256:")
        assert len(entry["preview_id"]) > 70
        assert "packet_id" in entry
        assert "target_surface_role" in entry
        assert "preview_hash" in entry
        assert len(entry["preview_hash"]) == 64
        assert entry["render_status"] in {"rendered", "blocked", "not_rendered"}
        assert entry["safety_status"] in {"safe", "blocked"}
        assert isinstance(entry["human_review_required"], bool)
        assert entry["local_mutation"] is False
        assert entry["remote_mutation"] is False


def test_surface_preview_no_preview_files_written_in_v1():
    preview = build_github_surface_preview()

    for entry in preview["preview_entries"]:
        assert entry["preview_artifact_path"] is None


def test_surface_preview_profile_readme_blocked_on_live_auth():
    preview = build_github_surface_preview()

    profile = next(
        e
        for e in preview["preview_entries"]
        if e["target_surface_role"] == "profile_readme_preview"
    )
    assert profile["render_status"] == "blocked"
    assert profile["safety_status"] == "blocked"
    assert any("live network" in s for s in profile["remaining_seams"])


def test_surface_preview_github_pages_blocked():
    preview = build_github_surface_preview()

    pages = next(
        e
        for e in preview["preview_entries"]
        if e["target_surface_role"] == "github_pages_preview"
    )
    assert pages["render_status"] == "blocked"


def test_surface_preview_is_schema_valid():
    preview = build_github_surface_preview()

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.validate(instance=preview, schema=schema)


def test_surface_preview_has_summary():
    preview = build_github_surface_preview()

    summary = preview["summary"]
    assert isinstance(summary, dict)
    assert "total_packets" in summary
    assert summary["total_packets"] == 7
    assert "previewed_count" in summary
    assert "blocked_count" in summary
    assert "not_rendered_count" in summary
    assert summary["next_recommended_action"] == "human_review_required"


def test_surface_preview_entries_require_human_review():
    preview = build_github_surface_preview()

    human_review_targets = {
        e["target_surface_role"]
        for e in preview["preview_entries"]
        if e["human_review_required"] is True
    }
    assert "profile_readme_preview" in human_review_targets
    assert "github_pages_preview" in human_review_targets


def test_surface_preview_entries_are_deterministic():
    preview1 = build_github_surface_preview()
    preview2 = build_github_surface_preview()

    ids1 = [e["preview_id"] for e in preview1["preview_entries"]]
    ids2 = [e["preview_id"] for e in preview2["preview_entries"]]
    assert ids1 == ids2


def test_surface_preview_no_remote_mutation_ever():
    preview = build_github_surface_preview()

    serialized = json.dumps(preview, sort_keys=True)
    assert preview["remote_mutation"] is False
    for forbidden in (
        "token_prefix",
        "access_token",
        "authorization",
        "raw_response",
        "raw_body",
    ):
        assert forbidden not in serialized
