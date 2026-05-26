from __future__ import annotations

from pathlib import Path

import pytest

from rig_relay.recovery.capability_admission import (
    CapabilityQuery,
    ConstraintCapabilityDisposition,
    EnforcementClass,
    RecoveryConstraintCapabilityAdmissionService,
    build_constraint_capability_disposition,
    compute_capability_projection,
)
from rig_relay.recovery.constrained_execution import ConstrainedExecutionRequest
from rig_relay.recovery.constraint_compiler import ConstraintCompilationReceipt
from rig_relay.recovery.models import CanonicalToolSurfaceManifest


def _sha256(data: str) -> str:
    import hashlib

    return f"sha256:{hashlib.sha256(data.encode()).hexdigest()}"


def _make_manifest() -> CanonicalToolSurfaceManifest:
    from rig_relay.recovery.models import AdmittedToolEntry, RecoveryAdmissionTier

    return CanonicalToolSurfaceManifest(
        manifest_id="d3-test",
        generated_at="2026-05-26T00:00:00Z",
        manifest_digest=_sha256("d3-manifest"),
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
        ],
    )


_MANIFEST = _make_manifest()


def _make_constraint_receipt() -> ConstraintCompilationReceipt:
    return ConstraintCompilationReceipt(
        compilation_id="comp_d3_test",
        manifest_digest=_MANIFEST.manifest_digest,
        target_profile="json_schema_safe",
        tools_total=2,
        tools_fully_representable=2,
        constraint_artifact_digest=_sha256("d3-artifact"),
        tool_schema_digests={
            "read_file": "sha256:f56995d814dcfa04d98b3f918206163fa37f4ea8c4f56076445a4cbffb21f21e",
            "write_file": "sha256:d73bc6b63e0f10b521bc84303472f48140d1eafe58114058bc18c9cc5ab64e7a",
        },
        receipt_digest=_sha256("d3-comp-receipt"),
    )


_CONSTRAINT_RECEIPT = _make_constraint_receipt()


_RANK = {
    EnforcementClass.UNSUPPORTED: 0,
    EnforcementClass.JSON_OBJECT_FORMATTING_ONLY: 1,
    EnforcementClass.NATIVE_JSON_SCHEMA: 2,
    EnforcementClass.NATIVE_GRAMMAR_GBNF: 3,
}


class TestEnforcementClass:
    def test_ordering_is_correct(self) -> None:
        assert (
            _RANK[EnforcementClass.NATIVE_JSON_SCHEMA]
            > _RANK[EnforcementClass.JSON_OBJECT_FORMATTING_ONLY]
        )
        assert (
            _RANK[EnforcementClass.NATIVE_GRAMMAR_GBNF]
            > _RANK[EnforcementClass.NATIVE_JSON_SCHEMA]
        )
        assert (
            _RANK[EnforcementClass.UNSUPPORTED]
            < _RANK[EnforcementClass.JSON_OBJECT_FORMATTING_ONLY]
        )
        assert (
            _RANK[EnforcementClass.JSON_OBJECT_FORMATTING_ONLY]
            < _RANK[EnforcementClass.NATIVE_JSON_SCHEMA]
        )

    def test_unsupported_is_weakest(self) -> None:
        for cls in EnforcementClass:
            if cls != EnforcementClass.UNSUPPORTED:
                assert _RANK[cls] > _RANK[EnforcementClass.UNSUPPORTED]


class TestConstraintCapabilityDisposition:
    def test_disposition_defaults_highest_class_to_unsupported(self) -> None:
        disp = ConstraintCapabilityDisposition(
            disposition_id="test",
            runtime_kind="ollama",
            runtime_endpoint_hash="sha256:" + ("00" * 32),
        )
        assert (
            disp.highest_enforcement_class_demonstrated == EnforcementClass.UNSUPPORTED
        )

    def test_disposition_accepts_valid_data(self) -> None:
        disp = ConstraintCapabilityDisposition(
            disposition_id="disp-1",
            runtime_kind="ollama",
            runtime_endpoint_hash="sha256:" + ("00" * 32),
            model_name_hash=_sha256("qwen2.5:0.5b"),
            highest_enforcement_class_demonstrated=EnforcementClass.NATIVE_JSON_SCHEMA,
            json_schema_enforcement_demonstrated=True,
            evidence_from_captured_local_model=True,
            proof_run_count=3,
        )
        assert (
            disp.highest_enforcement_class_demonstrated
            == EnforcementClass.NATIVE_JSON_SCHEMA
        )
        assert disp.json_schema_enforcement_demonstrated

    def test_disposition_exposes_content_light_output(self) -> None:
        disp = ConstraintCapabilityDisposition(
            disposition_id="disp-cl",
            runtime_kind="ollama",
            runtime_endpoint_hash="sha256:" + ("aa" * 32),
            highest_enforcement_class_demonstrated=EnforcementClass.NATIVE_JSON_SCHEMA,
        )
        data = disp.model_dump(mode="json")
        assert "sha256:" in data["runtime_endpoint_hash"]
        for forbidden in (
            "raw_emission",
            "raw_prompt",
            "raw_model_output",
            "file_content",
            "secret",
            "api_key",
        ):
            assert forbidden not in data


