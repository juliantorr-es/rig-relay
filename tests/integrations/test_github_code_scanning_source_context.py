"""Integration tests for code scanning source context acquisition — read-only, gated."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from rig_relay.integrations.github_provider._code_scanning_source_context import (
    _ENDPOINTS_MODELED,
    build_code_scanning_source_context,
)

pytestmark = [pytest.mark.contract]

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = (
    REPO_ROOT
    / "docs"
    / "schemas"
    / "rig.github.code_scanning_source_context.v1.schema.json"
)


def test_context_validates_against_schema():
    assert SCHEMA_PATH.exists()
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    report = build_code_scanning_source_context(generated_at_utc="2026-05-20T00:00:00Z")
    jsonschema.validate(instance=report, schema=schema)


def test_context_blocked_by_default():
    report = build_code_scanning_source_context(generated_at_utc="2026-05-20T00:00:00Z")
    assert "blocked" in report["source_context_status"]
    assert "no_live_access" in report["acquisition_mode"]
    assert report["live_api_attempted"] is False
    assert report["safe_context_available"] is False


def test_context_no_live_call_default():
    report = build_code_scanning_source_context(generated_at_utc="2026-05-20T00:00:00Z")
    gate = report["live_api_gate_status"]
    assert gate["live_allowed"] is False


def test_context_no_raw_source_persisted():
    report = build_code_scanning_source_context(generated_at_utc="2026-05-20T00:00:00Z")
    assert report["source_slice_summary"]["raw_slice_persisted"] is False
    assert report["source_slice_summary"]["slice_sha256"] is None


def test_context_permissions_separated():
    report = build_code_scanning_source_context(generated_at_utc="2026-05-20T00:00:00Z")
    perms = report["permissions_required"]
    assert "read" in perms
    assert "mutation_later" in perms
    assert "security_events:read" in perms["read"]
    assert "contents:read" in perms["read"]


def test_context_mutations_disabled():
    report = build_code_scanning_source_context(generated_at_utc="2026-05-20T00:00:00Z")
    assert report["local_mutation_status"] == "disabled"
    assert report["remote_mutation_status"] == "disabled"


def test_context_no_forbidden_fields():
    report = build_code_scanning_source_context(generated_at_utc="2026-05-20T00:00:00Z")
    serialized = json.dumps(report, sort_keys=True)
    for f in (
        "access_token",
        "authorization",
        "client_secret",
        "private_key",
        "raw_response",
        "raw_body",
        "code_snippet",
        "source_content",
        "secret_value",
    ):
        assert f'"{f}"' not in serialized


def test_context_no_token_patterns():
    report = build_code_scanning_source_context(generated_at_utc="2026-05-20T00:00:00Z")
    serialized = json.dumps(report, sort_keys=True)
    for p in ("ghp_", "gho_", "github_pat_", "BEGIN PRIVATE KEY"):
        assert p not in serialized


def test_context_references_source_artifacts():
    report = build_code_scanning_source_context(generated_at_utc="2026-05-20T00:00:00Z")
    assert "governance/github_security_queue" in report["source_queue_artifact"]
    assert (
        "governance/github_code_scanning_patch_proposal"
        in report["source_patch_proposal_artifact"]
    )


def test_context_selects_correct_alert():
    report = build_code_scanning_source_context(generated_at_utc="2026-05-20T00:00:00Z")
    assert report["selected_alert_number"] == 5
    assert report["rule_id_hash"] is not None


def test_context_has_unsafe_reasons():
    report = build_code_scanning_source_context(generated_at_utc="2026-05-20T00:00:00Z")
    assert len(report["unsafe_context_reasons"]) >= 3


def test_endpoints_modeled_are_read_only():
    for ep in _ENDPOINTS_MODELED:
        assert ep["method"] == "GET"


def test_endpoints_modeled_three_surfaces():
    endpoint_families = {e["endpoint_family"] for e in _ENDPOINTS_MODELED}
    assert "code_scanning_alert" in endpoint_families
    assert "repo_contents" in endpoint_families


def test_generated_artifact_validates():
    artifact_path = (
        REPO_ROOT
        / "docs"
        / "json"
        / "governance"
        / "github_code_scanning_source_context_v1.v1.json"
    )
    if not artifact_path.exists():
        pytest.skip("Artifact not yet generated")
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    report = json.loads(artifact_path.read_text(encoding="utf-8"))
    jsonschema.validate(instance=report, schema=schema)


def test_generated_artifact_no_forbidden_content():
    artifact_path = (
        REPO_ROOT
        / "docs"
        / "json"
        / "governance"
        / "github_code_scanning_source_context_v1.v1.json"
    )
    if not artifact_path.exists():
        pytest.skip("Artifact not yet generated")
    serialized = artifact_path.read_text(encoding="utf-8")
    for p in (
        "ghp_",
        "BEGIN PRIVATE KEY",
        '"access_token"',
        '"raw_body"',
        '"code_snippet"',
    ):
        assert p not in serialized, f"'{p}' found"
