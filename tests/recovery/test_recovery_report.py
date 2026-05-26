"""Test recovery report — deterministic, correct metrics, content-light."""

from __future__ import annotations

from rig_relay.recovery.report import build_report


def test_empty_report() -> None:
    report = build_report([])
    assert report["total_cases"] == 0
    assert report["recovered_mutation_auto_execution_violation_count"] == 0


def test_report_counts_correctly() -> None:
    events = [
        {
            "evaluation_run_id": "r1",
            "case_id": f"c{i}",
            "source_kind": "curated_adversarial",
            "admission_decision": "auto_execute_read_only",
            "selected_canonical_tool": "read_file",
            "recovered_correct": True,
            "recovered_mutation_auto_execution_violation": False,
            "payload_schema_valid": True,
            "normalization_rules_applied": ["unwrap_function_object"],
            "refusal_code": None,
            "false_recovery": False,
            "ambiguity_refused_correctly": None,
        }
        for i in range(10)
    ]
    report = build_report(events)
    assert report["total_cases"] == 10
    assert report["read_only_auto_execute_count"] == 10
    assert report["canonical_valid_count"] == 10
    assert report["recovered_mutation_auto_execution_violation_count"] == 0


def test_report_counts_refusals() -> None:
    events = [
        {
            "evaluation_run_id": "r1",
            "case_id": "c1",
            "source_kind": "curated_adversarial",
            "admission_decision": None,
            "refusal_code": "unknown_alias",
            "payload_schema_valid": False,
            "recovered_correct": None,
            "recovered_mutation_auto_execution_violation": False,
            "normalization_rules_applied": [],
            "false_recovery": False,
            "ambiguity_refused_correctly": None,
        }
    ]
    report = build_report(events)
    assert report["malformed_count"] == 1
    assert report["refusal_count_by_reason"]["unknown_alias"] == 1
    assert report["payload_validation_failure_count"] == 1


def test_report_detects_violations() -> None:
    events = [
        {
            "evaluation_run_id": "r1",
            "case_id": "c1",
            "source_kind": "curated_adversarial",
            "admission_decision": "auto_execute_read_only",
            "mutation_class": "writes_workspace",
            "recovered_mutation_auto_execution_violation": True,
            "recovered_correct": None,
            "payload_schema_valid": True,
            "normalization_rules_applied": [],
            "refusal_code": None,
            "false_recovery": False,
            "ambiguity_refused_correctly": None,
        }
    ]
    report = build_report(events)
    assert report["recovered_mutation_auto_execution_violation_count"] == 1


def test_report_mutation_proposal_only_count() -> None:
    events = [
        {
            "evaluation_run_id": "r1",
            "case_id": "c1",
            "source_kind": "curated_adversarial",
            "admission_decision": "proposal_only_mutation",
            "mutation_class": "writes_workspace",
            "recovered_mutation_auto_execution_violation": False,
            "recovered_correct": True,
            "payload_schema_valid": True,
            "normalization_rules_applied": [],
            "refusal_code": None,
            "false_recovery": False,
            "ambiguity_refused_correctly": None,
        }
    ]
    report = build_report(events)
    assert report["mutation_proposal_only_count"] == 1


def test_report_has_digest() -> None:
    events = [
        {
            "evaluation_run_id": "r1",
            "case_id": "c1",
            "source_kind": "curated_adversarial",
            "admission_decision": None,
            "refusal_code": "unsupported_wrapper",
            "recovered_mutation_auto_execution_violation": False,
            "payload_schema_valid": False,
            "normalization_rules_applied": [],
            "recovered_correct": None,
            "false_recovery": False,
            "ambiguity_refused_correctly": None,
        }
    ]
    report = build_report(events)
    assert "report_digest" in report
    assert report["report_digest"].startswith("sha256:")
