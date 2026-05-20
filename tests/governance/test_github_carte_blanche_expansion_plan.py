"""Tests for carte blanche expansion plan + live write gates."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from rig_relay.integrations.github_provider._carte_blanche_expansion_plan import (
    _SURFACES,
    build_expansion_plan,
)
from rig_relay.integrations.github_provider._code_scanning_live_pr_rehearsal import (
    build_live_pr_rehearsal,
)

pytestmark = [pytest.mark.contract, pytest.mark.real_artifact]
REPO_ROOT = Path(__file__).resolve().parents[2]
GOV = REPO_ROOT / "docs" / "json" / "governance"


def test_expansion_plan_surfaces():
    p = build_expansion_plan(generated_at_utc="2026-05-20T00:00:00Z")
    assert p["surface_count"] >= 20
    assert p["mutation_lane_count"] >= 8


def test_expansion_plan_sequencing():
    p = build_expansion_plan()
    assert len(p["sequencing_plan"]) == 5


def test_expansion_plan_no_forbidden():
    p = build_expansion_plan()
    s = json.dumps(p, sort_keys=True)
    for f in (
        '"access_token"',
        '"authorization"',
        '"secret_value"',
        '"raw_response"',
        '"code_snippet"',
    ):
        assert f not in s


def test_surfaces_separate_read_write():
    for sf in _SURFACES:
        perms = sf.get("required_perms", {})
        assert "read" in perms or "mutation" in perms


def test_mutation_lanes_default_blocked_or_forbidden():
    for lane in build_expansion_plan()["mutation_lanes"]:
        assert lane["default_status"] in (
            "blocked",
            "forbidden",
            "deferred",
            "dry_run_only",
        )


def test_expansion_artifact_exists():
    assert (GOV / "github_carte_blanche_expansion_plan_v1.v1.json").exists()


def test_live_write_blocked_by_default():
    r = build_live_pr_rehearsal(generated_at_utc="2026-05-20T00:00:00Z")
    assert r["status"] == "rehearsal_blocked"
    assert r["alert_update_deferred"] is True


def test_live_write_gates():
    r = build_live_pr_rehearsal()
    blocked = {g["gate"] for g in r["gates"] if not g["passed"]}
    assert "allow_live_writes" in blocked
    assert "execute_flag" in blocked
    assert "operator_acknowledged" in blocked


def test_live_write_alerts_deferred():
    r = build_live_pr_rehearsal()
    assert r["alert_updated"] is False
    assert r["pr_merged"] is False


def test_expansion_plan_redaction_clean():
    p = GOV / "github_carte_blanche_expansion_plan_v1.v1.json"
    s = p.read_text(encoding="utf-8")
    for pat in (
        "ghp_",
        "BEGIN PRIVATE KEY",
        '"access_token"',
        '"authorization"',
        '"raw_body"',
    ):
        assert pat not in s
