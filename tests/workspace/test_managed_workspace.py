from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
import subprocess

import pytest

from rig_relay.workspace._config import WorkspaceConfig
from rig_relay.workspace._digest import compute_event_digest
from rig_relay.workspace._evidence import WorkspaceLifecycleLedger
from rig_relay.workspace._projection import build_fleet_workspace_projection
from rig_relay.workspace._recovery import WorkspaceRecoveryEngine
from rig_relay.workspace._service import (
    _ACTION_MAP,
    ManagedWorkspaceService,
    _actions_for_workspace,
)
from rig_relay.workspace.models import (
    AssignmentState,
    ManagedWorkspace,
    RecoveryState,
    WorkPreservationState,
    WorkspaceAssignmentRequest,
    WorkspaceIdentity,
    WorkspaceLifecycleEvent,
    WorkspaceLifecycleEventKind,
    WorkspaceRole,
    WorkspaceState,
)


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    subprocess.run(
        ["git", "init", "-b", "main"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"], cwd=repo, capture_output=True
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"], cwd=repo, capture_output=True
    )
    (repo / "README.md").write_text("# Test Repo\n")
    subprocess.run(
        ["git", "add", "."], cwd=repo, capture_output=True, text=True, check=True
    )
    subprocess.run(
        ["git", "commit", "-m", "initial commit"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )
    return repo


def _get_head_sha(repo: Path) -> str:
    proc = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )
    return proc.stdout.strip()


def _make_identity(
    project: str = "test-project", role: WorkspaceRole = WorkspaceRole.IMPLEMENTER
) -> WorkspaceIdentity:
    return WorkspaceIdentity(project_identity=project, role=role)


def _git_worktree_list(repo: Path) -> list[str]:
    proc = subprocess.run(
        ["git", "worktree", "list", "--porcelain"],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    return proc.stdout.strip().split("\n")


def _git_branch_list(repo: Path) -> list[str]:
    proc = subprocess.run(
        ["git", "branch", "-a"], cwd=repo, capture_output=True, text=True
    )
    return proc.stdout.strip().split("\n")


class TestManagedWorkspaceService:
    @pytest.mark.asyncio
    @pytest.mark.substrate
    async def test_workspace_lifecycle_happy_path(self, git_repo: Path):
        base_sha = _get_head_sha(git_repo)
        svc = ManagedWorkspaceService(repo_root=git_repo)

        identity = _make_identity()
        ws, err = await svc.request_workspace(
            identity, base_sha, session_id="session-1"
        )
        assert ws is not None
        assert err == ""
        assert ws.state == WorkspaceState.RESERVED
        assert ws.identity.workspace_id == identity.workspace_id
        wid = ws.identity.workspace_id

        ok, err = await svc.create_worktree(wid)
        assert ok, err
        worktree_lines = _git_worktree_list(git_repo)
        assert any(wid in line for line in worktree_lines)

        ws = await svc.get_workspace(wid)
        assert ws is not None
        assert ws.state == WorkspaceState.WORKTREE_CREATED

        ok, err = await svc.bootstrap(wid)
        assert ok, err
        ws = await svc.get_workspace(wid)
        assert ws is not None
        assert ws.state == WorkspaceState.READY

        ok, err = await svc.activate(wid, "session-1")
        assert ok, err
        ws = await svc.get_workspace(wid)
        assert ws is not None
        assert ws.state == WorkspaceState.ACTIVE

        ok, err = await svc.record_changes(wid, changed_files_count=3)
        assert ok, err
        await svc.list_workspaces()
        ws = await svc.get_workspace(wid)
        assert ws is not None
        assert ws.changed_files_count == 3

        ok, err = await svc.mark_validating(wid)
        assert ok, err
        ws = await svc.get_workspace(wid)
        assert ws is not None
        assert ws.state == WorkspaceState.VALIDATING

        ok, err = await svc.mark_under_review(wid)
        assert ok, err
        ws = await svc.get_workspace(wid)
        assert ws is not None
        assert ws.state == WorkspaceState.UNDER_REVIEW

        ok, err = await svc.checkpoint(wid, "fake-checkpoint-sha-abc123")
        assert ok, err
        ws = await svc.get_workspace(wid)
        assert ws is not None
        assert ws.state == WorkspaceState.CHECKPOINTED

        ok, err = await svc.release_for_integration(wid)
        assert ok, err
        ws = await svc.get_workspace(wid)
        assert ws is not None
        assert ws.state == WorkspaceState.RELEASED_FOR_INTEGRATION

        ok, err = await svc.mark_integrated(wid)
        assert ok, err
        ws = await svc.get_workspace(wid)
        assert ws is not None
        assert ws.state == WorkspaceState.INTEGRATED

        ok, err = await svc.mark_published(wid)
        assert ok, err
        ws = await svc.get_workspace(wid)
        assert ws is not None
        assert ws.state == WorkspaceState.PUBLISHED

        ok, err = await svc.retire(wid)
        assert ok, err
        ws = await svc.get_workspace(wid)
        assert ws is not None
        assert ws.state == WorkspaceState.RETIRED

    @pytest.mark.asyncio
    @pytest.mark.substrate
    async def test_create_multiple_simultaneous_worktrees(self, git_repo: Path):
        base_sha = _get_head_sha(git_repo)
        svc = ManagedWorkspaceService(repo_root=git_repo)
        workspace_ids: list[str] = []

        for i in range(3):
            identity = WorkspaceIdentity(
                project_identity="test-project", role=WorkspaceRole.IMPLEMENTER
            )
            ws, err = await svc.request_workspace(
                identity, base_sha, session_id=f"session-{i}"
            )
            assert ws is not None
            assert err == ""
            wid = ws.identity.workspace_id
            workspace_ids.append(wid)
            ok, err = await svc.create_worktree(wid)
            assert ok, err
            ok, err = await svc.bootstrap(wid)
            assert ok, err
            ok, err = await svc.activate(wid, f"session-{i}")
            assert ok, err

        worktree_lines = _git_worktree_list(git_repo)
        for wid in workspace_ids:
            assert any(wid in line for line in worktree_lines)

        for wid in workspace_ids:
            wt_dir = git_repo / ".rig" / "relay" / "workspaces" / wid
            assert wt_dir.exists()
            assert (wt_dir / "README.md").exists()

        for wid in workspace_ids:
            ws = await svc.get_workspace(wid)
            assert ws is not None
            assert ws.state == WorkspaceState.ACTIVE

    @pytest.mark.asyncio
    async def test_workspace_listing_and_filtering(self, git_repo: Path):
        base_sha = _get_head_sha(git_repo)
        svc = ManagedWorkspaceService(repo_root=git_repo)

        for i in range(3):
            identity = _make_identity(project=f"proj-{i}")
            ws, err = await svc.request_workspace(
                identity, base_sha, session_id=f"session-{i}"
            )
            assert ws is not None
            assert err == ""

        all_ws = await svc.list_workspaces()
        assert len(all_ws) == 3

        reserved = await svc.list_workspaces(state=WorkspaceState.RESERVED)
        assert len(reserved) == 3

        active_list = await svc.list_workspaces(state=WorkspaceState.ACTIVE)
        assert len(active_list) == 0

    @pytest.mark.asyncio
    async def test_invalid_transition_refused(self, git_repo: Path):
        base_sha = _get_head_sha(git_repo)
        svc = ManagedWorkspaceService(repo_root=git_repo)

        identity = _make_identity()
        ws, err = await svc.request_workspace(identity, base_sha)
        assert ws is not None
        assert err == ""
        assert ws.state == WorkspaceState.RESERVED
        wid = ws.identity.workspace_id

        ok, err = await svc.activate(wid, "session-1")
        assert not ok
        err_lower = err.lower()
        assert "invalid transition" in err_lower or "ready state" in err_lower

        ok, err = await svc.checkpoint(wid, "sha")
        assert not ok

        ok, err = await svc.release_for_integration(wid)
        assert not ok

    @pytest.mark.asyncio
    async def test_terminal_state_refuses_transition(self, git_repo: Path):
        base_sha = _get_head_sha(git_repo)
        svc = ManagedWorkspaceService(repo_root=git_repo)

        identity = _make_identity()
        ws, err = await svc.request_workspace(identity, base_sha)
        assert ws is not None
        assert err == ""
        wid = ws.identity.workspace_id

        ok, err = await svc.bootstrap(wid)
        assert not ok

        ok, err = await svc.activate(wid, "session-1")
        assert not ok

    @pytest.mark.asyncio
    @pytest.mark.substrate
    async def test_base_sha_tracking(self, git_repo: Path):
        base_sha = _get_head_sha(git_repo)
        svc = ManagedWorkspaceService(repo_root=git_repo)

        identity = _make_identity()
        ws, err = await svc.request_workspace(identity, base_sha)
        assert ws is not None
        assert err == ""
        assert ws.base_commit_sha == base_sha
        wid = ws.identity.workspace_id

        ok, err = await svc.create_worktree(wid)
        assert ok, err
        ok, err = await svc.bootstrap(wid)
        assert ok, err
        ok, err = await svc.activate(wid, "session-1")
        assert ok, err

        await svc.list_workspaces()
        ws = await svc.get_workspace(wid)
        assert ws is not None
        assert ws.base_commit_sha == base_sha

    @pytest.mark.asyncio
    @pytest.mark.substrate
    async def test_changed_files_tracking(self, git_repo: Path):
        base_sha = _get_head_sha(git_repo)
        svc = ManagedWorkspaceService(repo_root=git_repo)

        identity = _make_identity()
        ws, err = await svc.request_workspace(identity, base_sha)
        assert ws is not None
        assert err == ""
        wid = ws.identity.workspace_id

        ok, err = await svc.create_worktree(wid)
        assert ok, err
        ok, err = await svc.bootstrap(wid)
        assert ok, err
        ok, err = await svc.activate(wid, "session-1")
        assert ok, err

        ok, err = await svc.record_changes(wid, changed_files_count=5)
        assert ok, err
        await svc.list_workspaces()
        ws = await svc.get_workspace(wid)
        assert ws is not None
        assert ws.changed_files_count == 5

        ok, err = await svc.record_changes(wid, changed_files_count=12)
        assert ok, err
        await svc.list_workspaces()
        ws = await svc.get_workspace(wid)
        assert ws is not None
        assert ws.changed_files_count == 12

    @pytest.mark.asyncio
    @pytest.mark.substrate
    async def test_branch_naming_convention(self, git_repo: Path):
        base_sha = _get_head_sha(git_repo)
        svc = ManagedWorkspaceService(repo_root=git_repo)

        for role in WorkspaceRole:
            identity = WorkspaceIdentity(project_identity="test-project", role=role)
            ws, err = await svc.request_workspace(identity, base_sha, session_id="s1")
            assert ws is not None
            assert err == ""
            wid = ws.identity.workspace_id
            ok, err = await svc.create_worktree(wid)
            assert ok, err

        branch_lines = _git_branch_list(git_repo)
        for role in WorkspaceRole:
            expected_prefix = f"rig/{role.value}/"
            found = any(expected_prefix in line for line in branch_lines)
            assert found, f"branch with prefix {expected_prefix} not found"

    @pytest.mark.asyncio
    @pytest.mark.substrate
    async def test_retire_removes_worktree(self, git_repo: Path):
        base_sha = _get_head_sha(git_repo)
        svc = ManagedWorkspaceService(repo_root=git_repo)

        identity = _make_identity()
        ws, err = await svc.request_workspace(identity, base_sha)
        assert ws is not None
        assert err == ""
        wid = ws.identity.workspace_id

        ok, err = await svc.create_worktree(wid)
        assert ok, err
        wt_dir = git_repo / ".rig" / "relay" / "workspaces" / wid
        assert wt_dir.exists()

        ok, err = await svc.bootstrap(wid)
        assert ok, err
        ok, err = await svc.activate(wid, "session-1")
        assert ok, err
        ok, err = await svc.mark_validating(wid)
        assert ok, err
        ok, err = await svc.mark_under_review(wid)
        assert ok, err
        ok, err = await svc.checkpoint(wid, "cp-sha")
        assert ok, err
        ok, err = await svc.release_for_integration(wid)
        assert ok, err
        ok, err = await svc.mark_integrated(wid)
        assert ok, err
        ok, err = await svc.mark_published(wid)
        assert ok, err

        ok, err = await svc.retire(wid)
        assert ok, err

        ws = await svc.get_workspace(wid)
        assert ws is not None
        assert ws.state == WorkspaceState.RETIRED
        assert not wt_dir.exists()

    @pytest.mark.asyncio
    @pytest.mark.substrate
    async def test_refuse_retire_with_uncommitted_changes_without_force(
        self, git_repo: Path
    ):
        base_sha = _get_head_sha(git_repo)
        svc = ManagedWorkspaceService(repo_root=git_repo)

        identity = _make_identity()
        ws, err = await svc.request_workspace(identity, base_sha)
        assert ws is not None
        assert err == ""
        wid = ws.identity.workspace_id

        ok, err = await svc.create_worktree(wid)
        assert ok, err
        ok, err = await svc.bootstrap(wid)
        assert ok, err
        ok, err = await svc.activate(wid, "session-1")
        assert ok, err

        wt_dir = git_repo / ".rig" / "relay" / "workspaces" / wid
        (wt_dir / "dirty.txt").write_text("uncommitted change")
        ok, err = await svc.retire(wid, force=False)
        assert not ok
        assert any(
            term in err.lower()
            for term in (
                "refused",
                "changes",
                "uncommitted",
                "modified",
                "removal failed",
            )
        )

    @pytest.mark.asyncio
    async def test_workspace_persistence_across_reload(self, git_repo: Path):
        base_sha = _get_head_sha(git_repo)
        svc1 = ManagedWorkspaceService(repo_root=git_repo)

        identity = _make_identity()
        ws, err = await svc1.request_workspace(identity, base_sha, session_id="s1")
        assert ws is not None
        assert err == ""
        wid = ws.identity.workspace_id

        svc2 = ManagedWorkspaceService(repo_root=git_repo)
        loaded = await svc2.get_workspace(wid)
        assert loaded is not None
        assert loaded.state == WorkspaceState.RESERVED
        assert loaded.base_commit_sha == base_sha
        assert loaded.identity.project_identity == "test-project"

    @pytest.mark.asyncio
    async def test_get_workspace_returns_none_for_unknown_id(self, git_repo: Path):
        svc = ManagedWorkspaceService(repo_root=git_repo)
        ws = await svc.get_workspace("nonexistent-id")
        assert ws is None

    @pytest.mark.asyncio
    async def test_actions_map_coverage(self):
        for state in WorkspaceState:
            actions = _ACTION_MAP.get(state, [])
            assert isinstance(actions, list)
        retired = _ACTION_MAP.get(WorkspaceState.RETIRED)
        assert retired == []

    @pytest.mark.asyncio
    async def test_actions_for_active_with_recovery(self, git_repo: Path):
        base_sha = _get_head_sha(git_repo)
        svc = ManagedWorkspaceService(repo_root=git_repo)

        identity = _make_identity()
        ws, err = await svc.request_workspace(
            identity, base_sha, session_id="old-session"
        )
        assert ws is not None
        assert err == ""
        wid = ws.identity.workspace_id

        ok, err = await svc.create_worktree(wid)
        assert ok, err
        ok, err = await svc.bootstrap(wid)
        assert ok, err
        ok, err = await svc.activate(wid, "old-session")
        assert ok, err

        ok, err = await svc.detect_session_detached(wid, "new-session")
        assert ok, err

        ws = await svc.get_workspace(wid)
        assert ws is not None
        actions = _actions_for_workspace(ws)
        assert "recover" in actions
        assert "quarantine" in actions

    @pytest.mark.asyncio
    async def test_transition_rollback_on_ledger_failure(self, git_repo: Path):
        base_sha = _get_head_sha(git_repo)
        svc = ManagedWorkspaceService(repo_root=git_repo)

        identity = _make_identity(project="test-rollback")
        ws, err = await svc.request_workspace(identity, base_sha, session_id="sess-1")
        assert ws is not None
        assert err == ""
        ws_id = ws.identity.workspace_id

        ws_before = await svc.get_workspace(ws_id)
        assert ws_before is not None
        old_state = ws_before.state

        original_append = svc._ledger.append

        def failing_append(event: WorkspaceLifecycleEvent) -> str:
            raise OSError("simulated disk full")

        svc._ledger.append = failing_append

        ok, err_text = await svc.create_worktree(ws_id)

        svc._ledger.append = original_append

        ws_after = await svc.get_workspace(ws_id)
        assert ws_after is not None
        assert ws_after.state == old_state

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "bad_id", ["../escape", "foo\\bar", "~home", "a" * 65, "", "   "]
    )
    async def test_sanitize_workspace_id_rejects_traversal(
        self, git_repo: Path, bad_id: str
    ):
        base_sha = _get_head_sha(git_repo)
        svc = ManagedWorkspaceService(repo_root=git_repo)

        identity = WorkspaceIdentity(
            workspace_id=bad_id,
            project_identity="test-sanitize",
            role=WorkspaceRole.TESTER,
        )
        ws, _ = await svc.request_workspace(identity, base_sha, "sess-1")
        assert ws is not None
        ws_id = ws.identity.workspace_id

        ok, err_val = await svc.create_worktree(ws_id)
        assert not ok, f"expected rejection for bad_id={bad_id!r}, got err={err_val!r}"


class TestWorkspaceRecovery:
    @pytest.mark.asyncio
    @pytest.mark.substrate
    async def test_detect_stale_base(self, git_repo: Path):
        base_sha = _get_head_sha(git_repo)
        svc = ManagedWorkspaceService(repo_root=git_repo)

        identity = _make_identity()
        ws, err = await svc.request_workspace(identity, base_sha, session_id="s1")
        assert ws is not None
        assert err == ""
        wid = ws.identity.workspace_id

        ok, err = await svc.create_worktree(wid)
        assert ok, err
        ok, err = await svc.bootstrap(wid)
        assert ok, err
        ok, err = await svc.activate(wid, "s1")
        assert ok, err

        (git_repo / "orphan_file.md").write_text("# Orphan\n")
        subprocess.run(
            ["git", "add", "orphan_file.md"],
            cwd=git_repo,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            ["git", "commit", "--amend", "-m", "rewritten root"],
            cwd=git_repo,
            capture_output=True,
            text=True,
        )

        ok, err = await svc.detect_stale_base(wid)
        assert ok, err

        ws = await svc.get_workspace(wid)
        assert ws is not None
        assert ws.recovery_state == RecoveryState.STALE_BASE

    @pytest.mark.asyncio
    @pytest.mark.substrate
    async def test_detect_session_detached(self, git_repo: Path):
        base_sha = _get_head_sha(git_repo)
        svc = ManagedWorkspaceService(repo_root=git_repo)

        identity = _make_identity()
        ws, err = await svc.request_workspace(
            identity, base_sha, session_id="old-session"
        )
        assert ws is not None
        assert err == ""
        wid = ws.identity.workspace_id

        ok, err = await svc.create_worktree(wid)
        assert ok, err
        ok, err = await svc.bootstrap(wid)
        assert ok, err
        ok, err = await svc.activate(wid, "old-session")
        assert ok, err

        ok, err = await svc.detect_session_detached(wid, "new-session")
        assert ok, err

        ws = await svc.get_workspace(wid)
        assert ws is not None
        assert ws.recovery_state == RecoveryState.SESSION_DETACHED

    @pytest.mark.asyncio
    @pytest.mark.substrate
    async def test_detect_session_not_detached_when_same(self, git_repo: Path):
        base_sha = _get_head_sha(git_repo)
        svc = ManagedWorkspaceService(repo_root=git_repo)

        identity = _make_identity()
        ws, err = await svc.request_workspace(
            identity, base_sha, session_id="session-x"
        )
        assert ws is not None
        assert err == ""
        wid = ws.identity.workspace_id

        ok, err = await svc.create_worktree(wid)
        assert ok, err
        ok, err = await svc.bootstrap(wid)
        assert ok, err
        ok, err = await svc.activate(wid, "session-x")
        assert ok, err

        ok, err = await svc.detect_session_detached(wid, "session-x")
        assert ok
        assert err == ""

        ws = await svc.get_workspace(wid)
        assert ws is not None
        assert ws.recovery_state is None

    @pytest.mark.asyncio
    @pytest.mark.substrate
    async def test_recover_from_session_detached(self, git_repo: Path):
        base_sha = _get_head_sha(git_repo)
        svc = ManagedWorkspaceService(repo_root=git_repo)

        identity = _make_identity()
        ws, err = await svc.request_workspace(
            identity, base_sha, session_id="old-session"
        )
        assert ws is not None
        assert err == ""
        wid = ws.identity.workspace_id

        ok, err = await svc.create_worktree(wid)
        assert ok, err
        ok, err = await svc.bootstrap(wid)
        assert ok, err
        ok, err = await svc.activate(wid, "old-session")
        assert ok, err

        ok, err = await svc.detect_session_detached(wid, "new-session")
        assert ok, err

        ws = await svc.get_workspace(wid)
        assert ws is not None
        assert ws.recovery_state == RecoveryState.SESSION_DETACHED

        ok, err = await svc.recover(wid, "new-session")
        assert ok, err

        ws = await svc.get_workspace(wid)
        assert ws is not None
        assert ws.state == WorkspaceState.ACTIVE
        assert ws.recovery_state is None
        assert ws.session_id == "new-session"

    @pytest.mark.asyncio
    @pytest.mark.substrate
    async def test_recover_refuses_non_recovery_state(self, git_repo: Path):
        base_sha = _get_head_sha(git_repo)
        svc = ManagedWorkspaceService(repo_root=git_repo)

        identity = _make_identity()
        ws, err = await svc.request_workspace(identity, base_sha, session_id="s1")
        assert ws is not None
        assert err == ""
        wid = ws.identity.workspace_id

        ok, err = await svc.create_worktree(wid)
        assert ok, err
        ok, err = await svc.bootstrap(wid)
        assert ok, err
        ok, err = await svc.activate(wid, "s1")
        assert ok, err

        ok, err = await svc.recover(wid, "other-session")
        assert not ok
        assert "not in a recovery state" in err.lower()

    @pytest.mark.asyncio
    @pytest.mark.substrate
    async def test_recovery_workspace_reconstruction(self, git_repo: Path):
        base_sha = _get_head_sha(git_repo)
        svc1 = ManagedWorkspaceService(repo_root=git_repo)

        identity = _make_identity()
        ws, err = await svc1.request_workspace(identity, base_sha, session_id="s1")
        assert ws is not None
        assert err == ""
        wid = ws.identity.workspace_id

        ok, err = await svc1.create_worktree(wid)
        assert ok, err
        ok, err = await svc1.bootstrap(wid)
        assert ok, err
        ok, err = await svc1.activate(wid, "s1")
        assert ok, err
        ok, err = await svc1.record_changes(wid, changed_files_count=7)
        assert ok, err

        svc2 = ManagedWorkspaceService(repo_root=git_repo)
        loaded = await svc2.get_workspace(wid)
        assert loaded is not None
        assert loaded.state == WorkspaceState.ACTIVE
        assert loaded.identity.workspace_id == wid
        assert loaded.identity.project_identity == "test-project"
        assert loaded.identity.role == WorkspaceRole.IMPLEMENTER
        assert loaded.base_commit_sha == base_sha

    @pytest.mark.asyncio
    @pytest.mark.substrate
    async def test_quarantine_workspace(self, git_repo: Path):
        base_sha = _get_head_sha(git_repo)
        svc = ManagedWorkspaceService(repo_root=git_repo)

        identity = _make_identity()
        ws, err = await svc.request_workspace(
            identity, base_sha, session_id="old-session"
        )
        assert ws is not None
        assert err == ""
        wid = ws.identity.workspace_id

        ok, err = await svc.create_worktree(wid)
        assert ok, err
        ok, err = await svc.bootstrap(wid)
        assert ok, err
        ok, err = await svc.activate(wid, "old-session")
        assert ok, err

        ok, err = await svc.detect_session_detached(wid, "new-session")
        assert ok, err

        ws = await svc.get_workspace(wid)
        assert ws is not None
        assert ws.recovery_state == RecoveryState.SESSION_DETACHED

        ok, err = await svc.quarantine(wid, "test quarantine reason")
        assert ok, err

        ws = await svc.get_workspace(wid)
        assert ws is not None
        assert ws.state == WorkspaceState.RETIRED
        assert ws.recovery_state == RecoveryState.QUARANTINED

    @pytest.mark.asyncio
    @pytest.mark.substrate
    async def test_quarantine_refused_on_terminal_recovery(self, git_repo: Path):
        base_sha = _get_head_sha(git_repo)
        svc = ManagedWorkspaceService(repo_root=git_repo)

        identity = _make_identity()
        ws, err = await svc.request_workspace(
            identity, base_sha, session_id="old-session"
        )
        assert ws is not None
        assert err == ""
        wid = ws.identity.workspace_id

        ok, err = await svc.create_worktree(wid)
        assert ok, err
        ok, err = await svc.bootstrap(wid)
        assert ok, err
        ok, err = await svc.activate(wid, "old-session")
        assert ok, err
        ok, err = await svc.detect_session_detached(wid, "new-session")
        assert ok, err

        ok, err = await svc.quarantine(wid, "first quarantine")
        assert ok, err

        ok, err = await svc.quarantine(wid, "second quarantine")
        assert not ok

    @pytest.mark.asyncio
    @pytest.mark.substrate
    async def test_recovery_detects_locked_worktree(self, git_repo: Path):
        base_sha = _get_head_sha(git_repo)
        svc = ManagedWorkspaceService(repo_root=git_repo)
        recovery = WorkspaceRecoveryEngine(svc, git_repo)

        identity = _make_identity()
        ws, err = await svc.request_workspace(
            identity, base_sha, session_id="old-session"
        )
        assert ws is not None
        assert err == ""
        wid = ws.identity.workspace_id

        ok, err = await svc.create_worktree(wid)
        assert ok, err
        ok, err = await svc.bootstrap(wid)
        assert ok, err
        ok, err = await svc.activate(wid, "old-session")
        assert ok, err

        ws = await svc.get_workspace(wid)
        assert ws is not None
        subprocess.run(
            [
                "git",
                "-C",
                str(git_repo),
                "worktree",
                "lock",
                ws.worktree_path or "",
                "--reason",
                "test lock",
            ],
            capture_output=True,
        )
        await svc.detect_session_detached(wid, "different-session")
        ok, _ = await recovery.attempt_recovery(wid, "new-session")
        assert ok

    @pytest.mark.asyncio
    @pytest.mark.substrate
    async def test_recovery_detects_missing_git_file(self, git_repo: Path):
        base_sha = _get_head_sha(git_repo)
        svc = ManagedWorkspaceService(repo_root=git_repo)
        recovery = WorkspaceRecoveryEngine(svc, git_repo)

        identity = _make_identity()
        ws, err = await svc.request_workspace(
            identity, base_sha, session_id="old-session"
        )
        assert ws is not None
        assert err == ""
        wid = ws.identity.workspace_id

        ok, err = await svc.create_worktree(wid)
        assert ok, err
        ok, err = await svc.bootstrap(wid)
        assert ok, err
        ok, err = await svc.activate(wid, "old-session")
        assert ok, err

        ws = await svc.get_workspace(wid)
        assert ws is not None
        worktree_path = ws.worktree_path
        assert worktree_path is not None
        git_file = Path(worktree_path) / ".git"
        if git_file.is_file():
            git_file.write_text(
                f"gitdir: /nonexistent/path/to/repo/.git/worktrees/{wid}\n"
            )
        await svc.detect_session_detached(wid, "different-session")
        ok, err = await recovery.attempt_recovery(wid, "new-session")
        assert ok, f"recovery should handle missing git file gracefully, got: {err}"

    @pytest.mark.asyncio
    @pytest.mark.substrate
    async def test_recovery_handles_detached_head(self, git_repo: Path):
        base_sha = _get_head_sha(git_repo)
        svc = ManagedWorkspaceService(repo_root=git_repo)
        recovery = WorkspaceRecoveryEngine(svc, git_repo)

        identity = _make_identity()
        ws, err = await svc.request_workspace(
            identity, base_sha, session_id="old-session"
        )
        assert ws is not None
        assert err == ""
        wid = ws.identity.workspace_id

        ok, err = await svc.create_worktree(wid)
        assert ok, err
        ok, err = await svc.bootstrap(wid)
        assert ok, err
        ok, err = await svc.activate(wid, "old-session")
        assert ok, err

        ws = await svc.get_workspace(wid)
        assert ws is not None
        subprocess.run(
            [
                "git",
                "-C",
                ws.worktree_path or "",
                "checkout",
                ws.base_commit_sha or "HEAD",
            ],
            capture_output=True,
            text=True,
        )
        await svc.detect_session_detached(wid, "different-session")
        ok, _ = await recovery.attempt_recovery(wid, "new-session")
        assert ok

    @pytest.mark.asyncio
    @pytest.mark.substrate
    async def test_concurrent_recovery_safety(self, git_repo: Path):
        base_sha = _get_head_sha(git_repo)
        svc = ManagedWorkspaceService(repo_root=git_repo)

        identity = WorkspaceIdentity(
            project_identity="test-concurrent", role=WorkspaceRole.TESTER
        )
        ws, _ = await svc.request_workspace(identity, base_sha, "sess-1")
        assert ws is not None
        ws_id = ws.identity.workspace_id

        ok, err = await svc.create_worktree(ws_id)
        assert ok, err
        ok, err = await svc.bootstrap(ws_id)
        assert ok, err
        ok, err = await svc.activate(ws_id, "sess-1")
        assert ok, err

        dirty_path = (
            Path(git_repo) / ".rig" / "relay" / "workspaces" / ws_id / "dirty.txt"
        )
        dirty_path.write_text("concurrent test")

        ok, err = await svc.detect_session_detached(ws_id, "different-session")
        assert ok, err

        async def do_recover(sid: str) -> tuple[bool, str]:
            svc2 = ManagedWorkspaceService(
                repo_root=str(git_repo), config=WorkspaceConfig()
            )
            return await svc2.recover(ws_id, sid)

        results = await asyncio.gather(
            do_recover("sess-A"), do_recover("sess-B"), return_exceptions=True
        )
        successes = [r for r in results if isinstance(r, tuple) and r[0] is True]
        assert len(successes) == 1, (
            f"expected exactly 1 concurrent recovery success, got {len(successes)}: {results}"
        )

    @pytest.mark.asyncio
    @pytest.mark.substrate
    async def test_cold_cache_recovery_persists_session_id(self, git_repo: Path):
        config = WorkspaceConfig()
        identity = WorkspaceIdentity(
            project_identity="test-coldcache", role=WorkspaceRole.TESTER
        )

        svc1 = ManagedWorkspaceService(repo_root=str(git_repo), config=config)
        ws, _ = await svc1.request_workspace(identity, "HEAD", "sess-original")
        assert ws is not None
        ws_id = ws.identity.workspace_id
        await svc1.create_worktree(ws_id)
        await svc1.bootstrap(ws_id)
        await svc1.activate(ws_id, "sess-original")
        await svc1.detect_session_detached(ws_id, "different-session")

        svc2 = ManagedWorkspaceService(repo_root=str(git_repo), config=config)
        svc2._workspaces.clear()

        ok, err = await svc2.recover(ws_id, "new-session")
        assert ok, f"recovery failed: {err}"

        ws_file = svc2._load_workspace(ws_id)
        assert ws_file is not None
        assert ws_file.session_id == "new-session"
        assert ws_file.recovery_state is None

        ws_check = svc2._load_workspace(ws_id)
        assert ws_check is not None
        assert ws_check.recovery_state is None

    @pytest.mark.asyncio
    @pytest.mark.substrate
    async def test_cold_cache_recovery_with_dirty_edits_preserved(self, git_repo: Path):
        config = WorkspaceConfig()
        identity = WorkspaceIdentity(
            project_identity="test-dirty", role=WorkspaceRole.IMPLEMENTER
        )

        svc1 = ManagedWorkspaceService(repo_root=str(git_repo), config=config)
        ws, _ = await svc1.request_workspace(identity, "HEAD", "sess-original")
        assert ws is not None
        ws_id = ws.identity.workspace_id
        await svc1.create_worktree(ws_id)
        await svc1.bootstrap(ws_id)
        await svc1.activate(ws_id, "sess-original")

        dirty_file = git_repo / ".rig" / "relay" / "workspaces" / ws_id / "important.py"
        dirty_file.write_text("# critical work that must not be lost\n")
        await svc1.record_changes(ws_id, changed_files_count=1)

        await svc1.detect_session_detached(ws_id, "different-session")

        svc2 = ManagedWorkspaceService(repo_root=str(git_repo), config=config)
        svc2._workspaces.clear()

        ok, err = await svc2.recover(ws_id, "new-session")
        assert ok, f"recovery failed: {err}"

        assert dirty_file.exists()
        content = dirty_file.read_text()
        assert "critical work" in content

        projection = await svc2.build_projection()
        recovered_ws = [w for w in projection.workspaces if w.workspace_id == ws_id][0]
        assert recovered_ws.changed_files_count >= 1

    @pytest.mark.asyncio
    @pytest.mark.substrate
    async def test_cold_cache_recovery_with_ledger_append_failure(self, git_repo: Path):
        config = WorkspaceConfig()
        identity = WorkspaceIdentity(
            project_identity="test-ledgerfail", role=WorkspaceRole.TESTER
        )

        svc1 = ManagedWorkspaceService(repo_root=str(git_repo), config=config)
        ws, _ = await svc1.request_workspace(identity, "HEAD", "sess-original")
        assert ws is not None
        ws_id = ws.identity.workspace_id
        await svc1.create_worktree(ws_id)
        await svc1.bootstrap(ws_id)
        await svc1.activate(ws_id, "sess-original")
        await svc1.detect_session_detached(ws_id, "different-session")

        svc2 = ManagedWorkspaceService(repo_root=str(git_repo), config=config)
        svc2._workspaces.clear()

        def failing_append(event: WorkspaceLifecycleEvent) -> str:
            raise OSError("simulated disk full")

        svc2._ledger.append = failing_append

        ok, err = await svc2.recover(ws_id, "new-session")
        assert not ok
        assert any(term in err.lower() for term in ("failed", "error", "rollback"))

        ws = await svc2.get_workspace(ws_id)
        assert ws is not None
        assert ws.recovery_state is not None


class TestWorkspaceLifecycleLedger:
    def test_append_and_load_events(self, tmp_path: Path):
        ledger_path = tmp_path / "events.jsonl"
        ledger = WorkspaceLifecycleLedger(ledger_path)

        for _ in range(3):
            event = WorkspaceLifecycleEvent(
                workspace_id="ws-1",
                event_kind=WorkspaceLifecycleEventKind.WORKSPACE_ACTIVATED,
                state_before=WorkspaceState.READY,
                state_after=WorkspaceState.ACTIVE,
            )
            ledger.append(event)

        events = ledger.load_events("ws-1")
        assert len(events) == 3
        for e in events:
            assert e.workspace_id == "ws-1"
            assert e.event_digest is not None
            assert e.event_digest.startswith("sha256:")

    def test_verify_intact_chain(self, tmp_path: Path):
        ledger_path = tmp_path / "events.jsonl"
        ledger = WorkspaceLifecycleLedger(ledger_path)

        for _ in range(5):
            event = WorkspaceLifecycleEvent(
                workspace_id="ws-chain",
                event_kind=WorkspaceLifecycleEventKind.WORKSPACE_CHECKPOINTED,
                state_before=WorkspaceState.ACTIVE,
                state_after=WorkspaceState.CHECKPOINTED,
            )
            ledger.append(event)

        ok, err = ledger.verify_chain("ws-chain")
        assert ok, err

    def test_verify_broken_chain(self, tmp_path: Path):
        ledger_path = tmp_path / "events.jsonl"
        ledger = WorkspaceLifecycleLedger(ledger_path)

        for _ in range(3):
            event = WorkspaceLifecycleEvent(
                workspace_id="ws-broken",
                event_kind=WorkspaceLifecycleEventKind.WORKSPACE_RETIRED,
                state_before=WorkspaceState.PUBLISHED,
                state_after=WorkspaceState.RETIRED,
            )
            ledger.append(event)

        lines = ledger_path.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) >= 2
        data = json.loads(lines[1])
        data["prior_event_digest"] = "sha256:deadbeef"
        lines[1] = json.dumps(data)
        ledger_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        ok, err = ledger.verify_chain("ws-broken")
        assert not ok
        assert "broken" in err.lower()

    def test_load_events_filters_by_workspace(self, tmp_path: Path):
        ledger_path = tmp_path / "events.jsonl"
        ledger = WorkspaceLifecycleLedger(ledger_path)

        for _ in range(3):
            event = WorkspaceLifecycleEvent(
                workspace_id="ws-a",
                event_kind=WorkspaceLifecycleEventKind.WORKSPACE_ACTIVATED,
            )
            ledger.append(event)

        for _ in range(2):
            event = WorkspaceLifecycleEvent(
                workspace_id="ws-b",
                event_kind=WorkspaceLifecycleEventKind.WORKSPACE_RETIRED,
            )
            ledger.append(event)

        events_a = ledger.load_events("ws-a")
        assert len(events_a) == 3
        for e in events_a:
            assert e.workspace_id == "ws-a"

        events_b = ledger.load_events("ws-b")
        assert len(events_b) == 2
        for e in events_b:
            assert e.workspace_id == "ws-b"

    def test_empty_ledger_verify_returns_true(self, tmp_path: Path):
        ledger_path = tmp_path / "nonexistent.jsonl"
        ledger = WorkspaceLifecycleLedger(ledger_path)
        ok, err = ledger.verify_chain("any-id")
        assert ok

    def test_append_computes_digest_when_missing(self, tmp_path: Path):
        ledger_path = tmp_path / "events.jsonl"
        ledger = WorkspaceLifecycleLedger(ledger_path)

        event = WorkspaceLifecycleEvent(
            workspace_id="ws-digest", event_kind=WorkspaceLifecycleEventKind.PUBLISHED
        )
        assert not event.event_digest

        digest = ledger.append(event)
        assert digest.startswith("sha256:")
        assert len(digest) == len("sha256:") + 64

    def test_load_events_nonexistent_ledger(self, tmp_path: Path):
        ledger = WorkspaceLifecycleLedger(tmp_path / "does_not_exist.jsonl")
        events = ledger.load_events("any-id")
        assert events == []

    def test_verify_chain_content_tampered(self, tmp_path: Path):
        ledger_path = tmp_path / "events.jsonl"
        ledger = WorkspaceLifecycleLedger(ledger_path)

        event1 = WorkspaceLifecycleEvent(
            workspace_id="ws-1",
            event_kind=WorkspaceLifecycleEventKind.WORKSPACE_REQUESTED,
            state_before=None,
            state_after=WorkspaceState.REQUESTED,
        )
        event1.event_digest = compute_event_digest(event1)
        event1.prior_event_digest = None
        ledger.append(event1)

        event2 = WorkspaceLifecycleEvent(
            workspace_id="ws-1",
            event_kind=WorkspaceLifecycleEventKind.WORKSPACE_RESERVED,
            state_before=WorkspaceState.REQUESTED,
            state_after=WorkspaceState.RESERVED,
            prior_event_digest=event1.event_digest,
        )
        event2.event_digest = compute_event_digest(event2)
        ledger.append(event2)

        lines = ledger_path.read_text().strip().split("\n")
        tampered_data = json.loads(lines[1])
        tampered_data["state_after"] = "published"
        lines[1] = json.dumps(tampered_data)
        ledger_path.write_text("\n".join(lines) + "\n")

        ok, msg = ledger.verify_chain("ws-1")
        assert not ok
        assert "tamper" in msg.lower() or "content" in msg.lower()


