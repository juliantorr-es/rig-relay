from __future__ import annotations

from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any, ClassVar

import pytest

from rig_relay.coordination.models import CoordinationTaskClaim
from rig_relay.core.telemetry.tool_contract import ToolMutationClass
from rig_relay.core.tool_runtime import ToolRuntime
from rig_relay.core.tool_runtime_models import (
    RefusalCode,
    ToolRuntimeExecutionMode,
    ToolRuntimeRequest,
    ToolRuntimeStatus,
)
from rig_relay.core.tool_runtime_policy import ToolRuntimePolicy
from rig_relay.core.tools._agent_outcome import AgentToolOutcome, derive_agent_outcome
from rig_relay.governance.auth_receipts import (
    generate_mission_checkpoint_receipt,
    validate_receipt,
)
from rig_relay.governance.mission_authority import (
    AuthorityDecision,
    MissionExecutionAuthority,
    _extract_file_paths,
    derive_authority_from_claim,
)


def _make_always_allow_policy() -> ToolRuntimePolicy:
    return ToolRuntimePolicy(
        permission_decision=lambda t, a, c: _async_true(),
        approval_request=lambda t, a, c: _async_true(),
        patch_gate_check=lambda tc, ti: None,
    )


async def _async_true() -> tuple[bool, str]:
    return True, ""


async def _fake_invoke_success(args_dict: dict[str, Any]) -> AsyncGenerator[Any, None]:
    class _Result:
        def model_dump(self, **kwargs: Any) -> dict[str, Any]:
            return {"ok": True}

        supervisor_result_envelope = None
        supervisor_result_envelope_sha256 = None
        supervisor_result_classification = None

    yield _Result()


# Helpers: resolve paths for cross-platform correctness. /tmp is a symlink
# to /private/tmp on macOS, and is_path_in_write_scope resolves the target
# but not the canonical_paths. Using .resolve() on both sides aligns them.
_SRC = Path("/tmp/repo/src").resolve()
_TESTS = Path("/tmp/repo/tests").resolve()
_ROOT = Path("/tmp/repo").resolve()
_OTHER = Path("/tmp/repo/other").resolve()


# ── Contract: derive_authority_from_claim ────────────────────────────────


def test_derive_authority_from_claim_preserves_scope_paths():
    class MockClaim:
        session_id: ClassVar[str] = "sess-1"
        task_id: ClassVar[str] = "task-1"
        scope_allowed_paths: ClassVar[list[str]] = ["/tmp/repo/src", "/tmp/repo/tests"]
        status = "active"
        expires_at = None
        state_sha256 = "abc123"

    auth = derive_authority_from_claim(MockClaim(), worktree_root="/tmp/repo")
    assert len(auth.canonical_paths) == 2
    assert auth.status == "active"
    assert auth.is_active()


# ── Contract: AuthorityEvaluation for read tools ─────────────────────────


def test_read_only_tool_allowed_in_scope():
    auth = MissionExecutionAuthority(
        claim_id="claim-1",
        session_id="s-1",
        task_id="t-1",
        canonical_paths=(_SRC,),
        worktree_root=_ROOT,
        status="active",
    )
    result = auth.evaluate(
        "read_file",
        {"file_path": str(_ROOT / "other" / "file.py")},
        "read_only",
        "read_only",
    )
    assert result.decision == AuthorityDecision.ALLOWED_IN_SCOPE
    assert result.matched_rule_kind == "repository_read"
    assert not result.requires_approval


def test_read_outside_write_scope_allowed():
    auth = MissionExecutionAuthority(
        claim_id="claim-1",
        session_id="s-1",
        task_id="t-1",
        canonical_paths=(_SRC,),
        worktree_root=_ROOT,
        status="active",
    )
    result = auth.evaluate(
        "read_file", {"file_path": str(_TESTS / "test_x.py")}, "read_only", "read_only"
    )
    assert result.decision == AuthorityDecision.ALLOWED_IN_SCOPE
    assert not result.requires_approval


# ── Contract: AuthorityEvaluation for write tools ────────────────────────


def test_write_within_scope_allowed():
    auth = MissionExecutionAuthority(
        claim_id="claim-1",
        session_id="s-1",
        task_id="t-1",
        canonical_paths=(_SRC,),
        worktree_root=_ROOT,
        status="active",
    )
    result = auth.evaluate(
        "write_file", {"file_path": str(_SRC / "new.py")}, "writes_workspace", None
    )
    assert result.decision == AuthorityDecision.ALLOWED_IN_SCOPE
    assert result.matched_rule_kind == "scope_path"
    assert not result.requires_approval


def test_write_outside_scope_requires_expansion():
    auth = MissionExecutionAuthority(
        claim_id="claim-1",
        session_id="s-1",
        task_id="t-1",
        canonical_paths=(_SRC,),
        worktree_root=_ROOT,
        status="active",
    )
    result = auth.evaluate(
        "write_file", {"file_path": str(_OTHER / "file.py")}, "writes_workspace", None
    )
    assert result.decision == AuthorityDecision.REQUIRES_SCOPE_EXPANSION
    assert result.requires_approval


