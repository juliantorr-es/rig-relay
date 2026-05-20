"""Integration tests for live permission probe — X-Accepted-GitHub-Permissions capture and normalization."""

from __future__ import annotations

import json

import pytest

from rig_relay.integrations.github_provider._live_permission_probe import (
    _PROBE_ENDPOINTS,
    _build_probe_entry,
    _normalize_observed_permission,
    is_live_probe_available,
    normalize_accepted_permissions_header,
    run_live_permission_verification,
)

pytestmark = [pytest.mark.contract]


# ── Header normalization tests ──


def test_normalize_single_permission():
    result = normalize_accepted_permissions_header("contents=read")
    assert result["parse_success"] is True
    assert len(result["normalized_permissions"]) == 1
    assert result["normalized_permissions"][0]["permission_key"] == "contents"
    assert result["normalized_permissions"][0]["access_level"] == "read"


def test_normalize_combined_permissions():
    result = normalize_accepted_permissions_header("pull_requests=write,contents=read")
    assert result["parse_success"] is True
    assert len(result["normalized_permissions"]) == 2
    keys = {p["permission_key"] for p in result["normalized_permissions"]}
    assert "pull_requests" in keys
    assert "contents" in keys


def test_normalize_empty_header():
    result = normalize_accepted_permissions_header("")
    assert result["parse_success"] is False
    assert result["parse_error"] == "empty_or_non_string_header"


def test_normalize_malformed_header():
    result = normalize_accepted_permissions_header("contents")
    assert result["parse_success"] is False
    assert result["parse_error"] is not None


def test_normalize_header_with_spaces():
    result = normalize_accepted_permissions_header(
        "  contents = read , pull_requests = write  "
    )
    assert result["parse_success"] is True
    assert len(result["normalized_permissions"]) == 2


def test_normalize_header_produces_hash():
    result = normalize_accepted_permissions_header("contents=read")
    assert result["raw_header_hash"] is not None
    assert len(result["raw_header_hash"]) == 64


# ── Observed permission matching tests ──


def test_normalize_observed_exact_match():
    static = [
        {"permission_id": "contents:read", "access_level": "read"},
        {"permission_id": "pull_requests:write", "access_level": "write"},
    ]
    result = _normalize_observed_permission("contents", "read", static)
    assert result["match_type"] == "exact"
    assert result["classification"] == "sufficient"


def test_normalize_observed_level_mismatch():
    static = [{"permission_id": "contents:read", "access_level": "read"}]
    result = _normalize_observed_permission("contents", "write", static)
    assert result["match_type"] == "partial_level_mismatch"
    assert result["classification"] == "ambiguous"


def test_normalize_observed_unmodeled():
    static = [{"permission_id": "contents:read", "access_level": "read"}]
    result = _normalize_observed_permission("metadata", "read", static)
    assert result["match_type"] == "unmodeled"
    assert result["classification"] == "unmodeled"


# ── Probe build tests ──


def test_build_probe_entry_success():
    spec = _PROBE_ENDPOINTS[0]
    static = [{"permission_id": "metadata:read", "access_level": "read"}]
    entry = _build_probe_entry(spec, 200, "metadata=read", static)
    assert entry["endpoint_family"] == "repo_metadata"
    assert entry["accessible"] is True
    assert entry["accepted_permissions_header"]["parse_success"] is True
    assert len(entry["accepted_permissions_header"]["observed_permissions"]) == 1


def test_build_probe_entry_404():
    spec = _PROBE_ENDPOINTS[0]
    static: list[dict[str, str]] = []
    entry = _build_probe_entry(spec, 404, None, static)
    assert entry["accessible"] is False
    assert entry["live_verification"] == "success"
    assert entry["accepted_permissions_header"] is None


def test_build_probe_entry_no_header():
    spec = _PROBE_ENDPOINTS[1]
    static: list[dict[str, str]] = []
    entry = _build_probe_entry(spec, 200, None, static)
    assert entry["accepted_permissions_header"] is None


# ── Live probe gate tests ──


def test_run_probe_skipped_without_env():
    result = run_live_permission_verification("testuser", access_token="")
    assert result["live_verification_run"] is False
    assert "RIG_LIVE_AUTH_TESTS" in result["skipped_reason"]


def test_run_probe_skipped_without_token():
    # RIG_LIVE_AUTH_TESTS might be set in CI, but with empty token it should still skip
    result = run_live_permission_verification("testuser", access_token="")
    assert result["live_verification_run"] is False


def test_is_live_probe_available_default_false():
    assert is_live_probe_available() is False


def test_probe_endpoints_are_well_formed():
    assert len(_PROBE_ENDPOINTS) >= 2
    for ep in _PROBE_ENDPOINTS:
        assert "endpoint_family" in ep
        assert "method" in ep
        assert ep["method"] == "GET"
        assert "route" in ep
        assert "expected_permission" in ep
        assert ep["operation_class"] == "read_only"


# ── Redaction tests ──


def test_probe_result_no_forbidden_fields():
    result = run_live_permission_verification("testuser")
    serialized = json.dumps(result, sort_keys=True)
    for forbidden in (
        "access_token",
        "authorization",
        "client_secret",
        "private_key",
        "raw_response",
        "raw_body",
        "raw_payload",
        "bearer",
    ):
        assert f'"{forbidden}"' not in serialized


def test_normalize_header_no_token_leakage():
    result = normalize_accepted_permissions_header("contents=read")
    serialized = json.dumps(result, sort_keys=True)
    for pattern in ("ghp_", "gho_", "github_pat_", "ya29.", "BEGIN PRIVATE KEY"):
        assert pattern not in serialized


def test_probe_endpoints_are_read_only():
    for ep in _PROBE_ENDPOINTS:
        assert ep["method"] == "GET"
        assert ep["operation_class"] == "read_only"