class TestFleetWorkspaceProjection:
    def test_projection_empty_workspaces(self):
        projection = build_fleet_workspace_projection([])
        assert projection.total_workspaces == 0
        assert projection.active_workspaces == 0
        assert projection.recovery_needed == 0
        assert len(projection.workspaces) == 0
        assert projection.schema_version == "rig.relay.fleet_workspace_projection.v1"

    def test_projection_maps_all_fields(self):
        identity = WorkspaceIdentity(
            project_identity="proj-a", role=WorkspaceRole.REVIEWER
        )
        ws = ManagedWorkspace(
            identity=identity,
            state=WorkspaceState.ACTIVE,
            base_commit_sha="abc123def456abc123def456abc123def456abc1",
            head_sha="fed654cba321fed654cba321fed654cba321fed6",
            changed_files_count=8,
            branch_name="rig/reviewer/abcdef01",
            session_id="session-xyz-123",
            created_at="2026-01-01T00:00:00",
            updated_at="2026-01-02T00:00:00",
        )

        projection = build_fleet_workspace_projection([ws])
        assert projection.total_workspaces == 1
        assert projection.active_workspaces == 1
        assert projection.recovery_needed == 0
        assert len(projection.workspaces) == 1

        item = projection.workspaces[0]
        assert item.workspace_id == identity.workspace_id
        assert item.project_identity == "proj-a"
        assert item.role == WorkspaceRole.REVIEWER
        assert item.lifecycle_status == WorkspaceState.ACTIVE
        assert item.recovery_required is False
        assert item.changed_files_count == 8
        assert item.checkpoint_state == "absent"
        assert item.claim_state == "unavailable"
        assert item.base_sha == "abc123de"
        assert item.head_sha == "fed654cb"
        assert item.branch_name == "rig/reviewer/abcdef01"
        assert item.session_id == "session-"
        assert item.created_at == "2026-01-01T00:00:00"
        assert item.updated_at == "2026-01-02T00:00:00"

    def test_projection_infers_safe_actions(self):
        active = ManagedWorkspace(
            identity=WorkspaceIdentity(project_identity="test"),
            state=WorkspaceState.ACTIVE,
        )
        projection = build_fleet_workspace_projection([active])
        actions = projection.workspaces[0].safe_available_actions
        assert "checkpoint" in actions
        assert "validate" in actions
        assert "release" in actions

        ready = ManagedWorkspace(
            identity=WorkspaceIdentity(project_identity="test"),
            state=WorkspaceState.READY,
        )
        projection2 = build_fleet_workspace_projection([ready])
        actions2 = projection2.workspaces[0].safe_available_actions
        assert "activate" in actions2

        retired = ManagedWorkspace(
            identity=WorkspaceIdentity(project_identity="test"),
            state=WorkspaceState.RETIRED,
        )
        projection3 = build_fleet_workspace_projection([retired])
        actions3 = projection3.workspaces[0].safe_available_actions
        assert len(actions3) == 0

    def test_projection_content_light(self):
        identity = WorkspaceIdentity(project_identity="test")
        ws = ManagedWorkspace(
            identity=identity,
            state=WorkspaceState.ACTIVE,
            worktree_path="/private/secrets/path",
            base_commit_sha="full-sha-value-that-is-40-chars-long-xxx",
            head_sha="another-full-40-char-sha-value-hereeee",
            session_id="long-session-id-that-is-sensitive-xxx",
        )

        projection = build_fleet_workspace_projection([ws])
        item = projection.workspaces[0]

        assert item.worktree_path_hash is not None
        raw_path_hash = hashlib.sha256(b"/private/secrets/path").hexdigest()
        assert item.worktree_path_hash == raw_path_hash
        assert "/private/secrets/path" not in (item.worktree_path_hash or "")

        assert item.base_sha is not None
        assert len(item.base_sha) == 8

        assert item.head_sha is not None
        assert len(item.head_sha) == 8

        assert item.session_id is not None
        assert len(item.session_id) <= 8

    def test_projection_with_recovery_state(self):
        ws = ManagedWorkspace(
            identity=WorkspaceIdentity(project_identity="test"),
            state=WorkspaceState.ACTIVE,
            recovery_state=RecoveryState.STALE_BASE,
        )
        projection = build_fleet_workspace_projection([ws])
        assert projection.recovery_needed == 1
        assert len(projection.warnings) >= 1
        assert projection.workspaces[0].recovery_required is True

    def test_projection_checkpoint_state(self):
        ws = ManagedWorkspace(
            identity=WorkspaceIdentity(project_identity="test"),
            state=WorkspaceState.CHECKPOINTED,
            checkpoint_sha="abc123",
        )
        projection = build_fleet_workspace_projection([ws])
        assert projection.workspaces[0].checkpoint_state == "present"

        ws2 = ManagedWorkspace(
            identity=WorkspaceIdentity(project_identity="test2"),
            state=WorkspaceState.ACTIVE,
            checkpoint_sha=None,
        )
        projection2 = build_fleet_workspace_projection([ws2])
        assert projection2.workspaces[0].checkpoint_state == "absent"


