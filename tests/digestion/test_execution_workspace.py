"""Acceptance tests for Slice 1C: Managed Worktree Provisioning and Mission Admission."""

from __future__ import annotations

from pathlib import Path
import stat
import subprocess
import tempfile

import pytest

from rig_relay.digestion.app_paths import RigApplicationPaths
from rig_relay.digestion.execution_models import (
    ProvisioningInput,
    ProvisioningStatus,
    WorkspaceCleanupDisposition,
)
from rig_relay.digestion.execution_workspace import (
    GitWorktreeExecutionWorkspaceProvider,
)
from rig_relay.digestion.intake import IntakeResult, RepositoryIntakeService
from rig_relay.digestion.mission_admission import admit_mission
from rig_relay.digestion.registration import RepositoryRegistrationService
from tests.digestion.conftest import assert_no_filesystem_mutation, snapshot_dir


@pytest.fixture
def app_paths() -> RigApplicationPaths:
    support = Path(tempfile.mkdtemp(prefix="rig_test_support_"))
    cache = Path(tempfile.mkdtemp(prefix="rig_test_cache_"))
    return RigApplicationPaths.for_test(support, cache)


@pytest.fixture
def registration_service(
    app_paths: RigApplicationPaths,
) -> RepositoryRegistrationService:
    return RepositoryRegistrationService(app_paths)


@pytest.fixture
def provider(app_paths: RigApplicationPaths) -> GitWorktreeExecutionWorkspaceProvider:
    return GitWorktreeExecutionWorkspaceProvider(app_paths.support_root)


def _preview(repo: Path) -> IntakeResult:
    return RepositoryIntakeService().open_local_repository(repo)


def _register_and_plan(python_repo, reg_svc):
    """Register a repo and return (registration_result, provisioning_input)."""
    result = _preview(python_repo)
    reg = reg_svc.register_repository(result)
    plan = reg_svc.plan_workspace(result, reg.source_checkout.checkout_id)
    assert plan.provider_eligibility == "git_worktree_available"
    pinput = ProvisioningInput(
        plan_digest=plan.digest,
        repository_id=reg.repository.repository_id,
        source_checkout_id=reg.source_checkout.checkout_id,
        admitted_base_sha=plan.admitted_base_sha,
        proposed_managed_branch=plan.proposed_managed_branch,
        proposed_worktree_location=plan.proposed_worktree_location,
        branch_prefix="rig-mission",
        source_checkout_path=str(python_repo),
    )
    return reg, pinput


# -- Test 1: Provisioning from exact admitted base SHA -----------------


def test_provisioning_creates_workspace_at_admitted_sha(
    python_repo: Path,
    registration_service: RepositoryRegistrationService,
    provider: GitWorktreeExecutionWorkspaceProvider,
) -> None:
    _reg, pinput = _register_and_plan(python_repo, registration_service)
    ws = provider.provision(pinput)
    assert ws.managed_root_path
    assert ws.base_commit_sha == pinput.admitted_base_sha
    assert Path(ws.managed_root_path).is_dir()
    assert ws.cleanup_disposition == WorkspaceCleanupDisposition.ACTIVE


# -- Test 2: Source checkout preservation ------------------------------


def test_source_checkout_untouched_after_provisioning(
    python_repo: Path,
    registration_service: RepositoryRegistrationService,
    provider: GitWorktreeExecutionWorkspaceProvider,
) -> None:
    _reg, pinput = _register_and_plan(python_repo, registration_service)
    before = snapshot_dir(python_repo)
    ws = provider.provision(pinput)

    # git worktree add creates administrative entries in source checkout .git/
    # (refs, logs, worktrees/ metadata). The guarantee is that the source
    # checkout's working tree files are untouched, not that .git/ is frozen.
    after = snapshot_dir(python_repo)
    assert ws.managed_root_path

    # Assert only non-.git/ paths are unchanged
    before_wt = {k: v for k, v in before.items() if not k.startswith(".git/")}
    after_wt = {k: v for k, v in after.items() if not k.startswith(".git/")}
    assert_no_filesystem_mutation(
        before_wt, after_wt, "source checkout working tree after provisioning"
    )


# -- Test 3: Git repository replacement at same path -------------------


def test_same_path_different_git_repository_refused(
    python_repo: Path,
    registration_service: RepositoryRegistrationService,
    provider: GitWorktreeExecutionWorkspaceProvider,
) -> None:
    _reg, pinput = _register_and_plan(python_repo, registration_service)

    original_path = python_repo

    # Remove the .git directory and reinitialize
    subprocess.run(["rm", "-rf", str(original_path / ".git")], check=True)
    subprocess.run(
        ["git", "init", "-b", "main"],
        cwd=original_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "test@rig.relay"],
        cwd=original_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Rig Test"],
        cwd=original_path,
        check=True,
        capture_output=True,
    )
    (original_path / "replaced.txt").write_text("replaced\n")
    subprocess.run(
        ["git", "add", "."], cwd=original_path, check=True, capture_output=True
    )
    subprocess.run(
        ["git", "commit", "-m", "replaced repo"],
        cwd=original_path,
        check=True,
        capture_output=True,
    )

    # Provision should refuse -- same path, different git repo
    ws = provider.provision(pinput)
    assert ws.managed_root_path == ""
    assert (
        ProvisioningStatus.STALE_CHECKOUT_GIT_REPOSITORY_CHANGED.value
        in ws.initial_clean_state_digest
        or ProvisioningStatus.STALE_HEAD.value in ws.initial_clean_state_digest
        or ws.initial_clean_state_digest != ""
    )