class TestCapabilityAdmissionService:
    def test_admit_json_schema_when_demonstrated(self) -> None:
        svc = RecoveryConstraintCapabilityAdmissionService()
        disp = ConstraintCapabilityDisposition(
            disposition_id="disp-js",
            runtime_kind="ollama",
            runtime_endpoint_hash="sha256:" + ("00" * 32),
            highest_enforcement_class_demonstrated=EnforcementClass.NATIVE_JSON_SCHEMA,
            json_schema_enforcement_demonstrated=True,
            json_schema_enforcement_receipt_bound=True,
            evidence_from_captured_local_model=True,
            proof_run_count=3,
            proof_event_ids=["p1", "p2", "p3"],
        )
        svc.register_disposition(disp)

        query = CapabilityQuery(
            query_id="q-js",
            required_enforcement_class=EnforcementClass.NATIVE_JSON_SCHEMA,
        )
        decision = svc.admit_capability(query)
        assert decision.runtime_capable
        assert decision.evidence_from_captured_local_model
        assert "satisfies required" in decision.reason
        assert decision.stronger_mechanism_unavailable

    def test_refuse_native_schema_when_receipt_not_bound(self) -> None:
        svc = RecoveryConstraintCapabilityAdmissionService()
        disp = ConstraintCapabilityDisposition(
            disposition_id="disp-js-unbound",
            runtime_kind="ollama",
            runtime_endpoint_hash="sha256:" + ("00" * 32),
            highest_enforcement_class_demonstrated=EnforcementClass.NATIVE_JSON_SCHEMA,
            json_schema_enforcement_demonstrated=True,
            json_schema_enforcement_receipt_bound=False,
            evidence_from_captured_local_model=True,
            proof_run_count=1,
        )
        svc.register_disposition(disp)

        query = CapabilityQuery(
            query_id="q-js-unbound",
            required_enforcement_class=EnforcementClass.NATIVE_JSON_SCHEMA,
        )
        decision = svc.admit_capability(query)
        assert not decision.runtime_capable
        assert "not digest-bound" in decision.reason

    def test_refuse_grammar_when_only_json_schema_demonstrated(self) -> None:
        svc = RecoveryConstraintCapabilityAdmissionService()
        disp = ConstraintCapabilityDisposition(
            disposition_id="disp-js-only",
            runtime_kind="ollama",
            runtime_endpoint_hash="sha256:" + ("00" * 32),
            highest_enforcement_class_demonstrated=EnforcementClass.NATIVE_JSON_SCHEMA,
            json_schema_enforcement_demonstrated=True,
            json_schema_enforcement_receipt_bound=True,
            evidence_from_captured_local_model=True,
            proof_run_count=1,
        )
        svc.register_disposition(disp)

        query = CapabilityQuery(
            query_id="q-grammar",
            required_enforcement_class=EnforcementClass.NATIVE_GRAMMAR_GBNF,
        )
        decision = svc.admit_capability(query)
        assert not decision.runtime_capable
        assert "weaker than required" in decision.reason

    def test_refuse_json_schema_when_only_json_object_demonstrated(self) -> None:
        svc = RecoveryConstraintCapabilityAdmissionService()
        disp = ConstraintCapabilityDisposition(
            disposition_id="disp-jo-only",
            runtime_kind="ollama",
            runtime_endpoint_hash="sha256:" + ("00" * 32),
            highest_enforcement_class_demonstrated=(
                EnforcementClass.JSON_OBJECT_FORMATTING_ONLY
            ),
            json_object_formatting_demonstrated=True,
            json_schema_enforcement_receipt_bound=True,
            evidence_from_captured_local_model=True,
            proof_run_count=1,
        )
        svc.register_disposition(disp)

        query = CapabilityQuery(
            query_id="q-js-needed",
            required_enforcement_class=EnforcementClass.NATIVE_JSON_SCHEMA,
        )
        decision = svc.admit_capability(query)
        assert not decision.runtime_capable
        assert "weaker than required" in decision.reason

    def test_refuse_when_no_dispositions_registered(self) -> None:
        svc = RecoveryConstraintCapabilityAdmissionService()
        query = CapabilityQuery(
            query_id="q-empty",
            required_enforcement_class=EnforcementClass.NATIVE_JSON_SCHEMA,
        )
        decision = svc.admit_capability(query)
        assert not decision.runtime_capable
        assert "No runtime capability dispositions" in decision.reason

    def test_refuse_when_no_captured_local_evidence(self) -> None:
        svc = RecoveryConstraintCapabilityAdmissionService()
        disp = ConstraintCapabilityDisposition(
            disposition_id="disp-no-captured",
            runtime_kind="ollama",
            runtime_endpoint_hash="sha256:" + ("00" * 32),
            highest_enforcement_class_demonstrated=EnforcementClass.NATIVE_JSON_SCHEMA,
            json_schema_enforcement_demonstrated=True,
            evidence_from_captured_local_model=False,
            proof_run_count=0,
            curated_fixture_run_count=3,
        )
        svc.register_disposition(disp)

        query = CapabilityQuery(
            query_id="q-need-captured",
            required_enforcement_class=EnforcementClass.NATIVE_JSON_SCHEMA,
            require_captured_local_model_evidence=True,
        )
        decision = svc.admit_capability(query)
        assert not decision.runtime_capable
        assert "captured local model evidence" in decision.reason

    def test_querying_does_not_modify_dispositions(self) -> None:
        svc = RecoveryConstraintCapabilityAdmissionService()
        disp = ConstraintCapabilityDisposition(
            disposition_id="disp-immutable",
            runtime_kind="ollama",
            runtime_endpoint_hash="sha256:" + ("00" * 32),
            highest_enforcement_class_demonstrated=EnforcementClass.NATIVE_JSON_SCHEMA,
            evidence_from_captured_local_model=True,
            proof_run_count=2,
        )
        svc.register_disposition(disp)

        original = disp.model_dump(mode="json")
        for _ in range(5):
            svc.query_capability("q", EnforcementClass.NATIVE_JSON_SCHEMA)

        after = svc.list_dispositions()[0].model_dump(mode="json")
        assert original == after


