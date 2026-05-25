"""Shared execution template for runtime tool invocations.

Extracted from tool_invocation_execution.py to eliminate duplicated
gating logic across the five execute_* methods. Provides a single
_execute_with_gating method that tool-specific executors delegate to.
"""

from __future__ import annotations

from pathlib import Path
import time
from typing import TYPE_CHECKING, Any

from rig_relay.runtime._lease_gate import (
    LeaseClaimOutcome,
    claim_mutation_lease,
    release_mutation_lease,
    resolve_coordination_root,
)
from rig_relay.runtime._result_builder import to_execution_result
from rig_relay.runtime.tool_invocation_adapter import (
    RuntimeToolIntent,
    RuntimeToolInvocationEnvelope,
    RuntimeToolInvocationStatus,
    RuntimeToolName,
)

if TYPE_CHECKING:
    from rig_relay.runtime.tool_invocation_execution import RuntimeToolExecutionResult


class _ExecutionTemplateMixin:
    """Shared execution template for runtime tool invocations.

    Used as a mixin on RuntimeToolExecutionRunner. Provides
    _execute_with_gating which encapsulates the common flow:
    tool-name gating, envelope preparation, schema validation,
    optional lease acquisition, tool execution, result construction,
    and receipt persistence.
    """

    async def _execute_with_gating(
        self: Any,
        intent: RuntimeToolIntent,
        resolution: Any,
        *,
        expected_tool: RuntimeToolName,
        unsupported_reason: str,
        needs_lease: bool = False,
        lease_file_path_attr: str = "",
        tool_receipt_kind: str | None = None,
    ) -> RuntimeToolExecutionResult:
        from rig_relay.runtime.tool_invocation_execution import (
            RuntimeToolExecutionResult,
            RuntimeToolExecutionStatus,
        )

        runner = self
        start = time.perf_counter()

        # Gate 1: tool name check
        if intent.tool_name != expected_tool:
            _result = RuntimeToolExecutionResult(
                status=RuntimeToolExecutionStatus.REFUSED,
                intent_id=intent.intent_id,
                tool_name=intent.tool_name.value,
                error_kind="unsupported_tool",
                refusal_reason=unsupported_reason,
            )
            runner._persist_if_configured(_result, None)
            return _result

        # Gate 2: adapter prepare
        envelope: RuntimeToolInvocationEnvelope = runner._adapter.prepare(
            intent, resolution
        )

        # Gate 3: blocked/refused
        if envelope.status == RuntimeToolInvocationStatus.BLOCKED:
            _result = RuntimeToolExecutionResult(
                status=RuntimeToolExecutionStatus.BLOCKED,
                intent_id=intent.intent_id,
                tool_name=intent.tool_name.value,
                error_kind=envelope.error_kind.value if envelope.error_kind else None,
                refusal_reason=envelope.refusal_reason,
            )
            runner._persist_if_configured(_result, envelope)
            return _result

        if envelope.status == RuntimeToolInvocationStatus.REFUSED:
            _result = RuntimeToolExecutionResult(
                status=RuntimeToolExecutionStatus.REFUSED,
                intent_id=intent.intent_id,
                tool_name=intent.tool_name.value,
                error_kind=envelope.error_kind.value if envelope.error_kind else None,
                refusal_reason=envelope.refusal_reason,
            )
            runner._persist_if_configured(_result, envelope)
            return _result

        # Gate 4: schema validation
        schema_valid, schema_errors = runner._validate_envelope_schema(envelope)
        if not schema_valid:
            _result = RuntimeToolExecutionResult(
                status=RuntimeToolExecutionStatus.FAILED,
                intent_id=intent.intent_id,
                tool_name=intent.tool_name.value,
                envelope_schema_valid=False,
                error_kind="envelope_schema_invalid",
                refusal_reason=(
                    f"Envelope failed schema validation: {'; '.join(schema_errors)}"
                ),
                duration_ms=(time.perf_counter() - start) * 1000,
            )
            runner._persist_if_configured(_result, envelope)
            return _result

        # Gate 5: optional lease acquisition
        lease_info: tuple[str, str, list[str]] | None = None
        coordination_root_path: Path | None = None
        if needs_lease:
            payload = envelope.payload or {}
            file_path = payload.get(lease_file_path_attr, "")
            coordination_root_path = resolve_coordination_root(
                worktree_path=envelope.worktree_path, repo_root=envelope.repo_root
            )
            lease_outcome: LeaseClaimOutcome = claim_mutation_lease(
                envelope=envelope,
                file_path=file_path,
                coordination_root=coordination_root_path,
            )
            if lease_outcome.blocked:
                _result = RuntimeToolExecutionResult(
                    status=RuntimeToolExecutionStatus.BLOCKED,
                    intent_id=lease_outcome.intent_id or intent.intent_id,
                    tool_name=lease_outcome.tool_name or intent.tool_name.value,
                    error_kind=lease_outcome.error_kind,
                    refusal_reason=lease_outcome.refusal_reason,
                )
                runner._persist_if_configured(_result, envelope)
                return _result
            lease_info = lease_outcome.lease_info if lease_outcome.granted else None

        # Execute tool with lease release in finally
        try:
            runtime_result = await runner._execute_runtime_tool(
                intent=intent, envelope=envelope
            )

            # ── Derive canonical agent outcome projection ──────────────
            agent_outcome: dict[str, Any] | None = None
            agent_outcome_schema_valid = False
            _projection_failure_kind: str | None = None
            try:
                from rig_relay.core.tools._agent_outcome import (
                    AgentToolOutcome,
                    derive_agent_outcome,
                )

                mutation_cls = expected_tool.mutation_class
                outcome: AgentToolOutcome = derive_agent_outcome(
                    runtime_result, mutation_cls
                )
                outcome_json = outcome.model_dump(mode="json")
                agent_outcome_schema_valid = True
                agent_outcome = outcome_json
            except Exception as exc:
                _projection_failure_kind = type(exc).__name__
                agent_outcome = {
                    "schema_version": "rig.relay.agent_tool_outcome.v1",
                    "tool_name": intent.tool_name.value,
                    "tool_call_id": getattr(runtime_result, "tool_call_id", ""),
                    "status": "degraded",
                    "error_kind": "agent_outcome_projection_failed",
                    "degraded_capabilities": ["agent_outcome_projection_failed"],
                    "mutation_disposition": "unknown",
                }
                agent_outcome_schema_valid = False

            payload = envelope.payload or {}
            _changed_paths: list[str] = []
            if needs_lease and lease_file_path_attr:
                fp = payload.get(lease_file_path_attr, "")
                if fp:
                    _changed_paths = [fp]
            _out = to_execution_result(
                runtime_result=runtime_result,
                intent=intent,
                envelope=envelope,
                start=start,
                changed_paths=_changed_paths,
                tool_receipt_kind=tool_receipt_kind,
                agent_outcome=agent_outcome,
                agent_outcome_schema_valid=agent_outcome_schema_valid,
            )
            runner._persist_if_configured(_out, envelope)
            return _out
        finally:
            if lease_info is not None and coordination_root_path is not None:
                session_id, task_id, paths = lease_info
                release_mutation_lease(
                    coordination_root=coordination_root_path,
                    session_id=session_id,
                    task_id=task_id,
                    paths=paths,
                )


__all__ = ["_ExecutionTemplateMixin"]
