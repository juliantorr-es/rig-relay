"""Canonical list of tools disabled in ACP non-interactive sessions.

These tools are excluded from the tool registry when running as an ACP agent.
Tools that require terminal/fs capabilities are handled separately via
_get_acp_tool_overrides() based on client capability negotiation.
"""

from __future__ import annotations

NON_INTERACTIVE_DISABLED_TOOLS: list[str] = [
    "exit_plan_mode",
    "checkpoint",
    "git_status",
    "git_diff",
    "git_branch",
    "git_log",
    "git_show",
    "git_ls_files",
    "git_commit",
    "git_checkout",
    "git_merge",
]

__all__ = ["NON_INTERACTIVE_DISABLED_TOOLS"]
