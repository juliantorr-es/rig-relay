from __future__ import annotations

from datetime import UTC, datetime
import fcntl
import os
from pathlib import Path
import subprocess
from typing import Any, Protocol

from rig_relay.coordination.fleet_claims import ActiveClaim, FleetClaimStore
from rig_relay.core.logger import logger
from rig_relay.workspace._config import WorkspaceConfig
from rig_relay.workspace._evidence import WorkspaceLifecycleLedger
from rig_relay.workspace._projection import build_fleet_workspace_projection
from rig_relay.workspace.models import (
    AssignmentState,
    CurrentAssignmentProjection,
    FleetWorkspaceProjection,
    ManagedWorkspace,
    RecoveryState,
    WorkLossAssessment,
    WorkspaceAssignmentReceipt,
    WorkspaceAssignmentRequest,
    WorkspaceIdentity,
    WorkspaceLifecycleEvent,
    WorkspaceLifecycleEventKind,
    WorkspaceState,
)

_GIT_TIMEOUT = 30.0
_SHA_HEX_LENGTH = 40
_MAX_WORKSPACE_ID_LENGTH = 64

_TERMINAL_RECOVERY: frozenset[RecoveryState] = frozenset({
    RecoveryState.RESERVATION_REFUSED,
    RecoveryState.REMOVAL_REFUSED,
    RecoveryState.RESET_REFUSED,
    RecoveryState.QUARANTINED,
})

_RECOVERY_REQUIRED_RECOVERY: frozenset[RecoveryState] = frozenset({
    RecoveryState.RECOVERY_REQUIRED,
    RecoveryState.SESSION_DETACHED,
    RecoveryState.STALE_BASE,
    RecoveryState.BOOTSTRAP_FAILED,
})

_VALID_TRANSITIONS: dict[
    tuple[WorkspaceState, RecoveryState | None],
    set[tuple[WorkspaceState, RecoveryState | None]],
] = {}


def _add(
    from_state: WorkspaceState,
    from_rec: RecoveryState | None,
    to_state: WorkspaceState,
    to_rec: RecoveryState | None = None,
) -> None:
    key = (from_state, from_rec)
    val = (to_state, to_rec)
    _VALID_TRANSITIONS.setdefault(key, set()).add(val)


_add(WorkspaceState.REQUESTED, None, WorkspaceState.RESERVED)
_add(
    WorkspaceState.REQUESTED,
    None,
    WorkspaceState.RETIRED,
    RecoveryState.RESERVATION_REFUSED,
)

_add(WorkspaceState.RESERVED, None, WorkspaceState.WORKTREE_CREATED)
_add(
    WorkspaceState.RESERVED,
    None,
    WorkspaceState.RETIRED,
    RecoveryState.BOOTSTRAP_FAILED,
)
_add(
    WorkspaceState.RESERVED,
    None,
    WorkspaceState.RETIRED,
    RecoveryState.RESERVATION_REFUSED,
)

_add(WorkspaceState.WORKTREE_CREATED, None, WorkspaceState.BOOTSTRAPPING)

_add(WorkspaceState.BOOTSTRAPPING, None, WorkspaceState.READY)
_add(
    WorkspaceState.BOOTSTRAPPING,
    None,
    WorkspaceState.RETIRED,
    RecoveryState.BOOTSTRAP_FAILED,
)

_add(WorkspaceState.READY, None, WorkspaceState.ACTIVE)

_add(WorkspaceState.ACTIVE, None, WorkspaceState.VALIDATING)
_add(WorkspaceState.ACTIVE, None, WorkspaceState.CHECKPOINTED)
_add(WorkspaceState.ACTIVE, None, WorkspaceState.ACTIVE, RecoveryState.SESSION_DETACHED)
_add(WorkspaceState.ACTIVE, None, WorkspaceState.ACTIVE, RecoveryState.STALE_BASE)
_add(
    WorkspaceState.ACTIVE, None, WorkspaceState.ACTIVE, RecoveryState.RECOVERY_REQUIRED
)
_add(WorkspaceState.ACTIVE, None, WorkspaceState.RETIRED, None)
_add(WorkspaceState.ACTIVE, None, WorkspaceState.RETIRED, RecoveryState.QUARANTINED)
_add(WorkspaceState.ACTIVE, None, WorkspaceState.RELEASED_FOR_INTEGRATION, None)

_add(WorkspaceState.VALIDATING, None, WorkspaceState.UNDER_REVIEW)
_add(WorkspaceState.VALIDATING, None, WorkspaceState.ACTIVE)

_add(WorkspaceState.UNDER_REVIEW, None, WorkspaceState.CHECKPOINTED)
_add(WorkspaceState.UNDER_REVIEW, None, WorkspaceState.ACTIVE)

_add(WorkspaceState.CHECKPOINTED, None, WorkspaceState.RELEASED_FOR_INTEGRATION)
_add(WorkspaceState.CHECKPOINTED, None, WorkspaceState.ACTIVE)

_add(WorkspaceState.RELEASED_FOR_INTEGRATION, None, WorkspaceState.INTEGRATED)
_add(
    WorkspaceState.RELEASED_FOR_INTEGRATION,
    None,
    WorkspaceState.RETIRED,
    RecoveryState.INTEGRATION_CONFLICT,
)

_add(WorkspaceState.INTEGRATED, None, WorkspaceState.PUBLISHED)

_add(WorkspaceState.PUBLISHED, None, WorkspaceState.RETIRED)

# Recovery transitions
for rec in _RECOVERY_REQUIRED_RECOVERY:
    _add(
        WorkspaceState.ACTIVE,
        rec,
        WorkspaceState.ACTIVE,
        RecoveryState.RECOVERY_REQUIRED,
    )
    _add(WorkspaceState.ACTIVE, rec, WorkspaceState.ACTIVE, RecoveryState.RECOVERED)
    _add(WorkspaceState.ACTIVE, rec, WorkspaceState.RETIRED, RecoveryState.QUARANTINED)

# Allow recovery states to transition to VALIDATING
for rec in {
    RecoveryState.SESSION_DETACHED,
    RecoveryState.RECOVERY_REQUIRED,
    RecoveryState.STALE_BASE,
    RecoveryState.BOOTSTRAP_FAILED,
    RecoveryState.RECOVERED,
}:
    _add(WorkspaceState.ACTIVE, rec, WorkspaceState.VALIDATING, None)

_add(
    WorkspaceState.ACTIVE,
    RecoveryState.SESSION_DETACHED,
    WorkspaceState.ACTIVE,
    RecoveryState.RECOVERED,
)
_add(WorkspaceState.ACTIVE, RecoveryState.RECOVERED, WorkspaceState.ACTIVE, None)
_add(WorkspaceState.ACTIVE, RecoveryState.RECOVERED, WorkspaceState.VALIDATING, None)
_add(
    WorkspaceState.ACTIVE,
    RecoveryState.RECOVERED,
    WorkspaceState.ACTIVE,
    RecoveryState.RECOVERY_REQUIRED,
)
_add(
    WorkspaceState.ACTIVE,
    RecoveryState.RECOVERED,
    WorkspaceState.RETIRED,
    RecoveryState.QUARANTINED,
)