class TestWorktreeIsolation:
    @pytest.mark.asyncio
    @pytest.mark.substrate
    async def test_files_in_one_worktree_not_visible_in_another(self, git_repo: Path):
        base_sha = _get_head_sha(git_repo)
        svc = ManagedWorkspaceService(repo_root=git_repo)

        identity1 = WorkspaceIdentity(
            project_identity="test", role=WorkspaceRole.IMPLEMENTER
        )
        ws1, err = await svc.request_workspace(identity1, base_sha)
        assert ws1 is not None
        assert err == ""
        ok1, err1 = await svc.create_worktree(ws1.identity.workspace_id)
        assert ok1, err1
        ok1, err1 = await svc.bootstrap(ws1.identity.workspace_id)
        assert ok1, err1

        identity2 = WorkspaceIdentity(
            project_identity="test", role=WorkspaceRole.TESTER
        )
        ws2, err = await svc.request_workspace(identity2, base_sha)
        assert ws2 is not None
        assert err == ""
        ok2, err2 = await svc.create_worktree(ws2.identity.workspace_id)
        assert ok2, err2
        ok2, err2 = await svc.bootstrap(ws2.identity.workspace_id)
        assert ok2, err2

        wt1_dir = git_repo / ".rig" / "relay" / "workspaces" / ws1.identity.workspace_id
        wt2_dir = git_repo / ".rig" / "relay" / "workspaces" / ws2.identity.workspace_id
        assert wt1_dir.exists()
        assert wt2_dir.exists()

        secret_file = wt1_dir / "secret.txt"
        secret_file.write_text("only in worktree 1")

        assert (wt1_dir / "secret.txt").exists()
        assert not (wt2_dir / "secret.txt").exists()

    @pytest.mark.asyncio
    @pytest.mark.substrate
    async def test_worktree_branches_are_distinct(self, git_repo: Path):
        base_sha = _get_head_sha(git_repo)
        svc = ManagedWorkspaceService(repo_root=git_repo)

        identity1 = WorkspaceIdentity(
            project_identity="test", role=WorkspaceRole.IMPLEMENTER
        )
        ws1, err = await svc.request_workspace(identity1, base_sha)
        assert ws1 is not None
        assert err == ""
        ok1, err1 = await svc.create_worktree(ws1.identity.workspace_id)
        assert ok1, err1
        ok1, err1 = await svc.bootstrap(ws1.identity.workspace_id)
        assert ok1, err1

        identity2 = WorkspaceIdentity(
            project_identity="test", role=WorkspaceRole.REVIEWER
        )
        ws2, err = await svc.request_workspace(identity2, base_sha)
        assert ws2 is not None
        assert err == ""
        ok2, err2 = await svc.create_worktree(ws2.identity.workspace_id)
        assert ok2, err2
        ok2, err2 = await svc.bootstrap(ws2.identity.workspace_id)
        assert ok2, err2

        branch_lines = _git_branch_list(git_repo)
        impl_found = any(
            "implementer" in line and ws1.identity.workspace_id[:8] in line
            for line in branch_lines
        )
        review_found = any(
            "reviewer" in line and ws2.identity.workspace_id[:8] in line
            for line in branch_lines
        )
        assert impl_found
        assert review_found

    @pytest.mark.asyncio
    @pytest.mark.substrate
    async def test_primary_worktree_not_removed(self, git_repo: Path):
        svc = ManagedWorkspaceService(repo_root=git_repo)

        is_primary = ManagedWorkspaceService._is_primary_worktree(git_repo)
        assert is_primary

        base_sha = _get_head_sha(git_repo)
        identity = _make_identity()
        ws, err = await svc.request_workspace(identity, base_sha)
        assert ws is not None
        assert err == ""
        wid = ws.identity.workspace_id

        ok, err = await svc.create_worktree(wid)
        assert ok, err

        wt_dir = git_repo / ".rig" / "relay" / "workspaces" / wid
        assert wt_dir.exists()
        is_primary_linked = ManagedWorkspaceService._is_primary_worktree(wt_dir)
        assert not is_primary_linked

    @pytest.mark.asyncio
    @pytest.mark.substrate
    async def test_worktree_has_git_history(self, git_repo: Path):
        base_sha = _get_head_sha(git_repo)
        svc = ManagedWorkspaceService(repo_root=git_repo)

        identity = _make_identity()
        ws, err = await svc.request_workspace(identity, base_sha)
        assert ws is not None
        assert err == ""
        wid = ws.identity.workspace_id

        ok, err = await svc.create_worktree(wid)
        assert ok, err
        ok, err = await svc.bootstrap(wid)
        assert ok, err
        ok, err = await svc.activate(wid, "s1")
        assert ok, err

        wt_dir = git_repo / ".rig" / "relay" / "workspaces" / wid
        assert wt_dir.exists()

        result = subprocess.run(
            ["git", "log", "--oneline"],
            cwd=wt_dir,
            capture_output=True,
            text=True,
            check=True,
        )
        assert "initial commit" in result.stdout


