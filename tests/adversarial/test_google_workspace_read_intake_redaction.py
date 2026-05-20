"""Adversarial redaction tests for Google Workspace read intake."""

from __future__ import annotations

import json

import pytest

from rig_relay.integrations.google_workspace._read_intake import (
    _assert_content_light,
    build_google_workspace_read_intake,
)

pytestmark = [pytest.mark.contract, pytest.mark.adversarial]


def test_rejects_access_token_in_intake():
    report = {
        "access_token": "ya29.secrettokenvalue",
        "schema_version": "rig.google_workspace.read_intake.v1",
    }
    with pytest.raises(ValueError):
        _assert_content_light(report)


def test_rejects_refresh_token_in_intake():
    report = {
        "refresh_token": "1//secret-refresh-token-value",
        "schema_version": "rig.google_workspace.read_intake.v1",
    }
    with pytest.raises(ValueError):
        _assert_content_light(report)


def test_rejects_client_secret_in_intake():
    report = {
        "client_secret": "GOCSPX-secret-thing",
        "schema_version": "rig.google_workspace.read_intake.v1",
    }
    with pytest.raises(ValueError):
        _assert_content_light(report)


def test_rejects_private_key_in_intake():
    report = {
        "private_key": "-----BEGIN PRIVATE KEY-----\nMIIEvg...",
        "schema_version": "rig.google_workspace.read_intake.v1",
    }
    with pytest.raises(ValueError):
        _assert_content_light(report)


def test_rejects_raw_email_in_intake():
    report = {
        "raw_email": "user@example.com",
        "schema_version": "rig.google_workspace.read_intake.v1",
    }
    with pytest.raises(ValueError):
        _assert_content_light(report)


def test_rejects_raw_body_in_intake():
    report = {
        "raw_body": "some raw response body text",
        "schema_version": "rig.google_workspace.read_intake.v1",
    }
    with pytest.raises(ValueError):
        _assert_content_light(report)


def test_rejects_token_prefix_in_intake():
    report = {
        "token_prefix": "ya29.",
        "schema_version": "rig.google_workspace.read_intake.v1",
    }
    with pytest.raises(ValueError):
        _assert_content_light(report)


def test_rejects_authorization_header_in_intake():
    report = {
        "authorization": "Bearer ya29.tokenvalue",
        "schema_version": "rig.google_workspace.read_intake.v1",
    }
    with pytest.raises(ValueError):
        _assert_content_light(report)


def test_rejects_google_token_pattern_in_nested_value():
    report = {
        "schema_version": "rig.google_workspace.read_intake.v1",
        "some": {"nested": {"value": "ya29.a0AfH6SMA-secret"}},
    }
    with pytest.raises(ValueError):
        _assert_content_light(report)


def test_built_intake_passes_redaction():
    report = build_google_workspace_read_intake(
        dry_run=True, live=False, generated_at_utc="2026-05-20T00:00:00Z"
    )
    serialized = json.dumps(report, sort_keys=True)
    for token_like in ("ya29.", "1//", "BEGIN PRIVATE KEY"):
        assert token_like not in serialized


def test_dry_run_intake_has_no_raw_api_bodies():
    report = build_google_workspace_read_intake(
        dry_run=True, live=False, generated_at_utc="2026-05-20T00:00:00Z"
    )
    serialized = json.dumps(report, sort_keys=True)
    assert '"raw_response"' not in serialized
    assert '"raw_body"' not in serialized
