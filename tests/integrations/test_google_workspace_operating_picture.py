"""Integration tests for Google Workspace operating picture."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from rig_relay.integrations.google_workspace._operating_picture import (
    _build_auth_summary,
    _build_next_actions,
    _build_refusals,
    _build_scope_posture,
    _build_surface_summary,
    build_google_workspace_operating_picture,
)

pytestmark = [pytest.mark.contract]

REPO_ROOT = Path(__file__).resolve().parents[2]


def _sample_live_auth() -> dict:
    return {
        "config_summary": {
            "oauth_configured": False,
            "redirect_uri_configured": False,
            "service_account_configured": False,
            "client_id_hash": "abc123",
        },
        "issues": [{"kind": "no_auth_configured"}],
    }


def _sample_scope_manifest() -> dict:
    return {
        "scopes": [
            {"scope_id": "openid", "sensitivity": "non_sensitive"},
            {
                "scope_id": "https://www.googleapis.com/auth/gmail.readonly",
                "sensitivity": "restricted",
            },
            {
                "scope_id": "https://www.googleapis.com/auth/calendar.readonly",
                "sensitivity": "non_sensitive",
            },
            {
                "scope_id": "https://www.googleapis.com/auth/drive.metadata.readonly",
                "sensitivity": "non_sensitive",
            },
        ]
    }


def _sample_capability_manifest() -> dict:
    return {
        "capabilities": [
            {
                "capability_id": "google_workspace.gmail.profile.get",
                "scope_sensitivity": "restricted",
            },
            {
                "capability_id": "google_workspace.gmail.labels.list",
                "scope_sensitivity": "non_sensitive",
            },
            {
                "capability_id": "google_workspace.calendar.calendarList.list",
                "scope_sensitivity": "sensitive",
            },
            {
                "capability_id": "google_workspace.drive.files.list",
                "scope_sensitivity": "restricted",
            },
            {
                "capability_id": "google_workspace.tasks.tasklists.list",
                "scope_sensitivity": "non_sensitive",
            },
            {
                "capability_id": "google_workspace.contacts.list",
                "scope_sensitivity": "non_sensitive",
            },
        ]
    }


def _sample_contract() -> dict:
    return {
        "scope_taxonomy": {
            "restricted_scope_policy": {
                "live_refused": True,
                "requires_security_assessment": True,
            },
            "sensitive_scope_policy": {"live_requires_verification_posture": True},
        },
        "delegation_policy": {"domain_wide_delegation_refused_in_v1": True},
    }


def test_build_auth_summary_no_data():
    result = _build_auth_summary(None, None, None)
    assert result["oauth_configured"] is False
    assert result["public_release_ready"] is False
    assert result["restricted_scope_count"] == 0


def test_build_auth_summary_with_scope_manifest():
    result = _build_auth_summary(None, _sample_scope_manifest(), None)
    assert result["requested_scope_count"] == 4
    assert result["restricted_scope_count"] == 1


def test_build_auth_summary_with_live_auth():
    result = _build_auth_summary(_sample_live_auth(), _sample_scope_manifest(), None)
    assert result["oauth_configured"] is False
    assert result["consent_mode"] == "external"


def test_build_surface_summary_from_capability_manifest():
    result = _build_surface_summary(None, _sample_capability_manifest(), None)
    assert result["gmail_profile"]["status"] == "missing"
    assert result["calendar_list"]["status"] == "missing"
    assert result["drive_metadata"]["status"] == "missing"
    assert result["tasks_readonly"]["status"] == "missing"
    assert result["contacts_people_readonly"]["status"] == "missing"


def test_build_surface_summary_no_data():
    result = _build_surface_summary(None, None, None)
    assert result["gmail_profile"]["status"] == "not_implemented"
    assert result["drive_metadata"]["status"] == "not_implemented"


def test_build_scope_posture_conservative():
    auth = _build_auth_summary(None, _sample_scope_manifest(), _sample_contract())
    result = _build_scope_posture(auth, _sample_contract())
    assert result["public_release_ready"] is False
    assert result["verification_required"] is True
    assert result["restricted_scopes_refused_or_deferred"] is True


def test_build_refusals_restricted_scopes():
    auth = _build_auth_summary(None, _sample_scope_manifest(), _sample_contract())
    surface = _build_surface_summary(None, _sample_capability_manifest(), None)
    refusals = _build_refusals(auth, surface, _sample_contract())
    assert any(r["refusal_kind"] == "restricted_scope_unverified" for r in refusals)
    assert any(r["refusal_kind"] == "domain_wide_delegation_deferred" for r in refusals)


def test_build_next_actions_no_auth():
    auth = _build_auth_summary(None, None, None)
    surface = _build_surface_summary(None, None, None)
    posture = _build_scope_posture(auth, None)
    actions = _build_next_actions(auth, surface, posture, False)
    assert "configure_oauth" in actions


def test_build_next_actions_with_auth_no_intake():
    auth = {
        "oauth_configured": True,
        "token_hash_present": True,
        "restricted_scope_count": 0,
        "requested_scope_count": 2,
        "missing_required_scopes": [],
        "sensitive_scope_count": 0,
    }
    surface = _build_surface_summary(None, None, None)
    posture = _build_scope_posture(auth, None)
    actions = _build_next_actions(auth, surface, posture, False)
    assert "run_dry_run" in actions or "run_live_read_intake" in actions


def test_build_operating_picture_basic():
    report = build_google_workspace_operating_picture(
        context={
            "generated_at_utc": "2026-05-20T00:00:00Z",
            "branch": "main",
            "head": "abc123",
        },
        source_artifacts=[
            {
                "artifact_id": "live_auth",
                "path": "test.json",
                "present": True,
                "status": "present",
                "artifact_hash": "a" * 64,
                "schema_version": "rig.google_workspace.live_auth_refusal.v1",
                "summary": {},
            }
        ],
        artifacts={"live_auth": _sample_live_auth()},
    )
    assert report["schema_version"] == "rig.google_workspace.operating_picture.v1"
    assert report["content_light"] is True
    assert report["remote_mutation"] is False


def test_operating_picture_no_forbidden_fields():
    report = build_google_workspace_operating_picture(
        context={},
        source_artifacts=[
            {
                "artifact_id": "test",
                "path": "test.json",
                "present": True,
                "status": "present",
                "artifact_hash": "a" * 64,
                "schema_version": None,
                "summary": {},
            }
        ],
        artifacts={},
    )
    serialized = json.dumps(report, sort_keys=True)
    forbidden = [
        "ya29.",
        "1//",
        "BEGIN PRIVATE KEY",
        '"access_token"',
        '"refresh_token"',
        '"token_prefix"',
        '"authorization"',
        '"client_secret"',
        '"private_key"',
    ]
    for f in forbidden:
        assert f not in serialized, f"Forbidden '{f}' found in report"


def test_build_from_missing_optional_artifacts():
    report = build_google_workspace_operating_picture(
        context={},
        source_artifacts=[
            {
                "artifact_id": "scope_manifest",
                "path": "missing.json",
                "present": False,
                "status": "missing",
                "artifact_hash": None,
                "schema_version": None,
                "summary": None,
            }
        ],
        artifacts={"scope_manifest": None},
    )
    assert report["schema_version"] == "rig.google_workspace.operating_picture.v1"
    assert report["content_light"] is True
