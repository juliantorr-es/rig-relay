from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess

import pytest

from rig_relay.core.telemetry.tool_contract import ToolMutationClass
from rig_relay.core.tool_runtime_models import (
    RefusalCode,
    ToolRuntimeRefusal,
    ToolRuntimeResult,
    ToolRuntimeStatus,
)
from rig_relay.core.tools._agent_outcome import (
    MutationDisposition,
    derive_agent_outcome,
    format_agent_outcome,
)
from rig_relay.core.tools.base import BaseToolState
from rig_relay.core.tools.builtins.search_replace import (
    SearchReplace,
    SearchReplaceArgs,
    SearchReplaceConfig,
)
from rig_relay.governance.dirty_guard import get_guard, reset_guard
from rig_relay.runtime.tool_invocation_adapter import RuntimeToolName
from rig_relay.runtime.tool_invocation_execution import (
    RuntimeToolExecutionResult,
    RuntimeToolExecutionStatus,
)
from tests.mock.utils import collect_result


def _sha256_bytes(data: bytes) -> str:
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


@pytest.mark.asyncio
@pytest.mark.real_artifact
@pytest.mark.substrate
async def test_stale_hash_refusal_produces_structured_recovery_projection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Stale expected_before_sha256 produces projection with error_kind=expected_hash_mismatch,
    recoverable=true, mutation_disposition=not_performed, suggested_next_action populated.
    """
    reset_guard()
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.chdir(repo)

    subprocess.run(
        ["git", "-c", "user.name=test", "-c", "user.email=test@test.com", "init"],
        cwd=repo,
        check=True,
        capture_output=True,
    )

    file_path = repo / "target.py"
    original = "print('hello')\n"
    file_path.write_text(original, encoding="utf-8")

    subprocess.run(
        [
            "git",
            "-c",
            "user.name=test",
            "-c",
            "user.email=test@test.com",
            "commit",
            "--allow-empty",
            "-m",
            "init",
        ],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "add", str(file_path)], cwd=repo, check=True, capture_output=True
    )
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=test",
            "-c",
            "user.email=test@test.com",
            "commit",
            "-m",
            "add target",
        ],
        cwd=repo,
        check=True,
        capture_output=True,
    )

    original_hash = _sha256_bytes(original.encode("utf-8"))

    modified = "print('modified by other session')\n"
    file_path.write_text(modified, encoding="utf-8")
    stale_hash = original_hash

    guard = get_guard()
    guard.capture()

    tool = SearchReplace(
        config_getter=lambda: SearchReplaceConfig(), state=BaseToolState()
    )
    patch = (
        "<<<<<<< SEARCH\nprint('hello')\n=======\nprint('hello world')\n>>>>>>> REPLACE"
    )
    result = await collect_result(
        tool.run(
            SearchReplaceArgs(
                file_path="target.py", content=patch, expected_before_sha256=stale_hash
            )
        )
    )

    assert result.status == "refused"
    assert result.error_kind == "expected_hash_mismatch"
    assert result.blocks_applied == 0
    assert result.changed_files == []

    sr_refusal = ToolRuntimeRefusal(
        refusal_code=RefusalCode.PATCH_PROPOSAL_REQUIRED,
        message=(
            "File 'target.py' bytes no longer match expected_before_sha256. "
            f"Expected {stale_hash}, current {_sha256_bytes(modified.encode('utf-8'))}. "
            "Re-read the file and apply a narrower patch preserving existing changes."
        ),
        recoverable=True,
        suggested_next_action="Re-read the file and retry with updated expected_before_sha256.",
    )
    runtime_result = ToolRuntimeResult(
        status=ToolRuntimeStatus.REFUSED,
        tool_name="search_replace",
        tool_call_id="call_test_stale",
        refusal=sr_refusal,
        error_kind="expected_hash_mismatch",
        execution_enabled=False,
        mutation_performed=False,
    )

    outcome = derive_agent_outcome(runtime_result, SearchReplace)

    assert outcome.status == "refused"
    assert outcome.error_kind == "expected_hash_mismatch"
    assert outcome.refusal_code == RefusalCode.PATCH_PROPOSAL_REQUIRED.value
    assert outcome.recoverable is True
    assert outcome.mutation_disposition == MutationDisposition.NOT_PERFORMED.value
    assert outcome.suggested_next_action is not None
    assert "expected_before_sha256" in outcome.suggested_next_action.lower()

    formatted = format_agent_outcome(outcome)
    inner = json.loads(
        formatted[len("<rig-tool-outcome>") : -len("</rig-tool-outcome>")]
    )
    assert "file_content" not in inner
    assert "patch_diff" not in inner
    assert original not in formatted

    reset_guard()


@pytest.mark.asyncio
@pytest.mark.real_artifact
@pytest.mark.sabotage
async def test_mutation_success_degraded_still_reports_performed() -> None:
    """Mutation succeeded but cache/observation degraded produces mutation_disposition=performed."""
    result = ToolRuntimeResult(
        status=ToolRuntimeStatus.DEGRADED,
        tool_name="search_replace",
        tool_call_id="call_test_degraded",
        mutation_performed=True,
        degraded_capabilities=["cache_write_failed"],
    )

    outcome = derive_agent_outcome(result, SearchReplace)

    assert outcome.status == "degraded"
    assert outcome.mutation_disposition == MutationDisposition.PERFORMED.value
    assert "cache_write_failed" in outcome.degraded_capabilities
    assert outcome.cache_hit is False


def test_bridge_and_agentloop_projection_agree_on_canonical_fields() -> None:
    result = ToolRuntimeResult(
        status=ToolRuntimeStatus.REFUSED,
        tool_name="search_replace",
        tool_call_id="call_test_bridge",
        refusal=ToolRuntimeRefusal(
            refusal_code=RefusalCode.TOOL_PERMISSION_DENIED,
            message="Expected hash mismatch",
            recoverable=True,
            suggested_next_action="Re-read the file and retry.",
        ),
        error_kind="expected_hash_mismatch",
        execution_enabled=False,
    )

    agentloop_outcome = derive_agent_outcome(result, SearchReplace)

    mutation_cls = RuntimeToolName.SEARCH_REPLACE.mutation_class
    bridge_outcome = derive_agent_outcome(result, mutation_cls)

    assert agentloop_outcome.status == bridge_outcome.status
    assert agentloop_outcome.error_kind == bridge_outcome.error_kind
    assert agentloop_outcome.refusal_code == bridge_outcome.refusal_code
    assert agentloop_outcome.recoverable == bridge_outcome.recoverable
    assert agentloop_outcome.mutation_disposition == bridge_outcome.mutation_disposition
    assert (
        agentloop_outcome.suggested_next_action == bridge_outcome.suggested_next_action
    )
    assert (
        agentloop_outcome.suggested_next_action_source
        == bridge_outcome.suggested_next_action_source
    )


def test_projection_failure_produces_degraded_outcome_not_silent() -> None:
    result = ToolRuntimeResult(
        status=ToolRuntimeStatus.FAILED,
        tool_name="unknown_tool",
        tool_call_id="call_test_unknown",
        error_kind="some_error",
    )

    outcome = derive_agent_outcome(result, ToolMutationClass.UNKNOWN)

    assert outcome.status == "failed"
    assert outcome.mutation_disposition == MutationDisposition.NOT_PERFORMED.value
    assert outcome.tool_name == "unknown_tool"
    assert outcome.tool_call_id == "call_test_unknown"


def test_suggested_next_action_in_projection_output() -> None:
    result = ToolRuntimeResult(
        status=ToolRuntimeStatus.REFUSED,
        tool_name="search_replace",
        tool_call_id="call_test_action",
        refusal=ToolRuntimeRefusal(
            refusal_code=RefusalCode.TOOL_PERMISSION_DENIED,
            message="Hash mismatch",
            recoverable=True,
            suggested_next_action="Re-read the file and retry.",
        ),
        error_kind="expected_hash_mismatch",
        execution_enabled=False,
    )

    outcome = derive_agent_outcome(result, SearchReplace)
    formatted = format_agent_outcome(outcome)

    assert "suggested_next_action" in formatted
    assert "Re-read the file and retry" in formatted
    assert formatted.startswith("<rig-tool-outcome>")
    assert formatted.endswith("</rig-tool-outcome>")

    inner = json.loads(
        formatted[len("<rig-tool-outcome>") : -len("</rig-tool-outcome>")]
    )
    assert inner["suggested_next_action"] == "Re-read the file and retry."
    assert inner["suggested_next_action_source"] == "runtime_refusal"


def test_runtime_execution_result_without_agent_outcome() -> None:
    result = RuntimeToolExecutionResult(
        status=RuntimeToolExecutionStatus.COMPLETED,
        intent_id="intent_123",
        tool_name="search_replace",
    )

    assert result.agent_outcome is None
    assert result.agent_outcome_schema_valid is False
