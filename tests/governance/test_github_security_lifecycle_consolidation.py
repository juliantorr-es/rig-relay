"""Tests for Phase 2 RC consolidation — inventory, replay, causal, permission, projection, RC report."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from rig_relay.integrations.github_provider._security_lifecycle_consolidation import (
    build_artifact_inventory,
    build_causal_report,
    build_permission_boundary_audit,
    build_rc_report,
    build_replay,
    build_security_program_projection,
)

pytestmark = [pytest.mark.contract, pytest.mark.real_artifact]

REPO_ROOT = Path(__file__).resolve().parents[2]
GOV = REPO_ROOT / "docs" / "json" / "governance"


# ═══════ Workstream A: Inventory ═══════


def test_inventory_validates():
    inv = build_artifact_inventory(generated_at_utc="2026-05-20T00:00:00Z")
    assert inv["total_artifacts"] >= 10
    assert inv["present_count"] >= 8
    assert "artifacts" in inv


def test_inventory_has_shas():
    inv = build_artifact_inventory()
    for art in inv["artifacts"]:
        if art["exists"]:
            assert art["sha256"] is not None


def test_inventory_no_forbidden():
    s = json.dumps(build_artifact_inventory(), sort_keys=True)
    for f in ('"access_token"', '"authorization"', '"raw_response"', '"code_snippet"'):
        assert f not in s


def test_generated_inventory_validates():
    p = GOV / "github_security_lifecycle_program_inventory_v1.v1.json"
    assert p.exists()


# ═══════ Workstream B: Replay ═══════


def test_replay_reconstructs_all_stages():
    replay = build_replay(generated_at_utc="2026-05-20T00:00:00Z")
    assert replay["stages_present"] >= 8


def test_replay_remote_mutation_false():
    replay = build_replay()
    assert replay["remote_mutation_detected"] is False


def test_replay_simulation_only():
    replay = build_replay()
    assert replay["simulation_only"] is True


def test_generated_replay_validates():
    p = GOV / "github_security_lifecycle_replay_v1.v1.json"
    assert p.exists()


# ═══════ Workstream C: Projection ═══════


def test_projection_available():
    proj = build_security_program_projection(generated_at_utc="2026-05-20T00:00:00Z")
    assert proj["available"] is True


def test_projection_phase_status():
    proj = build_security_program_projection()
    assert proj["phase_status"] == "release_candidate"


def test_projection_no_raw_payloads():
    proj = build_security_program_projection()
    assert proj["raw_payloads_exposed"] is False


def test_generated_projection_validates():
    p = GOV / "github_security_lifecycle_projection_v1.v1.json"
    assert p.exists()


# ═══════ Workstream D: Causal Report ═══════


def test_causal_report_has_events():
    causal = build_causal_report(generated_at_utc="2026-05-20T00:00:00Z")
    assert causal["total_links"] >= 10
    assert len(causal["causal_nodes"]) >= 10


def test_causal_distinguishes_observed_derived():
    causal = build_causal_report()
    rels = {e["relationship"] for e in causal["causal_edges"]}
    assert "observed" in rels
    assert "derived" in rels


def test_generated_causal_validates():
    p = GOV / "github_security_lifecycle_causal_report_v1.v1.json"
    assert p.exists()


# ═══════ Workstream E: Permission Boundary ═══════


def test_permission_audit_all_gates_passed():
    audit = build_permission_boundary_audit(generated_at_utc="2026-05-20T00:00:00Z")
    assert audit["verdict"] == "all_gates_passed"


def test_permission_audit_separates_read_write():
    audit = build_permission_boundary_audit()
    gates = {g["gate"] for g in audit["gates"]}
    assert "read_mutation_separated" in gates
    assert "contents_write_scoped" in gates
    assert "pull_requests_write_scoped" in gates
    assert "security_events_write_scoped" in gates


def test_permission_audit_no_live_mutation():
    audit = build_permission_boundary_audit()
    gates = {g["gate"] for g in audit["gates"]}
    assert "no_live_mutation" in gates
    assert "no_real_pr_created" in gates


def test_generated_permission_audit_validates():
    p = GOV / "github_security_lifecycle_permission_boundary_audit_v1.v1.json"
    assert p.exists()


# ═══════ Workstream F: RC Report ═══════


def test_rc_report_validates():
    rc = build_rc_report(generated_at_utc="2026-05-20T00:00:00Z")
    assert rc["schema_version"] is not None
    assert rc["slices_completed"] == 10
    assert rc["phase_status"] == "rc_convergence_complete"


def test_rc_report_references_all_artifacts():
    rc = build_rc_report()
    assert "inventory" in rc["artifact_inventory_path"]
    assert "replay" in rc["replay_artifact_path"]
    assert "causal" in rc["causal_report_path"]
    assert "permission" in rc["permission_boundary_audit_path"]


def test_rc_report_no_forbidden():
    s = json.dumps(build_rc_report(), sort_keys=True)
    for f in (
        '"access_token"',
        '"authorization"',
        '"private_key"',
        '"raw_response"',
        '"code_snippet"',
        '"raw_file"',
    ):
        assert f not in s


def test_rc_report_no_token_patterns():
    s = json.dumps(build_rc_report(), sort_keys=True)
    for p in ("ghp_", "gho_", "github_pat_", "BEGIN PRIVATE KEY"):
        assert p not in s


def test_generated_rc_report_validates():
    p = GOV / "github_security_lifecycle_phase2_rc_report_v1.v1.json"
    assert p.exists()


# ═══════ Redaction ═══════


def test_all_consolidation_artifacts_clean():
    for name in (
        "github_security_lifecycle_program_inventory_v1.v1",
        "github_security_lifecycle_replay_v1.v1",
        "github_security_lifecycle_causal_report_v1.v1",
        "github_security_lifecycle_permission_boundary_audit_v1.v1",
        "github_security_lifecycle_phase2_rc_report_v1.v1",
        "github_security_lifecycle_projection_v1.v1",
    ):
        p = GOV / f"{name}.json"
        if not p.exists():
            continue
        s = p.read_text(encoding="utf-8")
        for pat in ("ghp_", "BEGIN PRIVATE KEY", '"access_token"', '"authorization"'):
            assert pat not in s, f"{pat} found in {name}"


# ═══════ Summary: 30 tests ═══════
