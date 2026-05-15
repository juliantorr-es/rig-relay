"""Governance mixin for AgentLoop.

Extracted from agent_loop.py. Provides approval callbacks, tool
permission management, and session-level allow/deny rules. No LLM
or tool runtime dependency — purely policy configuration.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from rig_relay.core.config import VibeConfig
from rig_relay.core.tools.base import ToolPermission
from rig_relay.core.tools.permissions import ApprovedRule, RequiredPermission
from rig_relay.core.tools.utils import wildcard_match

if TYPE_CHECKING:
    pass


class GovernanceMixin:
    """Mixin providing approval and tool permission management."""

    def set_approval_callback(self, callback: object) -> None:
        self.approval_callback = callback

    def set_user_input_callback(self, callback: object) -> None:
        self.user_input_callback = callback

    def set_tool_permission(
        self, tool_name: str, permission: ToolPermission, save_permanently: bool = False
    ) -> None:
        if save_permanently:
            VibeConfig.save_updates({
                "tools": {tool_name: {"permission": permission.value}}
            })

        if tool_name not in self.config.tools:
            self.config.tools[tool_name] = {}

        self.config.tools[tool_name]["permission"] = permission.value

    def _add_session_rule(self, rule: ApprovedRule) -> None:
        self._session_rules.append(rule)

    def _is_permission_covered(self, tool_name: str, rp: RequiredPermission) -> bool:
        return any(
            rule.tool_name == tool_name
            and rule.scope == rp.scope
            and wildcard_match(rp.invocation_pattern, rule.session_pattern)
            for rule in self._session_rules
        )

    def approve_always(
        self,
        tool_name: str,
        required_permissions: list[RequiredPermission] | None,
        save_permanently: bool = False,
    ) -> None:
        if required_permissions:
            for rp in required_permissions:
                self._add_session_rule(
                    ApprovedRule(
                        tool_name=tool_name,
                        scope=rp.scope,
                        session_pattern=rp.session_pattern,
                    )
                )
            if save_permanently:
                self.config.add_tool_allowlist_patterns(
                    tool_name, [rp.session_pattern for rp in required_permissions]
                )
        else:
            self.set_tool_permission(
                tool_name, ToolPermission.ALWAYS, save_permanently=save_permanently
            )