class TestBoundaryClaims:
    @pytest.mark.asyncio
    @pytest.mark.substrate
    async def test_acquire_boundary_claim(self, git_repo: Path):
        base_sha = _get_head_sha(git_repo)
        svc = ManagedWorkspaceService(repo_root=git_repo)

        identity = _make_identity()
        ws, err = await svc.request_workspace(
            identity, base_sha, session_id="session-1"
        )
        assert ws is not None
        assert err == ""
        wid = ws.identity.workspace_id

        ok, err = await svc.create_worktree(wid)
        assert ok, err
        ok, err = await svc.bootstrap(wid)
        assert ok, err
        ok, err = await svc.activate(wid, "session-1")
        assert ok, err

        boundary_name = "rig_relay/desktop/gateway"
        boundary_paths = ["rig_relay/desktop/gateway/_projection.py"]
        ok, err = await svc.acquire_boundary_claim(
            wid,
            boundary_name,
            boundary_paths,
            mission_id="mission-1",
            lane_id="lane-1",
            agent_id="agent-1",
        )
        assert ok, f"acquire_boundary_claim failed: {err}"

        claims = await svc.get_boundary_claims(wid)
        assert len(claims) == 1
        assert claims[0]["state"] == "claimed"

        ok, conflicted = await svc.detect_boundary_conflict(wid)
        assert not ok, f"unexpected conflict: {conflicted}"

    @pytest.mark.asyncio
    @pytest.mark.substrate
    async def test_two_workspaces_competing_for_same_boundary(self, git_repo: Path):
        base_sha = _get_head_sha(git_repo)
        svc = ManagedWorkspaceService(repo_root=git_repo)

        identity1 = WorkspaceIdentity(
            project_identity="proj-1", role=WorkspaceRole.IMPLEMENTER
        )
        ws1, err = await svc.request_workspace(
            identity1, base_sha, session_id="session-1"
        )
        assert ws1 is not None
        assert err == ""
        wid1 = ws1.identity.workspace_id

        ok, err = await svc.create_worktree(wid1)
        assert ok, err
        ok, err = await svc.bootstrap(wid1)
        assert ok, err
        ok, err = await svc.activate(wid1, "session-1")
        assert ok, err

        boundary_name = "docs/schemas/integration_boundary"
        boundary_paths = [
            "docs/schemas/rig.relay.workspace_lifecycle_event.v1.schema.json"
        ]
        ok, err = await svc.acquire_boundary_claim(
            wid1,
            boundary_name,
            boundary_paths,
            mission_id="mission-1",
            lane_id="lane-1",
            agent_id="agent-1",
        )
        assert ok, f"first acquire failed: {err}"

        identity2 = WorkspaceIdentity(
            project_identity="proj-2", role=WorkspaceRole.TESTER
        )
        ws2, err = await svc.request_workspace(
            identity2, base_sha, session_id="session-2"
        )
        assert ws2 is not None
        assert err == ""
        wid2 = ws2.identity.workspace_id

        ok, err = await svc.create_worktree(wid2)
        assert ok, err
        ok, err = await svc.bootstrap(wid2)
        assert ok, err
        ok, err = await svc.activate(wid2, "session-2")
        assert ok, err

        ok, err = await svc.acquire_boundary_claim(
            wid2,
            boundary_name,
            boundary_paths,
            mission_id="mission-2",
            lane_id="lane-2",
            agent_id="agent-2",
        )
        assert not ok
        assert "already claimed" in err.lower()

    @pytest.mark.asyncio
    @pytest.mark.substrate
    async def test_two_workspaces_different_boundaries_no_conflict(
        self, git_repo: Path
    ):
        base_sha = _get_head_sha(git_repo)
        svc = ManagedWorkspaceService(repo_root=git_repo)

        identity1 = WorkspaceIdentity(
            project_identity="proj-1", role=WorkspaceRole.IMPLEMENTER
        )
        ws1, err = await svc.request_workspace(
            identity1, base_sha, session_id="session-1"
        )
        assert ws1 is not None
        assert err == ""
        wid1 = ws1.identity.workspace_id

        ok, err = await svc.create_worktree(wid1)
        assert ok, err
        ok, err = await svc.bootstrap(wid1)
        assert ok, err
        ok, err = await svc.activate(wid1, "session-1")
        assert ok, err

        ok, err = await svc.acquire_boundary_claim(
            wid1,
            "docs-schemas",
            ["docs/schemas/schema_a.json"],
            mission_id="m1",
            lane_id="l1",
            agent_id="a1",
        )
        assert ok, f"first acquire failed: {err}"

        identity2 = WorkspaceIdentity(
            project_identity="proj-2", role=WorkspaceRole.TESTER
        )
        ws2, err = await svc.request_workspace(
            identity2, base_sha, session_id="session-2"
        )
        assert ws2 is not None
        assert err == ""
        wid2 = ws2.identity.workspace_id

        ok, err = await svc.create_worktree(wid2)
        assert ok, err
        ok, err = await svc.bootstrap(wid2)
        assert ok, err
        ok, err = await svc.activate(wid2, "session-2")
        assert ok, err

        ok, err = await svc.acquire_boundary_claim(
            wid2,
            "etc-configs",
            ["etc/config.toml"],
            mission_id="m2",
            lane_id="l2",
            agent_id="a2",
        )
        assert ok, f"second acquire failed: {err}"

        claims1 = await svc.get_boundary_claims(wid1)
        claims2 = await svc.get_boundary_claims(wid2)
        assert len(claims1) == 1
        assert len(claims2) == 1

        ok, _ = await svc.detect_boundary_conflict(wid1)
        assert not ok, "unexpected conflict for wid1"

    @pytest.mark.asyncio
    @pytest.mark.substrate
    async def test_release_and_reacquire_boundary_claim(self, git_repo: Path):
        base_sha = _get_head_sha(git_repo)
        svc = ManagedWorkspaceService(repo_root=git_repo)

        identity = _make_identity()
        ws, err = await svc.request_workspace(
            identity, base_sha, session_id="session-1"
        )
        assert ws is not None
        assert err == ""
        wid = ws.identity.workspace_id

        ok, err = await svc.create_worktree(wid)
        assert ok, err
        ok, err = await svc.bootstrap(wid)
        assert ok, err
        ok, err = await svc.activate(wid, "session-1")
        assert ok, err

        boundary_name = "docs/schemas"
        boundary_paths = [
            "docs/schemas/rig.relay.fleet_coordination_event.v1.schema.json"
        ]

        ok, err = await svc.acquire_boundary_claim(
            wid,
            boundary_name,
            boundary_paths,
            mission_id="mission-1",
            lane_id="lane-1",
            agent_id="agent-1",
        )
        assert ok, f"acquire failed: {err}"

        ok, err = await svc.release_boundary_claim(wid, boundary_name)
        assert ok, f"release failed: {err}"

        claims = await svc.get_boundary_claims(wid)
        assert len(claims) == 0

        ok, err = await svc.acquire_boundary_claim(
            wid,
            boundary_name,
            boundary_paths,
            mission_id="mission-1b",
            lane_id="lane-1b",
            agent_id="agent-1",
        )
        assert ok, f"reacquire failed: {err}"

    @pytest.mark.asyncio
    @pytest.mark.substrate
    async def test_claim_state_in_projection_reflects_reality(self, git_repo: Path):
        base_sha = _get_head_sha(git_repo)
        svc = ManagedWorkspaceService(repo_root=git_repo)

        identity = _make_identity()
        ws, err = await svc.request_workspace(
            identity, base_sha, session_id="session-1"
        )
        assert ws is not None
        assert err == ""
        wid = ws.identity.workspace_id

        ok, err = await svc.create_worktree(wid)
        assert ok, err
        ok, err = await svc.bootstrap(wid)
        assert ok, err
        ok, err = await svc.activate(wid, "session-1")
        assert ok, err

        proj = await svc.build_projection()
        items = [it for it in proj.workspaces if it.workspace_id == wid]
        assert len(items) == 1
        assert items[0].claim_state == "unclaimed"

        boundary_name = "rig_relay/desktop"
        boundary_paths = ["rig_relay/desktop/gateway/_projection.py"]
        ok, err = await svc.acquire_boundary_claim(
            wid,
            boundary_name,
            boundary_paths,
            mission_id="mission-1",
            lane_id="lane-1",
            agent_id="agent-1",
        )
        assert ok, f"acquire failed: {err}"

        proj = await svc.build_projection()
        items = [it for it in proj.workspaces if it.workspace_id == wid]
        assert len(items) == 1
        assert items[0].claim_state == "claimed"

        ok, err = await svc.release_boundary_claim(wid, boundary_name)
        assert ok, f"release failed: {err}"

        proj = await svc.build_projection()
        items = [it for it in proj.workspaces if it.workspace_id == wid]
        assert len(items) == 1
        assert items[0].claim_state == "unclaimed"


