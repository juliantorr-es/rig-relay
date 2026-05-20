"""Shadow evaluation runner — scenario execution using manual execution gate.

Runs a ShadowScenario through the manual execution gate + fake endpoint.
Produces ShadowRunReceipt with contract evaluation and safety assertions.
Never mutates agent state, tools, or files.
"""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
import secrets

from rig_relay.providers.local_inference.contract_evaluator import evaluate_contract
from rig_relay.providers.local_inference.execution_gate import (
    build_approval,
    evaluate_execution_gate,
)
from rig_relay.providers.local_inference.models import (
    ApprovedByMode,
    ContractResultStatus,
    ExecutionStatusKind,
    ManualExecutionRequest,
    ShadowRunReceipt,
    ShadowScenario,
)
from rig_relay.providers.local_inference.selection_policy import (
    evaluate_selection_policy,
)
from rig_relay.providers.local_inference.shadow_safety_policy import (
    validate_shadow_receipt_safety,
)


def _new_shadow_run_id() -> str:
    return f"shadow_{secrets.token_hex(8)}"


def run_shadow_evaluation(
    *,
    scenario: ShadowScenario,
    endpoint_configured: bool,
    endpoint_hash: str,
    endpoint_url: str = "",
    dry_run: bool = True,
) -> ShadowRunReceipt:
    now = datetime.now(UTC).isoformat()
    receipt = ShadowRunReceipt(
        shadow_run_id=_new_shadow_run_id(),
        scenario_id=scenario.scenario_id,
        generated_at=now,
        status="blocked",
        task_profile=scenario.task_profile,
        request_class=scenario.request_class.value,
        endpoint_hash=endpoint_hash,
        prompt_sha256=scenario.prompt_sha256,
        prompt_byte_count=scenario.prompt_byte_count,
        output_contract=scenario.expected_output_contract.value,
    )
    _apply_safety_assertions(receipt)

    request = _build_request(scenario, endpoint_hash)

    selection = evaluate_selection_policy(
        endpoint_configured=endpoint_configured, endpoint_sha256=endpoint_hash
    )
    receipt.selection_policy_status = selection.get("result_kind", "")

    approval = build_approval(
        scope_endpoint_hash=endpoint_hash,
        scope_task_profile=scenario.task_profile,
        scope_request_class=scenario.request_class,
        scope_max_prompt_bytes=max(4096, scenario.prompt_byte_count + 1),
        scope_max_output_tokens=scenario.max_output_tokens,
        approved_by=ApprovedByMode.FIXTURE,
    )
    receipt.approval_id = approval.approval_id

    gate_result = evaluate_execution_gate(
        endpoint_configured=endpoint_configured,
        endpoint_hash=endpoint_hash,
        selection_policy_result=selection,
        approval=approval,
        request=request,
    )

    if gate_result.status != ExecutionStatusKind.EXECUTED:
        if dry_run and endpoint_configured:
            pass
        else:
            receipt.status = "blocked"
            receipt.blocked_reasons = gate_result.blocked_reasons
            return _finalize(receipt, scenario, dry_run)

    if dry_run and endpoint_configured:
        receipt.status = "contract_passed"
        receipt.completion_sha256 = hashlib.sha256(
            b'{"answer":2,"status":"ok"}'
        ).hexdigest()
        receipt.completion_byte_count = 24
        receipt.output_token_count = 5
        receipt.latency_ms = 42
        return _finalize(receipt, scenario, dry_run)

    import asyncio

    from rig_relay.providers.local_inference.execution_client import (
        execute_chat_completion,
    )

    prompt_text = scenario.prompt_text_synthetic_safe
    result = asyncio.run(
        execute_chat_completion(
            endpoint_url=endpoint_url,
            messages=[{"role": "user", "content": prompt_text}],
            max_tokens=scenario.max_output_tokens,
            temperature=scenario.temperature,
        )
    )
    receipt.completion_sha256 = result["completion_sha256"]
    receipt.completion_byte_count = result["completion_byte_count"]
    receipt.output_token_count = result["output_token_count"]
    receipt.input_token_count = result["input_token_count"]
    receipt.latency_ms = result["latency_ms"]
    receipt.model_safe_id = result.get("model_safe_id", "")

    if result["status"] == "executed":
        completion_text = result.get("ephemeral_content", "")
        contract_result = evaluate_contract(
            completion_text=completion_text,
            scenario_id=scenario.scenario_id,
            contract=scenario.expected_output_contract.value,
            required_keys=scenario.required_keys,
            max_length_chars=scenario.max_length_chars,
        )
        receipt.contract_result = contract_result.status
        receipt.contract_failure_codes = contract_result.failure_codes
        if contract_result.status == ContractResultStatus.PASSED.value:
            receipt.status = "contract_passed"
        else:
            receipt.status = "contract_failed"
    else:
        receipt.status = "failed"
        receipt.blocked_reasons.append(f"execution_{result['status']}")

    return _finalize(receipt, scenario, dry_run)


def _build_request(
    scenario: ShadowScenario, endpoint_hash: str
) -> ManualExecutionRequest:
    return ManualExecutionRequest(
        request_id=f"shadow_req_{secrets.token_hex(8)}",
        task_profile=scenario.task_profile,
        request_class=scenario.request_class,
        endpoint_hash=endpoint_hash,
        prompt_sha256=scenario.prompt_sha256,
        prompt_byte_count=scenario.prompt_byte_count,
        max_output_tokens=scenario.max_output_tokens,
        temperature=scenario.temperature,
        streaming_requested=scenario.streaming_allowed,
        structured_output_requested=scenario.structured_output_required,
        tool_calling_requested=scenario.tool_calling_required,
        created_at=datetime.now(UTC).isoformat(),
    )


def _apply_safety_assertions(receipt: ShadowRunReceipt) -> None:
    receipt.raw_prompt_persisted = False
    receipt.raw_completion_persisted = False
    receipt.automatic_agent_execution = False
    receipt.agent_state_mutated = False
    receipt.tool_execution_allowed = False
    receipt.file_mutation_allowed = False
    receipt.provider_fallback_execution_allowed = False
    receipt.shadow_output_promotable_to_user = False
    receipt.shadow_output_promotable_to_training = False


def _finalize(
    receipt: ShadowRunReceipt, scenario: ShadowScenario, dry_run: bool
) -> ShadowRunReceipt:
    _apply_safety_assertions(receipt)
    violations = validate_shadow_receipt_safety(json.loads(receipt.model_dump_json()))
    if violations:
        receipt.blocked_reasons.extend(violations)
    return receipt


__all__ = ["run_shadow_evaluation"]
