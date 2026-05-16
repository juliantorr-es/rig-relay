"""Adapter from runtime tool intents to ToolRuntime requests."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json

from rig_relay.core.tool_runtime_models import (
    ToolRuntimeExecutionMode,
    ToolRuntimeRequest,
)
from rig_relay.runtime.tool_invocation_adapter import (
    RuntimeToolInvocationEnvelope,
    RuntimeToolName,
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
            case RuntimeToolName.WRITE_FILE:
                return "write_file"
            case RuntimeToolName.BASH_LEGACY:
                return "bash"
            case _:
                return tool_name.value

    def _execution_mode(self, tool_name: RuntimeToolName) -> ToolRuntimeExecutionMode:
        if tool_name == RuntimeToolName.VALIDATE:
            return ToolRuntimeExecutionMode.READ_ONLY
        if tool_name in {RuntimeToolName.SEARCH_REPLACE, RuntimeToolName.WRITE_FILE}:
            return ToolRuntimeExecutionMode.MUTATION_EXECUTION
        if tool_name == RuntimeToolName.BASH_LEGACY:
            return ToolRuntimeExecutionMode.UNKNOWN
        return ToolRuntimeExecutionMode.UNKNOWN

    def _mutation_class(self, tool_name: RuntimeToolName) -> str:
        if tool_name == RuntimeToolName.VALIDATE:
            return "read_only"
        if tool_name == RuntimeToolName.BASH_LEGACY:
            return "shell"
        return "filesystem_mutation"

    def _determinism_class(self, tool_name: RuntimeToolName) -> str:
        if tool_name == RuntimeToolName.VALIDATE:
            return "deterministic"
        if tool_name == RuntimeToolName.BASH_LEGACY:
            return "non_deterministic"
        return "deterministic_with_io"

    def _approval_required(self, tool_name: RuntimeToolName) -> bool:
        return tool_name != RuntimeToolName.VALIDATE

    def _patch_proposal_required(self, tool_name: RuntimeToolName) -> bool:
        return tool_name in {RuntimeToolName.SEARCH_REPLACE, RuntimeToolName.WRITE_FILE}


__all__ = ["RuntimeToolRuntimeAdapter", "RuntimeToolRuntimeRequestBundle"]