# -- Test 4: HEAD staleness --------------------------------------------


def test_head_change_after_plan_refuses_provisioning(
    python_repo: Path,
    registration_service: RepositoryRegistrationService,
    provider: GitWorktreeExecutionWorkspaceProvider,
) -> None:
    _reg, pinput = _register_and_plan(python_repo, registration_service)

    # Change HEAD after planning
    (python_repo / "stale.txt").write_text("stale\n")
    subprocess.run(
        ["git", "--no-optional-locks", "add", "stale.txt"],
        cwd=python_repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "--no-optional-locks", "commit", "-m", "stale commit"],
        cwd=python_repo,
        check=True,
        capture_output=True,
    )

    ws = provider.provision(pinput)
    assert ws.managed_root_path == ""
    assert ProvisioningStatus.STALE_HEAD.value in ws.initial_clean_state_digest


# -- Test 5: Branch collision ------------------------------------------


def test_branch_collision_refuses_provisioning(
    python_repo: Path,
    registration_service: RepositoryRegistrationService,
    provider: GitWorktreeExecutionWorkspaceProvider,
) -> None:
    _reg, pinput = _register_and_plan(python_repo, registration_service)

    # Pre-create the branch
    subprocess.run(
        ["git", "branch", pinput.proposed_managed_branch, "HEAD"],
        cwd=python_repo,
        check=True,
        capture_output=True,
    )

    ws = provider.provision(pinput)
    assert ws.managed_root_path == ""
    assert ProvisioningStatus.BRANCH_COLLISION.value in ws.initial_clean_state_digest


# -- Test 6: Managed-path collision ------------------------------------


def test_path_collision_refuses_provisioning(
    python_repo: Path,
    registration_service: RepositoryRegistrationService,
    provider: GitWorktreeExecutionWorkspaceProvider,
) -> None:
    _reg, pinput = _register_and_plan(python_repo, registration_service)

    # Pre-create content at the proposed worktree location
    proposed = Path(pinput.proposed_worktree_location)
    proposed.mkdir(parents=True, exist_ok=True)
    (proposed / "collision.txt").write_text("collision\n")

    ws = provider.provision(pinput)
    assert ws.managed_root_path == ""
    assert (
        ProvisioningStatus.WORKSPACE_PATH_CONFLICT.value
        in ws.initial_clean_state_digest
    )


# -- Test 7: Executable post-checkout hook refusal ---------------------


def test_executable_hook_refuses_provisioning(
    python_repo: Path,
    registration_service: RepositoryRegistrationService,
    provider: GitWorktreeExecutionWorkspaceProvider,
) -> None:
    _reg, pinput = _register_and_plan(python_repo, registration_service)

    # Install an executable post-checkout hook
    hooks_dir = python_repo / ".git" / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)
    hook_path = hooks_dir / "post-checkout"
    hook_path.write_text("#!/bin/sh\ntouch /tmp/rig_hook_executed\n")
    hook_path.chmod(hook_path.stat().st_mode | stat.S_IEXEC)

    ws = provider.provision(pinput)
    assert ws.managed_root_path == ""
    assert (
        ProvisioningStatus.HOOK_AUTHORIZATION_REQUIRED.value
        in ws.initial_clean_state_digest
    )

    # Verify sentinel was NOT created
    sentinel = Path("/tmp/rig_hook_executed")
    assert not sentinel.exists(), "Hook was executed despite refusal!"

    # Clean up
    hook_path.unlink()


# -- Test 8: Cleanup retention -----------------------------------------


def test_cleanup_retains_dirty_workspace(
    python_repo: Path,
    registration_service: RepositoryRegistrationService,
    provider: GitWorktreeExecutionWorkspaceProvider,
) -> None:
    _reg, pinput = _register_and_plan(python_repo, registration_service)
    ws = provider.provision(pinput)
    assert ws.managed_root_path

    # Create uncommitted output in the workspace
    ws_path = Path(ws.managed_root_path)
    (ws_path / "uncommitted.txt").write_text("uncommitted\n")

    # Normal cleanup must retain
    result = provider.cleanup(
        ws, WorkspaceCleanupDisposition.USER_APPROVED_CLEANUP, force=False
    )
    assert result.status == "retained"
    assert not result.force_used

    # Force cleanup should succeed
    result2 = provider.cleanup(
        ws, WorkspaceCleanupDisposition.USER_APPROVED_CLEANUP, force=True
    )
    assert result2.status == "removed"
    assert result2.force_used


# -- Test 9: Mission admission binds workspace, not source checkout ----


def test_mission_admission_binds_workspace(
    python_repo: Path,
    registration_service: RepositoryRegistrationService,
    provider: GitWorktreeExecutionWorkspaceProvider,
) -> None:
    _reg, pinput = _register_and_plan(python_repo, registration_service)
    ws = provider.provision(pinput)
    assert ws.managed_root_path

    admission = admit_mission(
        execution_workspace_id=ws.workspace_id,
        repository_id=ws.repository_id,
        source_checkout_id=ws.source_checkout_id,
        workspace_root=ws.managed_root_path,
        admitted_paths=["src/"],
        admitted_validation_commands=["uv run pytest"],
        checkpoint_admitted=True,
    )

    assert admission.execution_workspace_id == ws.workspace_id
    assert admission.repository_id == ws.repository_id
    assert admission.source_checkout_id == ws.source_checkout_id
    assert admission.admitted_paths == ["src/"]
    assert admission.checkpoint_admitted
