"""Integration tests for cross-provider operating picture registry."""

from __future__ import annotations

import json

import pytest

from rig_relay.integrations.provider_registry._operating_picture_registry import (
    build_provider_operating_picture_registry,
    _derive_github_auth_status,
    _derive_github_intake_status,
    _derive_github_packet_status,
    _derive_google_auth_status,
    _derive_google_intake_status,
    _derive_meta_auth_status,
    _derive_meta_intake_status,
    _derive_risk_level,
    _build_provider_entry,
    _PROVIDER_DEFS,
)

pytestmark = [pytest.mark.contract]


def _sample_github_op() -> dict:
    return {
        "schema_version": "rig.github.operating_picture.v1",
        "content_light": True,
        "remote_mutation": False,
        "auth_summary": {
            "installation_access_proven": True,
            "app_installation_configured": True,
        },
        "permission_summary": {
            "refused_surfaces": [{"surface": "dependabot", "status": "refused"}],
            "known_available_surfaces": [
                {"surface": "code_scanning", "status": "present"}
            ],
        },
        "intake_summary": {
            "code_scanning": {"status": "present"},
            "dependabot": {"status": "refused"},
        },
        "packet_summary": {"packet_count": 27, "packet_index_stale": False},
        "next_recommended_actions": ["run_packet_lane"],
        "evidence_paths": ["test.json"],
    }


def _sample_google_op() -> dict:
    return {
        "schema_version": "rig.google_workspace.operating_picture.v1",
        "content_light": True,
        "remote_mutation": False,
        "auth_summary": {"oauth_configured": False, "token_hash_present": False},
        "surface_summary": {
            "gmail_profile": {"status": "refused"},
            "gmail_metadata": {"status": "dry_run_available"},
        },
        "source_artifacts": [],
        "refusals": [{"refusal_kind": "missing_scope"}],
        "next_recommended_actions": ["configure_oauth"],
        "evidence_paths": ["test.json"],
    }


def _sample_meta_op() -> dict:
    return {
        "schema_version": "rig.meta.operating_picture.v1",
        "content_light": True,
        "remote_mutation": False,
        "configured_summary": {"access_token_configured": False},
        "surface_summary": {
            "facebook_pages": "unconfigured",
            "publishing": "refused",
            "messaging": "refused",
        },
        "next_recommended_action": ["no_action", "build_surface_audit"],
        "evidence_paths": ["test.json"],
    }


def test_github_auth_status_working():
    assert _derive_github_auth_status(_sample_github_op()) == "working"


def test_github_intake_status_partial():
    assert _derive_github_intake_status(_sample_github_op()) == "partial"


def test_github_packet_status_present():
    assert _derive_github_packet_status(_sample_github_op()) == "present"


def test_google_auth_status_unconfigured():
    assert _derive_google_auth_status(_sample_google_op()) == "unconfigured"


def test_google_intake_status_refused():
    assert _derive_google_intake_status(_sample_google_op()) == "refused"


def test_meta_auth_status_unconfigured():
    assert _derive_meta_auth_status(_sample_meta_op()) == "unconfigured"


def test_meta_intake_status_partial():
    result = _derive_meta_intake_status(_sample_meta_op())
    assert result in ("partial", "refused")


def test_risk_level_derivation():
    assert _derive_risk_level(0, True, "working") == "low"
    assert _derive_risk_level(2, False, "working") == "medium"
    assert _derive_risk_level(5, False, "unconfigured") == "high"
    assert _derive_risk_level(0, False, "configured") == "medium"


def test_builds_registry_from_all_providers():
    report = build_provider_operating_picture_registry(
        generated_at_utc="2026-05-20T00:00:00Z",
        provider_op_pictures={
            "github": _sample_github_op(),
            "google_workspace": _sample_google_op(),
            "meta": _sample_meta_op(),
        },
    )
    assert report["schema_version"] == "rig.provider.operating_picture_registry.v1"
    assert report["content_light"] is True
    assert report["remote_mutation"] is False
    assert report["provider_count"] == 3

    providers = report["providers"]
    github = next(p for p in providers if p["provider_id"] == "github")
    assert github["auth_status"] == "working"
    assert github["public_release_ready"] is False

    google = next(p for p in providers if p["provider_id"] == "google_workspace")
    assert google["auth_status"] == "unconfigured"

    meta = next(p for p in providers if p["provider_id"] == "meta")
    assert meta["auth_status"] == "unconfigured"
    assert meta["public_release_ready"] is False


def test_missing_provider_is_structured_not_traceback():
    report = build_provider_operating_picture_registry(
        generated_at_utc="2026-05-20T00:00:00Z",
        provider_op_pictures={
            "github": _sample_github_op(),
            "google_workspace": None,
            "meta": None,
        },
    )
    providers = report["providers"]
    google = next(p for p in providers if p["provider_id"] == "google_workspace")
    assert google["operating_picture_present"] is False
    assert google["auth_status"] == "unknown"

    meta = next(p for p in providers if p["provider_id"] == "meta")
    assert meta["operating_picture_present"] is False


def test_release_gate_false_conservatively():
    report = build_provider_operating_picture_registry(
        generated_at_utc="2026-05-20T00:00:00Z",
        provider_op_pictures={
            "github": _sample_github_op(),
            "google_workspace": _sample_google_op(),
            "meta": _sample_meta_op(),
        },
    )
    assert report["release_gate_implications"]["public_release_ready"] is False


def test_no_forbidden_fields_in_registry():
    report = build_provider_operating_picture_registry(
        generated_at_utc="2026-05-20T00:00:00Z",
        provider_op_pictures={"github": _sample_github_op()},
    )
    serialized = json.dumps(report, sort_keys=True)
    for forbidden in ("ghp_", "gho_", "ya29.", "1//", "BEGIN PRIVATE KEY"):
        assert forbidden not in serialized


def test_aggregate_summary_has_correct_counts():
    report = build_provider_operating_picture_registry(
        generated_at_utc="2026-05-20T00:00:00Z",
        provider_op_pictures={
            "github": _sample_github_op(),
            "google_workspace": _sample_google_op(),
            "meta": _sample_meta_op(),
        },
    )
    agg = report["aggregate_summary"]
    assert agg["providers_configured_count"] == 1
    assert agg["providers_public_release_ready_count"] == 0
    assert agg["remote_mutation_enabled_count"] == 0


def test_readiness_matrix_has_all_providers():
    report = build_provider_operating_picture_registry(
        generated_at_utc="2026-05-20T00:00:00Z",
        provider_op_pictures={
            "github": _sample_github_op(),
            "google_workspace": _sample_google_op(),
            "meta": _sample_meta_op(),
        },
    )
    matrix = report["provider_readiness_matrix"]
    assert "github" in matrix
    assert "google_workspace" in matrix
    assert "meta" in matrix


def test_provider_defs_has_all_three():
    assert "github" in _PROVIDER_DEFS
    assert "google_workspace" in _PROVIDER_DEFS
    assert "meta" in _PROVIDER_DEFS


def test_build_provider_entry_with_remote_mutation_true():
    op = dict(_sample_github_op())
    op["remote_mutation"] = True
    from pathlib import Path

    entry = _build_provider_entry("github", op, Path("test.json"), "a" * 64)
    assert entry["remote_mutation"] is True


def test_schema_version_correct():
    report = build_provider_operating_picture_registry(
        generated_at_utc="2026-05-20T00:00:00Z",
        provider_op_pictures={"github": _sample_github_op()},
    )
    assert report["schema_version"] == "rig.provider.operating_picture_registry.v1"
