"""Adversarial redaction tests for cross-provider operating picture registry."""

from __future__ import annotations

import json

import pytest

from rig_relay.integrations.provider_registry._operating_picture_registry import (
    _assert_content_light,
    build_provider_operating_picture_registry,
)

pytestmark = [pytest.mark.contract, pytest.mark.adversarial]


def _sample_github_op() -> dict:
    return {
        "schema_version": "rig.github.operating_picture.v1",
        "content_light": True,
        "remote_mutation": False,
        "auth_summary": {"installation_access_proven": True},
        "permission_summary": {"refused_surfaces": []},
        "intake_summary": {
            "code_scanning": {"status": "present"},
            "dependabot": {"status": "refused"},
        },
        "packet_summary": {"packet_count": 10, "packet_index_stale": False},
        "next_recommended_actions": ["run_packet_lane"],
        "evidence_paths": ["test.json"],
    }


def test_rejects_access_token_in_registry():
    report = {
        "schema_version": "rig.provider.operating_picture_registry.v1",
        "access_token": "ghp_secrettoken",
    }
    with pytest.raises(ValueError):
        _assert_content_light(report)


def test_rejects_refresh_token_in_registry():
    report = {
        "schema_version": "rig.provider.operating_picture_registry.v1",
        "refresh_token": "1//secret",
    }
    with pytest.raises(ValueError):
        _assert_content_light(report)


def test_rejects_client_secret_in_registry():
    report = {
        "schema_version": "rig.provider.operating_picture_registry.v1",
        "client_secret": "GOCSPX-secret",
    }
    with pytest.raises(ValueError):
        _assert_content_light(report)


def test_rejects_private_key_in_registry():
    report = {
        "schema_version": "rig.provider.operating_picture_registry.v1",
        "private_key": "-----BEGIN PRIVATE KEY-----",
    }
    with pytest.raises(ValueError):
        _assert_content_light(report)


def test_rejects_raw_body_in_registry():
    report = {
        "schema_version": "rig.provider.operating_picture_registry.v1",
        "raw_body": "some response body",
    }
    with pytest.raises(ValueError):
        _assert_content_light(report)


def test_rejects_code_snippet_in_registry():
    report = {
        "schema_version": "rig.provider.operating_picture_registry.v1",
        "code_snippet": "some code",
    }
    with pytest.raises(ValueError):
        _assert_content_light(report)


def test_rejects_patch_in_registry():
    report = {
        "schema_version": "rig.provider.operating_picture_registry.v1",
        "patch": "some diff content",
    }
    with pytest.raises(ValueError):
        _assert_content_light(report)


def test_rejects_diff_in_registry():
    report = {
        "schema_version": "rig.provider.operating_picture_registry.v1",
        "diff": "some diff content",
    }
    with pytest.raises(ValueError):
        _assert_content_light(report)


def test_rejects_contents_in_registry():
    report = {
        "schema_version": "rig.provider.operating_picture_registry.v1",
        "contents": "file contents",
    }
    with pytest.raises(ValueError):
        _assert_content_light(report)


def test_built_registry_passes_redaction():
    report = build_provider_operating_picture_registry(
        generated_at_utc="2026-05-20T00:00:00Z",
        provider_op_pictures={"github": _sample_github_op()},
    )
    serialized = json.dumps(report, sort_keys=True)
    for token_like in ("ghp_", "gho_", "ya29.", "1//", "BEGIN PRIVATE KEY"):
        assert token_like not in serialized


def test_remote_mutation_reported_in_entry():
    op = dict(_sample_github_op())
    op["remote_mutation"] = True
    report = build_provider_operating_picture_registry(
        generated_at_utc="2026-05-20T00:00:00Z", provider_op_pictures={"github": op}
    )
    github = next(p for p in report["providers"] if p["provider_id"] == "github")
    assert github["remote_mutation"] is True