class TestCapabilityProjection:
    def test_projection_deterministic_digest(self) -> None:
        disp1 = ConstraintCapabilityDisposition(
            disposition_id="disp-a",
            runtime_kind="ollama",
            runtime_endpoint_hash="sha256:" + ("aa" * 32),
            highest_enforcement_class_demonstrated=EnforcementClass.NATIVE_JSON_SCHEMA,
            json_schema_enforcement_demonstrated=True,
            evidence_from_captured_local_model=True,
            proof_run_count=2,
            proposal_only_mutation_preserved=True,
        )
        disp2 = ConstraintCapabilityDisposition(
            disposition_id="disp-b",
            runtime_kind="ollama",
            runtime_endpoint_hash="sha256:" + ("bb" * 32),
            highest_enforcement_class_demonstrated=EnforcementClass.NATIVE_JSON_SCHEMA,
            json_schema_enforcement_demonstrated=True,
            evidence_from_captured_local_model=True,
            proof_run_count=1,
            proposal_only_mutation_preserved=True,
        )

        proj1 = compute_capability_projection([disp1, disp2], projection_id="pid-1")
        proj2 = compute_capability_projection([disp1, disp2], projection_id="pid-1")
        assert proj1["projection_digest"] == proj2["projection_digest"]

    def test_projection_includes_proposal_only_visibility(self) -> None:
        disp = ConstraintCapabilityDisposition(
            disposition_id="disp-prop",
            runtime_kind="ollama",
            runtime_endpoint_hash="sha256:" + ("00" * 32),
            highest_enforcement_class_demonstrated=EnforcementClass.NATIVE_JSON_SCHEMA,
            evidence_from_captured_local_model=True,
            proof_run_count=2,
            proposal_only_mutation_preserved=True,
        )
        proj = compute_capability_projection([disp])
        assert proj["proposal_only_mutation_preserved_count"] == 1
        assert proj["runtimes"][0]["proposal_only_preserved"]

    def test_projection_distinguishes_captured_from_curated(self) -> None:
        disp = ConstraintCapabilityDisposition(
            disposition_id="disp-mixed",
            runtime_kind="ollama",
            runtime_endpoint_hash="sha256:" + ("00" * 32),
            highest_enforcement_class_demonstrated=EnforcementClass.NATIVE_JSON_SCHEMA,
            evidence_from_captured_local_model=True,
            proof_run_count=3,
            curated_fixture_run_count=1,
        )
        proj = compute_capability_projection([disp])
        assert proj["total_captured_local_proof_runs"] == 3
        assert proj["total_curated_fixture_runs"] == 1

    def test_projection_content_light(self) -> None:
        disp = ConstraintCapabilityDisposition(
            disposition_id="disp-cl-proj",
            runtime_kind="ollama",
            runtime_endpoint_hash="sha256:" + ("00" * 32),
            highest_enforcement_class_demonstrated=EnforcementClass.NATIVE_JSON_SCHEMA,
        )
        proj = compute_capability_projection([disp])
        data_str = str(proj)
        for forbidden in (
            "raw_emission",
            "raw_prompt",
            "raw_model_output",
            "file_content",
            "secret",
            "api_key",
            "stdout",
            "stderr",
        ):
            assert forbidden not in data_str.lower(), (
                f"Found forbidden key: {forbidden}"
            )


