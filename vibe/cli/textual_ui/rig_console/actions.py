"""Safe action registry for the Rig Console command surface."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class RigConsoleAction:
    """Descriptor for a safe, read-only cockpit action."""

    name: str
    title: str
    description: str
    callback_name: str


class RigConsoleActionHost(Protocol):
    """Protocol for the dashboard/app surfaces that can dispatch safe actions."""

    def run_safe_action(self, action: RigConsoleAction) -> None: ...


ACTION_REFRESH = RigConsoleAction(
    name="refresh",
    title="Refresh",
    description="Refresh the cockpit projection",
    callback_name="action_refresh",
)
ACTION_SHOW_HELP = RigConsoleAction(
    name="show_help",
    title="Help",
    description="Show cockpit actions and shortcuts",
    callback_name="action_show_help",
)
ACTION_TOGGLE_DETAILS = RigConsoleAction(
    name="toggle_details",
    title="Toggle Details",
    description="Toggle detail hints in the footer",
    callback_name="action_toggle_details",
)
ACTION_SHOW_RUNTIME_STATUS = RigConsoleAction(
    name="show_runtime_status",
    title="Runtime Status",
    description="Show runtime adapter status",
    callback_name="action_show_runtime_status",
)
ACTION_SHOW_LEASES = RigConsoleAction(
    name="show_leases",
    title="Leases",
    description="Show active leases and blockers",
    callback_name="action_show_leases",
)
ACTION_SHOW_AUDIT_TIMELINE = RigConsoleAction(
    name="show_audit_timeline",
    title="Audit Timeline",
    description="Show recent audit and receipt activity",
    callback_name="action_show_audit_timeline",
)
ACTION_COPY_LATEST_RECEIPT_REF = RigConsoleAction(
    name="copy_latest_receipt_ref",
    title="Copy Receipt Ref",
    description="Copy the latest receipt reference if available",
    callback_name="action_copy_latest_receipt_ref",
)

SAFE_ACTIONS: tuple[RigConsoleAction, ...] = (
    ACTION_REFRESH,
    ACTION_SHOW_HELP,
    ACTION_TOGGLE_DETAILS,
    ACTION_SHOW_RUNTIME_STATUS,
    ACTION_SHOW_LEASES,
    ACTION_SHOW_AUDIT_TIMELINE,
    ACTION_COPY_LATEST_RECEIPT_REF,
)

ActionHandler = Callable[[], Awaitable[None] | None]


def action_names() -> tuple[str, ...]:
    return tuple(action.name for action in SAFE_ACTIONS)