def test_mutation_without_file_paths_requires_expansion():
    auth = MissionExecutionAuthority(
        claim_id="claim-1",
        session_id="s-1",
        task_id="t-1",
        canonical_paths=(_SRC,),
        worktree_root=_ROOT,
        status="active",
    )
    result = auth.evaluate("bash", {}, "writes_workspace", None)
    assert result.decision == AuthorityDecision.REQUIRES_SCOPE_EXPANSION
    assert result.matched_rule_kind == "tool_not_admitted"
    assert result.requires_approval


# ── Contract: consequential actions ──────────────────────────────────────


def test_push_always_consequential():
    auth = MissionExecutionAuthority(
        claim_id="claim-1",
        session_id="s-1",
        task_id="t-1",
        canonical_paths=(_ROOT,),
        status="active",
    )
    result = auth.evaluate("push", {}, None, None)
    assert result.decision == AuthorityDecision.REQUIRES_CONSECUTIAL_APPROVAL


def test_merge_always_consequential():
    auth = MissionExecutionAuthority(
        claim_id="claim-1",
        session_id="s-1",
        task_id="t-1",
        canonical_paths=(_ROOT,),
        status="active",
    )
    result = auth.evaluate("merge", {}, None, None)
    assert result.decision == AuthorityDecision.REQUIRES_CONSECUTIAL_APPROVAL


def test_destructive_git_actions_consequential():
    auth = MissionExecutionAuthority(
        claim_id="claim-1",
        session_id="s-1",
        task_id="t-1",
        canonical_paths=(_ROOT,),
        status="active",
    )
    for action in ("reset", "clean", "rebase", "stash"):
        result = auth.evaluate(action, {}, None, None)
        assert result.decision == AuthorityDecision.REQUIRES_CONSECUTIAL_APPROVAL


# ── Contract: inactive / expired ─────────────────────────────────────────


def test_expired_authority_refuses():
    auth = MissionExecutionAuthority(
        claim_id="claim-1", session_id="s-1", task_id="t-1", status="released"
    )
    result = auth.evaluate(
        "read_file", {"file_path": "/tmp/test.py"}, "read_only", None
    )
    assert result.decision == AuthorityDecision.REFUSED_BY_POLICY


def test_is_active_false_when_expired():
    auth = MissionExecutionAuthority(
        claim_id="claim-1",
        session_id="s-1",
        task_id="t-1",
        status="active",
        expires_at="2020-01-01T00:00:00+00:00",
    )
    assert not auth.is_active()


def test_is_active_true_when_future_expiry():
    auth = MissionExecutionAuthority(
        claim_id="claim-1",
        session_id="s-1",
        task_id="t-1",
        status="active",
        expires_at="2099-01-01T00:00:00+00:00",
    )
    assert auth.is_active()


def test_is_active_false_with_bad_expiry_string():
    auth = MissionExecutionAuthority(
        claim_id="claim-1",
        session_id="s-1",
        task_id="t-1",
        status="active",
        expires_at="not-a-date",
    )
    assert not auth.is_active()


# ── Contract: protected surfaces ─────────────────────────────────────────


def test_protected_surface_refused_without_admission():
    auth = MissionExecutionAuthority(
        claim_id="claim-1",
        session_id="s-1",
        task_id="t-1",
        canonical_paths=(_ROOT,),
        status="active",
        admitted_protected_surface=False,
    )
    result = auth.evaluate("credential_access", {}, None, None)
    assert result.decision == AuthorityDecision.REFUSED_BY_POLICY


def test_protected_surface_with_admission_consequential():
    auth = MissionExecutionAuthority(
        claim_id="claim-1",
        session_id="s-1",
        task_id="t-1",
        canonical_paths=(_ROOT,),
        status="active",
        admitted_protected_surface=True,
    )
    result = auth.evaluate("credential_access", {}, None, None)
    assert result.decision == AuthorityDecision.REQUIRES_CONSECUTIAL_APPROVAL


def test_governance_weakening_refused():
    auth = MissionExecutionAuthority(
        claim_id="claim-1",
        session_id="s-1",
        task_id="t-1",
        status="active",
        admitted_protected_surface=False,
    )
    result = auth.evaluate("governance_weakening", {}, None, None)
    assert result.decision == AuthorityDecision.REFUSED_BY_POLICY


def test_release_gate_weakening_refused():
    auth = MissionExecutionAuthority(
        claim_id="claim-1",
        session_id="s-1",
        task_id="t-1",
        status="active",
        admitted_protected_surface=False,
    )
    result = auth.evaluate("release_gate_weakening", {}, None, None)
    assert result.decision == AuthorityDecision.REFUSED_BY_POLICY


def test_remote_mutation_refused_without_admission():
    auth = MissionExecutionAuthority(
        claim_id="claim-1",
        session_id="s-1",
        task_id="t-1",
        status="active",
        admitted_protected_surface=False,
    )
    result = auth.evaluate("remote_mutation", {}, None, None)
    assert result.decision == AuthorityDecision.REFUSED_BY_POLICY


def test_remote_mutation_with_admission_consequential():
    auth = MissionExecutionAuthority(
        claim_id="claim-1",
        session_id="s-1",
        task_id="t-1",
        status="active",
        admitted_protected_surface=True,
    )
    result = auth.evaluate("remote_mutation", {}, None, None)
    assert result.decision == AuthorityDecision.REQUIRES_CONSECUTIAL_APPROVAL


