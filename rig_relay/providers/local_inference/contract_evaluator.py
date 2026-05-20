"""Output contract evaluator — metadata-only completion inspection.

Evaluates ephemeral completion text against output contracts.
Emits only pass/fail, failure codes, hashes, lengths, shape metadata.
Never persists raw completion.
"""

from __future__ import annotations

import hashlib
import json
import secrets

from rig_relay.providers.local_inference.models import (
    ContractResultStatus,
    OutputContractKind,
    OutputContractResult,
)


def _new_result_id() -> str:
    return f"ocr_{secrets.token_hex(8)}"


def evaluate_contract(
    *,
    completion_text: str,
    scenario_id: str,
    contract: str,
    required_keys: list[str] | None = None,
    max_length_chars: int = 0,
) -> OutputContractResult:
    result = OutputContractResult(
        result_id=_new_result_id(),
        scenario_id=scenario_id,
        contract=contract,
        completion_sha256=hashlib.sha256(completion_text.encode("utf-8")).hexdigest(),
        completion_byte_count=len(completion_text.encode("utf-8")),
        completion_char_count=len(completion_text),
    )

    try:
        parsed = json.loads(completion_text)
        result.completion_is_json = True
        if isinstance(parsed, dict):
            result.completion_top_level_type = "object"
        elif isinstance(parsed, list):
            result.completion_top_level_type = "array"
        else:
            result.completion_top_level_type = type(parsed).__name__
    except (json.JSONDecodeError, ValueError):
        result.completion_is_json = False
        result.completion_top_level_type = ""

    contract_enum = _resolve_contract(contract)

    if contract_enum == OutputContractKind.NON_EMPTY_TEXT:
        _eval_non_empty_text(completion_text, result)
    elif contract_enum == OutputContractKind.VALID_JSON:
        _eval_valid_json(result)
    elif contract_enum == OutputContractKind.JSON_OBJECT:
        _eval_json_object(result)
    elif contract_enum == OutputContractKind.JSON_SCHEMA:
        _eval_json_schema(completion_text, result)
    elif contract_enum == OutputContractKind.CONTAINS_REQUIRED_KEYS:
        _eval_required_keys(completion_text, required_keys or [], result)
    elif contract_enum == OutputContractKind.MAX_LENGTH:
        _eval_max_length(completion_text, max_length_chars, result)
    else:
        result.status = ContractResultStatus.UNSUPPORTED.value
        result.failure_codes.append("unsupported_contract")

    return result


def _resolve_contract(contract: str) -> OutputContractKind:
    try:
        return OutputContractKind(contract)
    except ValueError:
        return OutputContractKind.NONE


def _eval_non_empty_text(text: str, result: OutputContractResult) -> None:
    if text.strip():
        result.status = ContractResultStatus.PASSED.value
    else:
        result.status = ContractResultStatus.FAILED.value
        result.failure_codes.append("empty_output")


def _eval_valid_json(result: OutputContractResult) -> None:
    if result.completion_is_json:
        result.status = ContractResultStatus.PASSED.value
    else:
        result.status = ContractResultStatus.FAILED.value
        result.failure_codes.append("invalid_json")


def _eval_json_object(result: OutputContractResult) -> None:
    if result.completion_is_json and result.completion_top_level_type == "object":
        result.status = ContractResultStatus.PASSED.value
    else:
        result.status = ContractResultStatus.FAILED.value
        failure = "invalid_json" if not result.completion_is_json else "expected_object"
        result.failure_codes.append(failure)


def _eval_json_schema(text: str, result: OutputContractResult) -> None:
    if not result.completion_is_json:
        result.status = ContractResultStatus.FAILED.value
        result.failure_codes.append("invalid_json")
        return
    result.status = ContractResultStatus.UNSUPPORTED.value
    result.failure_codes.append("schema_validation_failed")


def _eval_required_keys(
    text: str, required_keys: list[str], result: OutputContractResult
) -> None:
    if not result.completion_is_json or result.completion_top_level_type != "object":
        result.status = ContractResultStatus.FAILED.value
        result.failure_codes.append("expected_object")
        return
    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        result.status = ContractResultStatus.FAILED.value
        result.failure_codes.append("invalid_json")
        return
    if not isinstance(parsed, dict):
        result.status = ContractResultStatus.FAILED.value
        result.failure_codes.append("expected_object")
        return
    found = []
    missing = []
    for key in required_keys:
        if key in parsed:
            found.append(key)
        else:
            missing.append(key)
    result.completion_required_keys_found = found
    result.completion_required_keys_missing = missing
    if missing:
        result.status = ContractResultStatus.FAILED.value
        result.failure_codes.append("missing_required_key")
    else:
        result.status = ContractResultStatus.PASSED.value


def _eval_max_length(text: str, max_chars: int, result: OutputContractResult) -> None:
    if len(text) <= max_chars:
        result.status = ContractResultStatus.PASSED.value
    else:
        result.status = ContractResultStatus.FAILED.value
        result.failure_codes.append("max_length_exceeded")
        result.max_length_exceeded = True


__all__ = ["evaluate_contract"]
