"""ToolExecutionBridge — tool proposal → execution boundary for local inference.

Provides a governed corridor from model-generated ToolCallProposals to the
ToolRuntime execution layer. Performs governance preflight before execution.

When session context is available and a ToolRuntime is wired: full execution
through ToolRuntime.execute_one() with session_id, turn_id, causation_id.

When session context is NOT available: stateless preflight only. Returns
pending_session_context status truthfully.

OMLX-informed: tool execution corridor pattern (Apache 2.0).
"""

from __future__ import annotations

import asyncio
import hashlib
import secrets
from typing import Any

from rig_relay.governance.governance_engine import GovernanceEngine
from rig_relay.local_inference.runtime._models import ToolCallProposal
from rig_relay.runtime.models import RuntimeCapabilityKind, RuntimeProviderTrustTier

_TOOL_CAPABILITY_MAP: dict[str, RuntimeCapabilityKind] = {
    "bash": RuntimeCapabilityKind.SHELL_PROPOSAL,
    "write_file": RuntimeCapabilityKind.FILE_WRITE_PROPOSAL,
    "search_replace": RuntimeCapabilityKind.PATCH_PROPOSAL,
}


class ToolExecutionBridge:
    """Governed bridge from tool proposals to execution.

    Performs preflight (governance legality check) for every proposal.
    When session context is bound and a ToolRuntime is wired, executes
    through ToolRuntime. When unbound, returns truthful pending_session_context
    status.
    """

    def __init__(self) -> None:
        self._session_context: dict[str, Any] | None = None
        self._bound: bool = False
        self._tool_runtime: Any = None
        self._executor: Any = None

    @property
    def has_session_context(self) -> bool:
        return self._bound and self._session_context is not None

    @property
    def has_executor(self) -> bool:
        return self._tool_runtime is not None or self._executor is not None

    def bind_session(self, session_context: dict[str, Any] | None) -> None:
        """Bind a session context for full tool execution.

        When None, the bridge operates in stateless-preflight-only mode.
        """
        self._session_context = session_context
        self._bound = session_context is not None

    def set_tool_runtime(self, runtime: Any) -> None:
        """Wire a ToolRuntime instance for governed tool execution.

        The runtime must expose an async execute_one(request) method
        that accepts a ToolRuntimeRequest and returns a ToolRuntimeResult.
        """
        self._tool_runtime = runtime
        self._executor = None

    def set_executor(self, executor: Any) -> None:
        """Wire a callable executor for tool execution.

        Accepts a callable that takes a ToolRuntimeRequest and returns
        an awaitable ToolRuntimeResult. Used when a full ToolRuntime
        is not available but a compatible executor exists.
        """
        self._executor = executor
        self._tool_runtime = None

    async def execute_proposal(
        self, proposal: ToolCallProposal, session_context: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Execute or preflight a single tool proposal.

        When session context is bound and an executor is wired, actually
        executes through ToolRuntime. Otherwise performs governance
        preflight only.

        Returns:
            dict with status, reason, and optional execution_result.
        """
        preflight = self._preflight_proposal(proposal)

        if preflight["status"] != "admitted_pending_execution":
            return preflight

        effective_context = session_context or self._session_context
        has_ctx = bool(effective_context) and self._bound

        if not has_ctx or effective_context is None:
            return {
                "status": "pending_session_context",
                "reason": (
                    "Tool proposal admitted through governance preflight. "
                    "Full execution through ToolRuntime requires session context. "
                    "Call bind_session() to wire context before executing."
                ),
                "preflight": preflight,
            }

        executor = self._tool_runtime or self._executor
        if executor is None:
            return {
                "status": "pending_session_context",
                "reason": (
                    "Tool proposal admitted through governance preflight. "
                    "Session context is bound but no ToolRuntime executor "
                    "is wired. Call set_tool_runtime() or set_executor() "
                    "to enable execution."
                ),
                "preflight": preflight,
            }

        return await self._execute_through_runtime(
            proposal, effective_context, executor, preflight
        )

    async def _execute_through_runtime(
        self,
        proposal: ToolCallProposal,
        context: dict[str, Any],
        executor: Any,
        preflight: dict[str, Any],
    ) -> dict[str, Any]:
        """Execute a preflight-admitted proposal through the ToolRuntime.

        Builds a ToolRuntimeRequest from the proposal and session context,
        calls execute_one(), captures the result, and emits evidence.
        """
        try:
            from rig_relay.core.tool_runtime_models import (
                ToolRuntimeExecutionMode,
                ToolRuntimeRequest,
            )
        except ImportError as e:
            return {
                "status": "failed",
                "reason": f"ToolRuntime import failed: {e}",
                "preflight": preflight,
            }

        session_id = context.get("session_id", "")
        turn_id = context.get("turn_id", "")
        causation_id = context.get("causation_id", "mlx_tool_execution")
        workspace_root = context.get("workspace_root", "")
        op_id = context.get("operation_id", _make_op_id())

        if not session_id:
            return {
                "status": "refused",
                "reason": "invalid_session_context",
                "preflight": preflight,
                "evidence_emitted": False,
            }

        request = ToolRuntimeRequest(
            tool_name=proposal.tool_name,
            tool_args=self._parse_args(proposal.arguments),
            tool_call_id=proposal.call_id,
            session_id=session_id,
            turn_id=turn_id,
            causation_id=causation_id,
            workspace_root=workspace_root,
            execution_mode=ToolRuntimeExecutionMode.MUTATION_EXECUTION,
        )

        try:
            if self._tool_runtime is not None:
                result = await self._tool_runtime.execute_one(request)
            else:
                result = await executor(request)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            terminal_outcome_id = secrets.token_hex(12)
            evidence_emitted = False
            try:
                evidence_emitted = self._emit_execution_evidence(
                    op_id, proposal, preflight, "failed", error=str(e)[:500]
                )
            except Exception:
                pass
            return {
                "status": "failed",
                "reason": f"ToolRuntime execution raised: {e}",
                "preflight": preflight,
                "evidence_emitted": evidence_emitted,
                "terminal_outcome_id": terminal_outcome_id,
                "execution_result": {"error": str(e)[:500]},
            }

        terminal_outcome_id = secrets.token_hex(12)
        status_value = result.status.value if hasattr(result, "status") else "unknown"
        evidence_emitted = False
        try:
            evidence_emitted = self._emit_execution_evidence(
                op_id,
                proposal,
                preflight,
                status_value,
                output_sha256=getattr(result, "receipt_refs", []),
                error=getattr(result, "error_message", None),
            )
        except Exception:
            pass

        mapped_status = _map_runtime_status(status_value)
        if not evidence_emitted and mapped_status == "executed":
            mapped_status = "executed_evidence_failed"

        return {
            "status": mapped_status,
            "reason": (f"Tool executed through ToolRuntime: {status_value}"),
            "preflight": preflight,
            "preflight_status": preflight.get("status"),
            "evidence_emitted": evidence_emitted,
            "terminal_outcome_id": terminal_outcome_id,
            "execution_result": result.to_debug_dict()
            if hasattr(result, "to_debug_dict")
            else {"status": status_value},
        }

    def _preflight_proposal(self, proposal: ToolCallProposal) -> dict[str, Any]:
        """Stateless governance preflight for a single tool proposal."""
        capability = _TOOL_CAPABILITY_MAP.get(proposal.tool_name)

        try:
            from rig_relay.local_inference.runtime._secrets import (
                scan_messages_for_secrets,
            )

            arg_scan = scan_messages_for_secrets([{"content": proposal.arguments}])
            if arg_scan["secrets_detected"]:
                return {"status": "refused", "reason": "secret_in_arguments"}
        except Exception:
            pass

        if capability is None:
            return {"status": "pending_review", "reason": "unknown_tool"}

        decision = GovernanceEngine.evaluate_action_legality(
            intent_id=proposal.call_id,
            intent_kind="tool_execution",
            requested_capabilities=[capability],
            provider_trust_tier=RuntimeProviderTrustTier.EXECUTOR_CANDIDATE,
            allow_mutation=True,
        )

        allowed = decision.decision.value == "allowed"
        return {
            "status": (
                "admitted_pending_execution" if allowed else "refused_by_governance"
            ),
            "reason": (
                str(decision.reasons[0].message)
                if decision.reasons
                else "preflight_complete"
            ),
            "governance_decision": decision.decision.value,
        }

    @staticmethod
    def _parse_args(arguments: str) -> dict[str, Any]:
        try:
            import json

            return json.loads(arguments)
        except Exception:
            return {"raw": arguments}

    @staticmethod
    def _emit_execution_evidence(
        op_id: str,
        proposal: ToolCallProposal,
        preflight: dict[str, Any],
        execution_status: str,
        output_sha256: Any = "",
        error: str | None = None,
    ) -> bool:
        from rig_relay.local_inference.runtime._evidence import (
            emit_tool_execution_outcome,
        )

        proposal_hash = (
            f"sha256:{hashlib.sha256(proposal.arguments.encode()).hexdigest()}"
        )
        payload: dict[str, Any] = {
            "schema_version": "rig.relay.runtime_execution_event.v1",
            "receipt_id": op_id,
            "operation_id": op_id,
            "task_id_hash": "",
            "status": execution_status,
            "prompt_sha256": "",
            "output_sha256": (
                output_sha256[0]
                if isinstance(output_sha256, list) and output_sha256
                else str(output_sha256)
                if output_sha256
                else ""
            ),
            "model_id_hash": "",
            "content_light": True,
            "proposal_hash": proposal_hash,
            "tool_name": proposal.tool_name,
            "call_id": proposal.call_id,
            "governance_preflight": preflight.get("governance_decision", ""),
        }
        if error:
            payload["error"] = error
        emit_tool_execution_outcome(op_id, payload)
        return True

    def build_projection(self) -> dict:
        return {
            "tool_execution_bridge": {
                "session_context_bound": self.has_session_context,
                "executor_wired": self.has_executor,
                "mode": (
                    "full_execution"
                    if self.has_session_context and self.has_executor
                    else "stateless_preflight_only"
                ),
                "tool_execution_authority": (
                    "ToolRuntime.execute_one()"
                    if self.has_session_context and self.has_executor
                    else "governance_preflight_only"
                ),
                "mode_detail": (
                    "Tool proposals are executed through ToolRuntime.execute_one() "
                    "with session context and governed evidence emission."
                )
                if self.has_session_context and self.has_executor
                else (
                    "Tool proposals are preflighted through GovernanceEngine. "
                    "Full execution through ToolRuntime requires session context "
                    "and an executor to be wired via set_tool_runtime() or set_executor()."
                ),
                "capability_count": len(_TOOL_CAPABILITY_MAP),
                "capability_names": list(_TOOL_CAPABILITY_MAP),
            }
        }


def _map_runtime_status(runtime_status: str) -> str:
    """Map ToolRuntimeStatus values to bridge status values."""
    mapping: dict[str, str] = {
        "completed": "executed",
        "cached": "executed",
        "refused": "refused",
        "approval_required": "refused",
        "failed": "failed",
        "timed_out": "failed",
        "skipped": "refused",
        "degraded": "executed_degraded",
    }
    return mapping.get(runtime_status, runtime_status)


def _make_op_id() -> str:
    from datetime import UTC, datetime

    return f"op_{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}_{secrets.token_hex(6)}"