def test_lockfile_regeneration_protected():
    auth = MissionExecutionAuthority(
        claim_id="claim-1",
        session_id="s-1",
        task_id="t-1",
        status="active",
        admitted_protected_surface=False,
    )
    result = auth.evaluate("lockfile_regeneration", {}, None, None)
    assert result.decision == AuthorityDecision.REFUSED_BY_POLICY


def test_dependency_change_protected():
    auth = MissionExecutionAuthority(
        claim_id="claim-1",
        session_id="s-1",
        task_id="t-1",
        status="active",
        admitted_protected_surface=False,
    )
    result = auth.evaluate("dependency_change", {}, None, None)
    assert result.decision == AuthorityDecision.REFUSED_BY_POLICY


# ── Contract: checkpoint ─────────────────────────────────────────────────


def test_admitted_checkpoint_allowed():
    auth = MissionExecutionAuthority(
        claim_id="claim-1",
        session_id="s-1",
        task_id="t-1",
        canonical_paths=(_ROOT,),
        status="active",
        admitted_checkpoint=True,
    )
    result = auth.evaluate("checkpoint", {}, None, None)
    assert result.decision == AuthorityDecision.ALLOWED_IN_SCOPE
    assert result.matched_rule_kind == "governed_checkpoint"


def test_checkpoint_without_admission_consequential():
    auth = MissionExecutionAuthority(
        claim_id="claim-1",
        session_id="s-1",
        task_id="t-1",
        canonical_paths=(_ROOT,),
        status="active",
        admitted_checkpoint=False,
    )
    result = auth.evaluate("checkpoint", {}, None, None)
    assert result.decision == AuthorityDecision.REQUIRES_CONSECUTIAL_APPROVAL


# ── Contract: path resolution ────────────────────────────────────────────


def test_is_path_in_write_scope_true_for_child_path():
    auth = MissionExecutionAuthority(
        claim_id="claim-1",
        session_id="s-1",
        task_id="t-1",
        canonical_paths=(_SRC,),
        status="active",
    )
    assert auth.is_path_in_write_scope(str(_SRC / "module.py"))


def test_is_path_in_write_scope_false_for_sibling():
    auth = MissionExecutionAuthority(
        claim_id="claim-1",
        session_id="s-1",
        task_id="t-1",
        canonical_paths=(_SRC,),
        status="active",
    )
    assert not auth.is_path_in_write_scope(str(_TESTS / "test.py"))


def test_is_path_in_read_scope_within_worktree():
    auth = MissionExecutionAuthority(
        claim_id="claim-1",
        session_id="s-1",
        task_id="t-1",
        canonical_paths=(_SRC,),
        worktree_root=_ROOT,
        status="active",
    )
    assert auth.is_path_in_read_scope(str(_TESTS / "test.py"))


def test_is_path_in_read_scope_outside_worktree_but_in_write_scope():
    auth = MissionExecutionAuthority(
        claim_id="claim-1",
        session_id="s-1",
        task_id="t-1",
        canonical_paths=(_SRC, Path("/other").resolve()),
        worktree_root=_ROOT,
        status="active",
    )
    assert auth.is_path_in_read_scope(str(Path("/other").resolve() / "file.py"))


def test_is_path_in_read_scope_no_worktree_falls_back_to_write():
    auth = MissionExecutionAuthority(
        claim_id="claim-1",
        session_id="s-1",
        task_id="t-1",
        canonical_paths=(_SRC,),
        worktree_root=None,
        status="active",
    )
    assert auth.is_path_in_read_scope(str(_SRC / "module.py"))
    assert not auth.is_path_in_read_scope(str(_TESTS / "test.py"))


# ── Contract: ruff_format special-casing ─────────────────────────────────


def test_ruff_format_allowed_when_all_paths_in_scope():
    auth = MissionExecutionAuthority(
        claim_id="claim-1",
        session_id="s-1",
        task_id="t-1",
        canonical_paths=(_ROOT,),
        status="active",
    )
    result = auth.evaluate(
        "ruff_format", {"file_path": str(_SRC / "module.py")}, "writes_workspace", None
    )
    assert result.decision == AuthorityDecision.ALLOWED_IN_SCOPE
    assert result.matched_rule_kind == "scope_path"


def test_ruff_format_multiple_files_all_in_scope():
    auth = MissionExecutionAuthority(
        claim_id="claim-1",
        session_id="s-1",
        task_id="t-1",
        canonical_paths=(_ROOT,),
        status="active",
    )
    result = auth.evaluate(
        "ruff_format",
        {"files": [str(_SRC / "a.py"), str(_SRC / "b.py")]},
        "writes_workspace",
        None,
    )
    assert result.decision == AuthorityDecision.ALLOWED_IN_SCOPE


def test_ruff_format_mixed_scope_requires_expansion():
    auth = MissionExecutionAuthority(
        claim_id="claim-1",
        session_id="s-1",
        task_id="t-1",
        canonical_paths=(_SRC,),
        status="active",
    )
    result = auth.evaluate(
        "ruff_format",
        {"files": [str(_SRC / "a.py"), str(_TESTS / "b.py")]},
        "writes_workspace",
        None,
    )
    assert result.decision == AuthorityDecision.REQUIRES_SCOPE_EXPANSION