_add(
    WorkspaceState.ACTIVE,
    RecoveryState.INTEGRATION_CONFLICT,
    WorkspaceState.RETIRED,
    None,
)
_add(
    WorkspaceState.ACTIVE,
    RecoveryState.INTEGRATION_CONFLICT,
    WorkspaceState.RETIRED,
    RecoveryState.QUARANTINED,
)

_add(WorkspaceState.RETIRED, RecoveryState.QUARANTINED, WorkspaceState.RETIRED, None)
_add(
    WorkspaceState.RETIRED,
    RecoveryState.RESERVATION_REFUSED,
    WorkspaceState.RETIRED,
    None,
)
_add(
    WorkspaceState.RETIRED, RecoveryState.REMOVAL_REFUSED, WorkspaceState.RETIRED, None
)
_add(WorkspaceState.RETIRED, RecoveryState.RESET_REFUSED, WorkspaceState.RETIRED, None)


def _is_terminal(state: WorkspaceState, recovery: RecoveryState | None) -> bool:
    if state == WorkspaceState.RETIRED:
        return True
    if recovery is not None and recovery in _TERMINAL_RECOVERY:
        return True
    return False


_ACTION_MAP: dict[WorkspaceState, list[str]] = {
    WorkspaceState.REQUESTED: ["create_worktree", "cancel"],
    WorkspaceState.RESERVED: ["create_worktree", "cancel"],
    WorkspaceState.WORKTREE_CREATED: ["bootstrap", "cancel"],
    WorkspaceState.BOOTSTRAPPING: ["cancel"],
    WorkspaceState.READY: ["activate"],
    WorkspaceState.ACTIVE: [
        "validate",
        "checkpoint",
        "record_changes",
        "release",
        "claim_boundary",
    ],
    WorkspaceState.VALIDATING: ["under_review", "back_to_active", "claim_boundary"],
    WorkspaceState.UNDER_REVIEW: ["checkpoint", "back_to_active", "claim_boundary"],
    WorkspaceState.CHECKPOINTED: ["release_for_integration", "back_to_active"],
    WorkspaceState.RELEASED_FOR_INTEGRATION: ["integrate", "claim_boundary"],
    WorkspaceState.INTEGRATED: ["publish"],
    WorkspaceState.PUBLISHED: ["retire"],
    WorkspaceState.RETIRED: [],
}


def _actions_for_workspace(ws: ManagedWorkspace) -> list[str]:
    actions = list(_ACTION_MAP.get(ws.state, []))
    rec = ws.recovery_state
    if rec is not None and rec not in _TERMINAL_RECOVERY:
        actions.append("recover")
        if rec not in {RecoveryState.RECOVERED}:
            actions.append("quarantine")
    elif rec is not None and rec in _TERMINAL_RECOVERY:
        pass
    return actions


class WorktreeProvider(Protocol):
    async def create(
        self,
        repo_root: Path,
        workspace_id: str,
        branch_name: str,
        base_sha: str,
        spawn: bool = True,
    ) -> tuple[bool, str, str | None]: ...
    async def remove(
        self, workspace_id: str, repo_root: Path, force: bool = False
    ) -> tuple[bool, str]: ...


