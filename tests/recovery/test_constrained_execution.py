from __future__ import annotations

import json
from pathlib import Path

import pytest

from rig_relay.recovery.constrained_execution import (
    ConstrainedExecutionRequest,
    ConstraintEnforcementDisposition,
    execute_constrained_recovery,
)
from rig_relay.recovery.constraint_compiler import ConstraintCompilationReceipt
from rig_relay.recovery.models import CanonicalToolSurfaceManifest


def _sha256(data: str) -> str:
    import hashlib

    return f"sha256:{hashlib.sha256(data.encode()).hexdigest()}"


def _make_manifest() -> CanonicalToolSurfaceManifest:
    from rig_relay.recovery.models import AdmittedToolEntry, RecoveryAdmissionTier

    return CanonicalToolSurfaceManifest(
        manifest_id="d2-test",
        generated_at="2026-05-26T00:00:00Z",
        manifest_digest=_sha256("d2-manifest"),
        admitted_tools=[
            AdmittedToolEntry(
                canonical_name="read_file",
                aliases=["read-file"],
                mutation_class="read_only",
                determinism_class="deterministic_repo_state",
                args_schema_digest=_sha256("rf"),
                arg_field_names=["file_path"],
                recovery_admission_tier=RecoveryAdmissionTier.READ_ONLY_RECOVERABLE,
            ),
            AdmittedToolEntry(
                canonical_name="write_file",
                aliases=["write-file"],
                mutation_class="writes_workspace",
                determinism_class="deterministic_repo_state",
                args_schema_digest=_sha256("wf"),
                arg_field_names=["file_path", "content"],
                recovery_admission_tier=RecoveryAdmissionTier.MUTATION_PROPOSAL_ONLY,
            ),
            AdmittedToolEntry(
                canonical_name="search_replace",
                aliases=["search-replace"],
                mutation_class="writes_workspace",
                determinism_class="deterministic_repo_state",
                args_schema_digest=_sha256("sr"),
                arg_field_names=["file_path", "old_string", "new_string"],
                recovery_admission_tier=RecoveryAdmissionTier.MUTATION_PROPOSAL_ONLY,
            ),
        ],
    )


_MANIFEST = _make_manifest()


def _make_constraint_receipt() -> ConstraintCompilationReceipt:
    return ConstraintCompilationReceipt(
        compilation_id="comp_d2_test",
        manifest_digest=_MANIFEST.manifest_digest,
        target_profile="json_schema_safe",
        tools_total=3,
        tools_fully_representable=3,
        constraint_artifact_digest=_sha256("test-artifact"),
        receipt_digest=_sha256("comp-receipt"),
    )


_CONSTRAINT_RECEIPT = _make_constraint_receipt()


@pytest.mark.asyncio
async def test_runtime_unavailable_produces_refusal_result(tmp_path: Path) -> None:
    request = ConstrainedExecutionRequest(
        execution_id="test-unavail",
        manifest_digest=_MANIFEST.manifest_digest,
        constraint_receipt_digest=_CONSTRAINT_RECEIPT.receipt_digest,
        target_tool_name="read_file",
        endpoint_url="http://localhost:9999",
        runtime_kind="none",
        model_name="",
    )

    result = await execute_constrained_recovery(
        request,
        _MANIFEST,
        _CONSTRAINT_RECEIPT,
        ledger_path=tmp_path / "evidence.jsonl",
        runtime_available=False,
    )

    assert result.execution_status == "runtime_unavailable"
    assert result.execution_error
    assert result.constraint_enforcement_disposition is not None
    disp = result.constraint_enforcement_disposition
    assert not disp.json_object_enforcement_exercised
    assert not disp.json_schema_enforcement_available


@pytest.mark.asyncio
async def test_tool_not_in_manifest_refused(tmp_path: Path) -> None:
    request = ConstrainedExecutionRequest(
        execution_id="test-no-tool",
        manifest_digest=_MANIFEST.manifest_digest,
        constraint_receipt_digest=_CONSTRAINT_RECEIPT.receipt_digest,
        target_tool_name="nonexistent_tool",
        endpoint_url="http://localhost:9999",
        runtime_kind="ollama",
        model_name="test",
    )

    result = await execute_constrained_recovery(
        request, _MANIFEST, _CONSTRAINT_RECEIPT, runtime_available=True
    )

    assert result.execution_status == "refused"
    assert result.refusal_code == "canonical_tool_not_admitted"


@pytest.mark.asyncio
async def test_execution_failed_on_bad_endpoint(tmp_path: Path) -> None:
    request = ConstrainedExecutionRequest(
        execution_id="test-bad-ep",
        manifest_digest=_MANIFEST.manifest_digest,
        constraint_receipt_digest=_CONSTRAINT_RECEIPT.receipt_digest,
        target_tool_name="read_file",
        endpoint_url="http://localhost:1",
        runtime_kind="ollama",
        model_name="qwen2.5:0.5b",
        timeout_sec=2.0,
    )

    result = await execute_constrained_recovery(
        request,
        _MANIFEST,
        _CONSTRAINT_RECEIPT,
        ledger_path=tmp_path / "evidence.jsonl",
        runtime_available=True,
    )

    assert result.execution_status in ("failed", "runtime_unavailable")
    assert result.constraint_enforcement_disposition is not None
    assert (
        not result.constraint_enforcement_disposition.json_object_enforcement_exercised
    )