class TestBuildConstraintCapabilityDisposition:
    def test_json_schema_demonstrated_from_execution_result(self) -> None:
        from rig_relay.recovery.constrained_execution import (
            ConstrainedExecutionResult,
            ConstraintEnforcementDisposition,
        )

        enforcement = ConstraintEnforcementDisposition(
            disposition_id="disp-proof",
            runtime_kind="ollama",
            runtime_endpoint_hash="sha256:" + ("00" * 32),
            model_name="qwen2.5:0.5b",
            json_schema_enforcement_exercised=True,
            json_schema_enforcement_available=True,
            enforced_mechanism="response_format_json_schema",
        )
        result = ConstrainedExecutionResult(
            execution_id="exec-proof",
            execution_status="executed",
            emission_source_kind="captured_local_model",
            emission_sha256="sha256:" + ("ab" * 32),
            output_token_count=20,
            latency_ms=500,
            constraint_enforcement_disposition=enforcement,
            proposal_only=False,
        )

        disp = build_constraint_capability_disposition(
            disposition_id="built-disp",
            runtime_kind="ollama",
            runtime_endpoint="http://localhost:11434",
            model_name="qwen2.5:0.5b",
            results=[result],
        )

        assert (
            disp.highest_enforcement_class_demonstrated
            == EnforcementClass.NATIVE_JSON_SCHEMA
        )
        assert disp.json_schema_enforcement_demonstrated
        assert disp.evidence_from_captured_local_model
        assert disp.proof_run_count == 1
        assert disp.curated_fixture_run_count == 0

    def test_json_object_only_from_result_without_schema_enforcement(self) -> None:
        from rig_relay.recovery.constrained_execution import (
            ConstrainedExecutionResult,
            ConstraintEnforcementDisposition,
        )

        enforcement = ConstraintEnforcementDisposition(
            disposition_id="disp-jo",
            runtime_kind="ollama",
            runtime_endpoint_hash="sha256:" + ("00" * 32),
            json_object_enforcement_exercised=True,
            json_object_enforcement_available=True,
            json_schema_enforcement_exercised=False,
        )
        result = ConstrainedExecutionResult(
            execution_id="exec-jo",
            execution_status="executed",
            emission_source_kind="captured_local_model",
            emission_sha256="sha256:" + ("cd" * 32),
            constraint_enforcement_disposition=enforcement,
        )

        disp = build_constraint_capability_disposition(
            disposition_id="built-disp-jo",
            runtime_kind="ollama",
            runtime_endpoint="http://localhost:11434",
            model_name="test",
            results=[result],
        )

        assert disp.highest_enforcement_class_demonstrated == (
            EnforcementClass.JSON_OBJECT_FORMATTING_ONLY
        )
        assert not disp.json_schema_enforcement_demonstrated
        assert disp.json_object_formatting_demonstrated

    def test_proposal_only_visibility(self) -> None:
        from rig_relay.recovery.constrained_execution import (
            ConstrainedExecutionResult,
            ConstraintEnforcementDisposition,
        )

        enforcement = ConstraintEnforcementDisposition(
            disposition_id="disp-prop-test",
            runtime_kind="ollama",
            runtime_endpoint_hash="sha256:" + ("00" * 32),
            json_schema_enforcement_exercised=True,
        )
        result = ConstrainedExecutionResult(
            execution_id="exec-prop",
            execution_status="executed",
            emission_source_kind="captured_local_model",
            emission_sha256="sha256:" + ("ef" * 32),
            proposal_only=True,
            mutation_class="writes_workspace",
            constraint_enforcement_disposition=enforcement,
        )

        disp = build_constraint_capability_disposition(
            disposition_id="disp-prop",
            runtime_kind="ollama",
            runtime_endpoint="http://localhost:11434",
            model_name="test",
            results=[result],
        )

        assert disp.proposal_only_mutation_preserved


