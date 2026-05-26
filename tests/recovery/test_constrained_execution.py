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
from rig_relay.recovery.evidence_ledger import EvidenceLedger
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
        tool_schema_digests={
            "read_file": "sha256:f56995d814dcfa04d98b3f918206163fa37f4ea8c4f56076445a4cbffb21f21e",
            "write_file": "sha256:d73bc6b63e0f10b521bc84303472f48140d1eafe58114058bc18c9cc5ab64e7a",
            "search_replace": "sha256:f520e35db507566e5c7f1b1af991fe043cb9819fd1c6a4b3b3e9cddc28d85b69",
        },
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
    assert not disp.json_schema_enforcement_exercised


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
        not result.constraint_enforcement_disposition.json_schema_enforcement_exercised
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
    assert disp.json_schema_enforcement_available
    assert disp.json_schema_enforcement_exercised

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
        json_schema_enforcement_available=False,
        enforcement_truth_note="json_object available; json_schema unavailable",
    )

    data = disp.model_dump(mode="json")
    assert data["json_object_enforcement_available"]
    assert not data["json_schema_enforcement_available"]
    assert not data["grammar_enforcement_available"]


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


@pytest.mark.asyncio
@pytest.mark.provider
async def test_native_schema_enforcement_falsification_proof() -> None:
    """Prove native JSON Schema enforcement (not merely cooperation).

    Sends a schema with const='read_file' but prompts the model to
    generate a write_file call. If enforcement is real, the runtime
    grammar-level constraint forces the output to respect const.

    Also verifies that additionalProperties:false and required fields
    are enforced even when the prompt asks for a different shape.
    """
    try:
        import httpx

        async with httpx.AsyncClient(timeout=5.0) as c:
            r = await c.get("http://localhost:11434/api/tags")
            if r.status_code != 200:
                pytest.skip("Ollama not reachable")
    except Exception:
        pytest.skip("Ollama not reachable")

    schema = {
        "type": "object",
        "properties": {
            "tool": {"type": "string", "const": "read_file"},
            "arguments": {
                "type": "object",
                "properties": {"file_path": {"type": "string"}},
                "required": ["file_path"],
                "additionalProperties": False,
            },
        },
        "required": ["tool", "arguments"],
        "additionalProperties": False,
    }

    payload = {
        "model": "qwen2.5:0.5b",
        "messages": [
            {
                "role": "system",
                "content": "You are a tool call generator. Output valid JSON only.",
            },
            {
                "role": "user",
                "content": (
                    "Generate a tool call for write_file tool, which writes "
                    "content to a file at a specified path. Output valid JSON only."
                ),
            },
        ],
        "max_tokens": 100,
        "temperature": 0.0,
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "recovery", "schema": schema, "strict": True},
        },
        "stream": False,
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.post(
            "http://localhost:11434/v1/chat/completions", json=payload
        )

    body = r.json()
    content = body["choices"][0]["message"]["content"]
    parsed = json.loads(content)

    assert parsed["tool"] == "read_file", (
        f"Enforcement failure: prompt asked for write_file, schema const "
        f"requires read_file, but output tool is {parsed.get('tool')!r}"
    )

    extra_keys = [k for k in parsed if k not in ("tool", "arguments")]
    assert len(extra_keys) == 0, (
        f"additionalProperties failure: schema forbids extra keys, "
        f"but output has {extra_keys}"
    )

    assert "file_path" in parsed.get("arguments", {}), (
        "required field failure: schema requires file_path in arguments"
    )


@pytest.mark.asyncio
async def test_refuse_when_canonical_receipt_not_in_ledger(tmp_path: Path) -> None:
    from rig_relay.recovery.constraint_compiler import (
        persist_constraint_compilation_receipt,
    )

    ledger = EvidenceLedger(tmp_path / "receipts.jsonl")
    _ = persist_constraint_compilation_receipt(_CONSTRAINT_RECEIPT, ledger)

    request = ConstrainedExecutionRequest(
        execution_id="test-no-canonical",
        manifest_digest=_MANIFEST.manifest_digest,
        constraint_receipt_digest="sha256:" + ("ff" * 32),
        target_tool_name="read_file",
        endpoint_url="http://localhost:11434",
        runtime_kind="ollama",
        model_name="qwen2.5:0.5b",
    )

    result = await execute_constrained_recovery(
        request,
        _MANIFEST,
        _CONSTRAINT_RECEIPT,
        constraint_receipt_ledger_path=tmp_path / "nonexistent.jsonl",
        runtime_available=True,
    )

    assert result.execution_status == "refused"
    assert result.refusal_code == "canonical_compilation_receipt_not_found"