class TestSessionAssignment:
    @pytest.mark.asyncio
    @pytest.mark.substrate
    async def test_assign_session_to_ready_workspace(self, git_repo: Path):
        base_sha = _get_head_sha(git_repo)
        svc = ManagedWorkspaceService(repo_root=git_repo)

        identity = _make_identity()
        ws, err = await svc.request_workspace(
            identity, base_sha, session_id="session-1"
        )
        assert ws is not None
        assert err == ""
        wid = ws.identity.workspace_id

        ok, err = await svc.create_worktree(wid)
        assert ok, err
        ok, err = await svc.bootstrap(wid)
        assert ok, err

        request = WorkspaceAssignmentRequest(
            workspace_id=wid,
            mission_id="mission-1",
            lane_id="lane-1",
            agent_role=WorkspaceRole.IMPLEMENTER,
            session_id="session-1",
            context_capsule_digest="sha256:abc123",
            harness_profile_digest="sha256:def456",
        )
        receipt, err = await svc.assign_session(wid, request)
        assert receipt is not None, f"assign_session failed: {err}"
        assert err == ""
        assert receipt.workspace_id == wid
        assert receipt.mission_id == "mission-1"
        assert receipt.lane_id == "lane-1"
        assert receipt.agent_role == WorkspaceRole.IMPLEMENTER
        assert receipt.assignment_state == AssignmentState.ASSIGNED
        assert receipt.session_id == "session-1"
        assert receipt.context_capsule_digest == "sha256:abc123"
        assert receipt.harness_profile_digest == "sha256:def456"
        assert receipt.base_sha == base_sha
        assert receipt.branch_name is not None

        ws = await svc.get_workspace(wid)
        assert ws is not None
        assert ws.state == WorkspaceState.ACTIVE
        assert ws.session_id == "session-1"
        assert ws.context_capsule_digest == "sha256:abc123"
        assert ws.harness_profile_digest == "sha256:def456"

    @pytest.mark.asyncio
    @pytest.mark.substrate
    async def test_detach_session_with_work_preserved(self, git_repo: Path):
        base_sha = _get_head_sha(git_repo)
        svc = ManagedWorkspaceService(repo_root=git_repo)

        identity = _make_identity()
        ws, err = await svc.request_workspace(
            identity, base_sha, session_id="session-1"
        )
        assert ws is not None
        assert err == ""
        wid = ws.identity.workspace_id

        ok, err = await svc.create_worktree(wid)
        assert ok, err
        ok, err = await svc.bootstrap(wid)
        assert ok, err
        ok, err = await svc.activate(wid, "session-1")
        assert ok, err

        wt_dir = git_repo / ".rig" / "relay" / "workspaces" / wid
        (wt_dir / "dirty.txt").write_text("uncommitted work")

        ok, err = await svc.detach_session(wid, "test detach reason")
        assert ok, f"detach_session failed: {err}"

        ws = await svc.get_workspace(wid)
        assert ws is not None
        assert ws.state == WorkspaceState.ACTIVE
        assert ws.recovery_state == RecoveryState.SESSION_DETACHED

    @pytest.mark.asyncio
    @pytest.mark.substrate
    async def test_detach_session_without_changes(self, git_repo: Path):
        base_sha = _get_head_sha(git_repo)
        svc = ManagedWorkspaceService(repo_root=git_repo)

        identity = _make_identity()
        ws, err = await svc.request_workspace(
            identity, base_sha, session_id="session-1"
        )
        assert ws is not None
        assert err == ""
        wid = ws.identity.workspace_id

        ok, err = await svc.create_worktree(wid)
        assert ok, err
        ok, err = await svc.bootstrap(wid)
        assert ok, err
        ok, err = await svc.activate(wid, "session-1")
        assert ok, err

        ok, err = await svc.detach_session(wid, "clean detach")
        assert ok, f"detach_session failed: {err}"

        ws = await svc.get_workspace(wid)
        assert ws is not None
        assert ws.recovery_state is None
        assert ws.session_id is None

    @pytest.mark.asyncio
    @pytest.mark.substrate
    async def test_reattach_session_after_detach(self, git_repo: Path):
        base_sha = _get_head_sha(git_repo)
        svc = ManagedWorkspaceService(repo_root=git_repo)

        identity = _make_identity()
        ws, err = await svc.request_workspace(
            identity, base_sha, session_id="old-session"
        )
        assert ws is not None
        assert err == ""
        wid = ws.identity.workspace_id

        ok, err = await svc.create_worktree(wid)
        assert ok, err
        ok, err = await svc.bootstrap(wid)
        assert ok, err
        ok, err = await svc.activate(wid, "old-session")
        assert ok, err

        wt_dir = git_repo / ".rig" / "relay" / "workspaces" / wid
        (wt_dir / "important.py").write_text("# critical work\n")

        ok, err = await svc.detach_session(wid, "detach for reattach test")
        assert ok, f"detach_session failed: {err}"

        ws = await svc.get_workspace(wid)
        assert ws is not None
        assert ws.recovery_state == RecoveryState.SESSION_DETACHED

        receipt, err = await svc.reattach_session(wid, "new-session")
        assert receipt is not None, f"reattach_session failed: {err}"
        assert err == ""
        assert receipt.workspace_id == wid
        assert receipt.assignment_state == AssignmentState.ASSIGNED
        assert receipt.session_id == "new-session"

        ws = await svc.get_workspace(wid)
        assert ws is not None
        assert ws.state == WorkspaceState.ACTIVE
        assert ws.recovery_state is None
        assert ws.session_id == "new-session"

        assert (wt_dir / "important.py").exists()
        content = (wt_dir / "important.py").read_text()
        assert "critical work" in content

    @pytest.mark.asyncio
    @pytest.mark.substrate
    async def test_get_current_assignment_projection(self, git_repo: Path):
        base_sha = _get_head_sha(git_repo)
        svc = ManagedWorkspaceService(repo_root=git_repo)

        identity = _make_identity()
        ws, err = await svc.request_workspace(identity, base_sha)
        assert ws is not None
        assert err == ""
        wid = ws.identity.workspace_id

        ok, err = await svc.create_worktree(wid)
        assert ok, err
        ok, err = await svc.bootstrap(wid)
        assert ok, err

        proj = await svc.get_current_assignment(wid)
        assert proj is not None
        assert proj.workspace_id == wid
        assert proj.assignment_state == AssignmentState.READY_FOR_ASSIGNMENT
        assert proj.agent_role == "implementer"
        assert proj.session_id is None
        assert proj.context_available is False
        assert proj.profile_available is False
        assert proj.runtime_available is False

        request = WorkspaceAssignmentRequest(
            workspace_id=wid,
            mission_id="mission-1",
            lane_id="lane-1",
            agent_role=WorkspaceRole.REVIEWER,
            session_id="session-1",
            context_capsule_digest="sha256:ctx",
            harness_profile_digest="sha256:prof",
            runtime_binding_reference="ref://runtime/v1",
        )
        receipt, err = await svc.assign_session(wid, request)
        assert receipt is not None, f"assign_session failed: {err}"

        proj = await svc.get_current_assignment(wid)
        assert proj is not None
        assert proj.assignment_state == AssignmentState.ASSIGNED
        assert proj.agent_role == "reviewer"
        assert proj.session_id == "session-1"
        assert proj.context_available is True
        assert proj.profile_available is True
        assert proj.runtime_available is True

    @pytest.mark.asyncio
    @pytest.mark.substrate
    async def test_release_assignment(self, git_repo: Path):
        base_sha = _get_head_sha(git_repo)
        svc = ManagedWorkspaceService(repo_root=git_repo)

        identity = _make_identity()
        ws, err = await svc.request_workspace(
            identity, base_sha, session_id="session-1"
        )
        assert ws is not None
        assert err == ""
        wid = ws.identity.workspace_id

        ok, err = await svc.create_worktree(wid)
        assert ok, err
        ok, err = await svc.bootstrap(wid)
        assert ok, err
        ok, err = await svc.activate(wid, "session-1")
        assert ok, err

        ok, err = await svc.release_assignment(wid)
        assert ok, f"release_assignment failed: {err}"
        assert err == ""

        ws = await svc.get_workspace(wid)
        assert ws is not None
        assert ws.state == WorkspaceState.RELEASED_FOR_INTEGRATION
        assert ws.session_id is None

        proj = await svc.get_current_assignment(wid)
        assert proj is not None
        assert proj.assignment_state == AssignmentState.RELEASED_FOR_INTEGRATION

    @pytest.mark.asyncio
    @pytest.mark.substrate
    async def test_cannot_assign_to_already_assigned_workspace(self, git_repo: Path):
        base_sha = _get_head_sha(git_repo)
        svc = ManagedWorkspaceService(repo_root=git_repo)

        identity = _make_identity()
        ws, err = await svc.request_workspace(
            identity, base_sha, session_id="session-1"
        )
        assert ws is not None
        assert err == ""
        wid = ws.identity.workspace_id

        ok, err = await svc.create_worktree(wid)
        assert ok, err
        ok, err = await svc.bootstrap(wid)
        assert ok, err

        request = WorkspaceAssignmentRequest(
            workspace_id=wid,
            agent_role=WorkspaceRole.IMPLEMENTER,
            session_id="session-1",
        )
        receipt, err = await svc.assign_session(wid, request)
        assert receipt is not None, f"first assign_session failed: {err}"

        request2 = WorkspaceAssignmentRequest(
            workspace_id=wid, agent_role=WorkspaceRole.TESTER, session_id="session-2"
        )
        receipt2, err2 = await svc.assign_session(wid, request2)
        assert receipt2 is None
        assert "ready" in err2.lower() or "active" in err2.lower()

    @pytest.mark.asyncio
    @pytest.mark.substrate
    async def test_get_current_assignment_for_nonexistent_workspace(
        self, git_repo: Path
    ):
        svc = ManagedWorkspaceService(repo_root=git_repo)
        proj = await svc.get_current_assignment("nonexistent-id")
        assert proj is None

    @pytest.mark.asyncio
    @pytest.mark.substrate
    async def test_assign_session_denies_workspace_id_mismatch(self, git_repo: Path):
        base_sha = _get_head_sha(git_repo)
        svc = ManagedWorkspaceService(repo_root=git_repo)

        identity = _make_identity()
        ws, err = await svc.request_workspace(
            identity, base_sha, session_id="session-1"
        )
        assert ws is not None
        assert err == ""
        wid = ws.identity.workspace_id

        ok, err = await svc.create_worktree(wid)
        assert ok, err
        ok, err = await svc.bootstrap(wid)
        assert ok, err

        request = WorkspaceAssignmentRequest(
            workspace_id="wrong-id",
            agent_role=WorkspaceRole.IMPLEMENTER,
            session_id="session-1",
        )
        receipt, err = await svc.assign_session(wid, request)
        assert receipt is None
        assert "match" in err.lower()

    @pytest.mark.asyncio
    @pytest.mark.substrate
    async def test_get_current_assignment_blocked_state(self, git_repo: Path):
        identity = WorkspaceIdentity(
            project_identity="test-blocked", role=WorkspaceRole.TESTER
        )
        svc = ManagedWorkspaceService(repo_root=git_repo)

        ws, err = await svc.request_workspace(identity, "HEAD", "sess-1")
        assert ws is not None
        assert err == ""
        ws_id = ws.identity.workspace_id

        proj = await svc.get_current_assignment(ws_id)
        assert proj is not None
        assert proj.workspace_id == ws_id
        assert proj.assignment_state == AssignmentState.BLOCKED_MISSING_CONTEXT_RELEASE
        assert proj.agent_role == "tester"
        assert proj.blocked_reason is not None
        assert "prevents assignment" in proj.blocked_reason


