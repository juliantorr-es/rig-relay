"""Governance artifact test for Google + Meta provider API research."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

pytestmark = [pytest.mark.contract, pytest.mark.real_artifact]

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = (
    REPO_ROOT
    / "docs"
    / "schemas"
    / "rig.provider_api_research.google_meta.v1.schema.json"
)
REPORT_PATH = (
    REPO_ROOT
    / "docs"
    / "json"
    / "research"
    / "provider_api_research_google_meta_v1.v1.json"
)

_FORBIDDEN_KEYS = frozenset({
    "access_token",
    "app_secret",
    "client_secret",
    "verify_token",
    "authorization",
    "bearer",
    "phone_number",
    "email",
    "raw_response",
    "raw_body",
    "webhook_payload",
    "message_text",
    "comment_text",
    "dm_text",
    "media_url",
    "image_url",
    "video_url",
    "post_caption",
})


def _assert_no_forbidden_keys(obj):
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key in _FORBIDDEN_KEYS:
                raise AssertionError(f"forbidden_key_found: {key}")
            _assert_no_forbidden_keys(value)
    elif isinstance(obj, list):
        for item in obj:
            _assert_no_forbidden_keys(item)


def test_research_artifact_validates_against_schema():
    assert SCHEMA_PATH.exists(), f"Schema file not found at {SCHEMA_PATH}"
    assert REPORT_PATH.exists(), f"Report file not found at {REPORT_PATH}"

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    jsonschema.validate(instance=report, schema=schema)

    assert report["schema_version"] == "rig.provider_api_research.google_meta.v1"


def test_has_at_least_8_official_source_citations():
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    citations = report.get("citations", [])
    assert len(citations) >= 8, f"Expected >= 8 citations, got {len(citations)}"
    providers = {c["provider"] for c in citations}
    assert "google" in providers
    assert "ietf" in providers or "meta" in providers


def test_google_and_meta_sections_exist():
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    assert "google" in report
    assert "meta" in report

    google = report["google"]
    assert "oauth_setup" in google
    assert "scope_matrix" in google
    assert "endpoint_matrix" in google
    assert "verification_matrix" in google
    assert "domain_wide_delegation" in google
    assert "security_constraints" in google
    assert "recommended_rig_posture" in google

    meta = report["meta"]
    assert "app_setup" in meta
    assert "token_matrix" in meta
    assert "permission_matrix" in meta
    assert "endpoint_surface_matrix" in meta
    assert "app_review_matrix" in meta
    assert "webhook_security" in meta
    assert "whatsapp_constraints" in meta
    assert "recommended_rig_posture" in meta


def test_remote_mutation_is_false():
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    assert report["redaction_status"]["remote_mutation"] is False
    assert report["redaction_status"]["live_network_used_for_product"] is False


def test_recommended_posture_refuses_risky_surfaces():
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))

    google_posture = report["google"]["recommended_rig_posture"]
    meta_posture = report["meta"]["recommended_rig_posture"]

    assert len(google_posture["refused_surfaces"]) > 0
    assert len(meta_posture["refused_surfaces"]) > 0

    refused_text = json.dumps(meta_posture["refused_surfaces"]).lower()
    assert "publishing" in refused_text
    assert "message" in refused_text

    assert len(google_posture["safe_surfaces"]) > 0
    assert len(meta_posture["safe_surfaces"]) > 0


def test_no_forbidden_token_content_keys():
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    _assert_no_forbidden_keys(report)

    serialized = json.dumps(report, sort_keys=True)
    assert "EAA" not in serialized
    assert "ghp_" not in serialized
    assert "gho_" not in serialized
    assert "github_pat_" not in serialized
    assert "-----BEGIN" not in serialized


def test_cross_provider_recommendations_present():
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    cross = report["cross_provider_recommendations"]
    assert cross["google_risk_level"] in ("low", "medium", "high", "restricted")
    assert cross["meta_risk_level"] == "restricted"
    assert len(cross["safe_v1_live_read_candidates"]) > 0
    assert len(cross["deferred_lanes"]) > 0
    assert len(cross["required_future_schemas"]) > 0


def test_uncertainties_acknowledged():
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    uncertainties = report.get("uncertainties", [])
    assert len(uncertainties) > 0

    has_meta_doc = any(
        "meta" in u.lower() or "bot-blocking" in u.lower() for u in uncertainties
    )
    has_permission = any("permission" in u.lower() for u in uncertainties)
    assert has_meta_doc or has_permission


def test_source_count_consistent():
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    citations = report.get("citations", [])
    assert report["source_count"] == len(citations)