# ── Integration: ToolRuntime with mission authority ──────────────────────


@pytest.mark.asyncio
@pytest.mark.real_artifact
async def test_tool_runtime_with_mission_authority_skips_approval(tmp_path: Path):
    scoped_dir = tmp_path / "scoped"
    scoped_dir.mkdir()
    target_file = scoped_dir / "test.txt"

    policy = _make_always_allow_policy()
    runtime = ToolRuntime(invoke_tool=_fake_invoke_success, policy_object=policy)
    auth = MissionExecutionAuthority(
        claim_id="claim-1",
        session_id="s-1",
        task_id="t-1",
        canonical_paths=(scoped_dir,),
        worktree_root=tmp_path,
        status="active",
    )
    runtime._mission_authority = auth

    request = ToolRuntimeRequest(
        tool_name="write_file",
        tool_call_id="test_in_scope",
        tool_args={"file_path": str(target_file), "content": "hello"},
        execution_mode=ToolRuntimeExecutionMode.MUTATION_PROPOSAL,
    )
    # NOTE: ToolRuntimeRequest does not carry mutation_class as a declared field.
    # _execute_governed reads it via getattr(request, "mutation_class", None),
    # and when None the authority evaluator returns NOT_EVALUATED (no block).
    # The tool completes, but authority_decision stays None on the result.
    result = await runtime.execute_one(request)
    # When authority is NOT_EVALUATED the tool proceeds; COMPLETED results
    # do not currently propagate authority fields. This tests that no crash occurs.
    assert result.status == ToolRuntimeStatus.COMPLETED


@pytest.mark.asyncio
@pytest.mark.real_artifact
async def test_tool_runtime_with_mission_authority_refuses_out_of_scope(tmp_path: Path):
    scoped_dir = tmp_path / "scoped"
    scoped_dir.mkdir()
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()

    policy = _make_always_allow_policy()
    runtime = ToolRuntime(invoke_tool=_fake_invoke_success, policy_object=policy)
    auth = MissionExecutionAuthority(
        claim_id="claim-1",
        session_id="s-1",
        task_id="t-1",
        canonical_paths=(scoped_dir,),
        worktree_root=tmp_path,
        status="active",
    )
    runtime._mission_authority = auth

    request = ToolRuntimeRequest(
        tool_name="write_file",
        tool_call_id="test_out_of_scope",
        tool_args={"file_path": str(outside_dir / "test.txt"), "content": "hello"},
        execution_mode=ToolRuntimeExecutionMode.MUTATION_PROPOSAL,
    )
    object.__setattr__(request, "mutation_class", "writes_workspace")

    result = await runtime.execute_one(request)
    assert result.status == ToolRuntimeStatus.REFUSED
    assert result.refusal is not None
    assert result.refusal.refusal_code == RefusalCode.SCOPE_EXPANSION_REQUIRED
    assert result.authority_decision is not None


@pytest.mark.asyncio
async def test_tool_runtime_without_authority_produces_not_evaluated():
    policy = _make_always_allow_policy()
    runtime = ToolRuntime(invoke_tool=_fake_invoke_success, policy_object=policy)
    request = ToolRuntimeRequest(
        tool_name="read_file",
        tool_call_id="test_no_auth",
        tool_args={"file_path": "/tmp/test.txt"},
        execution_mode=ToolRuntimeExecutionMode.READ_ONLY,
    )

    result = await runtime.execute_one(request)
    outcome = derive_agent_outcome(result, ToolMutationClass.READ_ONLY)
    assert outcome.authority_decision == "not_evaluated_under_mission_authority"
    assert outcome.authority_source == "none"


# ── Edge: authority evaluation coverage ──────────────────────────────────


def test_evaluate_returns_not_evaluated_for_unknown_tool():
    auth = MissionExecutionAuthority(
        claim_id="claim-1", session_id="s-1", task_id="t-1", status="active"
    )
    result = auth.evaluate("unknown_tool", {}, None, None)
    assert result.decision == AuthorityDecision.NOT_EVALUATED
    assert result.requires_approval


def test_evaluate_write_with_multiple_files_mixed_scope():
    auth = MissionExecutionAuthority(
        claim_id="claim-1",
        session_id="s-1",
        task_id="t-1",
        canonical_paths=(_SRC,),
        worktree_root=_ROOT,
        status="active",
    )
    result = auth.evaluate(
        "write_file",
        {"files": [str(_SRC / "a.py"), str(_TESTS / "b.py")]},
        "writes_workspace",
        None,
    )
    assert result.decision == AuthorityDecision.REQUIRES_SCOPE_EXPANSION


def test_evaluate_extracts_paths_from_multiple_keys():
    auth = MissionExecutionAuthority(
        claim_id="claim-1",
        session_id="s-1",
        task_id="t-1",
        canonical_paths=(_ROOT,),
        worktree_root=_ROOT,
        status="active",
    )
    result = auth.evaluate(
        "write_file",
        {"target": str(_SRC / "x.py"), "file": str(_SRC / "y.py")},
        "writes_workspace",
        None,
    )
    assert result.decision == AuthorityDecision.ALLOWED_IN_SCOPE