@pytest.mark.asyncio
@pytest.mark.provider
async def test_real_ollama_read_only_recovery(tmp_path: Path) -> None:
    try:
        import httpx

        async with httpx.AsyncClient(timeout=5.0) as c:
            r = await c.get("http://localhost:11434/api/tags")
            if r.status_code != 200:
                pytest.skip("Ollama not reachable")
    except Exception:
        pytest.skip("Ollama not reachable")

    request = ConstrainedExecutionRequest(
        execution_id="test-real-readonly",
        manifest_digest=_MANIFEST.manifest_digest,
        constraint_receipt_digest=_CONSTRAINT_RECEIPT.receipt_digest,
        target_tool_name="read_file",
        endpoint_url="http://localhost:11434",
        runtime_kind="ollama",
        model_name="qwen2.5:0.5b",
        max_tokens=100,
        timeout_sec=60.0,
    )

    result = await execute_constrained_recovery(
        request,
        _MANIFEST,
        _CONSTRAINT_RECEIPT,
        ledger_path=tmp_path / "evidence.jsonl",
        runtime_available=True,
    )

    assert result.execution_status == "executed"
    assert result.emission_sha256.startswith("sha256:")
    assert result.output_token_count > 0
    assert result.latency_ms > 0

    disp = result.constraint_enforcement_disposition
    assert disp is not None
    assert disp.json_object_enforcement_available
    assert disp.json_object_enforcement_exercised

    assert result.handoff_kind in (
        "read_only",
        "validation",
        "mutation_proposal_only",
        "refusal",
    )

    ledger_path = tmp_path / "evidence.jsonl"
    assert ledger_path.exists()
    events = [json.loads(l) for l in ledger_path.read_text().splitlines() if l.strip()]
    assert len(events) >= 1
    for event in events:
        assert "event_digest" in event


@pytest.mark.asyncio
@pytest.mark.provider
async def test_real_ollama_mutation_proposal_only(tmp_path: Path) -> None:
    try:
        import httpx

        async with httpx.AsyncClient(timeout=5.0) as c:
            r = await c.get("http://localhost:11434/api/tags")
            if r.status_code != 200:
                pytest.skip("Ollama not reachable")
    except Exception:
        pytest.skip("Ollama not reachable")

    request = ConstrainedExecutionRequest(
        execution_id="test-real-mutation",
        manifest_digest=_MANIFEST.manifest_digest,
        constraint_receipt_digest=_CONSTRAINT_RECEIPT.receipt_digest,
        target_tool_name="write_file",
        endpoint_url="http://localhost:11434",
        runtime_kind="ollama",
        model_name="qwen2.5:0.5b",
        max_tokens=150,
        timeout_sec=60.0,
    )

    result = await execute_constrained_recovery(
        request,
        _MANIFEST,
        _CONSTRAINT_RECEIPT,
        ledger_path=tmp_path / "evidence.jsonl",
        runtime_available=True,
    )

    assert result.execution_status in ("executed", "refused")

    if result.execution_status == "executed":
        assert result.handoff_kind in ("mutation_proposal_only", "refusal", "read_only")
        if result.handoff_kind == "mutation_proposal_only":
            assert result.proposal_only
            assert result.admission_decision == "proposal_only_mutation"
            assert result.mutation_class


def test_enforcement_disposition_truthfulness() -> None:
    disp = ConstraintEnforcementDisposition(
        disposition_id="test-disp",
        runtime_kind="ollama",
        runtime_endpoint_hash="sha256:" + ("00" * 32),
        model_name="qwen2.5:0.5b",
        json_object_enforcement_available=True,
        json_object_enforcement_exercised=True,
        enforcement_truth_note="json_object available; json_schema unconfirmed",
    )

    data = disp.model_dump(mode="json")
    assert data["json_object_enforcement_available"]
    assert not data["json_schema_enforcement_available"]
    assert not data["grammar_enforcement_available"]
    assert data["enforced_mechanism"] == ""


def test_evidence_ledger_integrity_after_execution(tmp_path: Path) -> None:
    from rig_relay.recovery.evidence_ledger import EvidenceLedger

    ledger = EvidenceLedger(tmp_path / "integrity.jsonl")
    event = {
        "schema_version": "rig.relay.tool_recovery_evaluation_event.v1",
        "case_id": "integrity-test",
        "source_kind": "captured_local_model",
        "admission_decision": "auto_execute_read_only",
        "created_at": "2026-05-26T00:00:00Z",
    }
    ledger.append_event(event)

    loaded = ledger.load_events()
    assert len(loaded) == 1
    assert loaded[0]["case_id"] == "integrity-test"

    count = ledger.count_events()
    assert count == 1
