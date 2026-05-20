"""Adversarial redaction tests for Google Workspace surface packets."""

from __future__ import annotations

import json

import pytest

from rig_relay.integrations.google_workspace._surface_packets import (
    _assert_content_light,
    project_google_workspace_surface_packets,
)

pytestmark = [pytest.mark.contract, pytest.mark.adversarial]


def test_rejects_access_token_in_packets():
    report = {
        "schema_version": "rig.google_workspace.surface_packets.v1",
        "access_token": "ya29.secrettokenvalue",
    }
    with pytest.raises(ValueError):
        _assert_content_light(report)


def test_rejects_refresh_token_in_packets():
    report = {
        "schema_version": "rig.google_workspace.surface_packets.v1",
        "refresh_token": "1//secret-token-value",
    }
    with pytest.raises(ValueError):
        _assert_content_light(report)


def test_rejects_private_key_in_packets():
    report = {
        "schema_version": "rig.google_workspace.surface_packets.v1",
        "private_key": "-----BEGIN PRIVATE KEY-----\nMIIEvQIBADANBgk...",
    }
    with pytest.raises(ValueError):
        _assert_content_light(report)


def test_rejects_raw_email_in_packets():
    report = {
        "schema_version": "rig.google_workspace.surface_packets.v1",
        "raw_email": "user@gmail.com",
    }
    with pytest.raises(ValueError):
        _assert_content_light(report)


def test_rejects_raw_body_in_packets():
    report = {
        "schema_version": "rig.google_workspace.surface_packets.v1",
        "raw_body": "some API response body",
    }
    with pytest.raises(ValueError):
        _assert_content_light(report)


def test_rejects_nested_google_token_in_packets():
    report = {
        "schema_version": "rig.google_workspace.surface_packets.v1",
        "packets": [{"packet_id": "test", "notes": "token: ya29.a0AfH6SMA-secret"}],
    }
    with pytest.raises(ValueError):
        _assert_content_light(report)


def test_built_packets_pass_redaction():
    report = project_google_workspace_surface_packets(
        operating_picture=None,
        read_intake=None,
        generated_at_utc="2026-05-20T00:00:00Z",
    )
    serialized = json.dumps(report, sort_keys=True)
    for token_like in ("ya29.", "1//", "BEGIN PRIVATE KEY"):
        assert token_like not in serialized


def test_no_contact_email_in_packets():
    report = project_google_workspace_surface_packets(
        operating_picture=None,
        read_intake=None,
        generated_at_utc="2026-05-20T00:00:00Z",
    )
    serialized = json.dumps(report, sort_keys=True)
    assert '"raw_contacts"' not in serialized
    assert '"contact_email"' not in serialized


def test_no_calendar_or_drive_content_in_packets():
    report = project_google_workspace_surface_packets(
        operating_picture=None,
        read_intake=None,
        generated_at_utc="2026-05-20T00:00:00Z",
    )
    serialized = json.dumps(report, sort_keys=True)
    assert '"calendar_description"' not in serialized
    assert '"drive_file_contents"' not in serialized
    assert '"raw_drive_content"' not in serialized
