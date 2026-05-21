"""Result builder for runtime tool execution.

Extracted from tool_invocation_execution.py to eliminate duplicated
result construction across the five execute_* methods.
"""

from __future__ import annotations

import hashlib
import json
import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from rig_relay.runtime.tool_invocation_execution import RuntimeToolExecutionResult


def build_tool_receipt(tool_name: str, result: Any) -> Any:
    """Build a receipt for a given tool result.

    Creates a minimal tool instance and delegates to its build_receipt method.
    """
    from rig_relay.core.tools.base import BaseToolState

    match tool_name:
        case "validate":
            from rig_relay.core.tools.builtins.validate import Validate
            from rig_relay.core.tools.builtins.validate_models import ValidateToolConfig

            tool = Validate(
                config_getter=lambda: ValidateToolConfig(), state=BaseToolState()
            )
        case "search_replace":
            from rig_relay.core.tools.builtins.search_replace import (
                SearchReplace,
                SearchReplaceConfig,
            )

            tool = SearchReplace(
                config_getter=lambda: SearchReplaceConfig(), state=BaseToolState()
            )
        case "write_file":
            from rig_relay.core.tools.builtins.write_file import (
                WriteFile,
                WriteFileConfig,
            )

            tool = WriteFile(
                config_getter=lambda: WriteFileConfig(), state=BaseToolState()
            )
        case "bash":
            from rig_relay.core.tools.builtins.bash import Bash, BashToolConfig

            tool = Bash(config_getter=lambda: BashToolConfig(), state=BaseToolState())
        case _:
            return None
    return tool.build_receipt(result)


def to_execution_result(
    *,
    runtime_result: Any,
    intent: Any,
    envelope: Any,
    start: float,
    changed_paths: list[str] | None = None,
    tool_receipt_kind: str | None = None,
) -> RuntimeToolExecutionResult:
    """Build a RuntimeToolExecutionResult from a tool runtime result.

    Classifies the runtime status into a RuntimeToolExecutionStatus
    (completed/refused/blocked/failed) and attaches content-light fields
    and receipt metadata.
    """
    from rig_relay.runtime.tool_invocation_execution import (
        RuntimeToolExecutionResult,
        RuntimeToolExecutionStatus,
    )

    duration = (time.perf_counter() - start) * 1000
    status_value = getattr(runtime_result.status, "value", runtime_result.status)
    provider = getattr(runtime_result, "provider_tool_response", None)
    provider_status = getattr(provider, "status", None)
    provider_status_value = getattr(provider_status, "value", provider_status)
    status_source = provider_status_value or status_value
    tool_status = provider_status_value or status_source
    provider_error_kind = getattr(provider, "error_kind", None)
    provider_refusal = getattr(provider, "refusal_reason", None)
    if status_source == "cached":
        execution_status = RuntimeToolExecutionStatus.COMPLETED
    elif status_source == "completed":
        execution_status = RuntimeToolExecutionStatus.COMPLETED
    elif status_source == "passed":
        execution_status = RuntimeToolExecutionStatus.COMPLETED
    elif status_source == "success":
        execution_status = RuntimeToolExecutionStatus.COMPLETED
    elif status_source == "refused":
        execution_status = RuntimeToolExecutionStatus.REFUSED
    elif status_source == "blocked":
        execution_status = RuntimeToolExecutionStatus.BLOCKED
    elif status_source == "failed":
        execution_status = RuntimeToolExecutionStatus.FAILED
    elif status_source == "timed_out":
        execution_status = RuntimeToolExecutionStatus.FAILED
    else:
        execution_status = RuntimeToolExecutionStatus.COMPLETED

    from rig_relay.runtime.tool_invocation_adapter import RuntimeToolName

    if (
        intent.tool_name == RuntimeToolName.BASH_LEGACY
        and execution_status == RuntimeToolExecutionStatus.FAILED
    ):
        tool_status = None

    provider_supervisor_envelope = getattr(
        getattr(runtime_result, "provider_tool_response", None),
        "supervisor_result_envelope",
        None,
    )
    supervisor_result_envelope_id = None
    if isinstance(provider_supervisor_envelope, dict):
        supervisor_result_envelope_id = provider_supervisor_envelope.get("result_id")

    result = RuntimeToolExecutionResult(
        status=execution_status,
        invocation_id=envelope.invocation_id,
        intent_id=intent.intent_id,
        tool_name=intent.tool_name.value,
        envelope_schema_valid=True,
        tool_status=tool_status,
        tool_error_kind=provider_error_kind,
        receipt_sha256=None,
        duration_ms=duration,
        error_kind=provider_error_kind,
        refusal_reason=provider_refusal
        or getattr(getattr(runtime_result, "refusal", None), "message", None),
        tool_receipt_kind=tool_receipt_kind or intent.tool_name.value,
        tool_receipt_schema_version=(
            f"rig.relay.{(tool_receipt_kind or intent.tool_name.value)}_receipt.v1"
        ),
        changed_paths=changed_paths or [],
        supervisor_result_envelope_id=supervisor_result_envelope_id,
        supervisor_result_envelope_sha256=getattr(
            runtime_result, "supervisor_result_envelope_sha256", None
        ),
        supervisor_result_classification=getattr(
            runtime_result, "supervisor_result_classification", None
        ),
    )
    result = result.model_copy(
        update={
            "receipt_sha256": hashlib.sha256(
                json.dumps(result.model_dump(mode="json"), sort_keys=True).encode()
            ).hexdigest()
        }
    )
    if result.status == RuntimeToolExecutionStatus.FAILED and result.error_kind is None:
        result = result.model_copy(update={"error_kind": "execution_error"})
    return attach_receipt(result)


def attach_receipt(result: RuntimeToolExecutionResult) -> RuntimeToolExecutionResult:
    """Attach a receipt model to the execution result."""
    from rig_relay.runtime.tool_invocation_receipt import (
        build_runtime_tool_invocation_receipt,
    )

    receipt_model = build_runtime_tool_invocation_receipt(result)
    result = result.model_copy(update={"receipt": receipt_model})
    return result


def build_validate_receipt(result: Any) -> Any:
    return build_tool_receipt("validate", result)


def build_search_replace_receipt(result: Any) -> Any:
    return build_tool_receipt("search_replace", result)


def build_write_file_receipt(result: Any) -> Any:
    return build_tool_receipt("write_file", result)


def build_bash_receipt(result: Any) -> Any:
    return build_tool_receipt("bash", result)


__all__ = [
    "attach_receipt",
    "build_bash_receipt",
    "build_search_replace_receipt",
    "build_tool_receipt",
    "build_validate_receipt",
    "build_write_file_receipt",
    "to_execution_result",
]
