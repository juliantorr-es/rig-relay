"""Shadow evaluation tests — contract evaluator, reference comparison,
safety policy, scenario runner, redaction, and CLI scenarios.

Classifications: contract, unit, integration, real-artifact, adversarial, substrate.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys

from rig_relay.providers.local_inference import (
    OutputContractKind,
    ShadowRunReceipt,
    ShadowScenario,
    build_safety_policy,
    compare_to_reference,
    evaluate_contract,
    run_shadow_evaluation,
    validate_shadow_receipt_safety,
)

SCHEMA_DIR = Path(__file__).resolve().parents[2] / "docs" / "schemas"


def _make_chat_scenario(
    scenario_id: str = "s1",
    contract: OutputContractKind = OutputContractKind.NON_EMPTY_TEXT,
    **kwargs: object,
) -> ShadowScenario:
    prompt = "What is 1+1?"
    pb = prompt.encode("utf-8")
    defaults = {
        "scenario_id": scenario_id,
        "task_profile": "chat_light",
        "prompt_sha256": hashlib.sha256(pb).hexdigest(),
        "prompt_byte_count": len(pb),
        "prompt_text_synthetic_safe": prompt,
        "expected_output_contract": contract,
    }
    defaults.update(kwargs)
    return ShadowScenario(**defaults)


class TestContractEvaluator:
    def test_non_empty_text_passes(self) -> None:
        result = evaluate_contract(
            completion_text="Hello, world.", scenario_id="s1", contract="non_empty_text"
        )
        assert result.status == "passed"

    def test_non_empty_text_fails_empty(self) -> None:
        result = evaluate_contract(
            completion_text="   ", scenario_id="s1", contract="non_empty_text"
        )
        assert result.status == "failed"
        assert "empty_output" in result.failure_codes

    def test_valid_json_passes(self) -> None:
        result = evaluate_contract(
            completion_text='{"x":1}', scenario_id="s1", contract="valid_json"
        )
        assert result.status == "passed"
        assert result.completion_is_json

    def test_valid_json_fails(self) -> None:
        result = evaluate_contract(
            completion_text="not json", scenario_id="s1", contract="valid_json"
        )
        assert result.status == "failed"
        assert "invalid_json" in result.failure_codes

    def test_json_object_passes(self) -> None:
        result = evaluate_contract(
            completion_text='{"a":1}', scenario_id="s1", contract="json_object"
        )
        assert result.status == "passed"

    def test_json_object_fails_array(self) -> None:
        result = evaluate_contract(
            completion_text="[1,2,3]", scenario_id="s1", contract="json_object"
        )
        assert result.status == "failed"
        assert "expected_object" in result.failure_codes

    def test_contains_required_keys_passes(self) -> None:
        result = evaluate_contract(
            completion_text='{"answer":2,"status":"ok"}',
            scenario_id="s1",
            contract="contains_required_keys",
            required_keys=["answer", "status"],
        )
        assert result.status == "passed"
        assert result.completion_required_keys_found == ["answer", "status"]

    def test_contains_required_keys_reports_missing(self) -> None:
        result = evaluate_contract(
            completion_text='{"answer":2}',
            scenario_id="s1",
            contract="contains_required_keys",
            required_keys=["answer", "status"],
        )
        assert result.status == "failed"
        assert "missing_required_key" in result.failure_codes
        assert result.completion_required_keys_missing == ["status"]

    def test_max_length_passes(self) -> None:
        result = evaluate_contract(
            completion_text="abc",
            scenario_id="s1",
            contract="max_length",
            max_length_chars=10,
        )
        assert result.status == "passed"

    def test_max_length_fails(self) -> None:
        result = evaluate_contract(
            completion_text="a" * 100,
            scenario_id="s1",
            contract="max_length",
            max_length_chars=10,
        )
        assert result.status == "failed"
        assert "max_length_exceeded" in result.failure_codes

    def test_unsupported_contract(self) -> None:
        result = evaluate_contract(
            completion_text="x", scenario_id="s1", contract="refusal_or_blocked_allowed"
        )
        assert result.status == "unsupported"
        assert "unsupported_contract" in result.failure_codes


class TestReferenceComparison:
    def test_no_reference(self) -> None:
        receipt = ShadowRunReceipt(
            shadow_run_id="sr1",
            scenario_id="s1",
            generated_at="2026-01-01T00:00:00Z",
            completion_sha256="abc",
        )
        cmp = compare_to_reference(shadow_receipt=receipt)
        assert cmp.comparison_status == "no_reference"

    def test_hash_match_passes(self) -> None:
        receipt = ShadowRunReceipt(
            shadow_run_id="sr1",
            scenario_id="s1",
            generated_at="2026-01-01T00:00:00Z",
            completion_sha256="abc",
        )
        cmp = compare_to_reference(shadow_receipt=receipt, reference_hash="abc")
        assert cmp.comparison_status == "comparison_passed"
        assert cmp.completion_hash_match

    def test_hash_mismatch_fails(self) -> None:
        receipt = ShadowRunReceipt(
            shadow_run_id="sr1",
            scenario_id="s1",
            generated_at="2026-01-01T00:00:00Z",
            completion_sha256="abc",
        )
        cmp = compare_to_reference(shadow_receipt=receipt, reference_hash="def")
        assert cmp.comparison_status == "comparison_failed"

    def test_contract_result_match(self) -> None:
        receipt = ShadowRunReceipt(
            shadow_run_id="sr1",
            scenario_id="s1",
            generated_at="2026-01-01T00:00:00Z",
            contract_result="passed",
        )
        cmp = compare_to_reference(
            shadow_receipt=receipt, reference_contract_result="passed"
        )
        assert cmp.contract_result_match

    def test_latency_class_comparison(self) -> None:
        receipt = ShadowRunReceipt(
            shadow_run_id="sr1",
            scenario_id="s1",
            generated_at="2026-01-01T00:00:00Z",
            latency_ms=300,
        )
        cmp = compare_to_reference(
            shadow_receipt=receipt, reference_latency_class="fast"
        )
        assert cmp.latency_class_match


class TestShadowSafetyPolicy:
    def test_policy_all_false(self) -> None:
        policy = build_safety_policy()
        assert policy.automatic_agent_execution is False
        assert policy.agent_state_mutated is False
        assert policy.tool_execution_allowed is False
        assert policy.file_mutation_allowed is False
        assert policy.raw_prompt_persisted is False
        assert policy.raw_completion_persisted is False

    def test_receipt_validation_passes(self) -> None:
        receipt = {
            "automatic_agent_execution": False,
            "agent_state_mutated": False,
            "tool_execution_allowed": False,
            "file_mutation_allowed": False,
            "provider_fallback_execution_allowed": False,
            "raw_prompt_persisted": False,
            "raw_completion_persisted": False,
        }
        violations = validate_shadow_receipt_safety(receipt)
        assert violations == []

    def test_receipt_validation_finds_violations(self) -> None:
        receipt = {
            "automatic_agent_execution": True,
            "agent_state_mutated": False,
            "tool_execution_allowed": True,
            "file_mutation_allowed": False,
            "provider_fallback_execution_allowed": False,
            "raw_prompt_persisted": False,
            "raw_completion_persisted": True,
        }
        violations = validate_shadow_receipt_safety(receipt)
        assert len(violations) == 3


class TestShadowEvaluation:
    def test_dry_run_produces_contract_passed(self) -> None:
        scenario = _make_chat_scenario()
        receipt = run_shadow_evaluation(
            scenario=scenario, endpoint_configured=True, endpoint_hash="", dry_run=True
        )
        assert receipt.status == "contract_passed"
        assert receipt.raw_prompt_persisted is False
        assert receipt.raw_completion_persisted is False
        assert receipt.automatic_agent_execution is False
        assert receipt.agent_state_mutated is False

    def test_unconfigured_blocks(self) -> None:
        scenario = _make_chat_scenario()
        receipt = run_shadow_evaluation(
            scenario=scenario, endpoint_configured=False, endpoint_hash="", dry_run=True
        )
        assert receipt.status == "blocked"


class TestShadowSubstrate:
    def test_no_raw_prompt_in_shadow_receipt(self) -> None:
        scenario = _make_chat_scenario()
        receipt = run_shadow_evaluation(
            scenario=scenario, endpoint_configured=True, endpoint_hash="", dry_run=True
        )
        data = json.loads(receipt.model_dump_json())
        assert data["raw_prompt_persisted"] is False
        assert data["raw_completion_persisted"] is False
        assert "What is 1+1" not in json.dumps(data)

    def test_no_auto_execution_enabled(self) -> None:
        scenario = _make_chat_scenario()
        receipt = run_shadow_evaluation(
            scenario=scenario, endpoint_configured=True, endpoint_hash="", dry_run=True
        )
        assert receipt.automatic_agent_execution is False
        assert receipt.tool_execution_allowed is False
        assert receipt.file_mutation_allowed is False


class TestShadowSchemas:
    def test_shadow_scenario_schema_exists(self) -> None:
        p = SCHEMA_DIR / "rig.local_inference.shadow_scenario.v1.schema.json"
        assert p.exists()

    def test_shadow_run_receipt_schema_exists(self) -> None:
        p = SCHEMA_DIR / "rig.local_inference.shadow_run_receipt.v1.schema.json"
        assert p.exists()

    def test_output_contract_schema_exists(self) -> None:
        p = SCHEMA_DIR / "rig.local_inference.output_contract_result.v1.schema.json"
        assert p.exists()

    def test_reference_comparison_schema_exists(self) -> None:
        p = SCHEMA_DIR / "rig.local_inference.reference_comparison.v1.schema.json"
        assert p.exists()

    def test_safety_policy_schema_exists(self) -> None:
        p = SCHEMA_DIR / "rig.local_inference.shadow_safety_policy.v1.schema.json"
        assert p.exists()

    def test_shadow_receipt_validates(self) -> None:
        import jsonschema

        schema_path = (
            SCHEMA_DIR / "rig.local_inference.shadow_run_receipt.v1.schema.json"
        )
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        scenario = _make_chat_scenario()
        receipt = run_shadow_evaluation(
            scenario=scenario, endpoint_configured=True, endpoint_hash="", dry_run=True
        )
        data = json.loads(receipt.model_dump_json())
        jsonschema.validate(data, schema)


class TestShadowCLI:
    SCRIPT = str(
        Path(__file__).resolve().parents[2]
        / "scripts"
        / "rig_local_inference_shadow_eval.py"
    )

    def _run(self, *args: str, **kwargs: object) -> subprocess.CompletedProcess[str]:
        cmd = [sys.executable, self.SCRIPT]
        cmd.extend(args)
        for k, v in kwargs.items():
            if v is True:
                cmd.append(f"--{k.replace('_', '-')}")
            elif v is not False:
                cmd.append(f"--{k.replace('_', '-')}")
                cmd.append(str(v))
        return subprocess.run(cmd, capture_output=True, text=True, timeout=30)

    def test_cli_no_scenario_errors(self, tmp_path: Path) -> None:
        result = self._run(
            config_root=str(tmp_path / "li"),
            output_dir=str(tmp_path / "out"),
            json=True,
        )
        assert result.returncode == 1

    def test_cli_dry_run_default(self, tmp_path: Path) -> None:
        result = self._run(
            config_root=str(tmp_path / "li"),
            output_dir=str(tmp_path / "out"),
            scenario_id="shadow_chat_light_non_empty",
            json=True,
        )
        data = json.loads(result.stdout)
        assert data["raw_prompt_persisted"] is False
        assert data["automatic_agent_execution"] is False