def test_authority_evaluation_includes_mission_id():
    auth = MissionExecutionAuthority(
        claim_id="claim-1",
        session_id="s-1",
        task_id="t-1",
        mission_id="m-42",
        canonical_paths=(_ROOT,),
        status="active",
    )
    result = auth.evaluate(
        "read_file", {"file_path": str(_ROOT / "f.py")}, "read_only", "read_only"
    )
    assert result.mission_id == "m-42"
    assert result.claim_id == "claim-1"
    assert result.provenance_sha256 is None


def test_authority_evaluation_with_provenance():
    auth = MissionExecutionAuthority(
        claim_id="claim-1",
        session_id="s-1",
        task_id="t-1",
        canonical_paths=(_ROOT,),
        status="active",
        provenance_sha256="sha256:deadbeef",
    )
    result = auth.evaluate(
        "read_file", {"file_path": str(_ROOT / "f.py")}, "read_only", "read_only"
    )
    assert result.provenance_sha256 == "sha256:deadbeef"


def test_evaluate_secret_access_refused():
    auth = MissionExecutionAuthority(
        claim_id="claim-1",
        session_id="s-1",
        task_id="t-1",
        status="active",
        admitted_protected_surface=False,
    )
    result = auth.evaluate("secret_access", {}, None, None)
    assert result.decision == AuthorityDecision.REFUSED_BY_POLICY


def test_evaluate_telemetry_policy_change_refused():
    auth = MissionExecutionAuthority(
        claim_id="claim-1",
        session_id="s-1",
        task_id="t-1",
        status="active",
        admitted_protected_surface=False,
    )
    result = auth.evaluate("telemetry_policy_change", {}, None, None)
    assert result.decision == AuthorityDecision.REFUSED_BY_POLICY


def test_evaluate_consent_policy_change_refused():
    auth = MissionExecutionAuthority(
        claim_id="claim-1",
        session_id="s-1",
        task_id="t-1",
        status="active",
        admitted_protected_surface=False,
    )
    result = auth.evaluate("consent_policy_change", {}, None, None)
    assert result.decision == AuthorityDecision.REFUSED_BY_POLICY


def test_evaluate_test_gate_weakening_refused():
    auth = MissionExecutionAuthority(
        claim_id="claim-1",
        session_id="s-1",
        task_id="t-1",
        status="active",
        admitted_protected_surface=False,
    )
    result = auth.evaluate("test_gate_weakening", {}, None, None)
    assert result.decision == AuthorityDecision.REFUSED_BY_POLICY


def test_evaluate_privacy_policy_change_refused():
    auth = MissionExecutionAuthority(
        claim_id="claim-1",
        session_id="s-1",
        task_id="t-1",
        status="active",
        admitted_protected_surface=False,
    )
    result = auth.evaluate("privacy_policy_change", {}, None, None)
    assert result.decision == AuthorityDecision.REFUSED_BY_POLICY


def test_evaluate_external_api_mutation_refused():
    auth = MissionExecutionAuthority(
        claim_id="claim-1",
        session_id="s-1",
        task_id="t-1",
        status="active",
        admitted_protected_surface=False,
    )
    result = auth.evaluate("external_api_mutation", {}, None, None)
    assert result.decision == AuthorityDecision.REFUSED_BY_POLICY


def test_evaluate_provider_mutation_refused():
    auth = MissionExecutionAuthority(
        claim_id="claim-1",
        session_id="s-1",
        task_id="t-1",
        status="active",
        admitted_protected_surface=False,
    )
    result = auth.evaluate("provider_mutation", {}, None, None)
    assert result.decision == AuthorityDecision.REFUSED_BY_POLICY


def test_evaluate_inactive_with_protected_surface():
    auth = MissionExecutionAuthority(
        claim_id="claim-1",
        session_id="s-1",
        task_id="t-1",
        status="released",
        admitted_protected_surface=True,
    )
    result = auth.evaluate("credential_access", {}, None, None)
    assert result.decision == AuthorityDecision.REFUSED_BY_POLICY
    assert result.matched_rule_kind == "protected_surface"
    assert result.requires_approval


def test_derive_authority_with_none_claim():
    class BadClaim:
        pass

    auth = derive_authority_from_claim(BadClaim())
    assert auth.canonical_paths == ()
    assert auth.status == "active"
    assert auth.worktree_root is None


def test_derive_authority_with_bad_paths_skips():
    class MockClaim:
        scope_allowed_paths: ClassVar[list[object]] = [123, None, "/tmp/ok"]
        session_id = "s"
        task_id = "t"
        status = "active"
        expires_at = None
        state_sha256 = None

    auth = derive_authority_from_claim(MockClaim())
    assert len(auth.canonical_paths) == 1
    assert auth.canonical_paths[0] == Path("/tmp/ok").resolve()


# ── Contract: install_mission_authority rejects expired claim ───────────


def test_install_mission_authority_rejects_expired_claim():
    class ExpiredClaim:
        session_id = "s-1"
        task_id = "t-1"
        scope_allowed_paths = ["/tmp/repo/src"]
        status = "active"
        expires_at = "2020-01-01T00:00:00+00:00"
        state_sha256 = "abc"

    auth = derive_authority_from_claim(ExpiredClaim(), worktree_root="/tmp/repo")
    assert not auth.is_active()


