from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
import subprocess

from rig_relay.workspace._config import WorkspaceConfig
from rig_relay.workspace._service import ManagedWorkspaceService
from rig_relay.workspace.models import (
    ManagedWorkspace,
    RecoveryState,
    WorkLossAssessment,
    WorkPreservationState,
    WorkspaceState,
)

_TERMINAL_STATES: frozenset[WorkspaceState] = frozenset({
    WorkspaceState.RETIRED,
    WorkspaceState.INTEGRATED,
    WorkspaceState.PUBLISHED,
})


class WorkspaceRecoveryEngine:
    def __init__(
        self, workspace_service: ManagedWorkspaceService, repo_root: str | Path
    ) -> None:
        self._service = workspace_service
        self._repo_root = Path(repo_root)
        self._config = WorkspaceConfig()

    async def scan_for_recovery_candidates(self) -> list[ManagedWorkspace]:
        workspaces: list[ManagedWorkspace] = await self._service.list_workspaces()
        recovery_states = {
            RecoveryState.RECOVERY_REQUIRED,
            RecoveryState.SESSION_DETACHED,
            RecoveryState.STALE_BASE,
            RecoveryState.RECOVERED,
        }
        active_states = {
            WorkspaceState.ACTIVE,
            WorkspaceState.VALIDATING,
            WorkspaceState.UNDER_REVIEW,
        }
        now = datetime.now(UTC)
        orphan_timeout = timedelta(seconds=self._config.stale_session_timeout_seconds)
        candidates: list[ManagedWorkspace] = []
        for ws in workspaces:
            if ws.state in active_states or ws.recovery_state in recovery_states:
                if ws.state in _TERMINAL_STATES:
                    continue
                recovery, _ = await self.assess_workspace(ws)
                if recovery is not None:
                    candidates.append(ws)
            elif ws.state == WorkspaceState.REQUESTED:
                created = datetime.fromisoformat(ws.created_at)
                if now - created > orphan_timeout:
                    candidates.append(ws)
        return candidates

    async def assess_workspace(
        self, workspace: ManagedWorkspace
    ) -> tuple[RecoveryState | None, str]:
        state = workspace.state
        if state in _TERMINAL_STATES:
            return (None, "terminal")
        if workspace.recovery_state in {
            RecoveryState.RESERVATION_REFUSED,
            RecoveryState.RESET_REFUSED,
            RecoveryState.REMOVAL_REFUSED,
            RecoveryState.QUARANTINED,
        }:
            return (None, "terminal_recovery")

        if workspace.worktree_path is None:
            probable_path = (
                self._repo_root
                / self._config.workspaces_root
                / workspace.identity.workspace_id
            )
            if probable_path.exists():
                return (
                    RecoveryState.RECOVERY_REQUIRED,
                    "worktree_path field missing but worktree directory exists",
                )
            return (None, "worktree_missing")

        if not self._worktree_exists(workspace.worktree_path):
            return (None, "worktree_missing")

        has_changes = self._has_uncommitted_changes(workspace.worktree_path)

        if workspace.base_commit_sha and self._is_stale_base(
            self._repo_root, workspace.base_commit_sha
        ):
            return (RecoveryState.STALE_BASE, "base_sha is not ancestor of HEAD")

        if workspace.session_id and workspace.state == WorkspaceState.ACTIVE:
            if has_changes:
                return (
                    RecoveryState.RECOVERY_REQUIRED,
                    "uncommitted changes present, session may be detached",
                )
            return (
                RecoveryState.SESSION_DETACHED,
                "worktree intact but session detached",
            )

        return (None, "workspace appears healthy")

    async def assess_work_loss(self, workspace_id: str) -> WorkLossAssessment:
        ws = await self._service.get_workspace(workspace_id)
        changed_files: list[str] = []
        uncommitted_count = 0
        current_head: str | None = None
        checkpoint_sha: str | None = None
        duplicate_checkpoint = False

        worktree_exists = (
            ws is not None
            and ws.worktree_path is not None
            and self._worktree_exists(ws.worktree_path)
        )

        if ws is not None and worktree_exists:
            checkpoint_sha = ws.checkpoint_sha
            if ws.base_commit_sha and ws.worktree_path:
                changed_files = self._get_changed_files(
                    ws.worktree_path, ws.base_commit_sha
                )
            if ws.worktree_path:
                uncommitted_count = self._count_uncommitted_changes(ws.worktree_path)
                current_head = self._get_current_head(ws.worktree_path)

        has_changes = changed_files or uncommitted_count > 0
        has_checkpoint = checkpoint_sha is not None

        if has_checkpoint and current_head and checkpoint_sha:
            if current_head == checkpoint_sha:
                duplicate_checkpoint = True

        if not worktree_exists:
            work_preservation = WorkPreservationState.NO_WORK_DETECTED
        elif duplicate_checkpoint:
            work_preservation = WorkPreservationState.REAPPLICATION_SUSPECTED
        elif has_checkpoint and has_changes:
            work_preservation = WorkPreservationState.UNCHECKPOINTED_EDITS_PRESENT
        elif has_changes and not has_checkpoint:
            work_preservation = WorkPreservationState.UNCOMMITTED_EDITS_PRESENT
        elif has_checkpoint and not has_changes:
            work_preservation = WorkPreservationState.CHECKPOINT_PRESENT
        elif not has_changes and not has_checkpoint:
            work_preservation = WorkPreservationState.CLEAN
        else:
            work_preservation = WorkPreservationState.NO_WORK_DETECTED

        recovery_required = work_preservation in {
            WorkPreservationState.UNCOMMITTED_EDITS_PRESENT,
            WorkPreservationState.UNCHECKPOINTED_EDITS_PRESENT,
        }
        validation_required = recovery_required or work_preservation in {
            WorkPreservationState.REAPPLICATION_SUSPECTED
        }

        return WorkLossAssessment(
            workspace_id=workspace_id,
            worktree_exists=worktree_exists,
            work_preservation=work_preservation,
            uncommitted_changes_count=uncommitted_count,
            changed_files=changed_files,
            current_head_sha=current_head,
            checkpoint_sha=checkpoint_sha,
            duplicate_checkpoint_detected=duplicate_checkpoint,
            duplicate_diff_detected=False,
            recovery_required=recovery_required,
            recovery_possible=worktree_exists,
            validation_required=validation_required,
        )

    async def list_orphaned_worktrees(self) -> list[str]:
        try:
            result = subprocess.run(
                ["git", "worktree", "list", "--porcelain"],
                capture_output=True,
                text=True,
                cwd=str(self._repo_root),
                timeout=10,
            )
        except (OSError, subprocess.TimeoutExpired):
            return []
        if result.returncode != 0:
            return []
        paths: dict[str, bool] = {}
        for line in result.stdout.split("\n"):
            if line.startswith("worktree "):
                paths[line[len("worktree ") :].strip()] = False
        all_workspaces = await self._service.list_workspaces()
        known = {ws.worktree_path for ws in all_workspaces if ws.worktree_path}
        return [p for p in paths if p not in known]

    async def attempt_recovery(
        self, workspace_id: str, session_id: str
    ) -> tuple[bool, str]:
        ws = await self._service.get_workspace(workspace_id)
        if ws is None:
            return (False, "workspace not found")
        _recovery_state, _msg = await self.assess_workspace(ws)
        return await self._service.recover(workspace_id, session_id)

    def _worktree_exists(self, path: str) -> bool:
        return Path(path).exists()

    def _get_current_head(self, worktree_path: str) -> str | None:
        try:
            result = subprocess.run(
                ["git", "-C", worktree_path, "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except (OSError, subprocess.TimeoutExpired):
            pass
        return None

    def _get_changed_files(self, worktree_path: str, base_sha: str) -> list[str]:
        try:
            result = subprocess.run(
                [
                    "git",
                    "-C",
                    worktree_path,
                    "diff",
                    "--name-only",
                    f"{base_sha}...HEAD",
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                return [line for line in result.stdout.strip().split("\n") if line]
        except (OSError, subprocess.TimeoutExpired):
            pass
        return []

    def _has_uncommitted_changes(self, worktree_path: str) -> bool:
        try:
            result = subprocess.run(
                ["git", "-C", worktree_path, "status", "--porcelain"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            return bool(result.stdout.strip())
        except (OSError, subprocess.TimeoutExpired):
            return False

    def _count_uncommitted_changes(self, worktree_path: str) -> int:
        try:
            result = subprocess.run(
                ["git", "-C", worktree_path, "status", "--porcelain"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                return len([line for line in result.stdout.strip().split("\n") if line])
        except (OSError, subprocess.TimeoutExpired):
            pass
        return 0

    def _is_stale_base(self, repo_root: Path, base_sha: str) -> bool:
        try:
            result = subprocess.run(
                ["git", "merge-base", "--is-ancestor", base_sha, "HEAD"],
                capture_output=True,
                cwd=str(repo_root),
                timeout=10,
            )
            return result.returncode != 0
        except (OSError, subprocess.TimeoutExpired):
            return False


__all__ = ["WorkspaceRecoveryEngine"]
