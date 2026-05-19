from __future__ import annotations

import json
from pathlib import Path

import pytest

pytestmark = [pytest.mark.contract, pytest.mark.real_artifact, pytest.mark.adversarial]

from jsonschema import validate

_ARTIFACT_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "docs"
    / "json"
    / "governance"
    / "cross_surface_v1_convergence_review.v1.json"
)
_SCHEMA_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "docs"
    / "schemas"
    / "rig.relay.cross_surface_v1_convergence_review.v1.schema.json"
)


def _artifact() -> dict:
    return json.loads(_ARTIFACT_PATH.read_text(encoding="utf-8"))


def _schema() -> dict:
    return json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))


# ── Schema validation ─────────────────────────────────────────────────


def test_schema_parses_as_json() -> None:
    assert _schema() is not None


def test_artifact_parses_as_json() -> None:
    assert _artifact() is not None


def test_artifact_validates_against_schema() -> None:
    validate(instance=_artifact(), schema=_schema())


# ── Surface coverage ───────────────────────────────────────────────────


def test_nine_surfaces_reviewed() -> None:
    assert len(_artifact()["surfaces_reviewed"]) == 9


def test_every_surface_has_source_artifacts() -> None:
    for surface in _artifact()["surfaces_reviewed"]:
        assert len(surface["source_artifacts"]) > 0, (
            f"Surface {surface['surface_id']} has no source artifacts"
        )


# ── Matrix completeness ────────────────────────────────────────────────


def test_traceability_matrix_has_rows() -> None:
    assert len(_artifact()["traceability_matrix"]) >= 15


def test_refusal_equivalence_matrix_has_rows() -> None:
    assert len(_artifact()["refusal_equivalence_matrix"]) >= 10


def test_receipt_vocabulary_matrix_has_rows() -> None:
    assert len(_artifact()["receipt_vocabulary_matrix"]) >= 10


def test_honest_deferral_matrix_has_rows() -> None:
    assert len(_artifact()["honest_deferral_matrix"]) >= 12


def test_seam_index_has_rows() -> None:
    assert len(_artifact()["seam_index"]) >= 8


def test_supported_claims_have_rows() -> None:
    assert len(_artifact()["release_paper_claims_supported"]) >= 8


def test_rejected_claims_have_rows() -> None:
    assert len(_artifact()["release_paper_claims_rejected"]) >= 10


def test_fake_green_attack_matrix_has_rows() -> None:
    assert len(_artifact()["fake_green_attack_matrix"]) >= 6


def test_proposed_cross_surface_tests_have_rows() -> None:
    assert len(_artifact()["proposed_cross_surface_tests"]) >= 8


# ── Seam classification ────────────────────────────────────────────────


def test_every_seam_has_release_classification() -> None:
    for seam in _artifact()["seam_index"]:
        assert seam["release_classification"] in {
            "release_blocker",
            "alpha_blocker",
            "v1_1_hardening",
            "future_slice",
            "out_of_scope",
        }, f"Seam {seam['seam_id']} has invalid release_classification"


def test_no_release_blockers_in_seam_index() -> None:
    for seam in _artifact()["seam_index"]:
        assert seam["release_classification"] != "release_blocker", (
            f"Seam {seam['seam_id']} is classified as release_blocker — must be gated"
        )


# ── Claims ─────────────────────────────────────────────────────────────


def test_every_supported_claim_has_support_level() -> None:
    for claim in _artifact()["release_paper_claims_supported"]:
        assert claim["support_level"] in {
            "strongly_supported",
            "supported_with_limitations",
            "speculative",
            "unsupported",
            "dishonest",
        }
        assert claim.get("required_caveats")


def test_every_rejected_claim_has_why_dishonest() -> None:
    for claim in _artifact()["release_paper_claims_rejected"]:
        assert len(claim["why_dishonest"]) > 0


# ── Proposed cross-surface tests ───────────────────────────────────────


_REQUIRED_PROPOSED_TESTS = {
    "bridge_to_sdk_to_mcp_refusal_trace_roundtrip",
    "sdk_to_a2a_task_delegation_receipt_trace_roundtrip",
    "provider_refusal_equivalence_github_google_sdk",
    "tool_runtime_refusal_receipt_joinable_with_otel_event",
    "compiler_counterexample_joinable_with_coordination_seam_event",
    "bash_reroute_receipt_joinable_with_agent_execution_trace",
    "acp_session_prompt_refusal_content_light_trace_roundtrip",
    "ci_evidence_indexes_cross_surface_readiness_artifacts",
}


def test_all_eight_required_proposed_tests_present() -> None:
    names = {t["test_name"] for t in _artifact()["proposed_cross_surface_tests"]}
    assert _REQUIRED_PROPOSED_TESTS.issubset(names), (
        f"Missing proposed tests: {_REQUIRED_PROPOSED_TESTS - names}"
    )


# ── RC recommendation ─────────────────────────────────────────────────


def test_rc_recommendation_is_valid() -> None:
    assert _artifact()["rc_recommendation"] in {
        "promote",
        "promote_with_v1_1_hardening",
        "hold",
        "reject",
    }


# ── Content-light enforcement ──────────────────────────────────────────


def test_artifact_no_forbidden_field_names() -> None:
    raw = json.dumps(_artifact())
    forbidden = [
        "ghp_",
        "gho_",
        "ghu_",
        "ghs_",
        "ghr_",
        "github_pat_",
        "sk-",
        "api_key",
        "client_secret",
        "private_key",
        "access_token",
    ]
    for fb in forbidden:
        assert fb not in raw, f"Forbidden token pattern '{fb}' found in artifact"


def test_artifact_has_redaction_status_content_light() -> None:
    assert _artifact()["redaction_status"] == "content_light"


# ── Referenced file paths exist ────────────────────────────────────────


def test_all_surface_source_artifact_paths_exist() -> None:
    repo_root = Path(__file__).resolve().parent.parent.parent
    for surface in _artifact()["surfaces_reviewed"]:
        for art_path in surface["source_artifacts"]:
            if "/" in art_path and not art_path.endswith("/"):
                full_path = repo_root / art_path
                assert full_path.exists(), (
                    f"Source artifact {art_path} for surface "
                    f"{surface['surface_id']} does not exist"
                )


# ── No Markdown report created ─────────────────────────────────────────


def test_no_markdown_report_created() -> None:
    md_paths = list(
        Path(__file__)
        .resolve()
        .parent.parent.parent.glob("docs/json/governance/cross_surface*.md")
    )
    assert len(md_paths) == 0, (
        "Markdown report found — JSON is the canonical evidence container"
    )


# ── Deferral classification coverage ──────────────────────────────────


def test_at_least_one_alpha_blocker_classified() -> None:
    blockers = [
        d
        for d in _artifact()["honest_deferral_matrix"]
        if d["classified_as"] == "alpha_blocker"
    ]
    assert len(blockers) >= 1, "Must classify at least one alpha blocker"


def test_at_least_one_v1_1_hardening_classified() -> None:
    hardening = [
        d
        for d in _artifact()["honest_deferral_matrix"]
        if d["classified_as"] == "v1_1_hardening"
    ]
    assert len(hardening) >= 3, "Must classify at least 3 v1.1 hardening deferrals"


# ── Repository state recorded ──────────────────────────────────────────


def test_repo_head_recorded() -> None:
    assert len(_artifact()["repo_head"]) == 40


def test_schemas_validated_recorded() -> None:
    assert _artifact()["schemas_validated"] > 200
