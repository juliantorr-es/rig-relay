from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
import hashlib
from pathlib import Path
from typing import Any

from rig_relay.core._agent_models import ToolDecision, ToolExecutionResponse
from rig_relay.core.guard import get_guard
from rig_relay.core.tools.base import ToolPermission
from rig_relay.core.tools.permissions import ApprovedRule, RequiredPermission


def _generate_decision_id(seed: str) -> str:
    return f"gd-{hashlib.sha256(seed.encode('utf-8')).hexdigest()[:16]}"


def _fail_closed_decision(
    tool_name: str, reason: str, surface: str = "agent_loop"
) -> ToolDecision:
    seed = f"{tool_name}:{reason}:{datetime.now(UTC).isoformat()}"
    return ToolDecision(
        verdict=ToolExecutionResponse.SKIP,
        approval_type=ToolPermission.NEVER,
        feedback=reason,
        decision_id=_generate_decision_id(seed),
        surface=surface,
        authority_tier="local_mutation",
    )


_TOOL_NAME_TO_CAPABILITY: dict[str, str] = {
    "write_file": "file_write_proposal",
    "search_replace": "file_write_proposal",
    "bash": "shell_proposal",
    "checkpoint": "coordination_write",
    "create_worktree": "worktree_write",
    "remove_worktree": "worktree_write",
}

_MUTATION_TOOL_NAME_PREFIXES: tuple[str, ...] = (
    "write_file",
    "search_replace",
    "bash",
    "checkpoint",
    "create_worktree",
    "remove_worktree",
    "push",
    "merge",
    "delete",
    "commit",
)


def _is_likely_mutation_tool(tool_name: str) -> bool:
    return any(tool_name.startswith(p) for p in _MUTATION_TOOL_NAME_PREFIXES)


