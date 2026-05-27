from __future__ import annotations

from datetime import UTC, datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import threading
from typing import Protocol

from rig_relay.workspace._config import WorkspaceConfig
from rig_relay.workspace.models import (
    FleetWorkspaceProjection,
    FleetWorkspaceProjectionItem,
    ManagedWorkspace,
    RecoveryState,
    WorkspaceIdentity,
    WorkspaceLifecycleEvent,
    WorkspaceLifecycleEventKind,
    WorkspaceState,
)

_GIT_TIMEOUT = 30.0
_SHA_HEX_LENGTH = 40

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

_add(
    WorkspaceState.ACTIVE,
    RecoveryState.SESSION_DETACHED,
    WorkspaceState.ACTIVE,
    RecoveryState.RECOVERED,
)
_add(WorkspaceState.ACTIVE, RecoveryState.RECOVERED, WorkspaceState.ACTIVE, None)
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
    WorkspaceState.ACTIVE: ["validate", "checkpoint", "record_changes", "release"],
    WorkspaceState.VALIDATING: ["under_review", "back_to_active"],
    WorkspaceState.UNDER_REVIEW: ["checkpoint", "back_to_active"],
    WorkspaceState.CHECKPOINTED: ["release_for_integration", "back_to_active"],
    WorkspaceState.RELEASED_FOR_INTEGRATION: ["integrate"],
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
        self._lock_mutex = threading.Lock()
        self._event_lock_path = self._events_path.with_suffix(".jsonl.lock")
        self._event_lock_path.touch(exist_ok=True)
        self._event_lock_fd = os.open(
            str(self._event_lock_path), os.O_RDWR | os.O_CREAT, 0o644
        )
        self._load_all()

    def _acquire_event_lock(self) -> None:
        self._lock_mutex.acquire()
        fcntl.flock(self._event_lock_fd, fcntl.LOCK_EX)

    def _release_event_lock(self) -> None:
        fcntl.flock(self._event_lock_fd, fcntl.LOCK_UN)
        self._lock_mutex.release()

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
            WorkspaceState.RESERVED,
            None,
            WorkspaceLifecycleEventKind.WORKSPACE_RESERVED,
        )
        if not ok:
            return None, err
        ws = self._workspaces.get(ws.identity.workspace_id)
        return ws, ""

    async def create_worktree(self, workspace_id: str) -> tuple[bool, str]:
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
            return False, f"git worktree add failed: {exc}"
        if proc.returncode != 0:
            err_msg = proc.stderr.strip() or "unknown error"
            ok, _ = await self._transition(
                workspace_id,
                WorkspaceState.RETIRED,
                RecoveryState.RESERVATION_REFUSED,
                WorkspaceLifecycleEventKind.RESERVATION_REFUSED,
                reason=f"git worktree add failed: {err_msg}",
            )
            return False, f"git worktree add failed: {err_msg}"
        ws.worktree_path = str(worktree_path)
        ws.branch_name = branch_name
        ws.managed_branch_name = branch_name
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
        return True, ""

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

    async def retire(self, workspace_id: str, force: bool = False) -> tuple[bool, str]:
        ws = self._load_workspace(workspace_id)
        if ws is None:
            return False, f"workspace not found: {workspace_id}"
        if ws.state == WorkspaceState.RETIRED:
            return False, "workspace already retired"
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
        ws = self._load_workspace(workspace_id)
        if ws is None:
            return False, f"workspace not found: {workspace_id}"
        rec = ws.recovery_state
        if rec is None:
            return False, "workspace is not in a recovery state"
        if rec in _TERMINAL_RECOVERY:
            return False, f"workspace recovery state is terminal: {rec}"
        if ws.worktree_path and not Path(ws.worktree_path).exists():
            return False, f"worktree path does not exist: {ws.worktree_path}"
        head_sha = self._get_head(ws)
        if head_sha:
            ws.head_sha = head_sha
        ws.session_id = session_id
        self._save_workspace(ws)
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
        return ok, err

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
        refusal_reason: str | None = None
        if self._is_primary_worktree(worktree_path):
            refusal_reason = "cannot remove primary worktree"
        elif worktree_path.exists():
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
        items: list[FleetWorkspaceProjectionItem] = []
        for ws in self._workspaces.values():
            recovery_required = (
                ws.recovery_state is not None
                and ws.recovery_state in _RECOVERY_REQUIRED_RECOVERY
            )
            checkpoint_state = "present" if ws.checkpoint_sha else "absent"
            claim_state = "none"
            item = FleetWorkspaceProjectionItem(
                workspace_id=ws.identity.workspace_id,
                project_identity=ws.identity.project_identity,
                role=ws.identity.role,
                branch_summary=ws.branch_name,
                lifecycle_status=ws.state,
                recovery_required=recovery_required,
                changed_files_count=ws.changed_files_count,
                checkpoint_state=checkpoint_state,
                claim_state=claim_state,
                safe_available_actions=_actions_for_workspace(ws),
                base_sha=(ws.base_commit_sha[:8] if ws.base_commit_sha else None),
                head_sha=(ws.head_sha[:8] if ws.head_sha else None),
            )
            items.append(item)
        return FleetWorkspaceProjection(workspaces=items)

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
        allowed = _VALID_TRANSITIONS.get(current, set())
        if target not in allowed:
            return False, f"invalid transition from {current} to {target}"
        state_before = ws.state
        recovery_before = ws.recovery_state
        ws.state = new_state
        ws.recovery_state = recovery_state
        ws.updated_at = datetime.now(UTC).isoformat()
        self._workspaces[ws.identity.workspace_id] = ws
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
        digest = self._compute_event_digest(event)
        event.event_digest = digest
        self._record_event(event)
        self._save_workspace(ws)
        return True, ""

    def _record_event(self, event: WorkspaceLifecycleEvent) -> str:
        self._acquire_event_lock()
        try:
            line = event.model_dump_json() + "\n"
            with open(self._events_path, "a", encoding="utf-8") as f:
                f.write(line)
                f.flush()
                os.fsync(f.fileno())
            return event.event_id
        except OSError:
            return ""
        finally:
            self._release_event_lock()

    def _build_branch_name(self, identity: WorkspaceIdentity) -> str:
        prefix = self._config.branch_prefix
        role = identity.role.value
        wsid_short = identity.workspace_id[:8]
        return f"{prefix}/{role}/{wsid_short}"

    def _compute_event_digest(self, event: WorkspaceLifecycleEvent) -> str:
        payload = event.model_dump(exclude={"event_digest", "prior_event_digest"})
        payload["event_digest"] = ""
        payload["prior_event_digest"] = None
        payload_data = json.dumps(
            payload, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return "sha256:" + hashlib.sha256(payload_data).hexdigest()

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

    @staticmethod
    def _is_primary_worktree(worktree_path: Path) -> bool:
        git_dir = worktree_path / ".git"
        try:
            return git_dir.resolve().is_dir()
        except OSError:
            return False


__all__ = ["ManagedWorkspaceService", "WorktreeProvider"]
