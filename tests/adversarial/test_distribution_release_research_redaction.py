"""Distribution release research redaction adversarial tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytestmark = [pytest.mark.adversarial]

REPO_ROOT = Path(__file__).resolve().parents[2]
ARTIFACT_DIR = REPO_ROOT / "docs" / "json" / "governance"

ARTIFACT_FILES = [
    "distribution_release_research_v1.v1.json",
    "distribution_release_channel_matrix_v1.v1.json",
    "distribution_release_credential_matrix_v1.v1.json",
    "distribution_release_api_matrix_v1.v1.json",
    "distribution_release_validation_matrix_v1.v1.json",
    "distribution_release_mutation_lane_matrix_v1.v1.json",
    "distribution_release_risk_register_v1.v1.json",
    "distribution_release_roadmap_v1.v1.json",
]

_FORBIDDEN_KEYS = frozenset({
    "private_key",
    "access_token",
    "api_key",
    "client_secret",
    "token",
    "service_account",
    "refresh_token",
    "bearer",
    "authorization",
    "raw_response",
    "raw_body",
    "package_body",
    "binary_body",
    "source_body",
    "patch",
    "diff",
    "contents",
    "code_snippet",
    "file_body",
    "auth_header",
    "app_specific_password",
    "issuer_id",
    "key_id",
})
_FORBIDDEN_PATTERNS = [
    "ghp_",
    "gho_",
    "ghu_",
    "ghs_",
    "ghr_",
    "github_pat_",
    "BEGIN PRIVATE KEY",
    "BEGIN CERTIFICATE",
]


def _assert_no_forbidden_keys(obj, path: str = "$"):
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key in _FORBIDDEN_KEYS:
                raise AssertionError(f"forbidden_key_found at {path}: {key}")
            _assert_no_forbidden_keys(value, f"{path}.{key}")
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            _assert_no_forbidden_keys(item, f"{path}[{i}]")


@pytest.mark.parametrize("artifact_file", ARTIFACT_FILES)
def test_artifact_no_forbidden_keys(artifact_file):
    path = ARTIFACT_DIR / artifact_file
    assert path.exists(), f"Missing: {artifact_file}"
    artifact = json.loads(path.read_text(encoding="utf-8"))
    _assert_no_forbidden_keys(artifact)


@pytest.mark.parametrize("artifact_file", ARTIFACT_FILES)
def test_artifact_no_forbidden_patterns(artifact_file):
    path = ARTIFACT_DIR / artifact_file
    serialized = json.dumps(
        json.loads(path.read_text(encoding="utf-8")), sort_keys=True
    )
    for pattern in _FORBIDDEN_PATTERNS:
        assert pattern not in serialized, (
            f"{artifact_file}: found forbidden pattern '{pattern}'"
        )


@pytest.mark.parametrize("artifact_file", ARTIFACT_FILES)
def test_artifact_content_light(artifact_file):
    path = ARTIFACT_DIR / artifact_file
    artifact = json.loads(path.read_text(encoding="utf-8"))
    assert artifact.get("content_light") is True, (
        f"{artifact_file}: content_light not True"
    )
    assert artifact.get("remote_mutation") is False, (
        f"{artifact_file}: remote_mutation not False"
    )


@pytest.mark.parametrize("artifact_file", ARTIFACT_FILES)
def test_artifact_no_live_network(artifact_file):
    path = ARTIFACT_DIR / artifact_file
    artifact = json.loads(path.read_text(encoding="utf-8"))
    assert artifact.get("live_network_used_for_product") is False, (
        f"{artifact_file}: live_network not False"
    )


def test_mutation_matrix_has_no_publishing_executed():
    path = ARTIFACT_DIR / "distribution_release_mutation_lane_matrix_v1.v1.json"
    mm = json.loads(path.read_text(encoding="utf-8"))
    assert mm["remote_mutation_performed"] is False
