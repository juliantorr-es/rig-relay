"""rig_relay.sdk — Protocol & SDK spine v1 client."""

from __future__ import annotations

from rig_relay.sdk._models import (
    RigCapabilityDecision,
    RigClient,
    RigReceiptRef,
    RigRefusal,
    RigRunResult,
    RigStatus,
    RigVerdict,
    compute_sha256,
)

__all__ = [
    "RigCapabilityDecision",
    "RigClient",
    "RigReceiptRef",
    "RigRefusal",
    "RigRunResult",
    "RigStatus",
    "RigVerdict",
    "compute_sha256",
    "evaluate_sdk_capability",
    "get_sdk_status",
    "run_mcp_read_only",
    "send_a2a_local_task",
    "start_acp_session",
]


def get_sdk_status() -> RigStatus:
    return RigClient().status()


def evaluate_sdk_capability(capability_id: str) -> RigCapabilityDecision:
    return RigClient().evaluate_capability(capability_id)


def run_mcp_read_only(tool_name: str, trace_id: str) -> RigRunResult:
    return RigClient(trace_id=trace_id).run_mcp_read_only(tool_name, trace_id)


def start_acp_session(trace_id: str) -> RigRunResult:
    return RigClient(trace_id=trace_id).start_acp_session(trace_id)


def send_a2a_local_task(task_id: str, agent_id: str, trace_id: str) -> RigRunResult:
    return RigClient(trace_id=trace_id).send_a2a_local_task(task_id, agent_id, trace_id)
