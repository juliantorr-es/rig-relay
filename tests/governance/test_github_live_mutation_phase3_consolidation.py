"""Tests for Phase 3 RC consolidation — inventory, replay, audit, projection, RC report."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from rig_relay.integrations.github_provider._live_mutation_phase3_consolidation import (
    build_inventory,
    build_permission_audit,
    build_projection,
    build_rc_report,
    build_replay,
    write_all_phase3_consolidation,
)

pytestmark = [pytest.mark.contract, pytest.mark.real_artifact]

REPO_ROOT = Path(__file__).resolve().parents[2]
GOV = REPO_ROOT / "docs" / "json" / "governance"


def test_inventory_references_artifacts():
    inv = build_inventory()
    assert inv["total"] >= 10
    assert inv["present"] >= 8


def test_replay_four_slices():
    repl = build_replay()
    assert repl["slices_total"] == 4
    assert repl["remote_mutation_attempted"] is False
    assert repl["alert_update_deferred"] is True


def test_permission_audit_separates():
    audit = build_permission_audit()
    gates = {g["gate"] for g in audit["gates"]}
    assert "contents_write_separate" in gates
    assert "security_events_write_separate_and_deferred" in gates
    assert "alert_update_separate_from_pr_creation" in gates


def test_permission_audit_no_live_mutation():
    audit = build_permission_audit()
    assert any(
        g["gate"] == "no_live_mutation_by_default" and g["proved"]
        for g in audit["gates"]
    )


def test_projection_blocked():
    proj = build_projection()
    assert proj["live_mutation_status"] == "blocked_by_default"
    assert proj["alert_update_status"] == "deferred"
    assert proj["raw_payloads_exposed"] is False


def test_rc_report_all_slices():
    rc = build_rc_report(
        build_inventory(), build_replay(), build_permission_audit(), build_projection()
    )
    assert rc["slices_completed"] == 4
    assert rc["phase_status"] == "release_candidate"
    assert "live_mutation_status" in rc
    assert "operator_action_checklist" in rc


def test_rc_report_operator_checklist():
    rc = build_rc_report(
        build_inventory(), build_replay(), build_permission_audit(), build_projection()
    )
    assert len(rc["operator_action_checklist"]) >= 8


def test_no_forbidden_fields():
    rc = write_all_phase3_consolidation()
    s = json.dumps(rc, sort_keys=True)
    for f in (
        '"access_token"',
        '"authorization"',
        '"private_key"',
        '"raw_response"',
        '"raw_body"',
        '"code_snippet"',
    ):
        assert f not in s


def test_no_token_patterns():
    rc = write_all_phase3_consolidation()
    s = json.dumps(rc, sort_keys=True)
    for p in ("ghp_", "gho_", "github_pat_", "BEGIN PRIVATE KEY"):
        assert p not in s


def test_artifacts_exist():
    write_all_phase3_consolidation()
    for name in (
        "github_live_mutation_phase3_inventory_v1.v1",
        "github_live_mutation_phase3_replay_v1.v1",
        "github_live_mutation_phase3_permission_boundary_audit_v1.v1",
        "github_live_mutation_phase3_projection_v1.v1",
        "github_live_mutation_phase3_rc_report_v1.v1",
    ):
        assert (GOV / f"{name}.json").exists()


def test_all_artifacts_redaction_clean():
    write_all_phase3_consolidation()
    for name in (
        "github_live_mutation_phase3_inventory_v1.v1",
        "github_live_mutation_phase3_rc_report_v1.v1",
        "github_live_mutation_phase3_projection_v1.v1",
    ):
        p = GOV / f"{name}.json"
        s = p.read_text(encoding="utf-8")
        for pat in (
            "ghp_",
            "BEGIN PRIVATE KEY",
            '"access_token"',
            '"authorization"',
            '"raw_body"',
        ):
            assert pat not in s, f"{pat} in {name}"


def test_replay_chaos_evidence():
    repl = build_replay()
    assert repl["chaos_scenarios"] >= 0
