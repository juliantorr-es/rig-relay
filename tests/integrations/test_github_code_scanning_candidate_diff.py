"""Tests for code scanning dry-run candidate diff — gated, real diff only with safe source."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from rig_relay.integrations.github_provider._code_scanning_candidate_diff import (
    _generate_unified_diff,
    _policy_gate_passes,
    build_code_scanning_candidate_diff,
)

pytestmark = [pytest.mark.contract, pytest.mark.real_artifact]

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = (
    REPO_ROOT
    / "docs"
    / "schemas"
    / "rig.github.code_scanning_dry_run_candidate_diff.v1.schema.json"
)


def _blocked_source_context() -> dict:
    return {
        "safe_context_available": False,
        "source_context_hash": None,
        "source_path": None,
    }


def _safe_source_context() -> dict:
    return {
        "safe_context_available": True,
        "source_context_hash": "abc123sourcehash",
        "source_path": "src/example.py",
        "source_before": "def foo():\n    unsafe_op()\n    return True\n",
        "source_after": "def foo():\n    safe_op()\n    return True\n",
    }


# ── Policy gate tests ──


def test_gate_passes_with_safe_context():
    ok, blocked = _policy_gate_passes(_safe_source_context(), 5)
    assert ok is True
    assert len(blocked) == 0


def test_gate_blocks_on_missing_context():
    ok, blocked = _policy_gate_passes({"safe_context_available": False}, 5)
    assert ok is False
    assert "safe_context_not_available" in blocked


def test_gate_blocks_on_missing_hash():
    ctx = _safe_source_context()
    ctx["source_context_hash"] = None
    ok, blocked = _policy_gate_passes(ctx, 5)
    assert ok is False
    assert "source_context_hash_missing" in blocked


def test_gate_blocks_on_missing_path():
    ctx = _safe_source_context()
    ctx["source_path"] = None
    ok, blocked = _policy_gate_passes(ctx, 5)
    assert ok is False
    assert "source_path_missing" in blocked


def test_gate_blocks_on_missing_alert():
    ok, blocked = _policy_gate_passes(_safe_source_context(), None)
    assert ok is False
    assert "alert_identity_missing" in blocked


# ── Blocked diff (default, no source context) ──


def test_blocked_diff_by_default(tmp_path):
    diff_path = tmp_path / "candidate.diff"
    report = build_code_scanning_candidate_diff(
        diff_path_override=diff_path,
        generated_at_utc="2026-05-20T00:00:00Z",
        source_context=_blocked_source_context(),
    )
    assert report["has_real_diff"] is False
    assert report["policy_gate_passed"] is False
    assert report["diff_classification"] == "blocked_explanation"
    assert report["raw_source_embedded_in_json"] is False
    assert report["remote_mutation"] is False
    assert report["local_mutation"] is False


def test_blocked_diff_validates_schema(tmp_path):
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    diff_path = tmp_path / "candidate.diff"
    report = build_code_scanning_candidate_diff(
        diff_path_override=diff_path,
        generated_at_utc="2026-05-20T00:00:00Z",
        source_context=_blocked_source_context(),
    )
    jsonschema.validate(instance=report, schema=schema)


def test_blocked_diff_writes_explanation_file(tmp_path):
    diff_path = tmp_path / "candidate.diff"
    build_code_scanning_candidate_diff(
        diff_path_override=diff_path, source_context=_blocked_source_context()
    )
    assert diff_path.exists()
    content = diff_path.read_text()
    assert "BLOCKED" in content
    assert "safe_context_not_available" in content


# ── Real diff (safe source context fixture) ──


def test_real_diff_generated_with_safe_context(tmp_path):
    diff_path = tmp_path / "candidate.diff"
    report = build_code_scanning_candidate_diff(
        diff_path_override=diff_path,
        generated_at_utc="2026-05-20T00:00:00Z",
        source_context=_safe_source_context(),
    )
    assert report["has_real_diff"] is True
    assert report["policy_gate_passed"] is True
    assert report["diff_classification"] == "dry_run_candidate_diff"
    assert report["diff_sha256"] is not None
    assert report["diff_bytes"] is not None
    assert report["diff_line_count"] is not None


def test_real_diff_validates_schema(tmp_path):
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    diff_path = tmp_path / "candidate.diff"
    report = build_code_scanning_candidate_diff(
        diff_path_override=diff_path,
        generated_at_utc="2026-05-20T00:00:00Z",
        source_context=_safe_source_context(),
    )
    jsonschema.validate(instance=report, schema=schema)


def test_real_diff_file_contains_diff(tmp_path):
    diff_path = tmp_path / "candidate.diff"
    build_code_scanning_candidate_diff(
        diff_path_override=diff_path, source_context=_safe_source_context()
    )
    content = diff_path.read_text()
    assert "unsafe_op" in content
    assert "safe_op" in content
    assert "--- a/src/example.py" in content
    assert "+++ b/src/example.py" in content


def test_real_diff_no_raw_source_in_json(tmp_path):
    diff_path = tmp_path / "candidate.diff"
    report = build_code_scanning_candidate_diff(
        diff_path_override=diff_path,
        generated_at_utc="2026-05-20T00:00:00Z",
        source_context=_safe_source_context(),
    )
    assert report["raw_source_embedded_in_json"] is False
    serialized = json.dumps(report, sort_keys=True)
    assert "unsafe_op" not in serialized
    assert "safe_op" not in serialized


def test_real_diff_no_mutation(tmp_path):
    diff_path = tmp_path / "candidate.diff"
    report = build_code_scanning_candidate_diff(
        diff_path_override=diff_path,
        generated_at_utc="2026-05-20T00:00:00Z",
        source_context=_safe_source_context(),
    )
    assert report["remote_mutation"] is False
    assert report["local_mutation"] is False
    assert report["pr_creation_status"] == "disabled"
    assert report["alert_update_status"] == "disabled"


def test_real_diff_no_forbidden_content(tmp_path):
    diff_path = tmp_path / "candidate.diff"
    report = build_code_scanning_candidate_diff(
        diff_path_override=diff_path,
        generated_at_utc="2026-05-20T00:00:00Z",
        source_context=_safe_source_context(),
    )
    serialized = json.dumps(report, sort_keys=True)
    for f in (
        '"access_token"',
        '"authorization"',
        '"private_key"',
        '"raw_response"',
        '"code_snippet"',
    ):
        assert f not in serialized


def test_real_diff_does_not_mutate_source(tmp_path):
    diff_path = tmp_path / "candidate.diff"
    build_code_scanning_candidate_diff(
        diff_path_override=diff_path, source_context=_safe_source_context()
    )
    report = build_code_scanning_candidate_diff(
        diff_path_override=diff_path, source_context=_safe_source_context()
    )
    assert report["remote_mutation"] is False


# ── Unified diff helper ──


def test_unified_diff_format():
    before = "line1\nline2\nline3\n"
    after = "line1\nline2_changed\nline3\n"
    result = _generate_unified_diff(before, after, "test.py")
    assert "--- a/test.py" in result
    assert "+++ b/test.py" in result
    assert "-line2" in result
    assert "+line2_changed" in result


# ── Generated artifact tests ──


def test_generated_artifact_validates():
    artifact_path = (
        REPO_ROOT
        / "docs"
        / "json"
        / "governance"
        / "code_scanning_dry_run_candidate_diff_v1.v1.json"
    )
    if not artifact_path.exists():
        pytest.skip("Artifact not yet generated")
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    report = json.loads(artifact_path.read_text(encoding="utf-8"))
    jsonschema.validate(instance=report, schema=schema)


def test_generated_artifact_no_forbidden():
    artifact_path = (
        REPO_ROOT
        / "docs"
        / "json"
        / "governance"
        / "code_scanning_dry_run_candidate_diff_v1.v1.json"
    )
    if not artifact_path.exists():
        pytest.skip("Artifact not yet generated")
    s = artifact_path.read_text(encoding="utf-8")
    for p in ("ghp_", "BEGIN PRIVATE KEY", '"access_token"', '"code_snippet"'):
        assert p not in s
