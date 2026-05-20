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
    / "rig.event_propagation_resource_allocation_audit.v1.schema.json"
)
REPORT_PATH = (
    REPO_ROOT
    / "docs"
    / "json"
    / "governance"
    / "event_propagation_resource_allocation_audit.v1.json"
)


def test_audit_artifact_validates_against_schema():
    assert SCHEMA_PATH.exists()
    assert REPORT_PATH.exists()

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))

    jsonschema.validate(instance=report, schema=schema)


def test_audit_has_required_sections():
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))

    required = [
        "audited_subsystems",
        "existing_event_like_surfaces",
        "resource_allocation_opportunities",
        "proposed_event_taxonomy",
        "proposed_control_loops",
        "event_command_boundary_findings",
        "frontend_bridge_backend_findings",
        "github_integration_findings",
        "test_release_gate_findings",
        "telemetry_redaction_findings",
        "anti_patterns",
        "recommended_v1_architecture",
        "spiderweb_ux_metaphor",
    ]
    for section in required:
        assert section in report, f"Missing section: {section}"


def test_audit_subsystems_have_required_fields():
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))

    for sub in report["audited_subsystems"]:
        assert "existing_mechanism" in sub
        assert "push_poll" in sub
        assert "gap" in sub


def test_control_loops_have_safety_gates():
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))

    for loop in report["proposed_control_loops"]:
        assert "input_events" in loop
        assert "decision" in loop
        assert "safety_gate" in loop
        assert "telemetry_implication" in loop
        assert "ux_visibility" in loop


def test_event_command_boundaries_are_explicit():
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))

    for finding in report["event_command_boundary_findings"]:
        assert "is_command" in finding
        assert "boundary_rule" in finding
        assert "event_type" in finding


def test_audit_is_content_light():
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))

    serialized = json.dumps(report, sort_keys=True)
    for forbidden in (
        "ghp_",
        "gho_",
        "ghu_",
        "ghs_",
        "github_pat_",
        "token_prefix",
        "access_token",
        "authorization",
        "raw_response",
        "raw_body",
        "BEGIN PRIVATE KEY",
    ):
        assert forbidden not in serialized


def test_event_taxonomy_has_required_properties():
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))

    taxonomy = report["proposed_event_taxonomy"]
    assert "categories" in taxonomy
    assert "envelope_spec" in taxonomy
    assert len(taxonomy["categories"]) >= 10


def test_spiderweb_ux_has_required_fields():
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))

    ux = report["spiderweb_ux_metaphor"]
    assert "metaphor" in ux
    assert "strand_states" in ux
    assert "ux_projections" in ux
    assert "derived_tension_rule" in ux


def test_v1_architecture_ducks_is_read_only():
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))

    arch = report["recommended_v1_architecture"]
    analytics = arch.get("transport", {}).get("analytics", "")
    assert "never mutation authority" in analytics or "read-side" in analytics
