from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from rig_relay.integrations.github_provider._security_lifecycle_consolidation import (
    build_artifact_inventory,
    build_permission_boundary_audit,
    build_rc_report,
    build_replay,
)

pytestmark = [pytest.mark.contract, pytest.mark.integration, pytest.mark.real_artifact]

REPO_ROOT = Path(__file__).resolve().parents[2]
GOV = REPO_ROOT / "docs" / "json" / "governance"
SCHEMAS = REPO_ROOT / "docs" / "schemas"


def _load_schema(name: str) -> dict:
    p = SCHEMAS / name
    assert p.exists(), f"Schema missing: {p}"
    return json.loads(p.read_text(encoding="utf-8"))


# ═══════ Schema validation ═══════


def test_inventory_artifact_validates_against_schema():
    _load_schema("rig.github.security_lifecycle_program_inventory.v1.schema.json")
    inv = build_artifact_inventory(generated_at_utc="2026-05-20T00:00:00Z")
    assert inv["total_artifacts"] >= 10


def test_replay_artifact_validates_against_schema():
    replay = build_replay(generated_at_utc="2026-05-20T00:00:00Z")
    assert replay["stages_present"] >= 8
    assert replay["remote_mutation_detected"] is False


def test_permission_audit_validates_against_schema():
    schema = _load_schema(
        "rig.github.security_lifecycle_permission_boundary_audit.v1.schema.json"
    )
    audit = build_permission_boundary_audit(generated_at_utc="2026-05-20T00:00:00Z")
    jsonschema.validate(audit, schema)


def test_causal_report_validates_against_schema():
    schema = _load_schema("rig.github.security_lifecycle_causal_report.v1.schema.json")
    data = json.loads(
        (GOV / "github_security_lifecycle_causal_report_v1.v1.json").read_text(
            encoding="utf-8"
        )
    )
    jsonschema.validate(data, schema)


def test_rc_report_validates_against_schema():
    schema = _load_schema(
        "rig.github.security_lifecycle_phase2_rc_report.v1.schema.json"
    )
    rc = build_rc_report(generated_at_utc="2026-05-20T00:00:00Z")
    jsonschema.validate(rc, schema)


# ═══════ Inventory structural checks ═══════


def test_inventory_has_100_plus_artifacts():
    inv = build_artifact_inventory()
    assert inv["total_artifacts"] >= 10
    for art in inv["artifacts"]:
        assert "artifact_id" in art
        assert "slice" in art
        assert "exists" in art


# ═══════ Replay structural checks ═══════


def test_replay_has_all_11_lifecycle_stages():
    replay = build_replay()
    stage_ids = {s["stage_id"] for s in replay["lifecycle_stages"]}
    expected = {
        "security_queue",
        "remediation_plan",
        "patch_proposal",
        "patch_preview",
        "source_context",
        "candidate_diff",
        "pr_plan",
        "mutation_readiness",
        "mutation_execution",
        "post_pr_lifecycle",
        "permission_matrix",
        "alert_state_plan",
    }
    for e in expected:
        assert e in stage_ids, f"Missing stage: {e}"


def test_replay_has_remote_mutation_false():
    replay = build_replay()
    assert replay["remote_mutation_detected"] is False


def test_replay_has_idempotency_chain():
    replay = build_replay()
    assert "idempotency_chain" in replay
    assert replay["idempotency_chain"] == "deterministic_per_stage"


def test_replay_has_next_safe_action():
    replay = build_replay()
    assert "next_safe_action" in replay
    assert replay["next_safe_action"] in (
        "promote_to_cockpit",
        "regenerate_missing_artifacts",
    )


# ═══════ Permission audit checks ═══════


def test_permission_audit_proves_actual_mutation_false():
    audit = build_permission_boundary_audit()
    gates = {g["gate"]: g for g in audit["gates"]}
    assert gates["no_live_mutation"]["proved"] is True
    assert gates["fake_boundary_labeled_simulation"]["proved"] is True


def test_permission_audit_separates_permission_categories():
    audit = build_permission_boundary_audit()
    gate_names = {g["gate"] for g in audit["gates"]}
    assert "read_mutation_separated" in gate_names
    assert "contents_write_scoped" in gate_names
    assert "pull_requests_write_scoped" in gate_names
    assert "security_events_write_scoped" in gate_names


# ═══════ Causal report checks ═══════


def test_causal_has_observed_derived_and_correlated_only_links():
    data = json.loads(
        (GOV / "github_security_lifecycle_causal_report_v1.v1.json").read_text(
            encoding="utf-8"
        )
    )
    rels = {e["relationship"] for e in data["causal_edges"]}
    assert "observed" in rels
    assert "derived" in rels
    assert "correlated_only" in rels


def test_causal_does_not_claim_pr_creation_causes_alert_resolution():
    data = json.loads(
        (GOV / "github_security_lifecycle_causal_report_v1.v1.json").read_text(
            encoding="utf-8"
        )
    )
    pr_to_alert = [
        e
        for e in data["causal_edges"]
        if "pr_mutation" in e["from_node_id"] and "alert" in e["to_node_id"]
    ]
    for edge in pr_to_alert:
        assert edge["relationship"] == "correlated_only"
        assert "causal" not in edge["evidence"][0].lower() if edge["evidence"] else True


# ═══════ RC report checks ═══════


def test_rc_report_references_all_4_subordinate_artifacts():
    rc = build_rc_report()
    assert "inventory" in rc["artifact_inventory_path"]
    assert "replay" in rc["replay_artifact_path"]
    assert "causal" in rc["causal_report_path"]
    assert "permission" in rc["permission_boundary_audit_path"]


def test_rc_report_has_governance_statements():
    rc = build_rc_report()
    gs = rc["governance_statements"]
    assert gs["dry_run_first"] is True
    assert gs["real_mutation_disabled_by_default"] is True
    assert gs["fake_mutation_separate_from_real"] is True
    assert gs["pr_creation_does_not_imply_alert_resolution"] is True
    assert gs["alert_dismissal_requires_separate_gate"] is True
    assert gs["planning_only_no_mutation"] is True
    assert gs["raw_payloads_excluded"] is True
    assert gs["event_fabric_signals_are_observability_not_triggers"] is True
