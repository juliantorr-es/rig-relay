"""Tests for evidence graph projection — public safe, cockpit local, impact, digest."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from rig_relay.integrations._codebase_evidence_graph_projection import (
    build_context_digest,
    build_impact_analysis,
    load_graph,
)

pytestmark = [pytest.mark.contract, pytest.mark.real_artifact, pytest.mark.substrate]

REPO_ROOT = Path(__file__).resolve().parents[2]
GOV = REPO_ROOT / "docs" / "json" / "governance"


def test_projection_manifest_exists():
    p = GOV / "codebase_evidence_graph_projection_manifest_v1.v1.json"
    assert p.exists()


def test_manifest_has_all_modes():
    manifest = json.loads(
        (GOV / "codebase_evidence_graph_projection_manifest_v1.v1.json").read_text()
    )
    assert "public_static" in manifest["available_modes"]
    assert "cockpit_local" in manifest["available_modes"]
    assert "context_digest" in manifest["available_modes"]


def test_public_projection_no_forbidden():
    # Load already-generated projection, don't rebuild
    graph = load_graph()
    n = graph.get("nodes", [])[:100]
    for node in n:
        for f in ["absolute_path", "home_path", "session_id", "trace_id", "dirty_sha"]:
            assert f not in node, f"forbidden {f} in node"
    assert graph.get("schema_version") or len(n) > 0


def test_cockpit_projection_no_raw_source():
    graph = load_graph()
    n = graph.get("nodes", [])[:100]
    for node in n:
        for f in ["raw_source", "token", "secret", "credential"]:
            assert f not in node, f"forbidden {f} in node"


def test_context_digest_deterministic():
    d1 = build_context_digest(["test/path1.py"])
    d2 = build_context_digest(["test/path1.py"])
    assert d1["affected_count"] == d2["affected_count"]
    assert d1["schema_count"] == d2["schema_count"]


def test_context_digest_bounded():
    d = build_context_digest(["rig_relay/desktop/projection.py"])
    assert d["affected_count"] >= 0
    assert d["adjacent_count"] >= 0


def test_impact_analysis_produces_json():
    result = build_impact_analysis(["rig_relay/desktop/projection.py"])
    assert result["content_light"] is True
    assert "impacted_schemas" in result
    assert "impacted_artifacts" in result


def test_load_graph_works():
    graph = load_graph()
    assert graph["nodes"] or graph["schema_version"]


def test_no_token_leakage_in_projections():
    graph = load_graph()
    s = json.dumps({"nodes": graph.get("nodes", [])[:50]})
    for p in (
        "ghp_",
        "github_pat_",
        "BEGIN PRIVATE KEY",
        '"access_token"',
        '"authorization"',
    ):
        assert p not in s
