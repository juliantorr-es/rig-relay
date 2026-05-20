"""Adversarial redaction tests for Google Workspace operating picture."""

from __future__ import annotations

import json

import pytest

from rig_relay.integrations.google_workspace._operating_picture import (
    _assert_content_light,
    build_google_workspace_operating_picture,
)

pytestmark = [pytest.mark.contract, pytest.mark.adversarial]


def test_rejects_access_token_in_report():
    report = {
        "schema_version": "rig.google_workspace.operating_picture.v1",
        "access_token": "ya29.secrettokenvalue",
        "content_light": True,
        "remote_mutation": False,
    }
    with pytest.raises(ValueError):
        _assert_content_light(report)


def test_rejects_client_secret_in_report():
    report = {
        "schema_version": "rig.google_workspace.operating_picture.v1",
        "client_secret": "GOCSPX-secret-value",
        "content_light": True,
    }
    with pytest.raises(ValueError):
        _assert_content_light(report)


def test_rejects_raw_body_in_report():
    report = {
        "schema_version": "rig.google_workspace.operating_picture.v1",
        "raw_body": "some raw response body",
    }
    with pytest.raises(ValueError):
        _assert_content_light(report)


def test_rejects_nested_forbidden_key():
    report = {
        "schema_version": "rig.google_workspace.operating_picture.v1",
        "nested": {"access_token": "ya29.nested-token"},
    }
    with pytest.raises(ValueError):
        _assert_content_light(report)


def test_rejects_google_token_pattern_in_string():
    report = {
        "schema_version": "rig.google_workspace.operating_picture.v1",
        "summary": "token: ya29.a0AfH6SMA-secret-value",
    }
    with pytest.raises(ValueError):
        _assert_content_light(report)


def test_rejects_private_key_pattern_in_string():
    report = {
        "schema_version": "rig.google_workspace.operating_picture.v1",
        "notes": "-----BEGIN PRIVATE KEY-----\nMIIEvAIBADANBgkq...",
    }
    with pytest.raises(ValueError):
        _assert_content_light(report)


def test_rejects_refresh_token_in_nested_dict():
    report = {
        "schema_version": "rig.google_workspace.operating_picture.v1",
        "auth": {"refresh_token": "1//secret-refresh-token"},
    }
    with pytest.raises(ValueError):
        _assert_content_light(report)


def test_built_report_passes_content_light():
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
    for token_like in ("ya29.", "1//", "BEGIN PRIVATE KEY"):
        assert token_like not in serialized


def test_report_has_conservative_scope_posture():
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
    assert report["scope_posture"]["public_release_ready"] is False
    assert report["scope_posture"]["least_privilege_ready"] is True


def test_restricted_scopes_not_marked_public_ready():
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
    assert report["scope_posture"]["public_release_ready"] is False
