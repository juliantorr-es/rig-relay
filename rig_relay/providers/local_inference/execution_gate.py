"""Manual execution gate for local inference.

Evaluates whether a manual local inference request is authorized.
Produces governed blocked/executed receipts. Never auto-executes.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
import json
import secrets
from typing import Any

from rig_relay.providers.local_inference.models import (
    ApprovedByMode,
    ExecutionStatusKind,
    ManualExecutionApproval,
    ManualExecutionRequest,
    ManualExecutionResponseReceipt,
    RequestClass,
)


def _new_execution_id() -> str:
    return f"exec_{secrets.token_hex(8)}"


def build_approval(
    *,
    approved_by: ApprovedByMode = ApprovedByMode.FIXTURE,
    scope_endpoint_hash: str = "",
    scope_task_profile: str = "",
    scope_request_class: RequestClass = RequestClass.CHAT,
    scope_max_prompt_bytes: int = 4096,
    scope_max_output_tokens: int = 512,
    scope_streaming_allowed: bool = False,
    scope_tool_calling_allowed: bool = False,
    scope_structured_output_allowed: bool = False,
    ttl_seconds: int = 300,
) -> ManualExecutionApproval:
    now = datetime.now(UTC)
    expires = now + timedelta(seconds=ttl_seconds)
    approval = ManualExecutionApproval(
        approval_id=f"appr_{secrets.token_hex(8)}",
        generated_at=now.isoformat(),
        expires_at=expires.isoformat(),
        ttl_seconds=ttl_seconds,
        approved_by=approved_by,
        scope_endpoint_hash=scope_endpoint_hash,
        scope_task_profile=scope_task_profile,
        scope_request_class=scope_request_class,
        scope_max_prompt_bytes=scope_max_prompt_bytes,
        scope_max_output_tokens=scope_max_output_tokens,
        scope_streaming_allowed=scope_streaming_allowed,
        scope_tool_calling_allowed=scope_tool_calling_allowed,
        scope_structured_output_allowed=scope_structured_output_allowed,
    )
    approval.approval_hash = compute_approval_hash(approval)
    return approval


def compute_approval_hash(approval: ManualExecutionApproval) -> str:
    payload = {
        "scope_endpoint_hash": approval.scope_endpoint_hash,
        "scope_task_profile": approval.scope_task_profile,
        "scope_request_class": approval.scope_request_class.value,
        "scope_max_prompt_bytes": approval.scope_max_prompt_bytes,
        "scope_max_output_tokens": approval.scope_max_output_tokens,
        "scope_streaming_allowed": approval.scope_streaming_allowed,
        "scope_tool_calling_allowed": approval.scope_tool_calling_allowed,
        "scope_structured_output_allowed": approval.scope_structured_output_allowed,
        "persistence_policy": approval.persistence_policy.value,
        "approved_by": approval.approved_by.value,
        "ttl_seconds": approval.ttl_seconds,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def evaluate_execution_gate(
    *,
    endpoint_configured: bool,
    endpoint_hash: str,
    selection_policy_result: dict[str, Any] | None,
    approval: ManualExecutionApproval | None,
    request: ManualExecutionRequest | None,
    now: str | None = None,
) -> ManualExecutionResponseReceipt:
    receipt = ManualExecutionResponseReceipt(
        execution_id=_new_execution_id(),
        request_id=request.request_id if request else "",
        generated_at=now or datetime.now(UTC).isoformat(),
        status=ExecutionStatusKind.BLOCKED,
        endpoint_hash=endpoint_hash,
        blocked_reasons=[],
    )
    _check_configured(endpoint_configured, receipt)
    _check_selection_policy(selection_policy_result, receipt)
    _check_approval(approval, receipt)
    _check_scope(approval, request, endpoint_hash, receipt)
    _check_request_bounds(request, approval, receipt)
    if not receipt.blocked_reasons:
        receipt.status = ExecutionStatusKind.EXECUTED
    return receipt


def build_blocked_receipt(
    blocked_reasons: list[str],
    *,
    request_or_none: ManualExecutionRequest | None = None,
    now: str | None = None,
) -> ManualExecutionResponseReceipt:
    return ManualExecutionResponseReceipt(
        execution_id=_new_execution_id(),
        request_id=request_or_none.request_id if request_or_none else "",
        generated_at=now or datetime.now(UTC).isoformat(),
        status=ExecutionStatusKind.BLOCKED,
        blocked_reasons=blocked_reasons,
        raw_prompt_persisted=False,
        raw_completion_persisted=False,
        automatic_agent_execution=False,
    )


def build_executed_receipt(
    request: ManualExecutionRequest,
    *,
    status: ExecutionStatusKind,
    completion_sha256: str = "",
    completion_byte_count: int = 0,
    output_token_count: int = 0,
    input_token_count: int = 0,
    latency_ms: int = 0,
    time_to_first_token_ms: int | None = None,
    error_class: str = "",
    selection_policy_status: str = "",
    model_safe_id: str = "",
    now: str | None = None,
) -> ManualExecutionResponseReceipt:
    return ManualExecutionResponseReceipt(
        execution_id=_new_execution_id(),
        request_id=request.request_id,
        generated_at=now or datetime.now(UTC).isoformat(),
        status=status,
        endpoint_hash=request.endpoint_hash,
        model_safe_id=model_safe_id,
        task_profile=request.task_profile,
        request_class=request.request_class.value,
        approval_id=request.approval_id,
        selection_policy_status=selection_policy_status,
        prompt_sha256=request.prompt_sha256,
        prompt_byte_count=request.prompt_byte_count,
        completion_sha256=completion_sha256,
        completion_byte_count=completion_byte_count,
        output_token_count=output_token_count,
        input_token_count=input_token_count,
        latency_ms=latency_ms,
        time_to_first_token_ms=time_to_first_token_ms,
        error_class=error_class,
        raw_prompt_persisted=False,
        raw_completion_persisted=False,
        automatic_agent_execution=False,
    )


def _check_configured(
    configured: bool, receipt: ManualExecutionResponseReceipt
) -> None:
    if not configured:
        receipt.blocked_reasons.append("endpoint_not_configured")


def _check_selection_policy(
    selection_policy_result: dict[str, Any] | None,
    receipt: ManualExecutionResponseReceipt,
) -> None:
    if selection_policy_result is None:
        receipt.blocked_reasons.append("no_selection_policy_result")
        return
    allowed = selection_policy_result.get("manual_selection_allowed", False)
    if not allowed:
        kind = selection_policy_result.get("result_kind", "unknown")
        receipt.blocked_reasons.append(f"selection_policy_not_manual_eligible ({kind})")


def _check_approval(
    approval: ManualExecutionApproval | None, receipt: ManualExecutionResponseReceipt
) -> None:
    if approval is None:
        receipt.blocked_reasons.append("approval_missing")
        return
    try:
        expires = datetime.fromisoformat(approval.expires_at)
    except (ValueError, TypeError):
        receipt.blocked_reasons.append("approval_invalid_expiry")
        return
    if datetime.now(UTC) > expires.replace(tzinfo=UTC):
        receipt.blocked_reasons.append("approval_expired")


def _check_scope(
    approval: ManualExecutionApproval | None,
    request: ManualExecutionRequest | None,
    endpoint_hash: str,
    receipt: ManualExecutionResponseReceipt,
) -> None:
    if approval is None or request is None:
        return
    if approval.scope_endpoint_hash and (approval.scope_endpoint_hash != endpoint_hash):
        receipt.blocked_reasons.append("endpoint_hash_mismatch")
    if approval.scope_task_profile and (
        approval.scope_task_profile != request.task_profile
    ):
        receipt.blocked_reasons.append("task_profile_mismatch")
    if approval.scope_request_class.value != request.request_class.value:
        receipt.blocked_reasons.append("request_class_mismatch")


def _check_request_bounds(
    request: ManualExecutionRequest | None,
    approval: ManualExecutionApproval | None,
    receipt: ManualExecutionResponseReceipt,
) -> None:
    if request is None or approval is None:
        return
    if request.prompt_byte_count > approval.scope_max_prompt_bytes:
        receipt.blocked_reasons.append("prompt_too_large")
    if request.max_output_tokens > approval.scope_max_output_tokens:
        receipt.blocked_reasons.append("output_tokens_too_large")
    if request.streaming_requested and not approval.scope_streaming_allowed:
        receipt.blocked_reasons.append("streaming_not_approved")
    if request.tool_calling_requested and not approval.scope_tool_calling_allowed:
        receipt.blocked_reasons.append("tool_calling_not_approved")
    if (
        request.structured_output_requested
        and not approval.scope_structured_output_allowed
    ):
        receipt.blocked_reasons.append("structured_output_not_approved")


__all__ = [
    "build_approval",
    "build_blocked_receipt",
    "build_executed_receipt",
    "compute_approval_hash",
    "evaluate_execution_gate",
]
