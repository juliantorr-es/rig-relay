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
    RetryabilityBasis,
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
from tests.mock.utils import collect_result


def _sha256_bytes(data: bytes) -> str:
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


@pytest.mark.asyncio
@pytest.mark.real_artifact
@pytest.mark.substrate
async def test_stale_hash_recoverable_true_retryable_false(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
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
    tool_result = await collect_result(
        tool.run(
            SearchReplaceArgs(
                file_path="target.py", content=patch, expected_before_sha256=stale_hash
            )
        )
    )

    assert tool_result.status == "refused"
    assert tool_result.error_kind == "expected_hash_mismatch"

    sr_refusal = ToolRuntimeRefusal(
        refusal_code=RefusalCode.PATCH_PROPOSAL_REQUIRED,
        message="Stale hash mismatch",
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

    assert outcome.recoverable is True
    assert outcome.retryable is False
    assert (
        outcome.retryability_basis
        == RetryabilityBasis.STALE_PRECONDITION_REQUIRES_REBUILD.value
    )

    reset_guard()


def test_degraded_mutation_performed_not_retryable() -> None:
    result = ToolRuntimeResult(
        status=ToolRuntimeStatus.DEGRADED,
        tool_name="search_replace",
        tool_call_id="call_test_degraded",
        mutation_performed=True,
        degraded_capabilities=["cache_write_failed"],
    )

    outcome = derive_agent_outcome(result, SearchReplace)

    assert outcome.retryable is False
    assert (
        outcome.retryability_basis
        == RetryabilityBasis.MUTATION_EFFECT_ALREADY_ESTABLISHED.value
    )


def test_read_only_transient_timeout_is_retryable() -> None:
    result = ToolRuntimeResult(
        status=ToolRuntimeStatus.FAILED,
        tool_name="read_file",
        tool_call_id="call_test_timeout",
        error_kind="timeout",
        mutation_performed=False,
    )

    outcome = derive_agent_outcome(result, ToolMutationClass.READ_ONLY)

    assert outcome.retryable is True
    assert (
        outcome.retryability_basis
        == RetryabilityBasis.READ_ONLY_TRANSIENT_FAILURE.value
    )


def test_unknown_disposition_not_retryable() -> None:
    result = ToolRuntimeResult(
        status=ToolRuntimeStatus.CACHED,
        tool_name="write_file",
        tool_call_id="call_test_cached_unknown",
        cache_hit=False,
        mutation_performed=False,
    )

    outcome = derive_agent_outcome(result, ToolMutationClass.WRITES_WORKSPACE)

    assert outcome.retryable is False
    assert outcome.mutation_disposition == "unknown"
    assert (
        outcome.retryability_basis
        == RetryabilityBasis.AMBIGUOUS_EFFECT_REQUIRES_INSPECTION.value
    )


def test_policy_refusal_not_retryable() -> None:
    result = ToolRuntimeResult.refused(
        tool_name="write_file",
        tool_call_id="call_test_policy_refusal",
        refusal=ToolRuntimeRefusal(
            refusal_code=RefusalCode.TOOL_PERMISSION_DENIED,
            message="Permission denied for mutation tool",
            recoverable=True,
        ),
    )

    outcome = derive_agent_outcome(result, ToolMutationClass.WRITES_WORKSPACE)

    assert outcome.retryable is False
    assert outcome.refusal_code == RefusalCode.TOOL_PERMISSION_DENIED.value
    assert (
        outcome.retryability_basis
        == RetryabilityBasis.POLICY_REFUSAL_REQUIRES_AUTHORIZATION.value
    )


def test_unsupported_no_safe_replay_rule_by_default() -> None:
    result = ToolRuntimeResult(
        status=ToolRuntimeStatus.FAILED,
        tool_name="write_file",
        tool_call_id="call_test_unknown_error",
        error_kind="some_cryptic_error",
        mutation_performed=False,
    )

    outcome = derive_agent_outcome(result, ToolMutationClass.WRITES_WORKSPACE)

    assert outcome.retryable is False
    assert (
        outcome.retryability_basis
        == RetryabilityBasis.UNSUPPORTED_NO_SAFE_REPLAY_RULE.value
    )


def test_bridge_and_agentloop_agree_on_retryability() -> None:
    refusal = ToolRuntimeRefusal(
        refusal_code=RefusalCode.TOOL_PERMISSION_DENIED,
        message="Expected hash mismatch",
        recoverable=True,
        suggested_next_action="Re-read the file and retry.",
    )
    result = ToolRuntimeResult(
        status=ToolRuntimeStatus.REFUSED,
        tool_name="search_replace",
        tool_call_id="call_test_bridge",
        refusal=refusal,
        error_kind="expected_hash_mismatch",
        execution_enabled=False,
        mutation_performed=False,
    )

    agentloop_outcome = derive_agent_outcome(result, SearchReplace)
    bridge_outcome = derive_agent_outcome(
        result, RuntimeToolName.SEARCH_REPLACE.mutation_class
    )

    assert agentloop_outcome.retryable == bridge_outcome.retryable
    assert agentloop_outcome.retryability_basis == bridge_outcome.retryability_basis
    assert agentloop_outcome.retryable is False
    assert (
        bridge_outcome.retryability_basis
        == RetryabilityBasis.STALE_PRECONDITION_REQUIRES_REBUILD.value
    )


def test_format_agent_outcome_includes_retryable() -> None:
    refusal = ToolRuntimeRefusal(
        refusal_code=RefusalCode.PATCH_PROPOSAL_REQUIRED,
        message="Stale hash mismatch",
        recoverable=True,
        suggested_next_action="Re-read the file and retry.",
    )
    result = ToolRuntimeResult(
        status=ToolRuntimeStatus.REFUSED,
        tool_name="search_replace",
        tool_call_id="call_test_format",
        refusal=refusal,
        error_kind="expected_hash_mismatch",
        execution_enabled=False,
        mutation_performed=False,
    )

    outcome = derive_agent_outcome(result, SearchReplace)
    formatted = format_agent_outcome(outcome)

    assert formatted.startswith("<rig-tool-outcome>")
    assert formatted.endswith("</rig-tool-outcome>")

    inner_json = formatted[len("<rig-tool-outcome>") : -len("</rig-tool-outcome>")]
    parsed = json.loads(inner_json)

    assert "retryable" in parsed
    assert "retryability_basis" in parsed
    assert parsed["retryable"] is False
    assert parsed["retryability_basis"] == "stale_precondition_requires_rebuild"


def test_retryability_basis_values_are_content_light() -> None:
    for member in RetryabilityBasis:
        value = member.value
        assert " " not in value, f"'{value}' contains spaces"
        parts = value.split("_")
        assert len(parts) >= 3, (
            f"'{value}' has only {len(parts)} underscore-separated parts, "
            f"expected at least 3"
        )


def test_cached_read_only_safe_replay() -> None:
    result = ToolRuntimeResult(
        status=ToolRuntimeStatus.CACHED,
        tool_name="read_file",
        tool_call_id="call_test_cached_ro",
        cache_hit=True,
    )

    outcome = derive_agent_outcome(result, ToolMutationClass.READ_ONLY)

    assert outcome.retryable is True
    assert (
        outcome.retryability_basis
        == RetryabilityBasis.CACHED_READ_ONLY_SAFE_REPLAY.value
    )


@pytest.mark.asyncio
@pytest.mark.real_artifact
async def test_real_policy_refusal_produces_correct_retryability(tmp_path):
    """Real ToolRuntime without governance — fail-closed policy refusal → retryable=false, policy_refusal_requires_authorization."""
    from rig_relay.core.telemetry.tool_contract import ToolMutationClass
    from rig_relay.core.tool_runtime import ToolRuntime
    from rig_relay.core.tool_runtime_models import (
        ToolRuntimeExecutionMode,
        ToolRuntimeRequest,
        ToolRuntimeStatus,
    )
    from rig_relay.core.tools._agent_outcome import derive_agent_outcome

    runtime = ToolRuntime()

    request = ToolRuntimeRequest(
        tool_name="write_file",
        tool_call_id="test_real_policy_refusal",
        tool_args={"file_path": str(tmp_path / "test.txt"), "content": "test"},
        bypass_permissions=False,
        execution_mode=ToolRuntimeExecutionMode.MUTATION_PROPOSAL,
    )

    result = await runtime.execute_one(request)

    assert result.status == ToolRuntimeStatus.REFUSED
    assert result.refusal is not None

    outcome = derive_agent_outcome(result, ToolMutationClass.WRITES_WORKSPACE)

    assert outcome.retryable is False
    assert outcome.retryability_basis == "policy_refusal_requires_authorization"
    assert outcome.refusal_code is not None
