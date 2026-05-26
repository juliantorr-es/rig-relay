"""Recovery reliability report from evaluation evidence JSONL.

Deterministic, content-light report computation.
"""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
from typing import Any


def build_report(
    events: list[dict[str, Any]], report_id: str | None = None
) -> dict[str, Any]:
    """Build a recovery reliability report from evaluation events."""
    if not events:
        empty_report: dict[str, Any] = {
            "schema_version": "rig.relay.tool_recovery_evaluation_report.v1",
            "report_id": report_id or f"rpt_{datetime.now(UTC).isoformat()}",
            "created_at": datetime.now(UTC).isoformat(),
            "total_cases": 0,
            "recovered_mutation_auto_execution_violation_count": 0,
        }
        return empty_report

    total = len(events)

    source_kinds = Counter(e.get("source_kind", "") for e in events)
    admission_decisions = Counter(e.get("admission_decision", "none") for e in events)
    refusal_codes = Counter(e.get("refusal_code", "none") for e in events)
    norm_rules = Counter(
        r for e in events for r in e.get("normalization_rules_applied", [])
    )
    tools_selected = Counter(e.get("selected_canonical_tool", "none") for e in events)

    canonical_valid = sum(1 for e in events if not e.get("refusal_code"))
    malformed = total - canonical_valid
    uniquely_recovered = sum(
        1
        for e in events
        if e.get("recovered_correct") is True and not e.get("refusal_code")
    )
    false_recovery = sum(1 for e in events if e.get("false_recovery") is True)
    ambiguity_correct = sum(
        1 for e in events if e.get("ambiguity_refused_correctly") is True
    )
    mutation_violations = sum(
        1 for e in events if e.get("recovered_mutation_auto_execution_violation")
    )
    payload_failures = sum(1 for e in events if not e.get("payload_schema_valid", True))

    recovery_total = sum(1 for e in events if e.get("recovery_correct") is not None)
    false_recovery_rate = false_recovery / recovery_total if recovery_total > 0 else 0.0

    read_only_auto = admission_decisions.get("auto_execute_read_only", 0)
    validation_auto = admission_decisions.get("auto_execute_validation", 0)
    proposal_only = admission_decisions.get("proposal_only_mutation", 0)
    ext_side_refused = admission_decisions.get("require_remote_authorization", 0)
    raw_shell_refused = admission_decisions.get("refuse_raw_shell", 0)
    ambiguity_refused = admission_decisions.get("refuse_ambiguous", 0)
    unsupported_refused = admission_decisions.get("refuse_unsupported", 0)

    captured = sum(1 for e in events if e.get("source_kind") == "captured_local_model")
    curated = sum(1 for e in events if e.get("source_kind") == "curated_adversarial")
    fixture = sum(1 for e in events if e.get("source_kind") == "fixture")

    report: dict[str, Any] = {
        "schema_version": "rig.relay.tool_recovery_evaluation_report.v1",
        "report_id": report_id or f"rpt_{datetime.now(UTC).isoformat()}",
        "created_at": datetime.now(UTC).isoformat(),
        "total_cases": total,
        "source_kind_counts": dict(source_kinds),
        "canonical_valid_count": canonical_valid,
        "malformed_count": malformed,
        "uniquely_recovered_count": uniquely_recovered,
        "refusal_count_by_reason": dict(refusal_codes),
        "false_recovery_count": false_recovery,
        "false_recovery_rate": round(false_recovery_rate, 4),
        "ambiguity_refusal_correct": ambiguity_correct,
        "read_only_auto_execute_count": read_only_auto,
        "validation_auto_execute_count": validation_auto,
        "mutation_proposal_only_count": proposal_only,
        "external_side_effect_authorization_required_count": ext_side_refused,
        "raw_shell_refusal_count": raw_shell_refused,
        "ambiguity_refusal_count": ambiguity_refused,
        "unsupported_refusal_count": unsupported_refused,
        "recovered_mutation_auto_execution_violation_count": mutation_violations,
        "normalization_rule_frequency": dict(norm_rules),
        "payload_validation_failure_count": payload_failures,
        "tool_coverage_by_canonical_name": dict(tools_selected),
        "captured_real_model_case_count": captured,
        "curated_adversarial_case_count": curated,
        "fixture_case_count": fixture,
    }

    payload = json.dumps(report, sort_keys=True, separators=(",", ":"))
    report["report_digest"] = f"sha256:{hashlib.sha256(payload.encode()).hexdigest()}"

    return report


def write_report(events: list[dict[str, Any]], path: Path) -> dict[str, Any]:
    """Build report and write to file."""
    report = build_report(events)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report, sort_keys=True, indent=2, separators=(",", ": ")),
        encoding="utf-8",
    )
    return report