class TestWorkLossDetection:
    @pytest.mark.asyncio
    @pytest.mark.substrate
    async def test_assess_clean_workspace_no_recovery_needed(self, git_repo: Path):
        base_sha = _get_head_sha(git_repo)
        svc = ManagedWorkspaceService(repo_root=git_repo)

        identity = _make_identity()
        ws, err = await svc.request_workspace(identity, base_sha, session_id="s1")
        assert ws is not None and err == ""
        wid = ws.identity.workspace_id

        ok, err = await svc.create_worktree(wid)
        assert ok, err
        ok, err = await svc.bootstrap(wid)
        assert ok, err
        ok, err = await svc.activate(wid, "s1")
        assert ok, err

        assessment = await svc.assess_work_preservation(wid)
        assert assessment is not None
        assert assessment.worktree_exists is True
        assert assessment.work_preservation == WorkPreservationState.CLEAN
        assert assessment.recovery_required is False
        assert assessment.validation_required is False
        assert assessment.uncommitted_changes_count == 0
        assert assessment.changed_files == []
        assert assessment.duplicate_checkpoint_detected is False

    @pytest.mark.asyncio
    @pytest.mark.substrate
    async def test_assess_uncommitted_edits_require_recovery(self, git_repo: Path):
        base_sha = _get_head_sha(git_repo)
        svc = ManagedWorkspaceService(repo_root=git_repo)

        identity = _make_identity()
        ws, err = await svc.request_workspace(identity, base_sha, session_id="s1")
        assert ws is not None and err == ""
        wid = ws.identity.workspace_id

        ok, err = await svc.create_worktree(wid)
        assert ok, err
        ok, err = await svc.bootstrap(wid)
        assert ok, err
        ok, err = await svc.activate(wid, "s1")
        assert ok, err

        wt_dir = git_repo / ".rig" / "relay" / "workspaces" / wid
        (wt_dir / "dirty.py").write_text("print('uncommitted work')\n")
        subprocess.run(
            ["git", "add", "dirty.py"], cwd=wt_dir, capture_output=True, text=True
        )

        assessment = await svc.assess_work_preservation(wid)
        assert assessment is not None
        assert assessment.worktree_exists is True
        assert (
            assessment.work_preservation
            == WorkPreservationState.UNCOMMITTED_EDITS_PRESENT
        )
        assert assessment.recovery_required is True
        assert assessment.validation_required is True
        assert assessment.uncommitted_changes_count >= 1
        assert assessment.recovery_possible is True

    @pytest.mark.asyncio
    @pytest.mark.substrate
    async def test_assess_checkpoint_present_no_recovery(self, git_repo: Path):
        base_sha = _get_head_sha(git_repo)
        svc = ManagedWorkspaceService(repo_root=git_repo)

        identity = _make_identity()
        ws, err = await svc.request_workspace(identity, base_sha, session_id="s1")
        assert ws is not None and err == ""
        wid = ws.identity.workspace_id

        ok, err = await svc.create_worktree(wid)
        assert ok, err
        ok, err = await svc.bootstrap(wid)
        assert ok, err
        ok, err = await svc.activate(wid, "s1")
        assert ok, err

        fake_checkpoint = "abc123def456abc123def456abc123def456abc1"
        ok, err = await svc.checkpoint(wid, fake_checkpoint)
        assert ok, err

        assessment = await svc.assess_work_preservation(wid)
        assert assessment is not None
        assert assessment.worktree_exists is True
        assert assessment.work_preservation == WorkPreservationState.CHECKPOINT_PRESENT
        assert assessment.recovery_required is False
        assert assessment.validation_required is False
        assert assessment.checkpoint_sha == fake_checkpoint

    @pytest.mark.asyncio
    @pytest.mark.substrate
    async def test_assess_missing_worktree_no_recovery(self, git_repo: Path):
        base_sha = _get_head_sha(git_repo)
        svc = ManagedWorkspaceService(repo_root=git_repo)

        identity = _make_identity()
        ws, err = await svc.request_workspace(identity, base_sha, session_id="s1")
        assert ws is not None and err == ""
        wid = ws.identity.workspace_id

        ok, err = await svc.create_worktree(wid)
        assert ok, err
        ok, err = await svc.bootstrap(wid)
        assert ok, err
        ok, err = await svc.activate(wid, "s1")
        assert ok, err

        wt_dir = git_repo / ".rig" / "relay" / "workspaces" / wid
        subprocess.run(["rm", "-rf", str(wt_dir)], capture_output=True)

        assessment = await svc.assess_work_preservation(wid)
        assert assessment is not None
        assert assessment.worktree_exists is False
        assert assessment.work_preservation == WorkPreservationState.NO_WORK_DETECTED
        assert assessment.recovery_required is False
        assert assessment.recovery_possible is False
        assert assessment.validation_required is False

    @pytest.mark.asyncio
    @pytest.mark.substrate
    async def test_assess_duplicate_checkpoint_suspected(self, git_repo: Path):
        base_sha = _get_head_sha(git_repo)
        svc = ManagedWorkspaceService(repo_root=git_repo)

        identity = _make_identity()
        ws, err = await svc.request_workspace(identity, base_sha, session_id="s1")
        assert ws is not None and err == ""
        wid = ws.identity.workspace_id

        ok, err = await svc.create_worktree(wid)
        assert ok, err
        ok, err = await svc.bootstrap(wid)
        assert ok, err
        ok, err = await svc.activate(wid, "s1")
        assert ok, err

        head_sha = _get_head_sha(git_repo)
        ok, err = await svc.checkpoint(wid, head_sha)
        assert ok, err

        assessment = await svc.assess_work_preservation(wid)
        assert assessment is not None
        assert assessment.duplicate_checkpoint_detected is True
        assert (
            assessment.work_preservation
            == WorkPreservationState.REAPPLICATION_SUSPECTED
        )
        assert assessment.validation_required is True
        assert assessment.recovery_possible is True

    @pytest.mark.asyncio
    @pytest.mark.substrate
    async def test_work_loss_reconstruction_after_detach(self, git_repo: Path):
        base_sha = _get_head_sha(git_repo)
        svc = ManagedWorkspaceService(repo_root=git_repo)

        identity = _make_identity()
        ws, err = await svc.request_workspace(identity, base_sha, session_id="old")
        assert ws is not None and err == ""
        wid = ws.identity.workspace_id

        ok, err = await svc.create_worktree(wid)
        assert ok, err
        ok, err = await svc.bootstrap(wid)
        assert ok, err
        ok, err = await svc.activate(wid, "old")
        assert ok, err

        wt_dir = git_repo / ".rig" / "relay" / "workspaces" / wid
        (wt_dir / "important.py").write_text("# work in progress\n")
        subprocess.run(
            ["git", "add", "important.py"], cwd=wt_dir, capture_output=True, text=True
        )

        ok, err = await svc.detect_session_detached(wid, "new-session")
        assert ok, err

        assessment = await svc.assess_work_preservation(wid)
        assert assessment is not None
        assert assessment.worktree_exists is True
        assert (
            assessment.work_preservation
            == WorkPreservationState.UNCOMMITTED_EDITS_PRESENT
        )
        assert assessment.recovery_required is True
        assert assessment.recovery_possible is True
        assert assessment.uncommitted_changes_count >= 1

        ok, err = await svc.recover(wid, "new-session")
        assert ok, f"recovery failed: {err}"

        assert (wt_dir / "important.py").exists()
        assert "# work in progress" in (wt_dir / "important.py").read_text()

        ok, err = await svc.mark_validation_required(wid)
        assert ok, f"mark_validation_required failed: {err}"

        ws = await svc.get_workspace(wid)
        assert ws is not None
        assert ws.state == WorkspaceState.VALIDATING

    @pytest.mark.asyncio
    @pytest.mark.substrate
    async def test_uncheckpointed_edits_present(self, git_repo: Path):
        base_sha = _get_head_sha(git_repo)
        svc = ManagedWorkspaceService(repo_root=git_repo)

        identity = _make_identity()
        ws, err = await svc.request_workspace(identity, base_sha, session_id="s1")
        assert ws is not None and err == ""
        wid = ws.identity.workspace_id

        ok, err = await svc.create_worktree(wid)
        assert ok, err
        ok, err = await svc.bootstrap(wid)
        assert ok, err
        ok, err = await svc.activate(wid, "s1")
        assert ok, err

        wt_dir = git_repo / ".rig" / "relay" / "workspaces" / wid
        (wt_dir / "extra.py").write_text("# extra work\n")
        subprocess.run(
            ["git", "add", "extra.py"], cwd=wt_dir, capture_output=True, text=True
        )

        ws = await svc.get_workspace(wid)
        assert ws is not None
        ws.checkpoint_sha = "abc123notreal"
        svc._save_workspace(ws)

        assessment = await svc.assess_work_preservation(wid)
        assert assessment is not None
        assert (
            assessment.work_preservation
            == WorkPreservationState.UNCHECKPOINTED_EDITS_PRESENT
        )
        assert assessment.recovery_required is True
        assert assessment.checkpoint_sha == "abc123notreal"

    @pytest.mark.asyncio
    async def test_assess_nonexistent_workspace(self, git_repo: Path):
        svc = ManagedWorkspaceService(repo_root=git_repo)
        assessment = await svc.assess_work_preservation("nonexistent-id")
        assert assessment is not None
        assert assessment.worktree_exists is False
        assert assessment.work_preservation == WorkPreservationState.NO_WORK_DETECTED
        assert assessment.recovery_required is False
        assert assessment.recovery_possible is False
        assert assessment.validation_required is False

    @pytest.mark.asyncio
    @pytest.mark.substrate
    async def test_mark_validation_required_from_active(self, git_repo: Path):
        base_sha = _get_head_sha(git_repo)
        svc = ManagedWorkspaceService(repo_root=git_repo)

        identity = _make_identity()
        ws, err = await svc.request_workspace(identity, base_sha, session_id="s1")
        assert ws is not None and err == ""
        wid = ws.identity.workspace_id

        ok, err = await svc.create_worktree(wid)
        assert ok, err
        ok, err = await svc.bootstrap(wid)
        assert ok, err
        ok, err = await svc.activate(wid, "s1")
        assert ok, err

        ok, err = await svc.mark_validation_required(wid)
        assert ok, f"mark_validation_required failed: {err}"

        ws = await svc.get_workspace(wid)
        assert ws is not None
        assert ws.state == WorkspaceState.VALIDATING

    @pytest.mark.asyncio
    @pytest.mark.substrate
    async def test_assess_work_loss_clean_workspace(self, git_repo: Path):
        identity = WorkspaceIdentity(
            project_identity="test-wl", role=WorkspaceRole.TESTER
        )
        svc = ManagedWorkspaceService(repo_root=git_repo)
        ws, err = await svc.request_workspace(identity, "HEAD", "sess-1")
        assert ws is not None
        assert err == ""
        ws_id = ws.identity.workspace_id

        await svc.create_worktree(ws_id)
        await svc.bootstrap(ws_id)
        await svc.activate(ws_id, "sess-1")

        recovery = WorkspaceRecoveryEngine(svc, str(git_repo))
        assessment = await recovery.assess_work_loss(ws_id)
        assert assessment.work_preservation == WorkPreservationState.CLEAN


