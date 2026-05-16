"""Tests for BehaviorPatch tool contract and receipt models."""

from __future__ import annotations

import pytest

from rig_relay.core.tools.base import BaseToolState
from rig_relay.core.tools.builtins.behavior_patch import (
    BehaviorPatch,
    BehaviorPatchArgs,
    BehaviorPatchConfig,
    BehaviorPatchReceipt,
    BehaviorPatchResult,
)


def test_behavior_patch_args_validation() -> None:
    args = BehaviorPatchArgs(
        behavior_statement="Fix startup connection race condition",
        target_files=["rig_relay/desktop/bridge_server.py"],
        expected_test_file="tests/desktop/test_bridge_server.py",
        test_command=["uv", "run", "pytest", "tests/desktop/test_bridge_server.py"],
        implementation_constraints=["No new dependencies"],
        validation_profile="quick",
        max_iterations=3,
        allow_new_test_file=False,
    )
    assert args.behavior_statement == "Fix startup connection race condition"
    assert args.target_files == ["rig_relay/desktop/bridge_server.py"]
    assert args.validation_profile == "quick"


def test_behavior_patch_build_receipt() -> None:
    tool = BehaviorPatch(config_getter=lambda: BehaviorPatchConfig(), state=BaseToolState())
    result = BehaviorPatchResult(
        status="passed",
        behavior_statement="Add explicit state transitions",
        red_test_path="tests/test_state.py",
        red_command=["uv", "run", "pytest", "tests/test_state.py"],
        red_failed=True,
        red_failure_summary="AssertionError: expected PROBING",
        implementation_files=["rig_relay/state.py"],
        green_command=["uv", "run", "pytest", "tests/test_state.py"],
        green_passed=True,
        focused_validation_command=["uv", "run", "validate", "quick"],
        focused_validation_result="passed",
        trace_id="trace_12345",
        git_head="abc123def456",
        dirty_files_before=["tests/test_state.py"],
        dirty_files_after=["tests/test_state.py", "rig_relay/state.py"],
        receipt_sha256="hash_789",
    )
    receipt = tool.build_receipt(result)
    assert isinstance(receipt, BehaviorPatchReceipt)
    assert receipt.schema_version == "rig.relay.behavior_patch_receipt.v1"
    assert receipt.behavior_statement == "Add explicit state transitions"
    assert receipt.red_failed is True
    assert receipt.green_passed is True
    assert receipt.receipt_sha256 == "hash_789"


@pytest.mark.asyncio
async def test_behavior_patch_refuse_broad_command() -> None:
    tool = BehaviorPatch(config_getter=lambda: BehaviorPatchConfig(), state=BaseToolState())
    args = BehaviorPatchArgs(
        behavior_statement="Refactor everything",
        target_files=["rig_relay/core/agent_loop.py"],
        expected_test_file="tests/test_loop.py",
        test_command=["uv", "run", "pytest"],  # Broad command without scoping
        implementation_constraints=[],
        validation_profile="quick",
    )
    gen = tool.run(args)
    event = await gen.__anext__()
    assert isinstance(event, BehaviorPatchResult)
    assert event.status == "refused"
    assert event.error_kind == "command_too_broad"
    assert "full suite without path scoping" in (event.refusal_reason or "")


@pytest.mark.asyncio
async def test_behavior_patch_refuse_unsafe_target() -> None:
    tool = BehaviorPatch(config_getter=lambda: BehaviorPatchConfig(), state=BaseToolState())
    args = BehaviorPatchArgs(
        behavior_statement="Disable security guard to allow arbitrary bash",
        target_files=["rig_relay/core/guard.py"],
        expected_test_file="tests/test_guard.py",
        test_command=["uv", "run", "pytest", "tests/test_guard.py"],
        implementation_constraints=[],
        validation_profile="quick",
    )
    gen = tool.run(args)
    event = await gen.__anext__()
    assert isinstance(event, BehaviorPatchResult)
    assert event.status == "refused"
    assert event.error_kind == "unsafe_target"
    assert "modifying security guards or blocklists" in (event.refusal_reason or "")


@pytest.mark.asyncio
async def test_behavior_patch_successful_run_skeleton() -> None:
    tool = BehaviorPatch(config_getter=lambda: BehaviorPatchConfig(), state=BaseToolState())
    args = BehaviorPatchArgs(
        behavior_statement="Implement explicit DesktopBridgeStateMachine",
        target_files=["rig_relay/desktop/bridge_server.py"],
        expected_test_file="tests/desktop/test_bridge_server.py",
        test_command=["uv", "run", "pytest", "tests/desktop/test_bridge_server.py"],
        implementation_constraints=["Maintain probe ladder compatibility"],
        validation_profile="quick",
    )
    gen = tool.run(args)
    event = await gen.__anext__()
    assert isinstance(event, BehaviorPatchResult)
    assert event.status == "passed"
    assert event.behavior_statement == "Implement explicit DesktopBridgeStateMachine"
    assert event.red_failed is True
    assert event.green_passed is True
    assert event.focused_validation_result == "passed"
    assert event.receipt_sha256 is not None