@dataclass(slots=True)
class GovernanceRuntime:
    dirty_guard: Any = field(default_factory=get_guard)
    approval_callback: Any | None = None
    config: Any | None = None
    session_rules: list = field(default_factory=list)
    evidence: Any | None = None

    def should_execute_tool(
        self, tool_call_id: str, tool_name: str, tool_args: dict, execution_mode: str
    ) -> ToolDecision:
        seed = f"{tool_call_id}:{tool_name}:{execution_mode}:{datetime.now(UTC).isoformat()}"

        if self.config and getattr(self.config, "bypass_tool_permissions", False):
            return ToolDecision(
                verdict=ToolExecutionResponse.EXECUTE,
                approval_type=ToolPermission.ALWAYS,
                decision_id=_generate_decision_id(f"{seed}:bypass"),
                surface="agent_loop",
                authority_tier="local_mutation",
            )

        tool_permission = self._resolve_tool_permission(tool_name)

        if tool_permission == ToolPermission.NEVER:
            return ToolDecision(
                verdict=ToolExecutionResponse.SKIP,
                approval_type=ToolPermission.NEVER,
                feedback=f"Tool '{tool_name}' is permanently disabled.",
                decision_id=_generate_decision_id(f"{seed}:never"),
                surface="agent_loop",
                authority_tier="local_mutation",
            )

        if tool_permission == ToolPermission.ASK:
            if self.approval_callback is not None:
                feedback_from_callback = self._invoke_approval_callback_sync(
                    tool_name, tool_args, tool_call_id
                )
                if feedback_from_callback is not None:
                    return ToolDecision(
                        verdict=ToolExecutionResponse.EXECUTE,
                        approval_type=ToolPermission.ASK,
                        feedback=feedback_from_callback,
                        decision_id=_generate_decision_id(f"{seed}:approved"),
                        surface="agent_loop",
                        authority_tier="local_mutation",
                    )
            return ToolDecision(
                verdict=ToolExecutionResponse.SKIP,
                approval_type=ToolPermission.ASK,
                feedback=f"Tool '{tool_name}' requires approval but no approval callback is available or approval was not granted.",
                decision_id=_generate_decision_id(f"{seed}:ask_no_callback"),
                surface="agent_loop",
                authority_tier="local_mutation",
            )

        if tool_permission == ToolPermission.ALWAYS:
            pass

        if _is_likely_mutation_tool(tool_name):
            allow_mutation = tool_permission == ToolPermission.ALWAYS
            capability = _TOOL_NAME_TO_CAPABILITY.get(tool_name, "file_write_proposal")
            governance_result = self.evaluate_mutation_legality(
                workspace_id=None,
                intent_id=tool_call_id,
                intent_kind=tool_name,
                requested_capabilities=[capability],
                allow_mutation=allow_mutation,
                allow_network=False,
                dirty_policy_satisfied=True,
            )

            evidence_persisted = self._persist_governance_decision(governance_result)

            if governance_result.decision in {"blocked", "requires_review"}:
                blocked_codes = [r.code for r in governance_result.reasons]
                reason_str = (
                    "; ".join(blocked_codes)
                    if blocked_codes
                    else "mutation_blocked_by_policy"
                )
                return ToolDecision(
                    verdict=ToolExecutionResponse.SKIP,
                    approval_type=ToolPermission.NEVER,
                    feedback=f"Governance blocked: {reason_str}",
                    decision_id=governance_result.decision_id,
                    surface="agent_loop",
                    authority_tier="local_mutation",
                )

            if not evidence_persisted:
                return ToolDecision(
                    verdict=ToolExecutionResponse.SKIP,
                    approval_type=ToolPermission.NEVER,
                    feedback="Governance evidence persistence failed for mutation operation",
                    decision_id=governance_result.decision_id,
                    surface="agent_loop",
                    authority_tier="local_mutation",
                )

        return ToolDecision(
            verdict=ToolExecutionResponse.EXECUTE,
            approval_type=ToolPermission.ALWAYS,
            decision_id=_generate_decision_id(f"{seed}:allowed"),
            surface="agent_loop",
            authority_tier="read_only_projection"
            if not _is_likely_mutation_tool(tool_name)
            else "local_mutation",
        )

    def _invoke_approval_callback_sync(
        self, tool_name: str, tool_args: dict, tool_call_id: str
    ) -> str | None:
        if self.approval_callback is None:
            return None
        try:
            from rig_relay.core.types import ApprovalResponse

            response, feedback = self.approval_callback(
                tool_name, tool_args, tool_call_id, []
            )
            if response == ApprovalResponse.YES:
                return feedback or "approved"
            return None
        except Exception:
            return None

    def _resolve_tool_permission(self, tool_name: str) -> ToolPermission:
        for rule in self.session_rules:
            if rule.tool_name == tool_name:
                return ToolPermission.ALWAYS
        if self.config is None:
            return ToolPermission.ASK
        tools_config = getattr(self.config, "tools", {}) or {}
        tool_overrides = tools_config.get(tool_name) or {}
        permission_str = tool_overrides.get("permission")
        if permission_str is not None:
            try:
                return ToolPermission(permission_str)
            except ValueError:
                pass
        return ToolPermission.ASK

    async def ask_approval(
        self,
        tool_name: str,
        tool_args: Any,
        tool_call_id: str,
        required_permissions: list[RequiredPermission],
    ) -> ToolDecision:
        if not self.approval_callback:
            return ToolDecision(
                verdict=ToolExecutionResponse.SKIP,
                approval_type=ToolPermission.ASK,
                feedback="Tool execution not permitted.",
            )
        try:
            from rig_relay.core.types import ApprovalResponse

            response, feedback = await self.approval_callback(
                tool_name, tool_args, tool_call_id, required_permissions
            )
        except Exception:
            return ToolDecision(
                verdict=ToolExecutionResponse.SKIP,
                approval_type=ToolPermission.ASK,
                feedback="governance_unavailable",
            )

        match response:
            case ApprovalResponse.YES:
                verdict = ToolExecutionResponse.EXECUTE
            case _:
                verdict = ToolExecutionResponse.SKIP

        return ToolDecision(
            verdict=verdict, approval_type=ToolPermission.ASK, feedback=feedback
        )

    def check_write_file(
        self,
        path: str | Path,
        *,
        allow_overwrite_protected: bool = False,
        expected_before_sha256: str | None = None,
    ) -> tuple[bool, str]:
        result = self.dirty_guard.check_write_file(
            path,
            allow_overwrite_protected=allow_overwrite_protected,
            expected_before_sha256=expected_before_sha256,
        )
        return result.allowed, result.reason

    def check_search_replace(
        self, path: str | Path, *, expected_before_sha256: str | None = None
    ) -> tuple[bool, str]:
        result = self.dirty_guard.check_search_replace(
            path, expected_before_sha256=expected_before_sha256
        )
        return result.allowed, result.reason

    def add_session_rule(self, rule: ApprovedRule) -> None:
        self.session_rules.append(rule)

    def set_tool_permission(
        self, tool_name: str, permission: ToolPermission, save_permanently: bool = False
    ) -> None:
        if save_permanently:
            from rig_relay.core.config import VibeConfig

            VibeConfig.save_updates({
                "tools": {tool_name: {"permission": permission.value}}
            })
        if self.config is None:
            return
        tools = getattr(self.config, "tools", {}) or {}
        if tool_name not in tools:
            tools[tool_name] = {}
        tools[tool_name]["permission"] = permission.value

    def is_permission_covered(self, tool_name: str, rp: RequiredPermission) -> bool:
        from rig_relay.core.tools.utils import wildcard_match

        return any(
            rule.tool_name == tool_name
            and rule.scope == rp.scope
            and wildcard_match(rp.invocation_pattern, rule.session_pattern)
            for rule in self.session_rules
        )

    def approve_always(
        self,
        tool_name: str,
        required_permissions: list[RequiredPermission] | None,
        save_permanently: bool = False,
    ) -> None:
        if required_permissions:
            for rp in required_permissions:
                self.add_session_rule(
                    ApprovedRule(
                        tool_name=tool_name,
                        scope=rp.scope,
                        session_pattern=rp.session_pattern,
                    )
                )
            if save_permanently and self.config is not None:
                self.config.add_tool_allowlist_patterns(
                    tool_name, [rp.session_pattern for rp in required_permissions]
                )
        else:
            self.set_tool_permission(
                tool_name, ToolPermission.ALWAYS, save_permanently=save_permanently
            )

    def evaluate_mutation_legality(self, **kwargs: Any) -> Any:
        from rig_relay.governance.governance_engine import GovernanceEngine

        return GovernanceEngine.evaluate_action_legality(**kwargs)

    def _persist_governance_decision(self, governance_result: Any) -> bool:
        if self.evidence is None:
            return False
        try:
            persist = getattr(self.evidence, "persist", None)
            if persist is None or not callable(persist):
                return False
            _ = persist(governance_result)
            return getattr(self.evidence, "persisted", lambda: False)()
        except Exception:
            return False


__all__ = ["GovernanceRuntime"]