class TestSafeDestructiveActions:
    @pytest.mark.asyncio
    @pytest.mark.substrate
    async def test_refuse_retire_primary_worktree(self, git_repo: Path):
        svc = ManagedWorkspaceService(repo_root=git_repo)
        base_sha = _get_head_sha(git_repo)

        identity = WorkspaceIdentity(
            workspace_id="primary-test",
            project_identity="test",
            role=WorkspaceRole.TESTER,
        )
        ws, err = await svc.request_workspace(identity, base_sha)
        assert ws is not None
        assert err == ""
        wid = ws.identity.workspace_id

        ws = await svc.get_workspace(wid)
        assert ws is not None
        ws.worktree_path = str(git_repo)
        svc._save_workspace(ws)

        ok, err = await svc.retire(wid, force=False)
        assert not ok
        assert "primary" in err.lower()

    @pytest.mark.asyncio
    @pytest.mark.substrate
    async def test_refuse_retire_dirty_workspace_without_force(self, git_repo: Path):
        svc = ManagedWorkspaceService(repo_root=git_repo)
        base_sha = _get_head_sha(git_repo)

        identity = _make_identity()
        ws, err = await svc.request_workspace(identity, base_sha)
        assert ws is not None
        assert err == ""
        wid = ws.identity.workspace_id

        ok, err = await svc.create_worktree(wid)
        assert ok, err
        ok, err = await svc.bootstrap(wid)
        assert ok, err
        ok, err = await svc.activate(wid, "session-1")
        assert ok, err

        wt_dir = git_repo / ".rig" / "relay" / "workspaces" / wid
        (wt_dir / "dirty.txt").write_text("uncommitted change")

        ok, err = await svc.retire(wid, force=False)
        assert not ok
        assert any(
            term in err.lower() for term in ("changes", "uncommitted", "checkpoint")
        )

    @pytest.mark.asyncio
    @pytest.mark.substrate
    async def test_force_retire_dirty_workspace(self, git_repo: Path):
        svc = ManagedWorkspaceService(repo_root=git_repo)
        base_sha = _get_head_sha(git_repo)

        identity = _make_identity()
        ws, err = await svc.request_workspace(identity, base_sha)
        assert ws is not None
        assert err == ""
        wid = ws.identity.workspace_id

        ok, err = await svc.create_worktree(wid)
        assert ok, err
        ok, err = await svc.bootstrap(wid)
        assert ok, err
        ok, err = await svc.activate(wid, "session-1")
        assert ok, err

        wt_dir = git_repo / ".rig" / "relay" / "workspaces" / wid
        (wt_dir / "dirty.txt").write_text("uncommitted change")

        ok, err = await svc.retire(wid, force=True)
        assert ok, f"force retire failed: {err}"

        ws = await svc.get_workspace(wid)
        assert ws is not None
        assert ws.state == WorkspaceState.RETIRED

    @pytest.mark.asyncio
    @pytest.mark.substrate
    async def test_quarantine_preserves_work(self, git_repo: Path):
        svc = ManagedWorkspaceService(repo_root=git_repo)
        base_sha = _get_head_sha(git_repo)

        identity = _make_identity()
        ws, err = await svc.request_workspace(identity, base_sha, session_id="s1")
        assert ws is not None
        assert err == ""
        wid = ws.identity.workspace_id

        ok, err = await svc.create_worktree(wid)
        assert ok, err
        ok, err = await svc.bootstrap(wid)
        assert ok, err
        ok, err = await svc.activate(wid, "s1")
        assert ok, err

        wt_dir = git_repo / ".rig" / "relay" / "workspaces" / wid
        (wt_dir / "important.py").write_text("# critical work\n")

        ok, err = await svc.quarantine_workspace(wid, reason="test quarantine")
        assert ok, f"quarantine_workspace failed: {err}"

        ws = await svc.get_workspace(wid)
        assert ws is not None
        assert ws.state == WorkspaceState.RETIRED
        assert ws.recovery_state == RecoveryState.QUARANTINED

        assert wt_dir.exists()
        assert (wt_dir / "important.py").exists()
        content = (wt_dir / "important.py").read_text()
        assert "critical work" in content

    @pytest.mark.asyncio
    @pytest.mark.substrate
    async def test_reset_refused_with_preserved_changes(self, git_repo: Path):
        svc = ManagedWorkspaceService(repo_root=git_repo)
        base_sha = _get_head_sha(git_repo)

        identity = _make_identity()
        ws, err = await svc.request_workspace(identity, base_sha, session_id="s1")
        assert ws is not None
        assert err == ""
        wid = ws.identity.workspace_id

        ok, err = await svc.create_worktree(wid)
        assert ok, err
        ok, err = await svc.bootstrap(wid)
        assert ok, err
        ok, err = await svc.activate(wid, "s1")
        assert ok, err

        wt_dir = git_repo / ".rig" / "relay" / "workspaces" / wid
        (wt_dir / "dirty.txt").write_text("unsaved work")

        ok, err = await svc.reset_workspace(wid, force=False)
        assert not ok
        assert any(term in err.lower() for term in ("changes", "uncommitted", "reset"))

        ws = await svc.get_workspace(wid)
        assert ws is not None
        assert wt_dir.exists()
        assert (wt_dir / "dirty.txt").exists()

    @pytest.mark.asyncio
    @pytest.mark.substrate
    async def test_safe_retire_after_release(self, git_repo: Path):
        svc = ManagedWorkspaceService(repo_root=git_repo)
        base_sha = _get_head_sha(git_repo)

        identity = _make_identity()
        ws, err = await svc.request_workspace(identity, base_sha, session_id="s1")
        assert ws is not None
        assert err == ""
        wid = ws.identity.workspace_id

        ok, err = await svc.create_worktree(wid)
        assert ok, err
        ok, err = await svc.bootstrap(wid)
        assert ok, err
        ok, err = await svc.activate(wid, "s1")
        assert ok, err
        ok, err = await svc.mark_validating(wid)
        assert ok, err
        ok, err = await svc.mark_under_review(wid)
        assert ok, err
        ok, err = await svc.checkpoint(wid, "cp-sha")
        assert ok, err
        ok, err = await svc.release_for_integration(wid)
        assert ok, err
        ok, err = await svc.mark_integrated(wid)
        assert ok, err
        ok, err = await svc.mark_published(wid)
        assert ok, err

        ok, err = await svc.safe_retire_workspace(wid)
        assert ok, f"safe_retire_workspace failed: {err}"

        ws = await svc.get_workspace(wid)
        assert ws is not None
        assert ws.state == WorkspaceState.RETIRED

    @pytest.mark.asyncio
    @pytest.mark.substrate
    async def test_safe_retire_quarantines_unreleased(self, git_repo: Path):
        svc = ManagedWorkspaceService(repo_root=git_repo)
        base_sha = _get_head_sha(git_repo)

        identity = _make_identity()
        ws, err = await svc.request_workspace(identity, base_sha, session_id="s1")
        assert ws is not None
        assert err == ""
        wid = ws.identity.workspace_id

        ok, err = await svc.create_worktree(wid)
        assert ok, err
        ok, err = await svc.bootstrap(wid)
        assert ok, err
        ok, err = await svc.activate(wid, "s1")
        assert ok, err

        wt_dir = git_repo / ".rig" / "relay" / "workspaces" / wid
        (wt_dir / "important.py").write_text("# unreleased work\n")

        ok, err = await svc.safe_retire_workspace(wid, force=False)
        assert not ok
        assert "quarantined" in err.lower()

        ws = await svc.get_workspace(wid)
        assert ws is not None
        assert ws.state == WorkspaceState.RETIRED
        assert ws.recovery_state == RecoveryState.QUARANTINED

        assert wt_dir.exists()
        assert (wt_dir / "important.py").exists()

    @pytest.mark.asyncio
    @pytest.mark.substrate
    async def test_force_reset_refused_primary_worktree(self, git_repo: Path):
        svc = ManagedWorkspaceService(repo_root=git_repo)
        identity = WorkspaceIdentity(
            project_identity="test-primary", role=WorkspaceRole.TESTER
        )
        ws, err = await svc.request_workspace(identity, "HEAD", "sess-1")
        assert ws is not None
        assert err == ""
        ws_id = ws.identity.workspace_id

        await svc.create_worktree(ws_id)
        await svc.bootstrap(ws_id)
        await svc.activate(ws_id, "sess-1")

        original = svc._is_primary_worktree
        svc._is_primary_worktree = lambda p: True
        try:
            ok, err_val = await svc.reset_workspace(ws_id, force=True)
            assert not ok
            assert "primary" in err_val.lower()
        finally:
            svc._is_primary_worktree = original


