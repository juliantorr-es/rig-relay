from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from rig_relay.core._agent_models import ToolDecision, ToolExecutionResponse
from rig_relay.core.guard import get_guard
from rig_relay.core.tools.base import ToolPermission

if TYPE_CHECKING:
    from rig_relay.core.tools.permissions import ApprovedRule, RequiredPermission


@dataclass(slots=True)
class GovernanceRuntime:
    dirty_guard: Any = field(default_factory=get_guard)
    approval_callback: Any | None = None
    config: Any | None = None
    session_rules: list = field(default_factory=list)

    def should_execute_tool(
        self, tool_call_id: str, tool_name: str, tool_args: dict, execution_mode: str
    ) -> ToolDecision:
        if self.config and getattr(self.config, "bypass_tool_permissions", False):
            return ToolDecision(
                verdict=ToolExecutionResponse.EXECUTE,
                approval_type=ToolPermission.ALWAYS,
            )
        return ToolDecision(
            verdict=ToolExecutionResponse.EXECUTE, approval_type=ToolPermission.ALWAYS
        )

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

    def evaluate_mutation_legality(self, **kwargs: Any) -> Any:
        from rig_relay.governance.governance_engine import GovernanceEngine

        return GovernanceEngine.evaluate_action_legality(**kwargs)


__all__ = ["GovernanceRuntime"]
