"""Offline recovery evaluation corridor — runs captured emissions through D0.

Never executes tools. Never creates proposals. Never invokes shell.
"""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
from typing import Any
import uuid

from rig_relay.recovery.admission_policy import decide_admission
from rig_relay.recovery.evidence_ledger import EvidenceLedger
from rig_relay.recovery.models import CanonicalToolSurfaceManifest, RawRecoveryInput
from rig_relay.recovery.receipt import (
    build_recovery_receipt_from_intent,
    build_recovery_receipt_from_refusal,
)
from rig_relay.recovery.transducer import transduce


def utcnow_iso() -> str:
    return datetime.now(UTC).isoformat()


def evaluate_cases(
    manifest: CanonicalToolSurfaceManifest,
    cases: list[dict[str, Any]],
    ledger_path: Path | None = None,
    evaluation_run_id: str | None = None,
) -> list[dict[str, Any]]:
    """Run a set of emission cases through the D0 pipeline.

    Args:
        manifest: Canonical tool-surface manifest
        cases: List of case dicts with at minimum:
            - case_id: str
            - raw_emission: dict | str
            - source_kind: curated_adversarial | captured_local_model | fixture
            Optional:
            - expected_decision, expected_tool, runtime_kind, model_id_hash

    Returns:
        List of evaluation event dicts.
    """
    run_id = evaluation_run_id or f"eval_{uuid.uuid4().hex[:12]}"
    events: list[dict[str, Any]] = []

    for case in cases:
        event = _evaluate_one(manifest, case, run_id)
        events.append(event)
        if ledger_path is not None:
            ledger = EvidenceLedger(ledger_path)
            ledger.append_event(event)

    return events


def _evaluate_one(
    manifest: CanonicalToolSurfaceManifest, case: dict[str, Any], run_id: str
) -> dict[str, Any]:
    """Evaluate one emission case."""
    raw_emission = case["raw_emission"]
    case_id = case["case_id"]
    source_kind = case.get("source_kind", "curated_adversarial")

    raw_str = (
        raw_emission
        if isinstance(raw_emission, str)
        else json.dumps(raw_emission, sort_keys=True)
    )
    emission_sha256 = f"sha256:{hashlib.sha256(raw_str.encode()).hexdigest()}"

    raw_input = RawRecoveryInput(
        raw_emission=raw_emission, emission_sha256=emission_sha256, call_id=case_id
    )

    result = transduce(raw_input, manifest)

    receipt_sha256: str | None = None
    selected_tool: str | None = None
    admission_decision: str | None = None
    mutation_class: str | None = None
    rules_applied: list[str] = []
    payload_valid: bool = False
    refusal_code: str | None = None
    candidate_count: int = 0

    if result.is_recovered and result.recovered_intent is not None:
        intent = result.recovered_intent
        selected_tool = intent.canonical_tool_name
        mutation_class = intent.mutation_class
        rules_applied = sorted(intent.rules_applied)
        payload_valid = True

        entry = next(
            (e for e in manifest.admitted_tools if e.canonical_name == selected_tool),
            None,
        )
        if entry is not None:
            adm_result = decide_admission(intent, entry)
            admission_decision = str(adm_result.admission_decision)
            receipt = build_recovery_receipt_from_intent(
                receipt_id=f"rcpt_{case_id}",
                intent=intent,
                manifest_digest=manifest.manifest_digest,
                emission_sha256=emission_sha256,
                admission_result=adm_result.admission_decision,
                proposal_only=adm_result.proposal_only,
            )
            receipt_sha256 = receipt.receipt_sha256
    elif result.is_refused and result.refusal is not None:
        refusal = result.refusal
        refusal_code = str(refusal.refusal_code)
        candidate_count = refusal.candidate_count
        rules_applied = sorted(refusal.rules_attempted)
        receipt = build_recovery_receipt_from_refusal(
            receipt_id=f"rcpt_{case_id}",
            refusal=refusal,
            manifest_digest=manifest.manifest_digest,
            emission_sha256=emission_sha256,
        )
        receipt_sha256 = receipt.receipt_sha256

    expected_decision = case.get("expected_decision")
    expected_tool = case.get("expected_tool")
    recovery_correct: bool | None = None
    false_recovery: bool = False
    ambiguity_refused_correctly: bool | None = None

    refusal_set = {"refuse_ambiguous", "refuse_unsupported"}

    if expected_decision is not None and admission_decision is not None:
        recovery_correct = admission_decision == expected_decision
        if admission_decision not in refusal_set and expected_decision in refusal_set:
            false_recovery = True

    if expected_decision in refusal_set and admission_decision in refusal_set:
        ambiguity_refused_correctly = True
    elif expected_decision in refusal_set:
        ambiguity_refused_correctly = False

    mutation_auto_violation = False
    if admission_decision and "auto_execute" in admission_decision and mutation_class:
        mc = mutation_class.lower()
        if mc in {"writes_workspace", "mutates_git_state", "external_side_effect"}:
            mutation_auto_violation = True

    event: dict[str, Any] = {
        "schema_version": "rig.relay.tool_recovery_evaluation_event.v1",
        "evaluation_run_id": run_id,
        "case_id": case_id,
        "source_kind": source_kind,
        "runtime_kind": case.get("runtime_kind"),
        "model_id_hash": case.get("model_id_hash"),
        "tool_surface_manifest_digest": manifest.manifest_digest,
        "raw_emission_sha256": emission_sha256,
        "recovery_receipt_sha256": receipt_sha256,
        "selected_canonical_tool": selected_tool,
        "admission_decision": admission_decision,
        "mutation_class": mutation_class,
        "normalization_rules_applied": rules_applied,
        "payload_schema_valid": payload_valid,
        "refusal_code": refusal_code,
        "candidate_count": candidate_count,
        "expected_decision": expected_decision,
        "expected_tool": expected_tool,
        "recovery_correct": recovery_correct,
        "false_recovery": false_recovery,
        "ambiguity_refused_correctly": ambiguity_refused_correctly,
        "recovered_mutation_auto_execution_violation": mutation_auto_violation,
        "created_at": utcnow_iso(),
    }
    _sha256 = hashlib.sha256(
        json.dumps(
            {k: v for k, v in event.items() if k != "event_digest"},
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    event["event_digest"] = f"sha256:{_sha256}"

    return event
