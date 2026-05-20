"""Adversarial redaction tests for GitHub carte blanche research."""

from __future__ import annotations

import pytest

pytestmark = [pytest.mark.contract, pytest.mark.adversarial]


def test_research_artifacts_are_content_light():
    from scripts.rig_github_carte_blanche_research import _assert_content_light

    # should not raise for clean data
    clean = {"schema_version": "test.v1", "summary": "research content", "counts": 42}
    _assert_content_light(clean)


def test_rejects_access_token():
    from scripts.rig_github_carte_blanche_research import _assert_content_light

    with pytest.raises(ValueError):
        _assert_content_light({"access_token": "ghp_secret"})


def test_rejects_private_key():
    from scripts.rig_github_carte_blanche_research import _assert_content_light

    with pytest.raises(ValueError):
        _assert_content_light({"private_key": "-----BEGIN PRIVATE KEY-----"})


def test_rejects_raw_body():
    from scripts.rig_github_carte_blanche_research import _assert_content_light

    with pytest.raises(ValueError):
        _assert_content_light({"raw_body": "some api response"})


def test_rejects_patch():
    from scripts.rig_github_carte_blanche_research import _assert_content_light

    with pytest.raises(ValueError):
        _assert_content_light({"patch": "diff content"})


def test_rejects_diff():
    from scripts.rig_github_carte_blanche_research import _assert_content_light

    with pytest.raises(ValueError):
        _assert_content_light({"diff": "diff content"})


def test_rejects_code_snippet():
    from scripts.rig_github_carte_blanche_research import _assert_content_light

    with pytest.raises(ValueError):
        _assert_content_light({"code_snippet": "vulnerable code"})


def test_rejects_contents():
    from scripts.rig_github_carte_blanche_research import _assert_content_light

    with pytest.raises(ValueError):
        _assert_content_light({"contents": "file contents"})


def test_rejects_token_pattern_in_string():
    from scripts.rig_github_carte_blanche_research import _assert_content_light

    with pytest.raises(ValueError):
        _assert_content_light({"note": "token: ghp_secret_value"})


def test_rejects_begin_private_key_in_string():
    from scripts.rig_github_carte_blanche_research import _assert_content_light

    with pytest.raises(ValueError):
        _assert_content_light({"note": "key: -----BEGIN PRIVATE KEY-----"})


def test_rejects_nested_forbidden_key():
    from scripts.rig_github_carte_blanche_research import _assert_content_light

    with pytest.raises(ValueError) as exc:
        _assert_content_light({"outer": {"inner": {"access_token": "ghp_nested"}}})
    assert "forbidden_key" in str(exc.value)


def test_generated_artifacts_project_contains_no_token_strings():
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[2]
    artifact_dir = repo_root / "docs" / "json" / "governance"

    for af in [
        "github_carte_blanche_research_v1.v1.json",
        "github_carte_blanche_permission_value_matrix_v1.v1.json",
        "github_carte_blanche_surface_lane_matrix_v1.v1.json",
        "github_carte_blanche_endpoint_matrix_v1.v1.json",
        "github_carte_blanche_webhook_matrix_v1.v1.json",
        "github_carte_blanche_mutation_lanes_v1.v1.json",
        "github_carte_blanche_risk_register_v1.v1.json",
        "github_carte_blanche_product_roadmap_v1.v1.json",
    ]:
        artifact_path = artifact_dir / af
        if not artifact_path.exists():
            continue
        serialized = artifact_path.read_text(encoding="utf-8")
        for pattern in (
            "ghp_",
            "gho_",
            "ghu_",
            "ghs_",
            "ghr_",
            "github_pat_",
            "ya29.",
            "1//",
            "BEGIN PRIVATE KEY",
        ):
            assert pattern not in serialized, f"Pattern '{pattern}' found in {af}"
