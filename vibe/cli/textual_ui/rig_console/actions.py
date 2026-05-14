"""Safe action registry for the Rig Console command surface."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol

from rig_relay.runtime.tool_invocation_adapter import RuntimeToolIntent, RuntimeToolName


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
ACTION_RUN_VALIDATE = RigConsoleAction(
    name="run_validate",
    title="Run Validate",
    description="Run governed validate via runtime_exec",
    callback_name="action_run_validate",
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
ACTION_TOGGLE_INSPECTOR = RigConsoleAction(
    name="toggle_inspector",
    title="Toggle Inspector",
    description="Open or close the inspector drawer",
    callback_name="action_toggle_inspector",
)
ACTION_NEXT_ITEM = RigConsoleAction(
    name="next_item",
    title="Next Item",
    description="Move to the next inspector item",
    callback_name="action_next_item",
)
ACTION_PREVIOUS_ITEM = RigConsoleAction(
    name="previous_item",
    title="Previous Item",
    description="Move to the previous inspector item",
    callback_name="action_previous_item",
)
ACTION_COPY_SELECTED_REF = RigConsoleAction(
    name="copy_selected_ref",
    title="Copy Selected Ref",
    description="Copy the selected receipt or result hash",
    callback_name="action_copy_selected_ref",
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


ACTION_QUEUE_RUN_NEXT = RigConsoleAction(
    name="queue_run_next",
    title="Run Next Queued Item",
    description="Execute the next eligible queued item through FleetQueueRunner",
    callback_name="action_queue_run_next",
)
ACTION_QUEUE_VALIDATE = RigConsoleAction(
    name="queue_validate",
    title="Queue Validate",
    description="Enqueue a validate item, then run through FleetQueueRunner",
    callback_name="action_queue_validate",
)
ACTION_QUEUE_REFRESH = RigConsoleAction(
    name="queue_refresh",
    title="Refresh Queue",
    description="Refresh the queue projection from stored events",
    callback_name="action_queue_refresh",
)
ACTION_QUEUE_MESSAGE = RigConsoleAction(
    name="queue_message",
    title="Queue Message",
    description="Queue the current input message",
    callback_name="action_queue_message",
)
ACTION_STEER_CURRENT_TASK = RigConsoleAction(
    name="steer_current_task",
    title="Steer Current Task",
    description="Request steering for the current task",
    callback_name="action_steer_current_task",
)
ACTION_CLEAR_INPUT = RigConsoleAction(
    name="clear_input",
    title="Clear Input",
    description="Clear the queue input bar",
    callback_name="action_clear_input",
)
ACTION_TOGGLE_QUEUE_PANEL = RigConsoleAction(
    name="toggle_queue_panel",
    title="Toggle Queue Panel",
    description="Show or hide the queue panel",
    callback_name="action_toggle_queue_panel",
)

SAFE_ACTIONS: tuple[RigConsoleAction, ...] = (
    ACTION_REFRESH,
    ACTION_RUN_VALIDATE,
    ACTION_QUEUE_MESSAGE,
    ACTION_STEER_CURRENT_TASK,
    ACTION_CLEAR_INPUT,
    ACTION_TOGGLE_QUEUE_PANEL,
    ACTION_QUEUE_RUN_NEXT,
    ACTION_QUEUE_VALIDATE,
    ACTION_QUEUE_REFRESH,
    ACTION_SHOW_HELP,
    ACTION_TOGGLE_DETAILS,
    ACTION_TOGGLE_INSPECTOR,
    ACTION_NEXT_ITEM,
    ACTION_PREVIOUS_ITEM,
    ACTION_COPY_SELECTED_REF,
    ACTION_SHOW_RUNTIME_STATUS,
    ACTION_SHOW_LEASES,
    ACTION_SHOW_AUDIT_TIMELINE,
    ACTION_COPY_LATEST_RECEIPT_REF,
)

ActionHandler = Callable[[], Awaitable[None] | None]


def action_names() -> tuple[str, ...]:
    return tuple(action.name for action in SAFE_ACTIONS)


def build_validate_runtime_exec_intent(
    *, intent_id: str, changed_paths: list[str] | None = None
) -> RuntimeToolIntent:
    payload: dict[str, object] = {
        "tool_name": RuntimeToolName.VALIDATE.value,
        "profile": "quick",
    }
    if changed_paths:
        payload["paths"] = changed_paths
    return RuntimeToolIntent(
        intent_id=intent_id,
        tool_name=RuntimeToolName.RUNTIME_EXEC,
        payload=payload,
        requested_paths=changed_paths or [],
        require_worktree=False,
        allow_main_repo_mutation=False,
    )
