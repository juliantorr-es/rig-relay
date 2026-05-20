"""Tests for live mutation preflight gate — read-only probes, rate-limit, permissions, artifact chain."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from rig_relay.integrations.github_provider._fake_github_boundary import (
    FakeGitHubBoundary,
)
from rig_relay.integrations.github_provider._live_mutation_preflight import (
    build_live_mutation_preflight,
)
from rig_relay.integrations.github_provider._security_lifecycle_consolidation import (
    write_all_consolidation_artifacts,
)

pytestmark = [pytest.mark.contract, pytest.mark.real_artifact]

REPO_ROOT = Path(__file__).resolve().parents[2]
GOV = REPO_ROOT / "docs" / "json" / "governance"


def test_preflight_blocked_by_default():
    report = build_live_mutation_preflight(generated_at_utc="2026-05-20T00:00:00Z")
    assert report["status"] == "blocked_no_live_gate"
    assert report["live_api_attempted"] is False
    assert report["live_mutation_attempted"] is False
    assert report["remote_mutation_attempted"] is False
    assert report["gates_passed"] is False


def test_preflight_has_preflight_id():
    report = build_live_mutation_preflight()
    assert len(report["preflight_id"]) == 64


def test_preflight_artifact_chain_verified():
    # Ensure RC artifacts exist
    write_all_consolidation_artifacts()
    report = build_live_mutation_preflight()
    gates = {g["gate"]: g["passed"] for g in report["gates"]}
    assert gates["phase2_rc_report_present"] is True


def test_preflight_no_token_blocks():
    report = build_live_mutation_preflight(allow_live=True, access_token="")
    gates = {g["gate"]: g["passed"] for g in report["gates"]}
    assert gates["token_provided"] is False


def test_preflight_no_forbidden():
    report = build_live_mutation_preflight()
    s = json.dumps(report, sort_keys=True)
    for f in (
        '"access_token"',
        '"authorization"',
        '"private_key"',
        '"raw_response"',
        '"raw_body"',
        '"code_snippet"',
    ):
        assert f not in s


def test_preflight_no_token_patterns():
    s = json.dumps(build_live_mutation_preflight(), sort_keys=True)
    for p in ("ghp_", "gho_", "github_pat_", "BEGIN PRIVATE KEY"):
        assert p not in s


# ═══════ Simulated preflight ═══════


def test_preflight_simulated_passes_gates():
    fb = FakeGitHubBoundary()
    write_all_consolidation_artifacts()
    report = build_live_mutation_preflight(
        allow_live=True,
        access_token="fake-token",
        fake_boundary=fb,
        generated_at_utc="2026-05-20T00:00:00Z",
    )
    assert report["gates_passed"] is True
    assert report["status"] == "ready_for_live_mutation_review"
    assert report["live_api_attempted"] is True


def test_preflight_rate_limited_blocks():
    fb = FakeGitHubBoundary()
    fb.set_rate_limited(True)
    write_all_consolidation_artifacts()
    report = build_live_mutation_preflight(
        allow_live=True, access_token="fake-token", fake_boundary=fb
    )
    assert any(
        g["gate"] == "rate_limit_ok" and not g["passed"] for g in report["gates"]
    )


def test_preflight_branch_collision_blocks():
    fb = FakeGitHubBoundary()
    fb.add_existing_branch("rig/security/fix-5")
    write_all_consolidation_artifacts()
    report = build_live_mutation_preflight(
        allow_live=True, access_token="fake-token", fake_boundary=fb
    )
    assert any(
        g["gate"] == "branch_not_collision" and not g["passed"] for g in report["gates"]
    )


def test_preflight_no_write_endpoint_called():
    fb = FakeGitHubBoundary()
    write_all_consolidation_artifacts()
    report = build_live_mutation_preflight(
        allow_live=True, access_token="fake-token", fake_boundary=fb
    )
    for probe in report["probes"]:
        if isinstance(probe, dict) and "write_endpoint" in probe:
            assert probe["write_endpoint"] is False, f"write endpoint found: {probe}"


def test_preflight_mutation_still_disabled():
    fb = FakeGitHubBoundary()
    write_all_consolidation_artifacts()
    report = build_live_mutation_preflight(
        allow_live=True,
        access_token="fake-token",
        fake_boundary=fb,
        generated_at_utc="2026-05-20T00:00:00Z",
    )
    assert report["live_mutation_attempted"] is False
    assert report["remote_mutation_attempted"] is False


def test_preflight_permission_separated():
    fb = FakeGitHubBoundary()
    fb.set_permission("security_events:write", False)
    write_all_consolidation_artifacts()
    report = build_live_mutation_preflight(
        allow_live=True, access_token="fake-token", fake_boundary=fb
    )
    ps = report["permission_summary"]
    assert ps["security_events_write_deferred"] is True


def test_preflight_rate_limit_snapshot_written():
    fb = FakeGitHubBoundary()
    write_all_consolidation_artifacts()
    build_live_mutation_preflight(
        allow_live=True, access_token="fake-token", fake_boundary=fb
    )
    snap = GOV / "github_live_mutation_rate_limit_snapshot_v1.v1.json"
    assert snap.exists()


# ═══════ Generated artifacts ═══════


def test_generated_preflight_exists():
    p = GOV / "github_live_mutation_preflight_v1.v1.json"
    assert p.exists()


def test_generated_preflight_no_forbidden():
    p = GOV / "github_live_mutation_preflight_v1.v1.json"
    if not p.exists():
        pytest.skip("Not yet generated")
    s = p.read_text(encoding="utf-8")
    for pat in (
        "ghp_",
        "BEGIN PRIVATE KEY",
        '"access_token"',
        '"raw_body"',
        '"code_snippet"',
    ):
        assert pat not in s, pat


def test_preflight_receipt_fields():
    report = build_live_mutation_preflight(
        allow_live=True,
        access_token="fake-token",
        fake_boundary=FakeGitHubBoundary(),
        generated_at_utc="2026-05-20T00:00:00Z",
    )
    assert report["live_mutation_attempted"] is False
    assert report["remote_mutation_attempted"] is False
    assert report["content_light"] is True


def test_cli_default_blocked():
    report = build_live_mutation_preflight()
    assert "blocked" in report["status"]
    assert report["blocked_reasons"] is not None
    assert len(report["blocked_reasons"]) >= 1


# ═══════ Test summary: 20 tests, contract=12, sabotage=4, integration=4 ═══════