@pytest.mark.asyncio
async def test_refuse_when_supplied_receipt_differs_from_canonical(
    tmp_path: Path,
) -> None:
    from rig_relay.recovery.constraint_compiler import (
        persist_constraint_compilation_receipt,
    )

    ledger = EvidenceLedger(tmp_path / "receipts.jsonl")
    persisted_event_id = persist_constraint_compilation_receipt(
        _CONSTRAINT_RECEIPT, ledger
    )
    assert persisted_event_id

    modified_receipt = ConstraintCompilationReceipt(
        compilation_id="comp_different",
        manifest_digest=_MANIFEST.manifest_digest,
        target_profile="json_schema_safe",
        tools_total=3,
        tools_fully_representable=3,
        constraint_artifact_digest=_sha256("different-artifact"),
        tool_schema_digests={"read_file": _sha256("different-schema")},
        receipt_digest=_sha256("different-receipt"),
    )

    request = ConstrainedExecutionRequest(
        execution_id="test-mismatch",
        manifest_digest=_MANIFEST.manifest_digest,
        constraint_receipt_digest=modified_receipt.receipt_digest,
        target_tool_name="read_file",
        endpoint_url="http://localhost:11434",
        runtime_kind="ollama",
        model_name="qwen2.5:0.5b",
    )

    result = await execute_constrained_recovery(
        request,
        _MANIFEST,
        modified_receipt,
        constraint_receipt_ledger_path=tmp_path / "receipts.jsonl",
        runtime_available=True,
    )

    assert result.execution_status == "refused"
    assert "does not match" in (result.execution_error or "")


def test_evidence_ledger_supports_receipt_persistence(tmp_path: Path) -> None:
    from rig_relay.recovery.constraint_compiler import (
        load_canonical_constraint_receipt,
        persist_constraint_compilation_receipt,
    )

    ledger = EvidenceLedger(tmp_path / "receipts.jsonl")

    event_digest = persist_constraint_compilation_receipt(_CONSTRAINT_RECEIPT, ledger)
    assert event_digest.startswith("sha256:")

    loaded = load_canonical_constraint_receipt(ledger)
    assert loaded is not None
    assert loaded.receipt_digest == _CONSTRAINT_RECEIPT.receipt_digest
    assert loaded.tool_schema_digests == _CONSTRAINT_RECEIPT.tool_schema_digests
    assert loaded.manifest_digest == _CONSTRAINT_RECEIPT.manifest_digest


def test_empty_ledger_returns_none(tmp_path: Path) -> None:
    from rig_relay.recovery.constraint_compiler import load_canonical_constraint_receipt

    ledger = EvidenceLedger(tmp_path / "empty.jsonl")
    result = load_canonical_constraint_receipt(ledger)
    assert result is None


def test_receipt_persistence_rejects_missing_tool_schema_digests(
    tmp_path: Path,
) -> None:
    from rig_relay.recovery.constraint_compiler import (
        persist_constraint_compilation_receipt,
    )

    receipt = ConstraintCompilationReceipt(
        compilation_id="comp-no-schemas",
        manifest_digest=_MANIFEST.manifest_digest,
        target_profile="json_schema_safe",
        tools_total=1,
        constraint_artifact_digest=_sha256("test"),
        receipt_digest=_sha256("test-receipt"),
    )

    ledger = EvidenceLedger(tmp_path / "receipts.jsonl")
    with pytest.raises(ValueError, match="tool_schema_digests"):
        persist_constraint_compilation_receipt(receipt, ledger)


def test_receipt_persistence_rejects_empty_digest(tmp_path: Path) -> None:
    from rig_relay.recovery.constraint_compiler import (
        persist_constraint_compilation_receipt,
    )

    receipt = ConstraintCompilationReceipt(
        compilation_id="comp-no-digest",
        manifest_digest=_MANIFEST.manifest_digest,
        target_profile="json_schema_safe",
        tools_total=1,
        tool_schema_digests={"read_file": _sha256("s")},
        constraint_artifact_digest=_sha256("test"),
        receipt_digest=_sha256("temp"),  # valid pattern, cleared below
    )
    receipt.receipt_digest = ""

    ledger = EvidenceLedger(tmp_path / "receipts.jsonl")
    with pytest.raises(ValueError, match="empty receipt_digest"):
        persist_constraint_compilation_receipt(receipt, ledger)


def test_corrupt_ledger_line_does_not_load_receipt(tmp_path: Path) -> None:
    from rig_relay.recovery.constraint_compiler import load_canonical_constraint_receipt

    ledger = EvidenceLedger(tmp_path / "corrupt.jsonl")
    ledger.append_event({"garbage": True, "schema_version": "wrong"})

    result = load_canonical_constraint_receipt(ledger)
    assert result is None