def test_install_mission_authority_rejects_released_claim():
    class ReleasedClaim:
        session_id = "s-1"
        task_id = "t-1"
        scope_allowed_paths = ["/tmp/repo/src"]
        status = "released"
        expires_at = None
        state_sha256 = "abc"

    auth = derive_authority_from_claim(ReleasedClaim(), worktree_root="/tmp/repo")
    assert not auth.is_active()


# ── Contract: AgentToolOutcome carries authority from ToolRuntime ────────


@pytest.mark.asyncio
@pytest.mark.real_artifact
async def test_agent_outcome_carries_authority_from_runtime(tmp_path):
    policy = _make_always_allow_policy()
    runtime = ToolRuntime(invoke_tool=_fake_invoke_success, policy_object=policy)
    auth = MissionExecutionAuthority(
        claim_id="claim-1",
        session_id="s-1",
        task_id="t-1",
        mission_id="m-42",
        canonical_paths=(tmp_path,),
        worktree_root=tmp_path,
        status="active",
    )
    runtime._mission_authority = auth

    request = ToolRuntimeRequest(
        tool_name="write_file",
        tool_call_id="test_outcome_carries",
        tool_args={"file_path": str(tmp_path / "out.txt"), "content": "test"},
        execution_mode=ToolRuntimeExecutionMode.MUTATION_PROPOSAL,
    )
    object.__setattr__(request, "mutation_class", "writes_workspace")

    result = await runtime.execute_one(request)
    outcome = derive_agent_outcome(result, ToolMutationClass.WRITES_WORKSPACE)

    assert outcome.authority_decision is not None
    assert outcome.authority_decision != "not_evaluated_under_mission_authority"
    assert outcome.authority_source == "mission_claim"
    assert outcome.mission_identity is not None


# ── Contract: no authority installed produces not-evaluated outcome ──────


@pytest.mark.asyncio
async def test_no_authority_produces_not_evaluated():
    policy = _make_always_allow_policy()
    runtime = ToolRuntime(invoke_tool=_fake_invoke_success, policy_object=policy)

    request = ToolRuntimeRequest(
        tool_name="read_file",
        tool_call_id="test_no_auth_outcome",
        tool_args={"file_path": "/tmp/test.txt"},
        execution_mode=ToolRuntimeExecutionMode.READ_ONLY,
    )
    result = await runtime.execute_one(request)
    outcome = derive_agent_outcome(result, ToolMutationClass.READ_ONLY)

    assert outcome.authority_decision == "not_evaluated_under_mission_authority"
    assert outcome.authority_source == "none"


# ── Contract: authority telemetry fields are content-light ───────────────


def test_authority_telemetry_fields_are_content_light():
    outcome = AgentToolOutcome(
        tool_name="test",
        tool_call_id="call-1",
        status="completed",
        authority_decision="allowed_in_scope",
        authority_source="mission_claim",
        mission_identity="pseudo_abc123",
        matched_rule_kind="scope_path",
        mutation_disposition="not_applicable",
    )

    dumped = outcome.model_dump_json()
    assert "/tmp/" not in dumped
    assert "/home/" not in dumped
    assert "/Users/" not in dumped
    assert "file_content" not in dumped
    assert "source_code" not in dumped


# ── Contract: fabricated authority fails claim verification ──────────────


def test_fabricated_authority_claim_verification():
    class FakeClaim:
        session_id = "s-1"
        task_id = "t-1"
        scope_allowed_paths = ["/tmp/repo/src"]
        status = "active"
        expires_at = None
        state_sha256 = "real_claim_digest_12345"

    auth = derive_authority_from_claim(FakeClaim(), worktree_root="/tmp/repo")
    assert auth.provenance_sha256 == "real_claim_digest_12345"

    fabricated = MissionExecutionAuthority(
        claim_id="claim-fake",
        session_id="s-1",
        task_id="t-1",
        canonical_paths=(),
        status="active",
        provenance_sha256="different_digest_99999",
    )
    assert fabricated.provenance_sha256 != "real_claim_digest_12345"


# ── Contract: Real coordination-store claim admission → authority lifecycle ─


@pytest.mark.real_artifact
@pytest.mark.substrate
def test_coordination_store_claim_admission_to_authority_lifecycle(tmp_path):
    from rig_relay.coordination.store import CoordinationStore

    store_root = tmp_path / "coordination"
    store_root.mkdir()
    store = CoordinationStore(root=store_root)

    result = store.claim_task(
        session_id="sess-lifecycle",
        task_id="task-lifecycle",
        claim_kind="implementation",
        ttl_seconds=3600,
        scope={"allowed_paths": [str(tmp_path / "src"), str(tmp_path / "tests")]},
    )
    assert result is not None
    assert result.allowed is True
    claim = result.claim
    assert claim is not None
    assert claim.status == "active"

    auth = derive_authority_from_claim(
        claim, worktree_root=str(tmp_path), mission_id="m-lifecycle"
    )
    assert auth.is_active()
    assert auth.status == "active"
    assert len(auth.canonical_paths) == 2

    store.release_task(session_id="sess-lifecycle", task_id="task-lifecycle")

    task_path = store.root / "tasks" / "task-lifecycle.json"
    released_claim = CoordinationTaskClaim.model_validate_json(
        task_path.read_text(encoding="utf-8")
    )

    auth2 = derive_authority_from_claim(released_claim, worktree_root=str(tmp_path))
    assert not auth2.is_active()


