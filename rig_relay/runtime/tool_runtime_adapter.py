"""Adapter from runtime tool intents to ToolRuntime requests."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json

from rig_relay.core.tool_runtime_models import (
    ToolRuntimeExecutionMode,
    ToolRuntimeRequest,
)
from rig_relay.core.tool_runtime_policy import ToolRuntimePolicy
from rig_relay.runtime.tool_invocation_adapter import (
    RuntimeToolInvocationEnvelope,
    RuntimeToolName,
)

_MUTATION_TOOLS: frozenset[str] = frozenset({"search_replace", "write_file"})
_SHELL_TOOLS: frozenset[str] = frozenset({"bash"})
_READ_ONLY_TOOLS: frozenset[str] = frozenset({"validate"})
_NON_WORKSPACE_MUTATING_PROPOSAL_TOOLS: frozenset[str] = frozenset({
    "search_replace_proposal"
})
_COORDINATION_STATE_MUTATION_TOOLS: frozenset[str] = frozenset({
    "create_pending_search_replace_proposal"
})
_ADMITTED_NON_EXECUTION_TOOLS: frozenset[str] = (
    _READ_ONLY_TOOLS
    | _NON_WORKSPACE_MUTATING_PROPOSAL_TOOLS
    | _COORDINATION_STATE_MUTATION_TOOLS
)


@dataclass(frozen=True)
class RuntimeToolRuntimeRequestBundle:
    request: ToolRuntimeRequest
    runtime_envelope_sha256: str


class RuntimeToolRuntimeAdapter:
    """Translate runtime envelopes into governed ToolRuntime requests."""

    def build_request(
        self,
        envelope: RuntimeToolInvocationEnvelope,
        *,
        actor: str | None = None,
        trust_tier: str | None = None,
    ) -> RuntimeToolRuntimeRequestBundle:
        payload = dict(envelope.payload or {})
        runtime_envelope_sha256 = hashlib.sha256(
            json.dumps(envelope.model_dump(mode="json"), sort_keys=True).encode()
        ).hexdigest()
        request = ToolRuntimeRequest(
            tool_name=self._map_tool_name(envelope.tool_name),
            tool_args=payload,
            tool_call_id=envelope.invocation_id,
            source_kind="runtime_intent",
            source_id=envelope.intent_id,
            invocation_id=envelope.invocation_id,
            turn_id=envelope.task_id,
            session_id=envelope.session_id,
            agent_id=envelope.agent_id,
            lane_id=envelope.lane_id,
            lease_id=envelope.lease_id,
            workspace_root=envelope.repo_root,
            worktree_path=envelope.worktree_path,
            actor=actor,
            execution_mode=self._execution_mode(envelope.tool_name),
            context_envelope_id=envelope.invocation_id,
            audit_context={
                "runtime_intent_id": envelope.intent_id,
                "invocation_id": envelope.invocation_id,
                "runtime_source": "runtime_tool_intent",
                "trust_tier": trust_tier,
            },
            runtime_envelope_sha256=runtime_envelope_sha256,
            receipt_context={
                "runtime_intent_id": envelope.intent_id,
                "invocation_id": envelope.invocation_id,
            },
            policy_hints={
                "mutation_class": self._mutation_class(envelope.tool_name),
                "determinism_class": self._determinism_class(envelope.tool_name),
                "approval_required": self._approval_required(envelope.tool_name),
                "patch_proposal_required": self._patch_proposal_required(
                    envelope.tool_name
                ),
            },
        )
        return RuntimeToolRuntimeRequestBundle(
            request=request, runtime_envelope_sha256=runtime_envelope_sha256
        )

    def _map_tool_name(self, tool_name: RuntimeToolName) -> str:
        match tool_name:
            case RuntimeToolName.VALIDATE:
                return "validate"
            case RuntimeToolName.SEARCH_REPLACE:
                return "search_replace"
            case RuntimeToolName.SEARCH_REPLACE_PROPOSAL:
                return "search_replace_proposal"
            case RuntimeToolName.CREATE_PENDING_SEARCH_REPLACE_PROPOSAL:
                return "create_pending_search_replace_proposal"
            case RuntimeToolName.WRITE_FILE:
                return "write_file"
            case RuntimeToolName.BASH_LEGACY:
                return "bash"
            case _:
                return tool_name.value

    def _execution_mode(self, tool_name: RuntimeToolName) -> ToolRuntimeExecutionMode:
        if tool_name == RuntimeToolName.VALIDATE:
            return ToolRuntimeExecutionMode.READ_ONLY
        if tool_name == RuntimeToolName.SEARCH_REPLACE_PROPOSAL:
            return ToolRuntimeExecutionMode.MUTATION_PROPOSAL
        if tool_name == RuntimeToolName.CREATE_PENDING_SEARCH_REPLACE_PROPOSAL:
            return ToolRuntimeExecutionMode.MUTATION_PROPOSAL
        if tool_name in {RuntimeToolName.SEARCH_REPLACE, RuntimeToolName.WRITE_FILE}:
            return ToolRuntimeExecutionMode.MUTATION_EXECUTION
        if tool_name == RuntimeToolName.BASH_LEGACY:
            return ToolRuntimeExecutionMode.UNKNOWN
        return ToolRuntimeExecutionMode.UNKNOWN

    def _mutation_class(self, tool_name: RuntimeToolName) -> str:
        if tool_name == RuntimeToolName.VALIDATE:
            return "read_only"
        if tool_name == RuntimeToolName.SEARCH_REPLACE_PROPOSAL:
            return "read_only"
        if tool_name == RuntimeToolName.CREATE_PENDING_SEARCH_REPLACE_PROPOSAL:
            return "coordination_state_mutation"
        if tool_name == RuntimeToolName.BASH_LEGACY:
            return "shell"
        return "filesystem_mutation"

    def _determinism_class(self, tool_name: RuntimeToolName) -> str:
        if tool_name == RuntimeToolName.VALIDATE:
            return "deterministic"
        if tool_name == RuntimeToolName.SEARCH_REPLACE_PROPOSAL:
            return "deterministic"
        if tool_name == RuntimeToolName.CREATE_PENDING_SEARCH_REPLACE_PROPOSAL:
            return "deterministic"
        if tool_name == RuntimeToolName.BASH_LEGACY:
            return "non_deterministic"
        return "deterministic_with_io"

    def _approval_required(self, tool_name: RuntimeToolName) -> bool:
        return tool_name not in {
            RuntimeToolName.VALIDATE,
            RuntimeToolName.SEARCH_REPLACE_PROPOSAL,
            RuntimeToolName.CREATE_PENDING_SEARCH_REPLACE_PROPOSAL,
        }

    def _patch_proposal_required(self, tool_name: RuntimeToolName) -> bool:
        return tool_name in {RuntimeToolName.SEARCH_REPLACE, RuntimeToolName.WRITE_FILE}

    def build_policy(self) -> ToolRuntimePolicy:
        """Build a static admission policy for the runtime adapter path.

        Genuinely read-only tools (validate) and proven non-workspace-mutating
        proposal-computation tools (search_replace_proposal) are admitted.
        Direct mutation execution (search_replace, write_file) and shell tools
        (bash) remain refused with ``policy_object_missing`` because the
        runtime path has no governance/approval wired for workspace mutation.

        This is a bounded static admission policy, not the completed general
        Governance Composer. Pending proposal persistence (durable
        coordination-store write) and execution authorization remain separate
        governed actions deferred to future slices.
        """

        async def _permission_decision(
            tool_name: str, args_dict: dict, call_id: str
        ) -> tuple[bool, str]:
            if tool_name in _ADMITTED_NON_EXECUTION_TOOLS:
                return True, ""
            return False, "policy_object_missing"

        async def _approval_request(
            tool_name: str, args_dict: dict, call_id: str
        ) -> tuple[bool, str]:
            if tool_name in _ADMITTED_NON_EXECUTION_TOOLS:
                return True, ""
            return False, "policy_object_missing"

        def _patch_gate_check(
            tool_call_ref: object, tool_instance_ref: object
        ) -> str | None:
            return None

        return ToolRuntimePolicy(
            permission_decision=_permission_decision,
            approval_request=_approval_request,
            patch_gate_check=_patch_gate_check,
            governance_engine=None,
            council_enabled=False,
            local_action_envelope_required=False,
            dirty_guard_satisfied=False,
        )


__all__ = ["RuntimeToolRuntimeAdapter", "RuntimeToolRuntimeRequestBundle"]
