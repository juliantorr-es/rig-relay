"""ToolRuntimePolicy — explicit governance policy object for ToolRuntime.

When ToolRuntime is constructed with a policy object, the policy's
callbacks govern permission, approval, and patch gating. When no
policy is provided, ToolRuntime defaults to fail-closed for mutation
tools (read-only tools still proceed).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any


class ToolRuntimePolicy:
    """Explicit governance policy object for ToolRuntime.

    Carries the three governance callbacks plus metadata flags
    that describe the policy posture. When a ToolRuntimePolicy is
    passed to ToolRuntime.__init__(), its callbacks are used in
    place of the fail-closed defaults.
    """

    def __init__(
        self,
        *,
        permission_decision: Callable[
            [str, dict[str, Any], str], Awaitable[tuple[bool, str]]
        ]
        | None = None,
        approval_request: Callable[
            [str, dict[str, Any], str], Awaitable[tuple[bool, str]]
        ]
        | None = None,
        patch_gate_check: Callable[[Any, Any], Any | None] | None = None,
        governance_engine: Any = None,
        council_enabled: bool = False,
        local_action_envelope_required: bool = False,
        dirty_guard_satisfied: bool = False,
    ) -> None:
        self.permission_decision = permission_decision
        self.approval_request = approval_request
        self.patch_gate_check = patch_gate_check
        self.governance_engine = governance_engine
        self.council_enabled = council_enabled
        self.local_action_envelope_required = local_action_envelope_required
        self.dirty_guard_satisfied = dirty_guard_satisfied


__all__ = ["ToolRuntimePolicy"]