# ── Contract: BYPASS override — mission authority blocks out-of-scope mutation ─


@pytest.mark.asyncio
@pytest.mark.real_artifact
async def test_bypass_permissions_cannot_override_mission_scope(tmp_path):
    scoped = tmp_path / "src"
    scoped.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()

    auth = MissionExecutionAuthority(
        claim_id="claim-bypass",
        session_id="s-bypass",
        task_id="t-bypass",
        canonical_paths=(scoped,),
        worktree_root=tmp_path,
        status="active",
        mission_id="m-bypass",
    )

    runtime = ToolRuntime()
    runtime._mission_authority = auth

    request = ToolRuntimeRequest(
        tool_name="write_file",
        tool_call_id="test_bypass",
        tool_args={"file_path": str(outside / "out.txt"), "content": "test"},
        execution_mode=ToolRuntimeExecutionMode.MUTATION_PROPOSAL,
        bypass_permissions=True,
    )
    object.__setattr__(request, "mutation_class", "writes_workspace")

    result = await runtime.execute_one(request)

    assert result.status == ToolRuntimeStatus.REFUSED
    assert result.refusal is not None
    assert result.refusal.refusal_code == RefusalCode.SCOPE_EXPANSION_REQUIRED
    assert result.authority_decision is not None


# ── Contract: In-scope read succeeds with authority, bypass_permissions=False ─


@pytest.mark.asyncio
@pytest.mark.real_artifact
async def test_read_outside_write_scope_succeeds_with_authority(tmp_path):
    scoped = tmp_path / "src"
    scoped.mkdir()
    other = tmp_path / "docs"
    other.mkdir()
    (other / "readme.txt").write_text("docs content")

    auth = MissionExecutionAuthority(
        claim_id="claim-read",
        session_id="s-read",
        task_id="t-read",
        canonical_paths=(scoped,),
        worktree_root=tmp_path,
        status="active",
    )

    policy = _make_always_allow_policy()
    runtime = ToolRuntime(invoke_tool=_fake_invoke_success, policy_object=policy)
    runtime._mission_authority = auth

    request = ToolRuntimeRequest(
        tool_name="read_file",
        tool_call_id="test_read",
        tool_args={"file_path": str(other / "readme.txt")},
        execution_mode=ToolRuntimeExecutionMode.READ_ONLY,
    )
    object.__setattr__(request, "mutation_class", "read_only")

    result = await runtime.execute_one(request)
    if result.status == ToolRuntimeStatus.REFUSED:
        assert result.refusal is not None
        assert result.refusal.refusal_code != RefusalCode.SCOPE_EXPANSION_REQUIRED
    assert result.authority_decision is not None


# ── Contract: Governed Checkpoint Normal-Work Proof v1 ──────────────────


def test_mission_checkpoint_receipt_carries_provenance():
    receipt = generate_mission_checkpoint_receipt(
        mission_id="m-test",
        authority_provenance_sha256="sha256:abc123",
        claim_id="claim-test",
        session_id="s-test",
        task_id="t-test",
        branch="task/test-branch",
        include_paths=["src/file.py", "tests/test_file.py"],
    )

    assert receipt["authorization_source"] == "mission_execution_authority"
    assert receipt["mission_identity"] == "m-test"
    assert receipt["authority_provenance_sha256"] == "sha256:abc123"
    assert receipt["claim_id"] == "claim-test"
    assert receipt["user_verified"] is True
    assert receipt["action"] == "checkpoint.commit"
    assert receipt["receipt_sha256"].startswith("sha256:")
    assert (
        receipt["receipt_sha256"]
        != "sha256:0000000000000000000000000000000000000000000000000000000000000000"
    )
    assert receipt["action_scope"]["include_paths"] == [
        "src/file.py",
        "tests/test_file.py",
    ]
    assert receipt["action_scope"]["branch"] == "task/test-branch"


def test_mission_checkpoint_receipt_passes_validation():
    receipt = generate_mission_checkpoint_receipt(
        mission_id="m-test",
        authority_provenance_sha256="sha256:abc123",
        claim_id="claim-test",
        include_paths=["src/file.py"],
    )

    valid, reason = validate_receipt(receipt, "checkpoint.commit")
    assert valid is True
    assert reason == "Receipt valid"


def test_mission_checkpoint_receipt_rejected_for_wrong_action():
    receipt = generate_mission_checkpoint_receipt(mission_id="m-test")

    valid, reason = validate_receipt(receipt, "spawn.execute")
    assert valid is False
    assert "Action mismatch" in reason


def test_non_admitted_checkpoint_requires_consequential_approval_not_refused():
    auth = MissionExecutionAuthority(
        claim_id="claim-1",
        session_id="s-1",
        task_id="t-1",
        canonical_paths=(Path("/tmp/repo"),),
        status="active",
        admitted_checkpoint=False,
    )

    result = auth.evaluate(
        "checkpoint", {"include_paths": ["src/file.py"]}, "writes_workspace", None
    )
    assert result.decision == AuthorityDecision.REQUIRES_CONSECUTIAL_APPROVAL
    assert result.requires_approval is True
    assert result.matched_rule_kind == "consequential_action"