@pytest.mark.asyncio
@pytest.mark.provider
async def test_real_ollama_capability_admission_integration(tmp_path: Path) -> None:
    """End-to-end D3 proof: real Ollama execution → capability admission."""
    try:
        import httpx

        async with httpx.AsyncClient(timeout=5.0) as c:
            r = await c.get("http://localhost:11434/api/tags")
            if r.status_code != 200:
                pytest.skip("Ollama not reachable")
    except Exception:
        pytest.skip("Ollama not reachable")

    from rig_relay.recovery.constrained_execution import execute_constrained_recovery
    from rig_relay.recovery.constraint_compiler import (
        persist_constraint_compilation_receipt,
    )
    from rig_relay.recovery.evidence_ledger import EvidenceLedger

    # Persist the receipt durably before execution
    receipt_ledger_path = tmp_path / "receipts.jsonl"
    receipt_ledger = EvidenceLedger(receipt_ledger_path)
    persist_constraint_compilation_receipt(_CONSTRAINT_RECEIPT, receipt_ledger)

    # Execute a constrained recovery call to generate real evidence
    request = ConstrainedExecutionRequest(
        execution_id="d3-real-proof",
        manifest_digest=_MANIFEST.manifest_digest,
        constraint_receipt_digest=_CONSTRAINT_RECEIPT.receipt_digest,
        target_tool_name="read_file",
        endpoint_url="http://localhost:11434",
        runtime_kind="ollama",
        model_name="qwen2.5:0.5b",
        emission_source_kind="captured_local_model",
        max_tokens=100,
        timeout_sec=60.0,
    )

    result = await execute_constrained_recovery(
        request,
        _MANIFEST,
        _CONSTRAINT_RECEIPT,
        ledger_path=tmp_path / "evidence.jsonl",
        constraint_receipt_ledger_path=receipt_ledger_path,
        runtime_available=True,
    )

    assert result.execution_status == "executed"
    assert result.emission_source_kind == "captured_local_model"
    assert result.receipt_loaded_from_durable_evidence

    # Build capability disposition from real result
    disp = build_constraint_capability_disposition(
        disposition_id="disp-d3-real",
        runtime_kind="ollama",
        runtime_endpoint="http://localhost:11434",
        model_name="qwen2.5:0.5b",
        results=[result],
        constraint_receipt_digest=_CONSTRAINT_RECEIPT.receipt_digest,
        manifest_digest=_MANIFEST.manifest_digest,
    )

    assert (
        disp.highest_enforcement_class_demonstrated
        == EnforcementClass.NATIVE_JSON_SCHEMA
    )

    # Admit for native_json_schema
    svc = RecoveryConstraintCapabilityAdmissionService()
    svc.register_disposition(disp)

    js_query = CapabilityQuery(
        query_id="q-real-js",
        required_enforcement_class=EnforcementClass.NATIVE_JSON_SCHEMA,
    )
    js_dec = svc.admit_capability(js_query)
    assert js_dec.runtime_capable, f"Should admit but got: {js_dec.reason}"
    assert js_dec.evidence_from_captured_local_model

    # Refuse for grammar
    grammar_query = CapabilityQuery(
        query_id="q-real-grammar",
        required_enforcement_class=EnforcementClass.NATIVE_GRAMMAR_GBNF,
    )
    grammar_dec = svc.admit_capability(grammar_query)
    assert not grammar_dec.runtime_capable
    assert "weaker than required" in grammar_dec.reason

    # Build projection
    proj = compute_capability_projection([disp])
    assert proj["disposition_count"] == 1
    assert proj["total_captured_local_proof_runs"] >= 1
    assert "projection_digest" in proj
    assert proj["projection_digest"].startswith("sha256:")

    # Verify content-light
    proj_str = str(proj)
    for forbidden in (
        "raw_emission",
        "raw_prompt",
        "secret",
        "api_key",
        "stdout",
        "stderr",
    ):
        assert forbidden not in proj_str.lower()
