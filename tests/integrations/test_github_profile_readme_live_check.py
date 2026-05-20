"""Integration tests for profile README live check."""

from __future__ import annotations

import json

import pytest

from rig_relay.integrations.github_provider._profile_readme_live_check import (
    _EXPLICITLY_NOT_REQUIRED,
    _REQUIRED_READ_PERMISSIONS,
    _REQUIRED_WRITE_PERMISSIONS,
    build_permission_audit,
    build_preview_artifact,
    check_profile_readme,
    is_live_auth_available,
)

pytestmark = [pytest.mark.contract]


def test_check_profile_readme_dry_run():
    result = check_profile_readme("juliantorr-es", dry_run=True)
    assert result["owner"] == "juliantorr-es"
    assert result["dry_run"] is True
    assert result["live_network"] is False
    assert result["status"] == "dry_run_available"
    assert result["profile_repo_name"] == "github.com/juliantorr-es/juliantorr-es"
    assert result["readme_sha256"] is None


def test_check_profile_readme_without_token_defaults_to_dry_run():
    result = check_profile_readme("testuser", dry_run=False, access_token="")
    assert result["dry_run"] is True
    assert result["status"] == "dry_run_available"


def test_build_preview_artifact_dry_run():
    check = check_profile_readme("juliantorr-es", dry_run=True)
    preview = build_preview_artifact(
        "juliantorr-es", check, generated_at_utc="2026-05-20T00:00:00Z"
    )
    assert preview["schema_version"] == "rig.github.profile_readme_preview.v1"
    assert preview["content_light"] is True
    assert preview["remote_mutation"] is False
    assert preview["preview_status"] == "blocked_dry_run"
    assert len(preview["files"]) == 1
    assert preview["files"][0]["operation"] == "create_new"
    assert preview["safety_checks"]["no_credentials"] is True
    assert preview["safety_checks"]["content_light_enforced"] is True


def test_build_preview_artifact_with_readme_present():
    check = {
        "owner": "juliantorr-es",
        "profile_repo_hash": "abc123",
        "readme_exists": True,
        "readme_sha256": "sha123",
        "readme_size_bytes": 2048,
        "readme_line_count": 42,
        "dry_run": False,
        "live_network": True,
    }
    preview = build_preview_artifact(
        "juliantorr-es", check, generated_at_utc="2026-05-20T00:00:00Z"
    )
    assert preview["preview_status"] == "ready_for_preview"
    assert preview["files"][0]["operation"] == "update_existing"
    assert preview["files"][0]["source_line_count"] == 42


def test_build_permission_audit_dry_run():
    check = check_profile_readme("juliantorr-es", dry_run=True)
    audit = build_permission_audit(
        "juliantorr-es", check, generated_at_utc="2026-05-20T00:00:00Z"
    )
    assert audit["schema_version"] == "rig.github.profile_readme_permission_audit.v1"
    assert audit["content_light"] is True
    assert audit["remote_mutation"] is False
    assert audit["proposed_operation"] == "publish_profile_readme_via_pull_request"
    assert audit["permission_classification"]["workflows_write_needed"] is False
    assert audit["permission_classification"]["actions_write_needed"] is False


def test_permission_audit_with_all_permissions():
    check = {
        "owner": "juliantorr-es",
        "profile_repo_hash": "abc123",
        "dry_run": False,
        "live_network": True,
    }
    audit = build_permission_audit(
        "juliantorr-es",
        check,
        effective_permissions=[
            "contents:read",
            "metadata:read",
            "contents:write",
            "pull_requests:write",
        ],
        generated_at_utc="2026-05-20T00:00:00Z",
    )
    assert audit["permission_classification"]["read_ready"] is True
    assert audit["permission_classification"]["write_ready"] is True
    assert audit["permission_classification"]["publish_possible"] == "permission_ready"
    assert audit["permission_gaps"] == []
    assert audit["recommended_action"] == "ready_for_pr_creation_lane"


def test_permission_audit_with_missing_write():
    check = {
        "owner": "juliantorr-es",
        "profile_repo_hash": "abc123",
        "dry_run": False,
        "live_network": True,
    }
    audit = build_permission_audit(
        "juliantorr-es",
        check,
        effective_permissions=["contents:read", "metadata:read"],
        generated_at_utc="2026-05-20T00:00:00Z",
    )
    assert audit["permission_classification"]["read_ready"] is True
    assert audit["permission_classification"]["write_ready"] is False
    assert "contents:write" in audit["permission_gaps"]
    assert audit["recommended_action"] == "request_permissions"


def test_explicitly_not_required_includes_workflows_and_actions():
    not_required_ids = {p["permission_id"] for p in _EXPLICITLY_NOT_REQUIRED}
    assert "workflows:write" in not_required_ids
    assert "actions:write" in not_required_ids


def test_required_read_permissions_correct():
    read_ids = {p["permission_id"] for p in _REQUIRED_READ_PERMISSIONS}
    assert "contents:read" in read_ids
    assert "metadata:read" in read_ids


def test_required_write_permissions_correct():
    write_ids = {p["permission_id"] for p in _REQUIRED_WRITE_PERMISSIONS}
    assert "contents:write" in write_ids
    assert "pull_requests:write" in write_ids


def test_no_forbidden_fields_in_dry_run_preview():
    check = check_profile_readme("juliantorr-es", dry_run=True)
    preview = build_preview_artifact(
        "juliantorr-es", check, generated_at_utc="2026-05-20T00:00:00Z"
    )
    serialized = json.dumps(preview, sort_keys=True)
    for forbidden in (
        "access_token",
        "token_prefix",
        "authorization",
        "client_secret",
        "private_key",
    ):
        assert f'"{forbidden}"' not in serialized


def test_no_forbidden_fields_in_dry_run_audit():
    check = check_profile_readme("juliantorr-es", dry_run=True)
    audit = build_permission_audit(
        "juliantorr-es", check, generated_at_utc="2026-05-20T00:00:00Z"
    )
    serialized = json.dumps(audit, sort_keys=True)
    for forbidden in (
        "access_token",
        "token_prefix",
        "authorization",
        "client_secret",
        "private_key",
        "raw_response",
        "raw_body",
        "bearer",
    ):
        assert f'"{forbidden}"' not in serialized


def test_preview_blocked_reasons_include_dry_run():
    check = check_profile_readme("juliantorr-es", dry_run=True)
    preview = build_preview_artifact(
        "juliantorr-es", check, generated_at_utc="2026-05-20T00:00:00Z"
    )
    assert "live_network_required" in preview["blocked_reasons"]


def test_is_live_auth_available_returns_bool():
    result = is_live_auth_available()
    assert isinstance(result, bool)


def test_profile_readme_without_source_marks_blocked():
    check = {
        "owner": "testuser",
        "profile_repo_hash": "abc",
        "readme_exists": False,
        "dry_run": False,
        "live_network": True,
    }
    preview = build_preview_artifact("testuser", check)
    assert preview["preview_status"] == "blocked_no_source"
    assert "no_readme_source" in preview["blocked_reasons"]
