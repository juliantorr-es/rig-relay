"""ToolRuntime — governed tool execution boundary.

ToolRuntime owns the policy for tool execution: cache lookup,
permission enforcement, approval dispatch, patch proposal gating,
tool invocation, result classification, receipt emission, cache
storage, and context observation.

AgentLoop remains the turn conductor. It builds a
ToolRuntimeRequest, calls ToolRuntime.execute_one(), receives a
structured ToolRuntimeResult, adapts events, and records telemetry.

Graceful degradation is first-class: failures, refusals, cache
unavailability, receipt unavailability, and timeouts all produce
typed ToolRuntimeResult values.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Awaitable, Callable
from typing import Any

from rig_relay.core.logger import logger
from rig_relay.core.tool_runtime_models import (
    RefusalCode,
    ToolRuntimeApprovalStatus,
    ToolRuntimeCacheStatus,
    ToolRuntimeExecutionMode,
    ToolRuntimeRefusal,
    ToolRuntimeRequest,
    ToolRuntimeResult,
    ToolRuntimeStatus,
)
from rig_relay.core.tool_runtime_policy import ToolRuntimePolicy
from rig_relay.core.tool_subprocess import ToolSubprocessRunner
from rig_relay.core.tools.base import ToolPermissionError
from rig_relay.governance.decisions import GovernanceDecisionKind
from rig_relay.governance.governance_engine import GovernanceEngine
from rig_relay.runtime.models import RuntimeCapabilityKind
from rig_relay.runtime.supervisor_result import RuntimeSupervisorResultClassification

_TOOL_CAPABILITY_KINDS: dict[str, list[RuntimeCapabilityKind]] = {
    "bash": [RuntimeCapabilityKind.SHELL_PROPOSAL],
    "write_file": [RuntimeCapabilityKind.FILE_WRITE_PROPOSAL],
    "search_replace": [RuntimeCapabilityKind.PATCH_PROPOSAL],
    "checkpoint": [RuntimeCapabilityKind.COORDINATION_WRITE],
    "coordination": [RuntimeCapabilityKind.COORDINATION_WRITE],
    "behavior_patch": [RuntimeCapabilityKind.PATCH_PROPOSAL],
    "task": [RuntimeCapabilityKind.SHELL_PROPOSAL],
    "worktree": [RuntimeCapabilityKind.WORKTREE_WRITE],
}


def _get_profile_gate() -> Any | None:
    """Return the CapabilityGate singleton or None if the governance module is unavailable."""
    try:
        from rig_relay.governance.service_state import get_capability_gate

        return get_capability_gate()
    except ImportError:
        return None


# ── Callback signatures for dependency injection ──────────────────────


InvokeToolFn = Callable[[dict[str, Any]], AsyncGenerator[Any, None]]
"""Async generator yielding tool stream events then the final result model."""

CacheCheckFn = Callable[[str, dict[str, Any]], tuple[bool, Any | None]]

CacheStoreFn = Callable[[str, dict[str, Any], dict[str, Any]], None]

PermissionDecisionFn = Callable[[str, dict[str, Any], str], Awaitable[tuple[bool, str]]]
"""Returns (permitted: bool, reason: str). Skip reasons are returned as non-permitted."""

ApprovalRequestFn = Callable[[str, dict[str, Any], str], Awaitable[tuple[bool, str]]]

PatchGateCheckFn = Callable[[Any, Any], Any | None]
"""Returns a gating event if blocked, None if allowed. Takes (tool_call, tool_instance)."""

ExpandArgsFn = Callable[[dict[str, Any]], dict[str, Any]]

ReceiptBuildFn = Callable[[str, Any], Any | None]
"""Returns a receipt model or None. Takes (tool_name, result_model)."""

ReceiptCaptureFn = Callable[[str, str, dict[str, Any]], None]

ContextObserveFn = Callable[[str, str, dict[str, Any], bool], None]

StatsDeltaFn = Callable[[str, int], None]


async def _async_allow() -> tuple[bool, str]:
    return True, ""


async def _async_deny(
    tool_name: str, args_dict: dict[str, Any], call_id: str
) -> tuple[bool, str]:
    return False, "policy_object_missing"


class ToolRuntime:
    """Governed tool execution runtime.

    All I/O goes through injected callables. ToolRuntime owns the
    governance sequence:

        cache → permission → approval → patch gate → invoke →
        receipt → cache store → context observation → result

    AgentLoop only builds the request, calls execute_one(), adapts
    the returned events, and records provider telemetry.
    """

    def __init__(
        self,
        *,
        invoke_tool: InvokeToolFn | None = None,
        cache_check: CacheCheckFn | None = None,
        cache_store: CacheStoreFn | None = None,
        permission_decision: PermissionDecisionFn | None = None,
        approval_request: ApprovalRequestFn | None = None,
        patch_gate_check: PatchGateCheckFn | None = None,
        expand_args: ExpandArgsFn | None = None,
        receipt_build: ReceiptBuildFn | None = None,
        receipt_capture: ReceiptCaptureFn | None = None,
        context_observe: ContextObserveFn | None = None,
        stats_delta: StatsDeltaFn | None = None,
        subprocess_runner: ToolSubprocessRunner | None = None,
        trace_recorder: Any | None = None,
        source_label: str = "agent_loop",
        policy_object: ToolRuntimePolicy | None = None,
        telemetry_client: Any | None = None,
    ) -> None:
        self._invoke_tool = invoke_tool or self._default_invoke_tool
        self._cache_check = cache_check or (lambda t, a: (False, None))
        self._cache_store = cache_store or (lambda t, a, r: None)
        self.telemetry_client = telemetry_client

        # ── Governance callbacks: fail-closed by default ─────────
        if policy_object is not None:
            self._permission_decision = (
                permission_decision
                or policy_object.permission_decision
                or (lambda t, a, c: _async_deny(t, a, c))
            )
            self._approval_request = (
                approval_request
                or policy_object.approval_request
                or (lambda t, a, c: _async_deny(t, a, c))
            )
            self._patch_gate_check = (
                patch_gate_check
                or policy_object.patch_gate_check
                or (lambda tc, ti: "policy_object_missing")
            )
            self._governance_engine = policy_object.governance_engine
            self._council_enabled = policy_object.council_enabled
            self._local_action_envelope_required = (
                policy_object.local_action_envelope_required
            )
            self._dirty_guard_satisfied = policy_object.dirty_guard_satisfied
            self._policy_provided = True
            if self.telemetry_client is not None:
                self.telemetry_client.emit_governance_gate_decision(
                    gate="tool_runtime_policy",
                    decision="allowed",
                    reason="policy_object_present",
                    severity="info",
                )
        else:
            self._permission_decision = permission_decision or (
                lambda t, a, c: _async_deny(t, a, c)
            )
            self._approval_request = approval_request or (
                lambda t, a, c: _async_deny(t, a, c)
            )
            self._patch_gate_check = patch_gate_check or (
                lambda tc, ti: "policy_object_missing"
            )
            self._governance_engine = None
            self._council_enabled = False
            self._local_action_envelope_required = False
            self._dirty_guard_satisfied = False
            self._policy_provided = bool(permission_decision and approval_request)
            if self.telemetry_client is not None:
                self.telemetry_client.emit_governance_gate_decision(
                    gate="tool_runtime_policy",
                    decision="failed_closed",
                    reason="policy_object_missing",
                    severity="critical",
                    operator_action_required=True,
                    mutation_intent=True,
                )

        self._expand_args = expand_args or (lambda a: a)
        self._receipt_build = receipt_build or (lambda tn, rm: None)
        self._receipt_capture = receipt_capture or (lambda s, t, r: None)
        self._context_observe = context_observe or (lambda s, tn, a, bp: None)
        self._stats_delta = stats_delta or (lambda k, d: None)
        self._subprocess_runner = subprocess_runner
        self._trace_recorder = trace_recorder
        self._source_label = source_label

    # ── Public API ──────────────────────────────────────────────────

    async def execute_one(self, request: ToolRuntimeRequest) -> ToolRuntimeResult:
        """Execute a single tool call with full governance sequencing.

        Owns the entire path: cache → permission → approval →
        patch gate → invoke → receipt → cache store →
        context observation → classified result.

        Returns a structured ToolRuntimeResult. Events produced
        during invocation are collected in ``result.tool_events``
        for AgentLoop to forward.

        Never raises — all failures become FAILED or REFUSED results.
        """
        try:
            return await self._execute_governed(request)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning(
                "ToolRuntime unexpected error for %s: %s",
                request.tool_name,
                exc,
                exc_info=True,
            )
            return ToolRuntimeResult.failed(
                tool_name=request.tool_name,
                tool_call_id=request.tool_call_id,
                error_kind="unexpected_runtime_error",
                error_message=str(exc)[:500],
                degraded_capabilities=["tool_runtime_internal_error"],
            )

    # ── Internal helpers ─────────────────────────────────────────

    @staticmethod
    def _finish_span(
        recorder: Any, span: Any, ts: Any, status: Any, attrs: dict[str, Any]
    ) -> None:
        """Close a trace span. No-op if recorder or span is None."""
        if recorder is not None and span is not None:
            recorder.end_span(span, status=status, attributes=attrs)

    @staticmethod
    def _emit_policy_missing_event(
        *, tool_name: str, session_id: str | None, turn_id: str | None
    ) -> None:
        logger.warning(
            "governance.tool_runtime_policy_missing session_id=%s turn_id=%s "
            "tool_name=%s severity=critical",
            session_id or "",
            turn_id or "",
            tool_name,
        )

    # ── Internal sequence ───────────────────────────────────────────

    async def _execute_governed(self, request: ToolRuntimeRequest) -> ToolRuntimeResult:
        tn = request.tool_name
        cid = request.tool_call_id
        tool_meta = dict(request.audit_context)
        tool_meta.update(request.policy_hints)
        tool_meta["source_kind"] = request.source_kind or self._source_label
        tool_meta["source_id"] = request.source_id
        tool_meta["invocation_id"] = request.invocation_id
        tool_meta["session_id"] = request.session_id
        tool_meta["lane_id"] = request.lane_id
        tool_meta["lease_id"] = request.lease_id
        tool_meta["workspace_root"] = request.workspace_root
        tool_meta["worktree_path"] = request.worktree_path
        tool_meta["actor"] = request.actor
        tool_meta["runtime_envelope_sha256"] = request.runtime_envelope_sha256
        if self._subprocess_runner is not None:
            tool_meta["subprocess_runner"] = self._subprocess_runner

        # ── Start tracing span ────────────────────────────────
        trace_span: Any = None
        trace_status: Any = None
        recorder: Any = None
        if self._trace_recorder is not None:
            recorder = self._trace_recorder
            from rig_relay.tracing.models import TraceStatus as _TS

            trace_status = _TS
            trace_span = recorder.start_span(
                "tool_runtime.execute_one",
                attributes={
                    "tool.name": tn,
                    "tool.call_id": cid,
                    "rig.runtime_source": request.source_kind or self._source_label,
                    "rig.execution_mode": str(request.execution_mode),
                },
            )

        # ── Span finalizer helper ──────────────────────────────
        def _finalize_span(
            status_str: str = "error",
            attrs: dict[str, Any] | None = None,
            error: str | None = None,
        ) -> None:
            if trace_span is None or recorder is None or trace_status is None:
                return
            status_map = {
                "ok": trace_status.ok,
                "error": trace_status.error,
                "refused": trace_status.refused,
                "cancelled": trace_status.cancelled,
                "timed_out": trace_status.timed_out,
                "degraded": trace_status.degraded,
            }
            end_attrs = dict(attrs or {})
            end_status = status_map.get(status_str, trace_status.error)
            recorder.end_span(
                trace_span, status=end_status, attributes=end_attrs, error=error
            )

        # ── 1. Profile gate check ─────────────────────────────
        is_mutation = request.execution_mode in {
            ToolRuntimeExecutionMode.MUTATION_EXECUTION,
            ToolRuntimeExecutionMode.MUTATION_PROPOSAL,
        }
        profile_gate = _get_profile_gate()
        if profile_gate is not None:
            allowed, reason = profile_gate.check_tool_execution(
                tool_name=tn, execution_mode=request.execution_mode
            )
            if not allowed:
                if self.telemetry_client is not None:
                    self.telemetry_client.emit_governance_gate_decision(
                        gate="profile_gate",
                        decision="blocked",
                        reason="capability_gated",
                        tool_name=tn,
                        mutation_intent=is_mutation,
                        severity="warning",
                        turn_id=request.turn_id or "",
                    )
                self._stats_delta("tool_calls_rejected", 1)
                _finalize_span(
                    status_str="refused",
                    attrs={
                        "tool.status": "refused",
                        "tool.refusal_code": "capability_gated",
                    },
                )
                return ToolRuntimeResult.refused(
                    tool_name=tn,
                    tool_call_id=cid,
                    refusal=ToolRuntimeRefusal(
                        refusal_code=RefusalCode.CAPABILITY_GATED,
                        message=f"Profile gate: {reason}",
                        recoverable=True,
                        suggested_next_action="Unlock the profile to enable mutation tools",
                    ),
                    approval_status=ToolRuntimeApprovalStatus.DENIED,
                ).model_copy(
                    update={
                        "source_kind": request.source_kind,
                        "source_id": request.source_id,
                        "runtime_envelope_sha256": request.runtime_envelope_sha256,
                    }
                )
            elif self.telemetry_client is not None:
                self.telemetry_client.emit_governance_gate_decision(
                    gate="profile_gate",
                    decision="allowed",
                    reason="profile_unlocked",
                    tool_name=tn,
                    severity="info",
                    turn_id=request.turn_id or "",
                )

        # ── 1.6. Governance engine check for mutation tools ────
        if request.execution_mode in {
            ToolRuntimeExecutionMode.MUTATION_EXECUTION,
            ToolRuntimeExecutionMode.MUTATION_PROPOSAL,
        }:
            caps = _TOOL_CAPABILITY_KINDS.get(tn.lower(), [])
            decision = GovernanceEngine.evaluate_action_legality(
                workspace_id=request.workspace_root,
                intent_id=cid,
                intent_kind="tool_execution",
                requested_capabilities=caps,
                allow_mutation=True,
            )
            if decision.decision == GovernanceDecisionKind.BLOCKED:
                block_msg = (
                    decision.blocked_intents[0].reason
                    if decision.blocked_intents
                    else "Governance blocked"
                )
                if self.telemetry_client is not None:
                    self.telemetry_client.emit_governance_gate_decision(
                        gate="governance_engine",
                        decision="blocked",
                        reason=block_msg,
                        tool_name=tn,
                        mutation_intent=True,
                        severity="warning",
                        turn_id=request.turn_id or "",
                    )
                self._stats_delta("tool_calls_rejected", 1)
                _finalize_span(
                    status_str="refused",
                    attrs={
                        "tool.status": "refused",
                        "tool.refusal_code": "governance_blocked",
                    },
                )
                return ToolRuntimeResult.refused(
                    tool_name=tn,
                    tool_call_id=cid,
                    refusal=ToolRuntimeRefusal(
                        refusal_code=RefusalCode.CAPABILITY_GATED,
                        message=f"Governance blocked: {block_msg}",
                        recoverable=True,
                        suggested_next_action="Resolve governance gates before retrying",
                    ),
                    approval_status=ToolRuntimeApprovalStatus.DENIED,
                ).model_copy(
                    update={
                        "source_kind": request.source_kind,
                        "source_id": request.source_id,
                        "runtime_envelope_sha256": request.runtime_envelope_sha256,
                    }
                )
            elif self.telemetry_client is not None:
                self.telemetry_client.emit_governance_gate_decision(
                    gate="governance_engine",
                    decision="allowed",
                    reason="all_checks_passed",
                    tool_name=tn,
                    severity="info",
                    turn_id=request.turn_id or "",
                )

        # ── 1.7. Local action envelope gate ────────────────────
        if request.execution_mode == ToolRuntimeExecutionMode.MUTATION_EXECUTION:
            from rig_relay.governance.local_action_gate import require_signed_envelope

            capability = f"tool:{tn}"
            decision = require_signed_envelope(
                action=tn,
                payload=request.tool_args,
                required_capability=capability,
                envelope=request.local_action_envelope,
            )
            if decision.decision != GovernanceDecisionKind.ALLOWED:
                reason_msg = (
                    decision.reasons[0].message if decision.reasons else "blocked"
                )
                if self.telemetry_client is not None:
                    self.telemetry_client.emit_governance_gate_decision(
                        gate="rig_relay.gate.local_action_envelope",
                        decision="blocked",
                        reason=reason_msg,
                        tool_name=tn,
                        mutation_intent=True,
                        severity="error",
                        turn_id=request.turn_id or "",
                    )
                self._stats_delta("tool_calls_rejected", 1)
                _finalize_span(
                    status_str="refused",
                    attrs={
                        "tool.status": "refused",
                        "tool.refusal_code": "local_action_envelope_required",
                    },
                )
                return ToolRuntimeResult.refused(
                    tool_name=tn,
                    tool_call_id=cid,
                    refusal=ToolRuntimeRefusal(
                        refusal_code=RefusalCode.LOCAL_ACTION_ENVELOPE_REQUIRED,
                        message=f"Local action envelope required: {reason_msg}",
                        recoverable=True,
                        suggested_next_action=(
                            "Provide a valid signed local action envelope"
                        ),
                    ),
                    approval_status=ToolRuntimeApprovalStatus.DENIED,
                ).model_copy(
                    update={
                        "source_kind": request.source_kind,
                        "source_id": request.source_id,
                        "runtime_envelope_sha256": request.runtime_envelope_sha256,
                    }
                )
            elif self.telemetry_client is not None:
                self.telemetry_client.emit_governance_gate_decision(
                    gate="rig_relay.gate.local_action_envelope",
                    decision="allowed",
                    reason="envelope_verified",
                    tool_name=tn,
                    mutation_intent=True,
                    severity="info",
                    turn_id=request.turn_id or "",
                )

        # ── 2. Permission check ─────────────────────────────────
        if not request.bypass_permissions:
            permitted, reason = await self._permission_decision(
                tn, request.tool_args, cid
            )
            if not permitted:
                if reason == "policy_object_missing" and not self._policy_provided:
                    self._emit_policy_missing_event(
                        tool_name=tn,
                        session_id=request.session_id,
                        turn_id=request.turn_id,
                    )
                if self.telemetry_client is not None:
                    self.telemetry_client.emit_governance_gate_decision(
                        gate="permission_check",
                        decision="blocked",
                        reason=reason or "permission_denied",
                        tool_name=tn,
                        mutation_intent=is_mutation,
                        severity="warning",
                        turn_id=request.turn_id or "",
                    )
                self._stats_delta("tool_calls_rejected", 1)
                _finalize_span(
                    status_str="refused",
                    attrs={
                        "tool.status": "refused",
                        "tool.refusal_code": "permission_denied",
                    },
                )
                return ToolRuntimeResult.refused(
                    tool_name=tn,
                    tool_call_id=cid,
                    refusal=ToolRuntimeRefusal(
                        refusal_code=RefusalCode.TOOL_PERMISSION_DENIED,
                        message=reason or f"Permission denied for '{tn}'",
                        recoverable=True,
                        suggested_next_action="Adjust tool permissions or request approval",
                    ),
                    approval_status=ToolRuntimeApprovalStatus.DENIED,
                ).model_copy(
                    update={
                        "source_kind": request.source_kind,
                        "source_id": request.source_id,
                        "runtime_envelope_sha256": request.runtime_envelope_sha256,
                    }
                )
            elif self.telemetry_client is not None:
                self.telemetry_client.emit_governance_gate_decision(
                    gate="permission_check",
                    decision="allowed",
                    reason="permission_granted",
                    tool_name=tn,
                    severity="info",
                    turn_id=request.turn_id or "",
                )

        # ── 3. Approval request ─────────────────────────────────
        approved, reason = await self._approval_request(tn, request.tool_args, cid)
        if not approved:
            if self.telemetry_client is not None:
                if "unavailable" in (reason or "").lower():
                    self.telemetry_client.emit_governance_gate_decision(
                        gate="approval_request",
                        decision="failed_closed",
                        reason="approval_unavailable",
                        tool_name=tn,
                        mutation_intent=is_mutation,
                        severity="critical",
                        turn_id=request.turn_id or "",
                    )
                else:
                    self.telemetry_client.emit_governance_gate_decision(
                        gate="approval_request",
                        decision="refused",
                        reason=reason or "approval_denied",
                        tool_name=tn,
                        mutation_intent=is_mutation,
                        severity="warning",
                        turn_id=request.turn_id or "",
                    )
            self._stats_delta("tool_calls_rejected", 1)
            _finalize_span(
                status_str="refused",
                attrs={
                    "tool.status": "refused",
                    "tool.refusal_code": "approval_denied",
                },
            )
            return ToolRuntimeResult.refused(
                tool_name=tn,
                tool_call_id=cid,
                refusal=ToolRuntimeRefusal(
                    refusal_code=RefusalCode.APPROVAL_DENIED,
                    message=reason or f"Approval denied for '{tn}'",
                    recoverable=True,
                    suggested_next_action="Request user approval",
                ),
                approval_status=ToolRuntimeApprovalStatus.DENIED,
            ).model_copy(
                update={
                    "source_kind": request.source_kind,
                    "source_id": request.source_id,
                    "runtime_envelope_sha256": request.runtime_envelope_sha256,
                }
            )
        elif self.telemetry_client is not None:
            self.telemetry_client.emit_governance_gate_decision(
                gate="approval_request",
                decision="allowed",
                reason="approved",
                tool_name=tn,
                severity="info",
                turn_id=request.turn_id or "",
            )

        # ── 4. Patch gate ───────────────────────────────────────
        gating = self._patch_gate_check(request, None)
        if gating is not None:
            if self.telemetry_client is not None:
                self.telemetry_client.emit_governance_gate_decision(
                    gate="patch_gate",
                    decision="blocked",
                    reason="patch_proposal_required",
                    tool_name=tn,
                    mutation_intent=True,
                    severity="warning",
                    turn_id=request.turn_id or "",
                )
            self._stats_delta("tool_calls_rejected", 1)
            _finalize_span(
                status_str="refused",
                attrs={"tool.status": "refused", "tool.refusal_code": "patch_gate"},
            )
            return ToolRuntimeResult.refused(
                tool_name=tn,
                tool_call_id=cid,
                refusal=ToolRuntimeRefusal(
                    refusal_code=RefusalCode.PATCH_PROPOSAL_REQUIRED,
                    message="Patch proposal required for mutation tool",
                    recoverable=True,
                    suggested_next_action="Submit a patch proposal instead",
                ),
                approval_status=ToolRuntimeApprovalStatus.NOT_REQUIRED,
            ).model_copy(
                update={
                    "source_kind": request.source_kind,
                    "source_id": request.source_id,
                    "runtime_envelope_sha256": request.runtime_envelope_sha256,
                }
            )
        elif self.telemetry_client is not None:
            self.telemetry_client.emit_governance_gate_decision(
                gate="patch_gate",
                decision="allowed",
                reason="no_patch_proposal_needed",
                tool_name=tn,
                severity="info",
                turn_id=request.turn_id or "",
            )

        self._stats_delta("tool_calls_agreed", 1)

        # ── 4.5. Cache check (after all governance, before invocation) ──
        hit, cached = self._cache_check(tn, request.tool_args)
        if trace_span is not None:
            trace_span.event("tool_runtime.cache_check", attributes={"cache.hit": hit})
        if hit and cached is not None:
            self._stats_delta("tool_calls_succeeded", 1)
            _finalize_span(
                status_str="ok", attrs={"tool.status": "cached", "cache.hit": True}
            )
            return ToolRuntimeResult.cached_result(
                tool_name=tn, tool_call_id=cid, provider_tool_response=cached
            ).model_copy(
                update={
                    "source_kind": request.source_kind,
                    "source_id": request.source_id,
                    "runtime_envelope_sha256": request.runtime_envelope_sha256,
                }
            )

        # ── 5. Invoke tool ──────────────────────────────────────
        expanded_args = self._expand_args(request.tool_args)
        expanded_args["_tool_runtime_name"] = tn
        expanded_args["_tool_runtime_call_id"] = cid
        tool_events: list[Any] = []
        result_model = None
        start_time = asyncio.get_event_loop().time()

        try:
            expanded_args["_tool_runtime_meta"] = tool_meta
            async for item in self._invoke_tool(expanded_args):
                if hasattr(item, "model_dump"):
                    result_model = item
                else:
                    tool_events.append(item)
        except asyncio.CancelledError:
            raise
        except ToolPermissionError:
            self._stats_delta("tool_calls_agreed", -1)
            self._stats_delta("tool_calls_rejected", 1)
            _finalize_span(
                status_str="refused",
                attrs={
                    "tool.status": "refused",
                    "tool.refusal_code": "tool_permission_error",
                },
            )
            return ToolRuntimeResult.refused(
                tool_name=tn,
                tool_call_id=cid,
                refusal=ToolRuntimeRefusal(
                    refusal_code=RefusalCode.TOOL_PERMISSION_DENIED,
                    message=f"ToolPermissionError during '{tn}'",
                    recoverable=False,
                ),
                approval_status=ToolRuntimeApprovalStatus.DENIED,
            ).model_copy(
                update={
                    "source_kind": request.source_kind,
                    "source_id": request.source_id,
                    "runtime_envelope_sha256": request.runtime_envelope_sha256,
                }
            )
        except Exception as exc:
            self._stats_delta("tool_calls_failed", 1)
            _finalize_span(
                status_str="error",
                attrs={
                    "tool.status": "failed",
                    "tool.error_kind": "tool_invocation_failed",
                },
                error=f"{tn} failed: {exc}"[:500],
            )
            return ToolRuntimeResult.failed(
                tool_name=tn,
                tool_call_id=cid,
                error_kind="tool_invocation_failed",
                error_message=f"{tn} failed: {exc}"[:500],
                refusal=ToolRuntimeRefusal(
                    refusal_code=RefusalCode.TOOL_INVOCATION_FAILED,
                    message=str(exc)[:200],
                    recoverable=True,
                ),
            ).model_copy(
                update={
                    "source_kind": request.source_kind,
                    "source_id": request.source_id,
                    "runtime_envelope_sha256": request.runtime_envelope_sha256,
                }
            )

        duration = asyncio.get_event_loop().time() - start_time

        if result_model is None:
            self._stats_delta("tool_calls_failed", 1)
            _finalize_span(
                status_str="error",
                attrs={"tool.status": "failed", "tool.error_kind": "no_result"},
                error="Tool did not yield a result",
            )
            return ToolRuntimeResult.failed(
                tool_name=tn,
                tool_call_id=cid,
                error_kind="tool_invocation_failed",
                error_message="Tool did not yield a result",
                refusal=ToolRuntimeRefusal(
                    refusal_code=RefusalCode.TOOL_INVOCATION_FAILED,
                    message="Tool did not yield a result",
                    recoverable=False,
                ),
            ).model_copy(
                update={
                    "source_kind": request.source_kind,
                    "source_id": request.source_id,
                    "runtime_envelope_sha256": request.runtime_envelope_sha256,
                }
            )

        # ── 6. Receipt ──────────────────────────────────────────
        try:
            receipt = self._receipt_build(tn, result_model)
            if receipt is not None:
                self._receipt_capture(
                    request.session_id or "", tn, receipt.model_dump(mode="json")
                )
        except Exception:
            logger.warning("Receipt capture failed for %s", tn, exc_info=True)

        # ── 7. Cache store ──────────────────────────────────────
        cache_status = ToolRuntimeCacheStatus.MISS
        try:
            self._cache_store(
                tn, request.tool_args, result_model.model_dump(mode="json")
            )
        except Exception:
            cache_status = ToolRuntimeCacheStatus.WRITE_FAILED

        # ── 8. Context observation ──────────────────────────────
        obs_status = "succeeded"
        try:
            self._context_observe("succeeded", tn, request.tool_args, False)
        except Exception:
            obs_status = "context_observation_failed"

        # ── 9. Classify result ──────────────────────────────────
        self._stats_delta("tool_calls_succeeded", 1)

        degraded: list[str] = []
        if cache_status == ToolRuntimeCacheStatus.WRITE_FAILED:
            degraded.append("cache_write_failed")
        if obs_status == "context_observation_failed":
            degraded.append("context_observation_failed")

        status = ToolRuntimeStatus.DEGRADED if degraded else ToolRuntimeStatus.COMPLETED
        supervisor_result = getattr(result_model, "supervisor_result_envelope", None)
        supervisor_result_sha256 = getattr(
            result_model, "supervisor_result_envelope_sha256", None
        )
        supervisor_result_classification = getattr(
            result_model, "supervisor_result_classification", None
        )
        if supervisor_result_classification is None and supervisor_result is not None:
            supervisor_result_classification = supervisor_result.get("classification")
        if supervisor_result_sha256 is None and supervisor_result is not None:
            supervisor_result_sha256 = supervisor_result.get("result_id")

        if trace_span is not None:
            trace_end_status = trace_status.ok
            if supervisor_result_classification is not None:
                match RuntimeSupervisorResultClassification(
                    str(supervisor_result_classification)
                ):
                    case RuntimeSupervisorResultClassification.COMPLETED:
                        trace_end_status = trace_status.ok
                    case RuntimeSupervisorResultClassification.CANCELLED:
                        trace_end_status = trace_status.cancelled
                    case RuntimeSupervisorResultClassification.TIMED_OUT:
                        trace_end_status = trace_status.timed_out
                    case RuntimeSupervisorResultClassification.REFUSED:
                        trace_end_status = trace_status.refused
                    case _:
                        trace_end_status = trace_status.error
            end_status = (
                trace_end_status
                if status == ToolRuntimeStatus.COMPLETED
                else trace_status.degraded
            )
            end_attrs: dict[str, Any] = {
                "tool.status": status,
                "tool.degraded": bool(degraded),
            }
            if supervisor_result_classification is not None:
                end_attrs["tool.supervisor_result_classification"] = str(
                    supervisor_result_classification
                )
            if supervisor_result_sha256 is not None:
                end_attrs["tool.supervisor_result_envelope_sha256"] = (
                    supervisor_result_sha256
                )
            if supervisor_result is not None and supervisor_result.get("result_id"):
                end_attrs["tool.supervisor_result_envelope_id"] = supervisor_result[
                    "result_id"
                ]
            recorder.end_span(trace_span, status=end_status, attributes=end_attrs)

        return ToolRuntimeResult(
            status=status,
            tool_name=tn,
            tool_call_id=cid,
            source_kind=request.source_kind,
            source_id=request.source_id,
            runtime_envelope_sha256=request.runtime_envelope_sha256,
            provider_tool_response=result_model,
            tool_events=tool_events,
            cache_status=cache_status,
            approval_status=ToolRuntimeApprovalStatus.APPROVED,
            context_observation_status=obs_status,
            execution_enabled=True,
            mutation_performed=False,
            degraded_capabilities=degraded,
            duration_ms=duration * 1000,
            receipt_refs=[],
            supervisor_result_envelope_id=(
                supervisor_result.get("result_id") if supervisor_result else None
            ),
            supervisor_result_envelope_sha256=supervisor_result_sha256,
            supervisor_result_classification=supervisor_result_classification,
        )

    @staticmethod
    async def _default_invoke_tool(
        args_dict: dict[str, Any],
    ) -> AsyncGenerator[Any, None]:
        if False:
            yield
