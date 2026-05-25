"""Result builder for runtime tool execution.

Extracted from tool_invocation_execution.py to eliminate duplicated
result construction across the five execute_* methods.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
import re
import subprocess
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


def bound_stdout(
    text: str, max_lines: int = 500, max_bytes: int = 16384
) -> tuple[str, bool, bool]:
    """Truncate text by lines and bytes, and perform basic sanitization/redaction."""
    redacted = False
    sensitive_patterns = [
        (
            r"(?i)(password|passwd|secret|private_key|token|auth_token|api_key)\s*[:=]\s*['\"][^'\"]+['\"]",
            r"\1 = [REDACTED]",
        ),
        (
            r"-----BEGIN [A-Z ]+ PRIVATE KEY-----[\s\S]+?-----END [A-Z ]+ PRIVATE KEY-----",
            "[REDACTED PRIVATE KEY]",
        ),
    ]

    sanitized = text
    for pattern, repl in sensitive_patterns:
        new_text = re.sub(pattern, repl, sanitized)
        if new_text != sanitized:
            sanitized = new_text
            redacted = True

    lines = sanitized.splitlines()
    truncated = False
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        truncated = True

    bounded = "\n".join(lines)
    if len(bounded.encode("utf-8")) > max_bytes:
        bounded = bounded[:max_bytes]
        truncated = True

    if truncated:
        bounded += "\n\n[TRUNCATED: Output exceeded limits]"

    return bounded, truncated, redacted


@dataclass(frozen=True)
class _ExecutionMetadata:
    execution_status: Any
    tool_status: str | None
    tool_error_kind: str | None
    refusal_reason: str | None
    supervisor_result_envelope_id: str | None
    supervisor_result_envelope_sha256: str | None
    supervisor_result_classification: str | None
    git_summary: Any | None


def _execution_status_for(status_source: str | None) -> Any:
    from rig_relay.runtime.tool_invocation_execution import RuntimeToolExecutionStatus

    match status_source:
        case "cached" | "completed" | "passed" | "success" | "timed_out":
            return RuntimeToolExecutionStatus.COMPLETED
        case "refused":
            return RuntimeToolExecutionStatus.REFUSED
        case "blocked":
            return RuntimeToolExecutionStatus.BLOCKED
        case "failed":
            return RuntimeToolExecutionStatus.FAILED
        case _:
            return RuntimeToolExecutionStatus.COMPLETED


def _git_output(cwd: str, *args: str) -> str | None:
    try:
        return (
            subprocess.check_output(
                ["git", *args], cwd=cwd, text=True, stderr=subprocess.DEVNULL
            ).strip()
            or None
        )
    except Exception:
        return None


def _dirty_file_paths(cwd: str) -> list[str] | None:
    try:
        status_out = subprocess.check_output(
            ["git", "status", "--porcelain=v1"],
            cwd=cwd,
            text=True,
            stderr=subprocess.DEVNULL,
        )
        from rig_relay.core.tools.base import BaseToolState
        from rig_relay.core.tools.builtins.git import GitStatus, GitToolConfig

        tool_inst = GitStatus(
            config_getter=lambda: GitToolConfig(), state=BaseToolState()
        )
        dirty_files, _, _, _, _ = tool_inst._parse_dirty_files(status_out)
        return sorted(dirty_files)
    except Exception:
        return None


def _dirty_file_count(cwd: str) -> int | None:
    dirty_paths = _dirty_file_paths(cwd)
    if dirty_paths is None:
        return None
    return len(dirty_paths)


def _resolve_status_source(runtime_result: Any, intent: Any) -> tuple[str | None, Any]:
    from rig_relay.runtime.tool_invocation_adapter import RuntimeToolName

    provider = getattr(runtime_result, "provider_tool_response", None)
    provider_status = getattr(provider, "status", None)
    provider_status_value = getattr(provider_status, "value", provider_status)
    if intent.tool_name == RuntimeToolName.CHECKPOINT and provider is not None:
        if not getattr(provider, "ok", True):
            provider_status_value = (
                "refused" if getattr(provider, "refusal_reason", None) else "failed"
            )
    status_value = getattr(runtime_result.status, "value", runtime_result.status)
    return provider_status_value or status_value, provider


def _build_git_summary(intent: Any, envelope: Any, provider: Any) -> Any | None:
    from rig_relay.runtime.tool_invocation_adapter import RuntimeToolName
    from rig_relay.runtime.tool_invocation_receipt import GitSummary

    if intent.tool_name not in {
        RuntimeToolName.GIT_STATUS,
        RuntimeToolName.GIT_DIFF,
        RuntimeToolName.GIT_LOG,
        RuntimeToolName.GIT_BRANCH,
        RuntimeToolName.GIT_SHOW,
        RuntimeToolName.GIT_LS_FILES,
        RuntimeToolName.CHECKPOINT,
    }:
        return None

    cwd = envelope.cwd or os.getcwd()
    branch_val = _git_output(cwd, "branch", "--show-current")
    head_val = _git_output(cwd, "rev-parse", "HEAD")
    dirty_paths = _dirty_file_paths(cwd)
    dirty_count = len(dirty_paths) if dirty_paths is not None else None
    bounded_stdout = None
    truncation_triggered = False
    redaction_triggered = False
    base_identity = None
    head_identity = None
    commit_identity = None
    checkpoint_receipt_sha256 = None
    changed_files_count = None
    changed_paths_list: list[str] = []

    if intent.tool_name == RuntimeToolName.GIT_STATUS:
        changed_paths_list = dirty_paths or []
        changed_files_count = len(changed_paths_list) or None

    if intent.tool_name in {RuntimeToolName.GIT_DIFF, RuntimeToolName.GIT_SHOW}:
        raw_stdout = getattr(provider, "stdout", "")
        if raw_stdout:
            bounded_stdout, truncation_triggered, redaction_triggered = bound_stdout(
                raw_stdout
            )
        changed_paths_list = list(intent.payload.get("paths") or [])
        changed_files_count = len(changed_paths_list) or None
        if intent.tool_name == RuntimeToolName.GIT_DIFF:
            base_identity = "HEAD"
            head_identity = "INDEX" if intent.payload.get("cached") else "WORKING_TREE"
        else:
            commit_identity = intent.payload.get("ref", "HEAD")
    elif intent.tool_name == RuntimeToolName.GIT_LOG:
        commit_identity = "HEAD"
        changed_paths_list = list(intent.payload.get("paths") or [])
        changed_files_count = len(changed_paths_list) or None
    elif intent.tool_name == RuntimeToolName.GIT_LS_FILES:
        changed_paths_list = list(intent.payload.get("paths") or [])
        changed_files_count = len(changed_paths_list) or None
    elif intent.tool_name == RuntimeToolName.CHECKPOINT and provider is not None:
        if getattr(provider, "ok", False):
            checkpoint_receipt_sha256 = getattr(provider, "artifact_sha256", None)
            changed_paths_list = list(getattr(provider, "files_committed", []))
            changed_files_count = len(changed_paths_list)
            commit_identity = getattr(provider, "commit_sha", None)

    return GitSummary(
        branch=branch_val,
        head=head_val,
        dirty_files_count=dirty_count,
        changed_files_count=changed_files_count,
        changed_paths=changed_paths_list,
        truncation_triggered=truncation_triggered,
        redaction_triggered=redaction_triggered,
        warnings=[],
        base_identity=base_identity,
        head_identity=head_identity,
        commit_identity=commit_identity,
        checkpoint_receipt_sha256=checkpoint_receipt_sha256,
        bounded_stdout=bounded_stdout,
    )


def _resolve_execution_metadata(
    runtime_result: Any, intent: Any, envelope: Any
) -> _ExecutionMetadata:
    from rig_relay.runtime.tool_invocation_adapter import RuntimeToolName
    from rig_relay.runtime.tool_invocation_execution import RuntimeToolExecutionStatus

    status_source, provider = _resolve_status_source(runtime_result, intent)
    execution_status = _execution_status_for(status_source)
    tool_status = None
    if not (
        intent.tool_name == RuntimeToolName.BASH_LEGACY
        and execution_status == RuntimeToolExecutionStatus.FAILED
    ):
        tool_status = status_source

    provider_refusal = getattr(provider, "refusal_reason", None)
    refusal_reason = provider_refusal or getattr(
        getattr(runtime_result, "refusal", None), "message", None
    )
    supervisor_result_envelope = getattr(provider, "supervisor_result_envelope", None)
    supervisor_result_envelope_id = None
    if isinstance(supervisor_result_envelope, dict):
        supervisor_result_envelope_id = supervisor_result_envelope.get("result_id")

    return _ExecutionMetadata(
        execution_status=execution_status,
        tool_status=tool_status,
        tool_error_kind=getattr(provider, "error_kind", None),
        refusal_reason=refusal_reason,
        supervisor_result_envelope_id=supervisor_result_envelope_id,
        supervisor_result_envelope_sha256=getattr(
            runtime_result, "supervisor_result_envelope_sha256", None
        ),
        supervisor_result_classification=getattr(
            runtime_result, "supervisor_result_classification", None
        ),
        git_summary=_build_git_summary(intent, envelope, provider),
    )


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
    metadata = _resolve_execution_metadata(runtime_result, intent, envelope)

    result = RuntimeToolExecutionResult(
        status=metadata.execution_status,
        invocation_id=envelope.invocation_id,
        intent_id=intent.intent_id,
        tool_name=intent.tool_name.value,
        envelope_schema_valid=True,
        tool_status=metadata.tool_status,
        tool_error_kind=metadata.tool_error_kind,
        receipt_sha256=None,
        duration_ms=duration,
        error_kind=metadata.tool_error_kind,
        refusal_reason=metadata.refusal_reason,
        tool_receipt_kind=tool_receipt_kind or intent.tool_name.value,
        tool_receipt_schema_version=(
            f"rig.relay.{(tool_receipt_kind or intent.tool_name.value)}_receipt.v1"
        ),
        changed_paths=changed_paths or [],
        supervisor_result_envelope_id=metadata.supervisor_result_envelope_id,
        supervisor_result_envelope_sha256=metadata.supervisor_result_envelope_sha256,
        supervisor_result_classification=metadata.supervisor_result_classification,
        git_summary=metadata.git_summary,
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
