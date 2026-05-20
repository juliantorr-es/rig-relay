"""Integration tests for Google Workspace read intake."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from rig_relay.integrations.google_workspace._read_intake import (
    _SURFACES,
    _build_scope_grants,
    _collect_dry_run,
    build_google_workspace_read_intake,
)

pytestmark = [pytest.mark.contract]

REPO_ROOT = Path(__file__).resolve().parents[2]


def _sample_scope_manifest() -> dict:
    return {
        "scopes": [
            {"scope_id": "openid", "sensitivity": "non_sensitive"},
            {
                "scope_id": "https://www.googleapis.com/auth/gmail.labels",
                "sensitivity": "non_sensitive",
            },
            {
                "scope_id": "https://www.googleapis.com/auth/calendar.readonly",
                "sensitivity": "non_sensitive",
            },
            {
                "scope_id": "https://www.googleapis.com/auth/tasks.readonly",
                "sensitivity": "non_sensitive",
            },
            {
                "scope_id": "https://www.googleapis.com/auth/contacts.readonly",
                "sensitivity": "non_sensitive",
            },
        ]
    }


def test_dry_run_no_network():
    report = build_google_workspace_read_intake(
        dry_run=True, live=False, generated_at_utc="2026-05-20T00:00:00Z"
    )
    assert report["schema_version"] == "rig.google_workspace.read_intake.v1"
    assert report["dry_run"] is True
    assert report["live"] is False
    assert report["content_light"] is True
    assert report["remote_mutation"] is False


def test_dry_run_produces_all_surfaces():
    report = build_google_workspace_read_intake(
        dry_run=True, live=False, generated_at_utc="2026-05-20T00:00:00Z"
    )
    surfaces = report["surfaces"]
    assert len(surfaces) == len(_SURFACES)
    surface_names = {s["surface"] for s in surfaces}
    assert "gmail_profile" in surface_names
    assert "gmail_labels" in surface_names
    assert "calendar_list" in surface_names
    assert "drive_files" in surface_names
    assert "tasklists" in surface_names
    assert "contacts" in surface_names


def test_dry_run_restricted_scopes_refused():
    report = build_google_workspace_read_intake(
        dry_run=True, live=False, generated_at_utc="2026-05-20T00:00:00Z"
    )
    refused_surfaces = [
        s["surface"] for s in report["surfaces"] if s["status"] == "refused"
    ]
    assert "gmail_profile" in refused_surfaces
    assert "drive_files" in refused_surfaces


def test_dry_run_non_restricted_dry_run_available():
    report = build_google_workspace_read_intake(
        dry_run=True, live=False, generated_at_utc="2026-05-20T00:00:00Z"
    )
    available = [
        s["surface"] for s in report["surfaces"] if s["status"] == "dry_run_available"
    ]
    assert "gmail_labels" in available
    assert "calendar_list" in available
    assert "tasklists" in available
    assert "contacts" in available


def test_refusals_have_correct_structure():
    report = build_google_workspace_read_intake(
        dry_run=True, live=False, generated_at_utc="2026-05-20T00:00:00Z"
    )
    refusals = report["refusals"]
    assert len(refusals) > 0
    for refusal in refusals:
        assert refusal["status"] == "refused"
        assert refusal["remote_mutation"] is False
        assert "refusal_reason" in refusal
        assert "surface" in refusal


def test_content_light_no_forbidden_fields():
    report = build_google_workspace_read_intake(
        dry_run=True, live=False, generated_at_utc="2026-05-20T00:00:00Z"
    )
    serialized = json.dumps(report, sort_keys=True)
    for forbidden in (
        "access_token",
        "refresh_token",
        "token_prefix",
        "authorization",
        "client_secret",
        "private_key",
        "raw_response",
        "raw_body",
    ):
        assert f'"{forbidden}"' not in serialized, f"Forbidden '{forbidden}' found"


def test_schema_version_correct():
    report = build_google_workspace_read_intake(
        dry_run=True, live=False, generated_at_utc="2026-05-20T00:00:00Z"
    )
    assert report["schema_version"] == "rig.google_workspace.read_intake.v1"


def test_summary_has_correct_counts():
    report = build_google_workspace_read_intake(
        dry_run=True, live=False, generated_at_utc="2026-05-20T00:00:00Z"
    )
    summary = report["summary"]
    assert summary["total_surfaces"] == len(_SURFACES)
    assert summary["present_surfaces"] >= 0
    assert summary["refused_surfaces"] >= 0
    assert (
        summary["present_surfaces"]
        + summary["refused_surfaces"]
        + summary["not_implemented_surfaces"]
        == summary["total_surfaces"]
    )


def test_collect_dry_run_returns_tuples():
    surfaces, refusals = _collect_dry_run(None)
    assert isinstance(surfaces, list)
    assert isinstance(refusals, list)
    assert len(surfaces) == len(_SURFACES)


def test_build_scope_grants_empty():
    grants = _build_scope_grants(None)
    assert grants == []


def test_build_scope_grants_from_manifest():
    grants = _build_scope_grants(_sample_scope_manifest())
    assert len(grants) == 5
    assert all("scope" in g for g in grants)
    assert all("granted" in g for g in grants)
    assert all("sensitivity" in g for g in grants)