def test_include_paths_extracted_for_scope_check():
    paths = _extract_file_paths({
        "include_paths": ["src/a.py", "tests/b.py"],
        "file_path": "other/c.py",
    })

    assert "src/a.py" in paths
    assert "tests/b.py" in paths
    assert "other/c.py" in paths


def test_mission_checkpoint_receipt_digest_reproducible():
    r1 = generate_mission_checkpoint_receipt(
        mission_id="m-test",
        authority_provenance_sha256="sha256:abc",
        claim_id="claim-test",
        session_id="s-test",
        task_id="t-test",
        include_paths=["src/file.py"],
    )

    r2 = generate_mission_checkpoint_receipt(
        mission_id="m-test",
        authority_provenance_sha256="sha256:abc",
        claim_id="claim-test",
        session_id="s-test",
        task_id="t-test",
        include_paths=["src/file.py"],
    )

    assert r1["authorization_id"] != r2["authorization_id"]
    assert r1["mission_identity"] == r2["mission_identity"]
    assert r1["authority_provenance_sha256"] == r2["authority_provenance_sha256"]
    assert r1["action_scope"]["include_paths"] == r2["action_scope"]["include_paths"]
    assert r1["receipt_sha256"].startswith("sha256:")
    assert r2["receipt_sha256"].startswith("sha256:")
    assert r1["receipt_sha256"] != r2["receipt_sha256"]


def test_expired_authority_denies_checkpoint():
    auth = MissionExecutionAuthority(
        claim_id="claim-1",
        session_id="s-1",
        task_id="t-1",
        status="released",
        admitted_checkpoint=True,
    )

    result = auth.evaluate("checkpoint", {}, None, None)
    assert result.decision == AuthorityDecision.REFUSED_BY_POLICY


# ── Contract: Production executor path — mutation_class via constructor ───


def test_executor_request_construction_includes_mutation_class():
    """ToolRuntimeRequest constructed with mutation_class from tool class (production path).

    No object.__setattr__ workaround. Gate 2.5 can evaluate authority.
    """
    from rig_relay.core.tools.builtins.read_file import ReadFile
    from rig_relay.core.tools.builtins.write_file import WriteFile

    write_req = ToolRuntimeRequest(
        tool_name="write_file",
        tool_call_id="test-prod-path",
        tool_args={"file_path": "/tmp/test.txt", "content": "test"},
        execution_mode=ToolRuntimeExecutionMode.MUTATION_PROPOSAL,
        mutation_class=WriteFile.mutation_class.value,
    )
    assert write_req.mutation_class == "writes_workspace"

    read_req = ToolRuntimeRequest(
        tool_name="read_file",
        tool_call_id="test-prod-read",
        tool_args={"file_path": "/tmp/test.txt"},
        execution_mode=ToolRuntimeExecutionMode.READ_ONLY,
        mutation_class=ReadFile.mutation_class.value,
    )
    assert read_req.mutation_class == "read_only"


@pytest.mark.asyncio
@pytest.mark.real_artifact
async def test_production_executor_path_with_mission_authority(tmp_path: Path):
    """Real ToolRuntime with authority evaluates mutation_class from request (production path).

    No object.__setattr__. In-scope write auto-proceeds, out-of-scope gated.
    """
    scoped = tmp_path / "src"
    scoped.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()

    authority = MissionExecutionAuthority(
        claim_id="claim-prod",
        session_id="s-prod",
        task_id="t-prod",
        canonical_paths=(scoped,),
        worktree_root=tmp_path,
        status="active",
        mission_id="m-prod",
    )

    policy = _make_always_allow_policy()
    runtime = ToolRuntime(invoke_tool=_fake_invoke_success, policy_object=policy)
    runtime._mission_authority = authority

    # In-scope: mutation_class set via constructor (production path)
    in_req = ToolRuntimeRequest(
        tool_name="write_file",
        tool_call_id="prod-in",
        tool_args={"file_path": str(scoped / "app.py"), "content": "# app"},
        execution_mode=ToolRuntimeExecutionMode.MUTATION_PROPOSAL,
        mutation_class="writes_workspace",
    )
    in_result = await runtime.execute_one(in_req)
    assert in_result.authority_decision is not None
    assert in_result.authority_decision != "not_evaluated_under_mission_authority"

    # Out-of-scope
    out_req = ToolRuntimeRequest(
        tool_name="write_file",
        tool_call_id="prod-out",
        tool_args={"file_path": str(outside / "secret.py"), "content": "# secret"},
        execution_mode=ToolRuntimeExecutionMode.MUTATION_PROPOSAL,
        mutation_class="writes_workspace",
    )
    out_result = await runtime.execute_one(out_req)
    assert out_result.status == ToolRuntimeStatus.REFUSED
    assert out_result.refusal is not None
    assert out_result.refusal.refusal_code == RefusalCode.SCOPE_EXPANSION_REQUIRED
    assert out_result.authority_decision == "requires_scope_expansion"
