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
    / "rig.github.evidence_backed_claims_index.v1.schema.json"
)
REPORT_PATH = (
    REPO_ROOT
    / "docs"
    / "json"
    / "governance"
    / "github_evidence_backed_claims_index_v1.v1.json"
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


def test_claims_index_artifact_validates_against_schema():
    assert SCHEMA_PATH.exists(), f"Schema file not found at {SCHEMA_PATH}"
    assert REPORT_PATH.exists(), f"Report file not found at {REPORT_PATH}"

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))

    jsonschema.validate(instance=report, schema=schema)


def test_claims_index_artifact_is_content_light():
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))

    assert not _has_forbidden_key(report)

    serialized = json.dumps(report, sort_keys=True)
    for token_pattern in ("ghp_", "gho_", "ghu_", "ghs_", "github_pat_"):
        assert token_pattern not in serialized


def test_claims_index_artifact_has_correct_metadata():
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))

    assert report["schema_version"] == "rig.github.evidence_backed_claims_index.v1"
    assert report["content_light"] is True
    assert report["remote_mutation"] is False
    assert report["local_mutation"] is False
    assert isinstance(report["claims"], list)
    assert isinstance(report["summary"], dict)
    assert len(report["claims"]) > 0