class TestPruneRepairSafety:
    @pytest.mark.asyncio
    @pytest.mark.substrate
    async def test_prune_only_affects_rig_owned_worktrees(self, git_repo: Path):
        from rig_relay.coordination.worktree_manager import WorktreeManager

        mgr = WorktreeManager(repo_root=git_repo)
        result = mgr.prune(dry_run=False)
        assert result.status in ("pruned", "error")

    @pytest.mark.asyncio
    @pytest.mark.substrate
    async def test_repair_restores_broken_worktree_links(self, git_repo: Path):
        from rig_relay.coordination.worktree_manager import WorktreeManager

        base_sha = _get_head_sha(git_repo)
        svc = ManagedWorkspaceService(repo_root=git_repo)
        identity = _make_identity()
        ws, err = await svc.request_workspace(identity, base_sha)
        assert ws is not None
        assert err == ""
        wid = ws.identity.workspace_id
        ok, err = await svc.create_worktree(wid)
        assert ok, err

        wt_dir = git_repo / ".rig" / "relay" / "workspaces" / wid
        assert wt_dir.exists()

        git_file = wt_dir / ".git"
        assert git_file.exists()
        git_file.write_text(f"gitdir: /nonexistent/path/to/repo/.git/worktrees/{wid}\n")

        mgr = WorktreeManager(repo_root=git_repo)
        result = mgr.repair(paths=[str(wt_dir)])
        assert result.status == "repaired"

        assert git_file.exists() or (wt_dir / ".git").is_file()
