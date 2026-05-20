from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from rig_relay.integrations.github_provider._claims_index import (
    build_github_claims_index,
)

pytestmark = [pytest.mark.contract, pytest.mark.integration]

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = (
    REPO_ROOT
    / "docs"
    / "schemas"
    / "rig.github.evidence_backed_claims_index.v1.schema.json"
)

_FORBIDDEN_KEYS = frozenset({
    "token_prefix",
    "access_token",
    "authorization",
    "raw_response",
    "raw_body",
    "code_snippet",
    "patch",
    "diff",
    "contents",
    "secret",
})


def _has_forbidden_key(obj: object) -> bool:
    if isinstance(obj, dict):
        for key in obj:
            if key in _FORBIDDEN_KEYS:
                return True
            if _has_forbidden_key(obj[key]):
                return True
    elif isinstance(obj, list):
        for item in obj:
            if _has_forbidden_key(item):
                return True
    return False


def test_claims_index_has_valid_schema_version():
    result = build_github_claims_index()

    assert result["schema_version"] == "rig.github.evidence_backed_claims_index.v1"
    assert result["content_light"] is True
    assert result["remote_mutation"] is False
    assert result["local_mutation"] is False


def test_claims_index_validates_against_schema():
    result = build_github_claims_index()

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.validate(instance=result, schema=schema)


def test_claims_index_is_content_light():
    result = build_github_claims_index()

    assert not _has_forbidden_key(result)

    serialized = json.dumps(result, sort_keys=True)
    for token_pattern in ("ghp_", "gho_", "ghu_", "ghs_", "github_pat_"):
        assert token_pattern not in serialized


def test_claims_are_deterministically_ordered():
    result = build_github_claims_index()
    claims = result["claims"]
    claim_ids = [c["claim_id"] for c in claims]
    assert claim_ids == sorted(claim_ids)


def test_each_claim_has_required_fields():
    result = build_github_claims_index()
    claims = result["claims"]
    assert len(claims) > 0

    for claim in claims:
        assert len(claim["claim_id"]) == 64
        assert claim["claim_category"] in (
            "functionality_claim",
            "security_claim",
            "release_readiness_claim",
            "platform_support_claim",
            "test_coverage_claim",
            "documentation_claim",
            "installation_claim",
            "performance_claim",
            "stability_claim",
            "integration_claim",
            "governance_claim",
            "telemetry_privacy_claim",
            "unknown_claim",
        )
        assert claim["support_status"] in (
            "supported",
            "partially_supported",
            "unsupported",
            "contradicted",
            "unknown",
        )
        assert claim["confidence"] in ("high", "medium", "low")
        assert claim["public_wording_risk"] in ("high", "medium", "low")
        assert claim["suggested_action"] in (
            "keep",
            "caveat",
            "downgrade",
            "remove",
            "request_human_review",
        )
        assert isinstance(claim["human_review_required"], bool)
        assert claim["local_mutation"] is False
        assert claim["remote_mutation"] is False
        assert isinstance(claim["remaining_seams"], list)
        assert isinstance(claim["evidence_refs"], list)
        assert len(claim["normalized_claim_summary"]) > 0
        assert len(claim["source_surface_ref"]) > 0


def test_claims_index_has_summary():
    result = build_github_claims_index()

    summary = result["summary"]
    assert isinstance(summary, dict)
    assert "total_claims" in summary
    assert "supported_count" in summary
    assert "unsupported_count" in summary
    assert "partially_supported_count" in summary
    assert "contradicted_count" in summary
    assert "unknown_count" in summary
    assert "next_recommended_action" in summary

    assert summary["total_claims"] == len(result["claims"])
    total = (
        summary["supported_count"]
        + summary["unsupported_count"]
        + summary["partially_supported_count"]
        + summary["contradicted_count"]
        + summary["unknown_count"]
    )
    assert total == summary["total_claims"]


def test_claims_index_has_source_hashes():
    result = build_github_claims_index()

    assert "source_operating_picture_hash" in result
    assert "source_surface_audit_hash" in result
    assert "source_operating_picture_path" in result
    assert "source_surface_audit_path" in result


def test_release_readiness_claim_is_contradicted():
    result = build_github_claims_index()
    claims = result["claims"]

    rc_claims = [c for c in claims if c["claim_category"] == "release_readiness_claim"]
    assert len(rc_claims) > 0
    for claim in rc_claims:
        if (
            "alpha" in claim["normalized_claim_summary"]
            or "HOLD" in claim["normalized_claim_summary"]
        ):
            assert claim["support_status"] == "contradicted"
            assert claim["human_review_required"] is True


def test_claims_index_has_validation_commands():
    result = build_github_claims_index()

    assert isinstance(result["validation_commands"], list)
    assert len(result["validation_commands"]) >= 2
    for cmd in result["validation_commands"]:
        assert "pytest" in cmd or "rig_relay_validate_schemas" in cmd
