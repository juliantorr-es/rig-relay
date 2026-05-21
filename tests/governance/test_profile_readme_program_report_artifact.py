"""Governance artifact test for Phase 1 Profile README program report."""

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
    / "rig.github.profile_readme_program_report.v1.schema.json"
)
REPORT_PATH = (
    REPO_ROOT
    / "docs"
    / "json"
    / "governance"
    / "profile_readme_program_report_v1.v1.json"
)


def test_schema_exists():
    assert SCHEMA_PATH.exists()


def test_report_validates_against_schema():
    assert SCHEMA_PATH.exists()
    assert REPORT_PATH.exists(), "Program report artifact not yet generated"

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    jsonschema.validate(instance=report, schema=schema)


def test_report_includes_all_five_slices():
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    slices = report["slices_completed"]
    assert len(slices) == 5
    slice_ids = {s["slice_id"] for s in slices}
    assert "phase1_slice1" in slice_ids
    assert "phase1_slice5" in slice_ids
    for s in slices:
        assert s["status"] == "complete"


def test_report_references_core_governance_artifacts():
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    gen_artifacts = report["generated_artifacts"]
    artifact_paths = {a["path"] for a in gen_artifacts}
    assert (
        "docs/json/governance/github_profile_readme_live_check_v1.v1.json"
        in artifact_paths
    )
    assert (
        "docs/json/governance/github_profile_readme_preview_v1.v1.json"
        in artifact_paths
    )
    assert (
        "docs/json/governance/github_publish_pr_permission_audit_v1.v1.json"
        in artifact_paths
    )
    assert (
        "docs/json/governance/github_profile_readme_pr_plan_v1.v1.json"
        in artifact_paths
    )
    assert ".build/rig-relay/previews/profile_readme_preview.md" in artifact_paths


def test_report_includes_preview_metadata():
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    preview = report["preview_generation_summary"]
    assert (
        preview["preview_sha256"]
        == "2913479f2209878fc0ca1a5f0d5091f601d869008f949c79d4818527127bdf45"
    )
    assert preview["preview_bytes"] == 1987
    assert preview["preview_line_count"] == 52
    assert preview["included_claim_count"] == 18
    assert preview["excluded_claim_count"] == 10


def test_report_includes_all_gates():
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    gates = report["gate_model"]["gates"]
    assert len(gates) == 9
    gate_names = {g.split(" — ")[0] for g in gates}
    assert "explicit_publish_flag" in gate_names
    assert "target_path_safe" in gate_names
    assert "workflows_not_required" in gate_names


def test_report_includes_planned_steps_with_permissions():
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    steps = report["pr_plan_summary"]["planned_steps"]
    assert len(steps) == 5
    operations = {s["operation"] for s in steps}
    assert "create_pull_request" in operations
    assert "write_file" in operations

    pr_step = next(s for s in steps if s["operation"] == "create_pull_request")
    assert pr_step["permission"] == "pull_requests:write"
    file_step = next(s for s in steps if s["operation"] == "write_file")
    assert file_step["permission"] == "contents:write"


def test_report_live_publish_deferred():
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    assert "unimplemented" in report["live_publish_status"]


def test_report_remote_mutation_disabled():
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    assert "disabled" in report["remote_mutation_status"]


def test_report_workflows_not_required():
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    not_required = report["permission_model"]["explicitly_not_required"]
    assert "workflows:write" in not_required
    assert "actions:write" in not_required


def test_report_includes_cockpit_widget_summary():
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    cockpit = report["cockpit_widgets"]
    assert len(cockpit) >= 1
    assert any("ProfileReadmeLane" in w for w in cockpit)


def test_report_passes_redaction_scan():
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    redaction = report["redaction_summary"]
    assert redaction["redaction_matches"] == 0


def test_report_no_forbidden_fields():
    serialized = REPORT_PATH.read_text(encoding="utf-8")
    report = json.loads(serialized)
    # Extract redaction patterns from the redaction_summary documentation to exclude them from scan
    redaction = report.get("redaction_summary", {})
    redaction.get("forbidden_patterns", "")
    # Only check for forbidden fields as JSON keys, not documentation strings
    forbidden_keys = [
        '"access_token"',
        '"authorization"',
        '"client_secret"',
        '"private_key"',
        '"raw_response"',
        '"raw_body"',
        '"bearer"',
    ]
    for key in forbidden_keys:
        assert key not in serialized, f"'{key}' found in report"


def test_report_phase_status_complete():
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    assert report["phase_status"] == "complete"


def test_report_recommends_phase_2():
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    assert report["recommended_next_phase"] == "phase_2 — Security Queue Manager"