class ManagedWorkspaceService:
    def __init__(
        self,
        *,
        repo_root: str | Path,
        config: WorkspaceConfig | None = None,
        worktree_provider: WorktreeProvider | None = None,
        claim_store: FleetClaimStore | None = None,
    ) -> None:
        self.repo_root = Path(repo_root)
        self._config = config or WorkspaceConfig()
        self._worktree_provider = worktree_provider
        self._store_path = self.repo_root / self._config.workspaces_store_path
        self._store_path.mkdir(parents=True, exist_ok=True)
        (self._store_path / "..").resolve()
        self._events_path = self.repo_root / self._config.lifecycle_events_path
        self._events_path.parent.mkdir(parents=True, exist_ok=True)
        self._workspaces: dict[str, ManagedWorkspace] = {}
        self._ledger = WorkspaceLifecycleLedger(self._events_path)
        if claim_store is not None:
            self._claim_store = claim_store
        else:
            claims_root = (
                self.repo_root / ".rig" / "relay" / "workspaces" / "fleet_claims"
            )
            self._claim_store = FleetClaimStore(root=claims_root)
        self._load_all()

    def _load_all(self) -> None:
        self._workspaces.clear()
        if not self._store_path.exists():
            return
        for path in sorted(self._store_path.glob("*.json")):
            try:
                ws = ManagedWorkspace.model_validate_json(
                    path.read_text(encoding="utf-8")
                )
                self._workspaces[ws.identity.workspace_id] = ws
            except Exception:
                continue

    async def request_workspace(
        self,
        identity: WorkspaceIdentity,
        base_commit_sha: str,
        session_id: str | None = None,
    ) -> tuple[ManagedWorkspace | None, str]:
        ws = ManagedWorkspace(
            identity=identity,
            state=WorkspaceState.REQUESTED,
            base_commit_sha=base_commit_sha,
            session_id=session_id,
        )
        self._workspaces[ws.identity.workspace_id] = ws
        self._save_workspace(ws)
        ok, err = await self._transition(
            ws.identity.workspace_id,
            WorkspaceState.REQUESTED,
            None,
            WorkspaceLifecycleEventKind.WORKSPACE_REQUESTED,
        )
        if not ok:
            return None, err
        ok, err = await self._transition(
            ws.identity.workspace_id,
            WorkspaceState.RESERVED,
            None,
            WorkspaceLifecycleEventKind.WORKSPACE_RESERVED,
        )
        if not ok:
            return None, err
        ws = self._workspaces.get(ws.identity.workspace_id)
        return ws, ""

    async def create_worktree(self, workspace_id: str) -> tuple[bool, str]:
        valid, err = self._sanitize_workspace_id(workspace_id)
        if not valid:
            return False, f"invalid workspace_id: {err}"
        ws = self._load_workspace(workspace_id)
        if ws is None:
            return False, f"workspace not found: {workspace_id}"
        if ws.state != WorkspaceState.RESERVED:
            return False, f"workspace must be in RESERVED state, current: {ws.state}"
        branch_name = self._build_branch_name(ws.identity)
        worktree_parent = self.repo_root / self._config.workspaces_root
        worktree_parent.mkdir(parents=True, exist_ok=True)
        worktree_path = worktree_parent / workspace_id
        base_sha = ws.base_commit_sha or "HEAD"
        argv = ["worktree", "add", "-b", branch_name, str(worktree_path), base_sha]
        add_error: str | None = None
        proc = None
        try:
            proc = subprocess.run(
                ["git", *argv],
                capture_output=True,
                text=True,
                cwd=str(self.repo_root),
                stdin=subprocess.DEVNULL,
                timeout=_GIT_TIMEOUT,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
            add_error = f"git worktree add failed: {exc}"
        if add_error is None and proc is not None and proc.returncode != 0:
            err_msg = proc.stderr.strip() or "unknown error"
            await self._transition(
                workspace_id,
                WorkspaceState.RETIRED,
                RecoveryState.RESERVATION_REFUSED,
                WorkspaceLifecycleEventKind.RESERVATION_REFUSED,
                reason=f"git worktree add failed: {err_msg}",
            )
            add_error = f"git worktree add failed: {err_msg}"
        if add_error is not None:
            return False, add_error
        ws.worktree_path = str(worktree_path)
        ws.branch_name = branch_name
        ws.managed_branch_name = branch_name
        self._workspaces[workspace_id] = ws
        self._save_workspace(ws)
        ok, err = await self._transition(
            workspace_id,
            WorkspaceState.WORKTREE_CREATED,
            None,
            WorkspaceLifecycleEventKind.WORKTREE_CREATED,
            worktree_path=str(worktree_path),
            branch_name=branch_name,
        )
        if not ok:
            return False, err
        return True, ""

    async def bootstrap(self, workspace_id: str) -> tuple[bool, str]:
        ws = self._load_workspace(workspace_id)
        if ws is None:
            return False, f"workspace not found: {workspace_id}"
        if ws.state != WorkspaceState.WORKTREE_CREATED:
            return (
                False,
                f"workspace must be in WORKTREE_CREATED state, current: {ws.state}",
            )
        ok, err = await self._transition(
            workspace_id,
            WorkspaceState.BOOTSTRAPPING,
            None,
            WorkspaceLifecycleEventKind.BOOTSTRAP_STARTED,
        )
        if not ok:
            return False, err
        ok, err = await self._transition(
            workspace_id,
            WorkspaceState.READY,
            None,
            WorkspaceLifecycleEventKind.BOOTSTRAP_COMPLETED,
        )
        if not ok:
            return False, err
        return True, ""

    async def activate(self, workspace_id: str, session_id: str) -> tuple[bool, str]:
        ws = self._load_workspace(workspace_id)
        if ws is None:
            return False, f"workspace not found: {workspace_id}"
        if ws.state != WorkspaceState.READY:
            return False, f"workspace must be in READY state, current: {ws.state}"
        ws.session_id = session_id
        self._save_workspace(ws)
        ok, err = await self._transition(
            workspace_id,
            WorkspaceState.ACTIVE,
            None,
            WorkspaceLifecycleEventKind.WORKSPACE_ACTIVATED,
            session_id=session_id,
        )
        return ok, err

    async def record_changes(
        self, workspace_id: str, changed_files_count: int
    ) -> tuple[bool, str]:
        ws = self._load_workspace(workspace_id)
        if ws is None:
            return False, f"workspace not found: {workspace_id}"
        if ws.state != WorkspaceState.ACTIVE:
            return False, f"workspace must be in ACTIVE state, current: {ws.state}"
        ws.changed_files_count = changed_files_count
        head_sha = self._get_head(ws)
        if head_sha:
            ws.head_sha = head_sha
        self._save_workspace(ws)
        self._workspaces[workspace_id] = ws
        ok, err = await self._transition(
            workspace_id,
            WorkspaceState.ACTIVE,
            None,
            WorkspaceLifecycleEventKind.CHANGES_RECORDED,
            changed_files_count=changed_files_count,
        )
        return ok, err

    async def checkpoint(
        self, workspace_id: str, checkpoint_sha: str
    ) -> tuple[bool, str]:
        ws = self._load_workspace(workspace_id)
        if ws is None:
            return False, f"workspace not found: {workspace_id}"
        if ws.state not in {WorkspaceState.ACTIVE, WorkspaceState.UNDER_REVIEW}:
            return (
                False,
                f"workspace must be ACTIVE or UNDER_REVIEW for checkpoint, current: {ws.state}",
            )
        ws.checkpoint_sha = checkpoint_sha
        head_sha = self._get_head(ws)
        if head_sha:
            ws.head_sha = head_sha
        self._save_workspace(ws)
        self._workspaces[workspace_id] = ws
        ok, err = await self._transition(
            workspace_id,
            WorkspaceState.CHECKPOINTED,
            None,
            WorkspaceLifecycleEventKind.WORKSPACE_CHECKPOINTED,
            checkpoint_sha=checkpoint_sha,
        )
        return ok, err

    async def mark_validating(self, workspace_id: str) -> tuple[bool, str]:
        ws = self._load_workspace(workspace_id)
        if ws is None:
            return False, f"workspace not found: {workspace_id}"
        if ws.state != WorkspaceState.ACTIVE:
            return False, f"workspace must be in ACTIVE state, current: {ws.state}"
        ok, err = await self._transition(
            workspace_id,
            WorkspaceState.VALIDATING,
            None,
            WorkspaceLifecycleEventKind.VALIDATION_STARTED,
        )
        return ok, err

    async def mark_under_review(self, workspace_id: str) -> tuple[bool, str]:
        ws = self._load_workspace(workspace_id)
        if ws is None:
            return False, f"workspace not found: {workspace_id}"
        if ws.state != WorkspaceState.VALIDATING:
            return False, f"workspace must be in VALIDATING state, current: {ws.state}"
        ok, err = await self._transition(
            workspace_id,
            WorkspaceState.UNDER_REVIEW,
            None,
            WorkspaceLifecycleEventKind.REVIEW_STARTED,
        )
        return ok, err

    async def assess_work_preservation(
        self, workspace_id: str
    ) -> WorkLossAssessment | None:
        from rig_relay.workspace._recovery import WorkspaceRecoveryEngine

        engine = WorkspaceRecoveryEngine(self, self.repo_root)
        return await engine.assess_work_loss(workspace_id)

    async def mark_validation_required(self, workspace_id: str) -> tuple[bool, str]:
        ws = self._load_workspace(workspace_id)
        if ws is None:
            return False, f"workspace not found: {workspace_id}"
        ok, err = await self._transition(
            workspace_id,
            WorkspaceState.VALIDATING,
            None,
            WorkspaceLifecycleEventKind.VALIDATION_REQUIRED,
        )
        return ok, err

    async def release_for_integration(self, workspace_id: str) -> tuple[bool, str]:
        ws = self._load_workspace(workspace_id)
        if ws is None:
            return False, f"workspace not found: {workspace_id}"
        if ws.state != WorkspaceState.CHECKPOINTED:
            return (
                False,
                f"workspace must be in CHECKPOINTED state, current: {ws.state}",
            )
        ok, err = await self._transition(
            workspace_id,
            WorkspaceState.RELEASED_FOR_INTEGRATION,
            None,
            WorkspaceLifecycleEventKind.RELEASED_FOR_INTEGRATION,
        )
        return ok, err

    async def mark_integrated(self, workspace_id: str) -> tuple[bool, str]:
        ws = self._load_workspace(workspace_id)
        if ws is None:
            return False, f"workspace not found: {workspace_id}"
        if ws.state != WorkspaceState.RELEASED_FOR_INTEGRATION:
            return (
                False,
                f"workspace must be in RELEASED_FOR_INTEGRATION state, current: {ws.state}",
            )
        ok, err = await self._transition(
            workspace_id,
            WorkspaceState.INTEGRATED,
            None,
            WorkspaceLifecycleEventKind.INTEGRATED,
        )
        return ok, err

    async def mark_published(self, workspace_id: str) -> tuple[bool, str]:
        ws = self._load_workspace(workspace_id)
        if ws is None:
            return False, f"workspace not found: {workspace_id}"
        if ws.state != WorkspaceState.INTEGRATED:
            return False, f"workspace must be in INTEGRATED state, current: {ws.state}"
        ok, err = await self._transition(
            workspace_id,
            WorkspaceState.PUBLISHED,
            None,
            WorkspaceLifecycleEventKind.PUBLISHED,
        )
        return ok, err

    async def _verify_destructive_action_safe(
        self, workspace_id: str, action: str, force: bool = False
    ) -> tuple[bool, str]:
        ws = self._load_workspace(workspace_id)
        if ws is None:
            return False, f"workspace not found: {workspace_id}"
        worktree_path_str = ws.worktree_path
        if worktree_path_str is not None:
            worktree_path = Path(worktree_path_str)
            if self._is_primary_worktree(worktree_path):
                return False, f"cannot {action} primary worktree"
            if worktree_path.exists():
                dirty_check = self._has_uncommitted_changes(worktree_path)
                if not force and dirty_check is not False:
                    return (
                        False,
                        "workspace has uncommitted changes — use force=True or checkpoint first",
                    )
            else:
                pass
        unreleased_states = {
            WorkspaceState.ACTIVE,
            WorkspaceState.VALIDATING,
            WorkspaceState.UNDER_REVIEW,
        }
        if ws.state in unreleased_states and not force:
            return (
                False,
                f"workspace is {ws.state.value} — release or checkpoint first",
            )
        return True, ""

    async def retire(self, workspace_id: str, force: bool = False) -> tuple[bool, str]:
        ws = self._load_workspace(workspace_id)
        if ws is None:
            return False, f"workspace not found: {workspace_id}"
        if ws.state == WorkspaceState.RETIRED:
            return False, "workspace already retired"
        safe, reason = await self._verify_destructive_action_safe(
            workspace_id, "retire", force
        )
        if not safe:
            return False, reason
        if ws.worktree_path:
            removed, rem_err = await self.remove_worktree(workspace_id, force=force)
            if not removed and not force:
                return False, f"worktree removal failed: {rem_err}"
        ok, err = await self._transition(
            workspace_id,
            WorkspaceState.RETIRED,
            None,
            WorkspaceLifecycleEventKind.WORKSPACE_RETIRED,
        )
        return ok, err

    async def detect_stale_base(self, workspace_id: str) -> tuple[bool, str]:
        ws = self._load_workspace(workspace_id)
        if ws is None:
            return False, f"workspace not found: {workspace_id}"
        base_sha = ws.base_commit_sha
        if not base_sha:
            return False, "no base commit SHA on workspace"
        try:
            proc = subprocess.run(
                ["git", "merge-base", "--is-ancestor", base_sha, "HEAD"],
                capture_output=True,
                text=True,
                cwd=str(self.repo_root),
                stdin=subprocess.DEVNULL,
                timeout=_GIT_TIMEOUT,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
            return False, f"git merge-base failed: {exc}"
        if proc.returncode == 0:
            return True, ""
        ok, err = await self._transition(
            workspace_id,
            WorkspaceState.ACTIVE,
            RecoveryState.STALE_BASE,
            WorkspaceLifecycleEventKind.STALE_BASE_DETECTED,
            reason=f"base {base_sha[:8]} is not an ancestor of HEAD",
        )
        return ok, err

    async def detect_session_detached(
        self, workspace_id: str, current_session_id: str
    ) -> tuple[bool, str]:
        ws = self._load_workspace(workspace_id)
        if ws is None:
            return False, f"workspace not found: {workspace_id}"
        if ws.session_id and ws.session_id != current_session_id:
            ok, err = await self._transition(
                workspace_id,
                WorkspaceState.ACTIVE,
                RecoveryState.SESSION_DETACHED,
                WorkspaceLifecycleEventKind.SESSION_DETACHED,
                reason=f"session mismatch: stored={ws.session_id}, current={current_session_id}",
            )
            return ok, err
        return True, ""

    async def recover(self, workspace_id: str, session_id: str) -> tuple[bool, str]:
        lock_path = self._store_path / f"{workspace_id}.lock"
        lock_fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR)
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(lock_fd)
            return (False, "recovery already in progress for this workspace")
        try:
            ws = self._load_workspace(workspace_id)
            if ws is None:
                return False, f"workspace not found: {workspace_id}"
            rec = ws.recovery_state
            if rec is None or rec in _TERMINAL_RECOVERY:
                msg = (
                    "workspace is not in a recovery state"
                    if rec is None
                    else f"workspace recovery state is terminal: {rec}"
                )
                return False, msg
            if ws.worktree_path and not Path(ws.worktree_path).exists():
                return False, f"worktree path does not exist: {ws.worktree_path}"
            original_session_id = ws.session_id
            original_head_sha = ws.head_sha
            head_sha = self._get_head(ws)
            if head_sha:
                ws.head_sha = head_sha
            ws.session_id = session_id
            cached = self._workspaces.get(workspace_id)
            if cached is not None:
                if head_sha:
                    cached.head_sha = head_sha
                cached.session_id = session_id
            else:
                cached = self._load_workspace(workspace_id)
                if cached is not None:
                    if head_sha:
                        cached.head_sha = head_sha
                    cached.session_id = session_id
                    self._workspaces[workspace_id] = cached
            ok, err = await self._transition(
                workspace_id,
                WorkspaceState.ACTIVE,
                RecoveryState.RECOVERED,
                WorkspaceLifecycleEventKind.RECOVERED,
                session_id=session_id,
            )
            if not ok:
                return False, err
            ok, err = await self._transition(
                workspace_id,
                WorkspaceState.ACTIVE,
                None,
                WorkspaceLifecycleEventKind.WORKSPACE_ACTIVATED,
                session_id=session_id,
            )
            if not ok:
                ws.session_id = original_session_id
                ws.head_sha = original_head_sha
                if cached:
                    cached.session_id = original_session_id
                    cached.head_sha = original_head_sha
                    self._workspaces[workspace_id] = cached
                self._save_workspace(ws)
                await self._transition(
                    workspace_id,
                    WorkspaceState.ACTIVE,
                    RecoveryState.RECOVERY_REQUIRED,
                    WorkspaceLifecycleEventKind.RECOVERY_REQUIRED,
                    reason=f"reactivation failed, retry: {err}",
                )
                return False, err
            return ok, err
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            os.close(lock_fd)

    async def quarantine(self, workspace_id: str, reason: str) -> tuple[bool, str]:
        ws = self._load_workspace(workspace_id)
        if ws is None:
            return False, f"workspace not found: {workspace_id}"
        if ws.recovery_state is not None and ws.recovery_state in _TERMINAL_RECOVERY:
            return False, f"workspace already in terminal recovery: {ws.recovery_state}"
        ok, err = await self._transition(
            workspace_id,
            WorkspaceState.RETIRED,
            RecoveryState.QUARANTINED,
            WorkspaceLifecycleEventKind.QUARANTINED,
            reason=reason,
        )
        return ok, err

    async def remove_worktree(
        self, workspace_id: str, force: bool = False
    ) -> tuple[bool, str]:
        ws = self._load_workspace(workspace_id)
        if ws is None:
            return False, f"workspace not found: {workspace_id}"
        worktree_path_str = ws.worktree_path
        if not worktree_path_str:
            return False, "no worktree path on workspace"
        worktree_path = Path(worktree_path_str)
        safe, reason = await self._verify_destructive_action_safe(
            workspace_id, "remove", force
        )
        if not safe:
            refusal_reason = reason
            ok, err = await self._transition(
                workspace_id,
                WorkspaceState.RETIRED,
                RecoveryState.REMOVAL_REFUSED,
                WorkspaceLifecycleEventKind.REMOVAL_REFUSED,
                reason=refusal_reason,
            )
            return ok, err
        refusal_reason: str | None = None
        if worktree_path.exists():
            refusal_reason = await self._try_git_worktree_remove(worktree_path, force)
        if refusal_reason is not None:
            ok, err = await self._transition(
                workspace_id,
                WorkspaceState.RETIRED,
                RecoveryState.REMOVAL_REFUSED,
                WorkspaceLifecycleEventKind.REMOVAL_REFUSED,
                reason=refusal_reason,
            )
            return ok, err
        ws.worktree_path = None
        ws.branch_name = None
        ws.managed_branch_name = None
        self._save_workspace(ws)
        return True, ""

    async def reset_workspace(
        self, workspace_id: str, force: bool = False
    ) -> tuple[bool, str]:
        ws = self._load_workspace(workspace_id)
        if ws is None:
            return False, f"workspace not found: {workspace_id}"
        if ws.state == WorkspaceState.RETIRED:
            return False, "workspace already retired"
        safe, reason = await self._verify_destructive_action_safe(
            workspace_id, "reset", force
        )
        if not safe:
            if force:
                return await self._reset_workspace_forced(workspace_id)
            ok, err = await self._transition(
                workspace_id,
                WorkspaceState.RETIRED,
                RecoveryState.RESET_REFUSED,
                WorkspaceLifecycleEventKind.RESET_REFUSED,
                reason=reason,
            )
            return ok, err
        return await self._reset_workspace_retire(workspace_id)

    async def _reset_workspace_forced(self, workspace_id: str) -> tuple[bool, str]:
        ws = self._load_workspace(workspace_id)
        if ws is None:
            return False, f"workspace not found after force reload: {workspace_id}"
        if ws.worktree_path and self._is_primary_worktree(Path(ws.worktree_path)):
            return (False, "cannot force-reset primary worktree")
        worktree_path_str = ws.worktree_path
        was_locked = False
        if worktree_path_str:
            worktree_path = Path(worktree_path_str)
            if worktree_path.exists():
                lock_ok, lock_err = await self._lock_worktree(
                    worktree_path, reason="reset operation"
                )
                if not lock_ok:
                    ok, err = await self._transition(
                        workspace_id,
                        WorkspaceState.RETIRED,
                        RecoveryState.RESET_REFUSED,
                        WorkspaceLifecycleEventKind.RESET_REFUSED,
                        reason=f"worktree lock failed during reset: {lock_err}",
                    )
                    return ok, err
                was_locked = True
                try:
                    removed, _ = await self._try_git_worktree_remove_and_clear(
                        workspace_id, worktree_path, force=True
                    )
                finally:
                    if was_locked:
                        await self._unlock_worktree(worktree_path)
                if not removed:
                    ok, err = await self._transition(
                        workspace_id,
                        WorkspaceState.RETIRED,
                        RecoveryState.RESET_REFUSED,
                        WorkspaceLifecycleEventKind.RESET_REFUSED,
                        reason="worktree removal failed during reset",
                    )
                    return ok, err
        return await self._reset_workspace_retire(workspace_id)

    async def _reset_workspace_retire(self, workspace_id: str) -> tuple[bool, str]:
        return await self._transition(
            workspace_id,
            WorkspaceState.RETIRED,
            None,
            WorkspaceLifecycleEventKind.WORKSPACE_RETIRED,
        )

    async def quarantine_workspace(
        self, workspace_id: str, reason: str
    ) -> tuple[bool, str]:
        ws = self._load_workspace(workspace_id)
        if ws is None:
            return False, f"workspace not found: {workspace_id}"
        ok, err = await self.quarantine(workspace_id, reason)
        if not ok:
            return ok, err
        worktree_path_str = ws.worktree_path
        if worktree_path_str:
            worktree_path = Path(worktree_path_str)
            if worktree_path.exists():
                try:
                    lock_ok, lock_err = await self._lock_worktree(
                        worktree_path, reason=f"quarantined: {reason}"
                    )
                    if not lock_ok:
                        logger.warning(
                            "quarantine_workspace: lock failed for workspace=%s: %s",
                            workspace_id,
                            lock_err,
                        )
                except Exception:
                    logger.warning(
                        "quarantine_workspace: lock exception for workspace=%s",
                        workspace_id,
                        exc_info=True,
                    )
        return True, ""

    async def safe_retire_workspace(
        self, workspace_id: str, force: bool = False
    ) -> tuple[bool, str]:
        ws = self._load_workspace(workspace_id)
        if ws is None:
            return False, f"workspace not found: {workspace_id}"
        if ws.state == WorkspaceState.RETIRED:
            return False, "workspace already retired"
        if ws.recovery_state == RecoveryState.QUARANTINED:
            return False, "workspace already quarantined"
        unreleased_states = {
            WorkspaceState.ACTIVE,
            WorkspaceState.VALIDATING,
            WorkspaceState.UNDER_REVIEW,
            WorkspaceState.CHECKPOINTED,
        }
        has_unreleased = ws.state in unreleased_states or (
            ws.worktree_path
            and Path(ws.worktree_path).exists()
            and self._has_uncommitted_changes(Path(ws.worktree_path)) is not False
        )
        if has_unreleased and not force:
            q_ok, q_err = await self.quarantine_workspace(
                workspace_id, reason="safe_retire: unreleased work preserved"
            )
            if not q_ok:
                return False, f"quarantine failed: {q_err}"
            return False, "workspace quarantined — unreleased work preserved"
        return await self.retire(workspace_id, force=force)

    @staticmethod
    def _has_uncommitted_changes(worktree_path: Path) -> bool | None:
        try:
            proc = subprocess.run(
                ["git", "status", "--porcelain"],
                capture_output=True,
                text=True,
                cwd=str(worktree_path),
                stdin=subprocess.DEVNULL,
                timeout=10.0,
            )
            if proc.returncode != 0:
                return None
            return bool(proc.stdout.strip())
        except (FileNotFoundError, OSError, subprocess.TimeoutExpired, Exception):
            return None

    async def _lock_worktree(
        self, worktree_path: Path, *, reason: str
    ) -> tuple[bool, str]:
        try:
            proc = subprocess.run(
                ["git", "worktree", "lock", "--reason", reason, str(worktree_path)],
                capture_output=True,
                text=True,
                cwd=str(self.repo_root),
                stdin=subprocess.DEVNULL,
                timeout=_GIT_TIMEOUT,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
            return False, f"git worktree lock failed: {exc}"
        if proc.returncode != 0:
            return (
                False,
                f"git worktree lock failed: {proc.stderr.strip() or 'unknown error'}",
            )
        return True, ""

    async def _unlock_worktree(self, worktree_path: Path) -> None:
        try:
            subprocess.run(
                ["git", "worktree", "unlock", str(worktree_path)],
                capture_output=True,
                text=True,
                cwd=str(self.repo_root),
                stdin=subprocess.DEVNULL,
                timeout=_GIT_TIMEOUT,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            pass

    async def _try_git_worktree_remove_and_clear(
        self, workspace_id: str, worktree_path: Path, force: bool
    ) -> tuple[bool, str | None]:
        err = await self._try_git_worktree_remove(worktree_path, force)
        if err is not None:
            return False, err
        ws = self._load_workspace(workspace_id)
        if ws is not None:
            ws.worktree_path = None
            ws.branch_name = None
            ws.managed_branch_name = None
            self._save_workspace(ws)
        return True, None

    async def _try_git_worktree_remove(
        self, worktree_path: Path, force: bool
    ) -> str | None:
        argv = ["worktree", "remove", str(worktree_path)]
        if force:
            argv.insert(2, "--force")
        try:
            proc = subprocess.run(
                ["git", *argv],
                capture_output=True,
                text=True,
                cwd=str(self.repo_root),
                stdin=subprocess.DEVNULL,
                timeout=_GIT_TIMEOUT,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
            return f"git worktree remove failed: {exc}"
        if proc.returncode != 0:
            err_msg = proc.stderr.strip() or "unknown error"
            return f"git worktree remove failed: {err_msg}"
        return None

    async def get_workspace(self, workspace_id: str) -> ManagedWorkspace | None:
        ws = self._workspaces.get(workspace_id)
        if ws is not None:
            return ws
        return self._load_workspace(workspace_id)

    async def list_workspaces(
        self, state: WorkspaceState | None = None
    ) -> list[ManagedWorkspace]:
        self._load_all()
        if state is None:
            return list(self._workspaces.values())
        return [ws for ws in self._workspaces.values() if ws.state == state]

    async def build_projection(self) -> FleetWorkspaceProjection:
        self._load_all()
        workspaces = list(self._workspaces.values())
        claim_data: dict[str, list[ActiveClaim]] = {}
        if self._claim_store is not None:
            for ws in workspaces:
                claims = self._claim_store.get_workspace_claims(
                    ws.identity.workspace_id
                )
                claim_data[ws.identity.workspace_id] = claims
        return build_fleet_workspace_projection(workspaces, workspace_claims=claim_data)

    # ── Boundary claim methods ─────────────────────────────────────────────

    async def acquire_boundary_claim(
        self,
        workspace_id: str,
        boundary_name: str,
        boundary_paths: list[str],
        mission_id: str = "",
        lane_id: str = "",
        agent_id: str = "",
    ) -> tuple[bool, str]:
        ws = self._workspaces.get(workspace_id) or self._load_workspace(workspace_id)
        if ws is None:
            return False, f"workspace not found: {workspace_id}"
        allowed = {
            WorkspaceState.ACTIVE,
            WorkspaceState.VALIDATING,
            WorkspaceState.UNDER_REVIEW,
            WorkspaceState.RELEASED_FOR_INTEGRATION,
        }
        if ws.state not in allowed:
            return (
                False,
                f"workspace must be in one of {[s.value for s in allowed]} to acquire a boundary claim, current: {ws.state}",
            )

        claimed, other_claim_id = self._claim_store.is_workspace_boundary_claimed(
            workspace_id, boundary_name
        )
        if claimed:
            return (
                False,
                f"integration boundary {boundary_name} already claimed by workspace {other_claim_id}",
            )

        result = self._claim_store.acquire_workspace_claim(
            workspace_id=workspace_id,
            mission_id=mission_id or ws.identity.mission_id or "unknown",
            lane_id=lane_id or ws.identity.lane_id or "unknown",
            agent_id=agent_id or ws.identity.agent_profile_name or "unknown",
            claimed_paths=boundary_paths,
            workspace_authority_id=f"workspace:{workspace_id}",
        )
        if not result.acquired:
            raw_reason = result.refusal_reason or "claim refused"
            friendly_reason = raw_reason
            if raw_reason.startswith("conflict_"):
                friendly_reason = (
                    f"integration boundary {boundary_name} already claimed "
                    f"(code: {raw_reason})"
                )
            return False, friendly_reason

        claim_id = result.claim.claim_id if result.claim else "unknown"
        event = WorkspaceLifecycleEvent(
            workspace_id=workspace_id,
            event_kind=WorkspaceLifecycleEventKind.BOUNDARY_CLAIM_ACQUIRED,
            state_before=ws.state,
            state_after=ws.state,
            reason=f"boundary={boundary_name} claim_id={claim_id}",
            session_id=ws.session_id,
            worktree_path=ws.worktree_path,
        )
        try:
            self._ledger.append(event)
        except Exception:
            self._claim_store.release_workspace_claim(claim_id)
            return False, "failed to record boundary claim evidence — claim released"
        return True, ""

    async def release_boundary_claim(
        self, workspace_id: str, boundary_name: str
    ) -> tuple[bool, str]:
        ws = self._workspaces.get(workspace_id) or self._load_workspace(workspace_id)
        if ws is None:
            return False, f"workspace not found: {workspace_id}"

        claims = self._claim_store.get_workspace_claims(workspace_id)
        matching = [c for c in claims if boundary_name in str(c.claimed_paths)]
        if not matching:
            return False, f"no active claim found for boundary {boundary_name}"

        claim = matching[0]
        claim_id = claim.claim_id
        saved_mission_id = claim.mission_id
        saved_lane_id = claim.lane_id
        saved_agent_id = claim.agent_id
        saved_paths = list(claim.claimed_paths)
        saved_authority_id = claim.workspace_authority_id
        result = self._claim_store.release_workspace_claim(claim_id)
        if not result.acquired:
            reason = result.refusal_reason or "release failed"
            return False, reason

        event = WorkspaceLifecycleEvent(
            workspace_id=workspace_id,
            event_kind=WorkspaceLifecycleEventKind.BOUNDARY_CLAIM_RELEASED,
            state_before=ws.state,
            state_after=ws.state,
            reason=f"boundary={boundary_name} claim_id={claim_id}",
            session_id=ws.session_id,
            worktree_path=ws.worktree_path,
        )
        try:
            self._ledger.append(event)
        except Exception:
            self._claim_store.acquire_workspace_claim(
                workspace_id=workspace_id,
                mission_id=saved_mission_id,
                lane_id=saved_lane_id,
                agent_id=saved_agent_id,
                claimed_paths=saved_paths,
                workspace_authority_id=saved_authority_id,
            )
            return (
                False,
                "failed to record boundary claim release evidence — claim preserved",
            )
        return True, ""

    async def get_boundary_claims(self, workspace_id: str) -> list[dict[str, Any]]:
        claims = self._claim_store.get_workspace_claims(workspace_id)
        result: list[dict[str, Any]] = []
        for c in claims:
            result.append({
                "claim_id": c.claim_id,
                "boundary_name": c.claimed_paths,
                "paths": c.claimed_paths,
                "state": c.state.value,
                "acquired_at": c.acquired_at,
            })
        return result

    async def detect_boundary_conflict(self, workspace_id: str) -> tuple[bool, str]:
        claims = self._claim_store.get_workspace_claims(workspace_id)
        if not claims:
            return False, ""
        all_claimed_paths: list[str] = []
        for c in claims:
            all_claimed_paths.extend(c.claimed_paths)
        conflicted, other_ws, conflict_paths = (
            self._claim_store.detect_integration_conflict(
                workspace_id, all_claimed_paths
            )
        )
        if conflicted:
            event = WorkspaceLifecycleEvent(
                workspace_id=workspace_id,
                event_kind=WorkspaceLifecycleEventKind.BOUNDARY_CONFLICT_DETECTED,
                reason=f"conflict with {other_ws} on paths {conflict_paths}",
            )
            self._ledger.append(event)
            return True, str(conflict_paths)
        return False, ""

    # ── Session assignment methods ────────────────────────────────────────

    @staticmethod
    def _derive_assignment_state(ws: ManagedWorkspace) -> AssignmentState:
        match ws.state:
            case WorkspaceState.READY:
                return AssignmentState.READY_FOR_ASSIGNMENT
            case WorkspaceState.ACTIVE:
                match ws.recovery_state:
                    case RecoveryState.SESSION_DETACHED:
                        return AssignmentState.DETACHED_WITH_WORK_PRESERVED
                    case RecoveryState.RECOVERY_REQUIRED:
                        return AssignmentState.RECOVERY_REQUIRED
                    case RecoveryState.RECOVERED:
                        return AssignmentState.RECOVERED
                    case _:
                        return AssignmentState.ASSIGNED
            case WorkspaceState.RELEASED_FOR_INTEGRATION:
                return AssignmentState.RELEASED_FOR_INTEGRATION
            case WorkspaceState.RETIRED:
                return AssignmentState.RETIRED
            case _:
                return AssignmentState.BLOCKED_MISSING_CONTEXT_RELEASE

    def _git_has_uncommitted_changes(self, worktree_path: str) -> bool:
        try:
            proc = subprocess.run(
                ["git", "status", "--porcelain"],
                capture_output=True,
                text=True,
                cwd=worktree_path,
                stdin=subprocess.DEVNULL,
                timeout=_GIT_TIMEOUT,
            )
            return bool(proc.stdout.strip())
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            return False

    async def assign_session(
        self, workspace_id: str, request: WorkspaceAssignmentRequest
    ) -> tuple[WorkspaceAssignmentReceipt | None, str]:
        valid, err = self._sanitize_workspace_id(workspace_id)
        if not valid:
            return None, f"invalid workspace_id: {err}"
        ws = self._load_workspace(workspace_id)
        if ws is None:
            return None, f"workspace not found: {workspace_id}"

        if request.workspace_id != workspace_id:
            return None, "request workspace_id does not match target workspace"

        if ws.state == WorkspaceState.READY:
            pass
        elif ws.state == WorkspaceState.ACTIVE and ws.session_id is None:
            pass
        else:
            return (
                None,
                f"workspace must be READY (or ACTIVE with no session), current state: {ws.state}",
            )

        if ws.state == WorkspaceState.READY:
            ok, err = await self._transition(
                workspace_id,
                WorkspaceState.ACTIVE,
                None,
                WorkspaceLifecycleEventKind.WORKSPACE_ACTIVATED,
                session_id=request.session_id,
            )
            if not ok:
                return None, err

        ws = self._load_workspace(workspace_id)
        if ws is None:
            return None, "workspace lost after assignment"
        ws.session_id = request.session_id
        ws.identity.mission_id = request.mission_id or ws.identity.mission_id
        ws.identity.lane_id = request.lane_id or ws.identity.lane_id
        ws.identity.role = request.agent_role
        ws.context_capsule_digest = request.context_capsule_digest
        ws.harness_profile_digest = request.harness_profile_digest
        ws.runtime_binding_reference = request.runtime_binding_reference
        self._save_workspace(ws)
        self._workspaces[workspace_id] = ws

        receipt = WorkspaceAssignmentReceipt(
            workspace_id=workspace_id,
            mission_id=request.mission_id,
            lane_id=request.lane_id,
            agent_role=request.agent_role,
            assignment_state=self._derive_assignment_state(ws),
            session_id=request.session_id,
            base_sha=ws.base_commit_sha,
            branch_name=ws.branch_name,
            context_capsule_digest=request.context_capsule_digest,
            harness_profile_digest=request.harness_profile_digest,
            runtime_binding_reference=request.runtime_binding_reference,
        )
        return receipt, ""

    async def detach_session(self, workspace_id: str, reason: str) -> tuple[bool, str]:
        valid, err = self._sanitize_workspace_id(workspace_id)
        if not valid:
            return False, f"invalid workspace_id: {err}"
        ws = self._load_workspace(workspace_id)
        if ws is None:
            return False, f"workspace not found: {workspace_id}"
        if ws.state != WorkspaceState.ACTIVE:
            return (False, f"workspace must be in ACTIVE state, current: {ws.state}")

        has_changes = False
        if ws.worktree_path and Path(ws.worktree_path).exists():
            has_changes = self._git_has_uncommitted_changes(ws.worktree_path)

        if has_changes:
            ok, err = await self._transition(
                workspace_id,
                WorkspaceState.ACTIVE,
                RecoveryState.SESSION_DETACHED,
                WorkspaceLifecycleEventKind.SESSION_DETACHED,
                reason=reason,
            )
            return ok, err

        ws.session_id = None
        self._save_workspace(ws)
        self._workspaces[workspace_id] = ws
        event = WorkspaceLifecycleEvent(
            workspace_id=workspace_id,
            event_kind=WorkspaceLifecycleEventKind.SESSION_DETACHED,
            state_before=WorkspaceState.ACTIVE,
            state_after=WorkspaceState.ACTIVE,
            session_id=None,
            worktree_path=ws.worktree_path,
            reason=f"session detached (no work preserved): {reason}",
        )
        self._ledger.append(event)
        return True, ""

    async def reattach_session(
        self, workspace_id: str, new_session_id: str
    ) -> tuple[WorkspaceAssignmentReceipt | None, str]:
        valid, err = self._sanitize_workspace_id(workspace_id)
        if not valid:
            return None, f"invalid workspace_id: {err}"
        ws = self._load_workspace(workspace_id)
        if ws is None:
            return None, f"workspace not found: {workspace_id}"
        if ws.recovery_state not in {
            RecoveryState.SESSION_DETACHED,
            RecoveryState.RECOVERY_REQUIRED,
        }:
            return (
                None,
                f"workspace must be DETACHED_WITH_WORK_PRESERVED or RECOVERY_REQUIRED, "
                f"current recovery: {ws.recovery_state}",
            )
        if ws.worktree_path and not Path(ws.worktree_path).exists():
            return None, f"worktree path no longer exists: {ws.worktree_path}"

        ok, err = await self.recover(workspace_id, new_session_id)
        if not ok:
            return None, f"reattach recovery failed: {err}"

        ws = self._load_workspace(workspace_id)
        if ws is None:
            return None, "workspace lost after reattach"
        receipt = WorkspaceAssignmentReceipt(
            workspace_id=workspace_id,
            mission_id=ws.identity.mission_id,
            lane_id=ws.identity.lane_id,
            agent_role=ws.identity.role,
            assignment_state=self._derive_assignment_state(ws),
            session_id=new_session_id,
            base_sha=ws.base_commit_sha,
            branch_name=ws.branch_name,
            context_capsule_digest=ws.context_capsule_digest,
            harness_profile_digest=ws.harness_profile_digest,
            runtime_binding_reference=ws.runtime_binding_reference,
        )
        return receipt, ""

    async def get_current_assignment(
        self, workspace_id: str
    ) -> CurrentAssignmentProjection | None:
        ws = self._workspaces.get(workspace_id) or self._load_workspace(workspace_id)
        if ws is None:
            return None
        assignment_state = self._derive_assignment_state(ws)
        blocked_reason: str | None = None
        match assignment_state:
            case AssignmentState.BLOCKED_MISSING_CONTEXT_RELEASE:
                blocked_reason = f"workspace state {ws.state} prevents assignment"
            case _:
                pass
        return CurrentAssignmentProjection(
            workspace_id=workspace_id,
            assignment_state=assignment_state,
            agent_role=ws.identity.role.value,
            session_id=ws.session_id,
            context_available=ws.context_capsule_digest is not None,
            profile_available=ws.harness_profile_digest is not None,
            runtime_available=ws.runtime_binding_reference is not None,
            blocked_reason=blocked_reason,
        )

    async def release_assignment(self, workspace_id: str) -> tuple[bool, str]:
        valid, err = self._sanitize_workspace_id(workspace_id)
        if not valid:
            return False, f"invalid workspace_id: {err}"
        ws = self._load_workspace(workspace_id)
        if ws is None:
            return False, f"workspace not found: {workspace_id}"
        if ws.state != WorkspaceState.ACTIVE:
            return (False, f"workspace must be in ACTIVE state, current: {ws.state}")
        ok, err = await self._transition(
            workspace_id,
            WorkspaceState.RELEASED_FOR_INTEGRATION,
            None,
            WorkspaceLifecycleEventKind.RELEASED_FOR_INTEGRATION,
        )
        if not ok:
            return False, err
        ws = self._load_workspace(workspace_id)
        if ws is None:
            return False, "workspace lost after release"
        ws.session_id = None
        self._save_workspace(ws)
        self._workspaces[workspace_id] = ws
        return True, ""

    async def _transition(
        self,
        workspace_id: str,
        new_state: WorkspaceState,
        recovery_state: RecoveryState | None,
        event_kind: WorkspaceLifecycleEventKind,
        **kwargs: object,
    ) -> tuple[bool, str]:
        ws = self._workspaces.get(workspace_id)
        if ws is None:
            ws = self._load_workspace(workspace_id)
        if ws is None:
            return False, f"workspace not found: {workspace_id}"
        current = (ws.state, ws.recovery_state)
        if (
            _is_terminal(ws.state, ws.recovery_state)
            and recovery_state != RecoveryState.QUARANTINED
        ):
            return (
                False,
                f"workspace is in terminal state: state={ws.state}, recovery={ws.recovery_state}",
            )
        target = (new_state, recovery_state)
        state_changed = target != current
        if state_changed:
            allowed = _VALID_TRANSITIONS.get(current, set())
            if target not in allowed:
                return False, f"invalid transition from {current} to {target}"
        state_before = ws.state
        recovery_before = ws.recovery_state
        if state_changed:
            ws.state = new_state
            ws.recovery_state = recovery_state
            ws.updated_at = datetime.now(UTC).isoformat()
            self._workspaces[ws.identity.workspace_id] = ws
            try:
                self._save_workspace(ws)
            except Exception as exc:
                ws.state = state_before
                ws.recovery_state = recovery_before
                return (False, f"failed to persist workspace state: {exc}")
        event = WorkspaceLifecycleEvent(
            workspace_id=workspace_id,
            event_kind=event_kind,
            state_before=state_before,
            state_after=new_state,
            recovery_before=recovery_before,
            recovery_after=recovery_state,
            worktree_path=(str(ws.worktree_path) if ws.worktree_path else None),
            branch_name=ws.branch_name,
            base_commit_sha=ws.base_commit_sha,
            head_sha=ws.head_sha,
            session_id=ws.session_id,
            changed_files_count=ws.changed_files_count,
            checkpoint_sha=ws.checkpoint_sha,
        )
        reason = kwargs.pop("reason", None)
        if reason is not None and isinstance(reason, str):
            event.reason = reason
        for key in (
            "worktree_path",
            "branch_name",
            "checkpoint_sha",
            "session_id",
            "base_commit_sha",
            "head_sha",
            "changed_files_count",
        ):
            if key in kwargs:
                setattr(event, key, kwargs[key])
        try:
            self._ledger.append(event)
        except Exception as exc:
            if state_changed:
                ws.state = state_before
                ws.recovery_state = recovery_before
                try:
                    self._save_workspace(ws)
                except Exception as save_err:
                    logger.error(
                        "Critical: rollback save failed for workspace %s: %s",
                        workspace_id,
                        save_err,
                    )
                    return (
                        False,
                        f"failed to roll back workspace state after ledger failure — manual inspection required for {workspace_id}",
                    )
            return (
                False,
                f"failed to record lifecycle event — state rolled back: {exc}",
            )
        return True, ""

    def _build_branch_name(self, identity: WorkspaceIdentity) -> str:
        prefix = self._config.branch_prefix
        role = identity.role.value
        wsid_short = identity.workspace_id[:8]
        return f"{prefix}/{role}/{wsid_short}"

    def _load_workspace(self, workspace_id: str) -> ManagedWorkspace | None:
        path = self._store_path / f"{workspace_id}.json"
        if not path.exists():
            return None
        try:
            return ManagedWorkspace.model_validate_json(
                path.read_text(encoding="utf-8")
            )
        except Exception:
            return None

    def _save_workspace(self, workspace: ManagedWorkspace) -> None:
        path = self._store_path / f"{workspace.identity.workspace_id}.json"
        tmp_path = path.with_suffix(".json.tmp")
        text = workspace.model_dump_json(indent=None)
        tmp_path.write_text(text, encoding="utf-8")
        os.replace(str(tmp_path), str(path))

    def _get_head(self, ws: ManagedWorkspace) -> str | None:
        if not ws.worktree_path:
            try:
                proc = subprocess.run(
                    ["git", "rev-parse", "HEAD"],
                    capture_output=True,
                    text=True,
                    cwd=str(self.repo_root),
                    stdin=subprocess.DEVNULL,
                    timeout=_GIT_TIMEOUT,
                )
                if proc.returncode == 0:
                    sha = proc.stdout.strip()
                    if len(sha) == _SHA_HEX_LENGTH:
                        return sha
            except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
                pass
            return None
        worktree_path = Path(ws.worktree_path)
        if not worktree_path.exists():
            return None
        try:
            proc = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                cwd=str(worktree_path),
                stdin=subprocess.DEVNULL,
                timeout=_GIT_TIMEOUT,
            )
            if proc.returncode == 0:
                sha = proc.stdout.strip()
                if len(sha) == _SHA_HEX_LENGTH:
                    return sha
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            pass
        return None

    def _sanitize_workspace_id(self, workspace_id: str) -> tuple[bool, str]:
        if not workspace_id or not workspace_id.strip():
            return (False, "empty workspace_id")
        if len(workspace_id) > _MAX_WORKSPACE_ID_LENGTH:
            return (False, "workspace_id too long")
        if any(c in workspace_id for c in ("/", "\\", "..", "~")):
            return (False, "workspace_id contains traversal characters")
        if not all(c.isalnum() or c in "-_" for c in workspace_id):
            return (False, "workspace_id contains invalid characters")
        return (True, "")

    @staticmethod
    def _is_primary_worktree(worktree_path: Path) -> bool:
        git_dir = worktree_path / ".git"
        try:
            return git_dir.resolve().is_dir()
        except OSError:
            return False


__all__ = ["ManagedWorkspaceService", "WorktreeProvider"]
