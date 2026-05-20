"""Adversarial redaction tests for profile README live check."""

from __future__ import annotations

import json

import pytest

from rig_relay.integrations.github_provider._profile_readme_live_check import (
    _FORBIDDEN_PERMISSION_AUDIT,
    _FORBIDDEN_PREVIEW,
    _assert_content_light_fieldset,
    build_permission_audit,
    build_preview_artifact,
    check_profile_readme,
)

pytestmark = [pytest.mark.adversarial, pytest.mark.contract]


def test_rejects_access_token_in_preview():
    with pytest.raises(ValueError):
        _assert_content_light_fieldset(
            {"access_token": "ghp_secret"}, _FORBIDDEN_PREVIEW
        )


def test_rejects_authorization_in_preview():
    with pytest.raises(ValueError):
        _assert_content_light_fieldset(
            {"authorization": "Bearer ghp_token"}, _FORBIDDEN_PREVIEW
        )


def test_rejects_private_key_in_preview():
    with pytest.raises(ValueError):
        _assert_content_light_fieldset(
            {"private_key": "-----BEGIN PRIVATE KEY-----"}, _FORBIDDEN_PREVIEW
        )


def test_rejects_raw_body_in_preview():
    with pytest.raises(ValueError):
        _assert_content_light_fieldset(
            {"raw_body": "some api response"}, _FORBIDDEN_PREVIEW
        )


def test_rejects_patch_in_preview():
    with pytest.raises(ValueError):
        _assert_content_light_fieldset({"patch": "diff content"}, _FORBIDDEN_PREVIEW)


def test_rejects_access_token_in_audit():
    with pytest.raises(ValueError):
        _assert_content_light_fieldset(
            {"access_token": "ghp_secret"}, _FORBIDDEN_PERMISSION_AUDIT
        )


def test_rejects_bearer_in_audit():
    with pytest.raises(ValueError):
        _assert_content_light_fieldset(
            {"bearer": "ghp_secret"}, _FORBIDDEN_PERMISSION_AUDIT
        )


def test_dry_run_check_has_no_token_leakage():
    result = check_profile_readme("juliantorr-es", dry_run=True)
    serialized = json.dumps(result, sort_keys=True)
    for pattern in ("ghp_", "gho_", "github_pat_", "ya29.", "BEGIN PRIVATE KEY"):
        assert pattern not in serialized


def test_dry_run_preview_has_no_token_leakage():
    check = check_profile_readme("juliantorr-es", dry_run=True)
    preview = build_preview_artifact(
        "juliantorr-es", check, generated_at_utc="2026-05-20T00:00:00Z"
    )
    serialized = json.dumps(preview, sort_keys=True)
    for pattern in ("ghp_", "gho_", "github_pat_", "BEGIN PRIVATE KEY"):
        assert pattern not in serialized


def test_dry_run_audit_has_no_token_leakage():
    check = check_profile_readme("juliantorr-es", dry_run=True)
    audit = build_permission_audit(
        "juliantorr-es", check, generated_at_utc="2026-05-20T00:00:00Z"
    )
    serialized = json.dumps(audit, sort_keys=True)
    for pattern in ("ghp_", "gho_", "github_pat_", "BEGIN PRIVATE KEY"):
        assert pattern not in serialized


def test_generated_artifacts_have_no_raw_content():
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[2]
    artifact_dir = repo_root / "docs" / "json" / "governance"

    for af in (
        "github_profile_readme_preview_v1.v1.json",
        "github_publish_pr_permission_audit_v1.v1.json",
    ):
        path = artifact_dir / af
        if not path.exists():
            continue
        serialized = path.read_text(encoding="utf-8")
        for pattern in (
            "ghp_",
            "gho_",
            "github_pat_",
            "BEGIN PRIVATE KEY",
            '"access_token"',
            '"token_prefix"',
            '"authorization"',
        ):
            assert pattern not in serialized, f"'{pattern}' found in {af}"
