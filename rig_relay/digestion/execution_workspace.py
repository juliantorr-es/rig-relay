"""Execution workspace provisioning — isolated workspace creation.

Slice 1C: Managed Worktree Provisioning and Mission Admission.
GitWorktreeExecutionWorkspaceProvider creates managed worktrees from
explicitly admitted plans. Hook inspection gates provisioning before
any Git mutation occurs.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
import hashlib
import json
import os
from pathlib import Path
import subprocess
import uuid

from rig_relay.digestion.execution_models import (
    CleanupResult,
    ExecutionWorkspace,
    ForceCleanupAuthorization,
    ProvisioningInput,
    ProvisioningStatus,
    WorkspaceCleanupDisposition,
    WorkspaceProviderType,
    WorkspaceState,
)


class ExecutionWorkspaceProvider(ABC):
    """Abstract interface for creating isolated execution workspaces.

    One concrete implementation: GitWorktreeExecutionWorkspaceProvider.
    Deferred: ImportedCopyExecutionWorkspaceProvider, NonGitSandboxExecutionWorkspaceProvider.
    Domain vocabulary says "execution workspace" everywhere outside the implementation.
    """

    @abstractmethod
    def provision(self, input_: ProvisioningInput) -> ExecutionWorkspace:
        """Provision an isolated execution workspace."""
        ...

    @abstractmethod
    def inspect(self, workspace: ExecutionWorkspace) -> WorkspaceState:
        """Inspect the current state of an execution workspace."""
        ...

    @abstractmethod
    def cleanup(
        self,
        workspace: ExecutionWorkspace,
        disposition: str,
        force_authorization: ForceCleanupAuthorization | None = None,
    ) -> CleanupResult:
        """Clean up an execution workspace.

        Normal runtime path must NOT use force_authorization.
        Dirty workspaces must be retained, not silently removed.
        """
        ...


class GitWorktreeExecutionWorkspaceProvider(ExecutionWorkspaceProvider):
    """Creates managed Git worktrees from admitted plans.

    Provisioning lifecycle:
    1. Revalidate plan digest against admitted inputs.
    2. Re-observe source checkout through read-only Git boundary.
    3. Refuse if path digest, Git common-directory digest, or HEAD SHA
       no longer match the admitted plan and checkout record.
    4. Inspect hook configuration before git worktree add.
    5. Refuse if executable post-checkout hook exists.
    6. Refuse if branch or path collision detected.
    7. Create managed worktree from exact admitted base SHA.
    8. Persist execution workspace record.
    """

    def __init__(self, app_support_root: Path, cache_root: Path | None = None) -> None:
        self._support_root = app_support_root
        self._cache_root = cache_root or app_support_root

    def provision(self, input_: ProvisioningInput) -> ExecutionWorkspace:
        """Provision a managed worktree from an admitted plan."""
        workspace_id = str(uuid.uuid4())
        now = _utc_now_iso()

        # 1. Validate plan digest
        expected_digest = input_.plan_digest
        actual_digest = _compute_provisioning_digest(input_)
        if expected_digest and expected_digest != actual_digest:
            return _refused(
                workspace_id,
                input_,
                ProvisioningStatus.STALE_PLAN_DIGEST,
                "Plan digest mismatch. Re-plan before provisioning.",
            )

        source_path = Path(input_.source_checkout_path).resolve()

        # 2. Re-observe source checkout
        source_head = _git_readonly(source_path, "rev-parse", "HEAD")
        source_common_dir_raw = _resolve_git_common_dir(source_path)

        # 3. Path digest match (caller verifies against registered checkout record)

        # 3a. Git common-directory replaced check
        # Even if path is the same, the underlying git repository may have been replaced
        plan_common_dir_digest = _compute_common_dir_digest_from_plan(input_)
        if plan_common_dir_digest and source_common_dir_raw:
            current_common_dir = _digest_common_dir_content(source_common_dir_raw)
            if current_common_dir != plan_common_dir_digest:
                return _refused(
                    workspace_id,
                    input_,
                    ProvisioningStatus.STALE_CHECKOUT_GIT_REPOSITORY_CHANGED,
                    "Path matches but Git repository has been replaced. "
                    "Re-preview and re-plan before provisioning.",
                )

        # 3b. HEAD staleness
        if source_head != input_.admitted_base_sha:
            return _refused(
                workspace_id,
                input_,
                ProvisioningStatus.STALE_HEAD,
                f"Source HEAD changed. Admitted: {input_.admitted_base_sha[:12]}, "
                f"Current: {source_head[:12] if source_head else 'N/A'}. "
                "Re-digest and re-plan before provisioning.",
            )

        # 4. Hook inspection
        hook_check = _inspect_hooks(source_path)
        if hook_check is not None:
            return _refused(
                workspace_id,
                input_,
                ProvisioningStatus.HOOK_AUTHORIZATION_REQUIRED,
                f"Executable post-checkout hook detected: {hook_check}. "
                "Hook authorization is required before provisioning.",
            )

        # 5. Branch collision
        if _branch_exists(source_path, input_.proposed_managed_branch):
            return _refused(
                workspace_id,
                input_,
                ProvisioningStatus.BRANCH_COLLISION,
                f"Branch '{input_.proposed_managed_branch}' already exists. "
                "Choose a different branch or clean up the existing one.",
            )

        # 6. Path collision
        proposed_path = Path(input_.proposed_worktree_location)
        if proposed_path.exists():
            return _refused(
                workspace_id,
                input_,
                ProvisioningStatus.WORKSPACE_PATH_CONFLICT,
                f"Worktree path already exists: {proposed_path}. "
                "Clean up or choose a different location.",
            )

        # 7. Create managed worktree
        try:
            _git_admin(
                source_path,
                "worktree",
                "add",
                "-b",
                input_.proposed_managed_branch,
                str(proposed_path),
                input_.admitted_base_sha,
            )
        except subprocess.CalledProcessError as e:
            return _refused(
                workspace_id,
                input_,
                ProvisioningStatus.REFUSED,
                f"Worktree creation failed: {e.stderr if hasattr(e, 'stderr') else e}",
            )

        # 8. Inspect and persist workspace record
        worktree_head = _git_readonly(proposed_path, "rev-parse", "HEAD")
        clean_digest = _compute_workspace_clean_digest(proposed_path)

        workspace = ExecutionWorkspace(
            workspace_id=workspace_id,
            repository_id=input_.repository_id,
            source_checkout_id=input_.source_checkout_id,
            provider_type=WorkspaceProviderType.GIT_WORKTREE,
            managed_root_path=str(proposed_path),
            managed_branch=input_.proposed_managed_branch,
            base_commit_sha=worktree_head or input_.admitted_base_sha,
            created_at=now,
            initial_clean_state_digest=clean_digest,
            cleanup_disposition=WorkspaceCleanupDisposition.ACTIVE,
        )

        _persist_workspace_record(self._support_root, workspace)
        return workspace

    def inspect(self, workspace: ExecutionWorkspace) -> WorkspaceState:
        """Inspect the current state of an execution workspace."""
        ws_path = Path(workspace.managed_root_path)
        exists = ws_path.is_dir()
        if not exists:
            return WorkspaceState(
                workspace_id=workspace.workspace_id,
                exists=False,
                cleanup_disposition=workspace.cleanup_disposition,
            )

        branch = _git_readonly(ws_path, "rev-parse", "--abbrev-ref", "HEAD")
        head = _git_readonly(ws_path, "rev-parse", "HEAD")
        porcelain = _git_readonly(ws_path, "status", "--porcelain=v2", "--branch")
        dirty_count = _count_dirty_from_porcelain(porcelain)

        return WorkspaceState(
            workspace_id=workspace.workspace_id,
            exists=True,
            is_dirty=dirty_count > 0,
            branch=branch or None,
            head_sha=head or None,
            uncommitted_file_count=dirty_count,
            checkpoint_count=0,
            cleanup_disposition=workspace.cleanup_disposition,
        )

    def cleanup(
        self,
        workspace: ExecutionWorkspace,
        disposition: str,
        force_authorization: ForceCleanupAuthorization | None = None,
    ) -> CleanupResult:
        """Clean up a managed worktree.

        Normal path: force_authorization=None. Dirty workspaces are retained.
        Force removal only with valid ForceCleanupAuthorization.
        """
        ws_path = Path(workspace.managed_root_path)

        if not ws_path.exists():
            return CleanupResult(
                workspace_id=workspace.workspace_id,
                status="removed",
                reason="Workspace path no longer exists.",
                force_used=False,
            )

        state = self.inspect(workspace)
        if state.is_dirty and force_authorization is None:
            return CleanupResult(
                workspace_id=workspace.workspace_id,
                status="retained",
                reason="Workspace has uncommitted changes. Use explicit cleanup with force "
                "only after reviewing uncommitted output.",
                force_used=False,
            )

        use_force = False
        if force_authorization is not None:
            # Validate authorization
            if force_authorization.execution_workspace_id != workspace.workspace_id:
                return CleanupResult(
                    workspace_id=workspace.workspace_id,
                    status="retained",
                    reason="Force cleanup authorization does not match this workspace.",
                    force_used=False,
                )

            if force_authorization.disposition != "user_approved_cleanup":
                return CleanupResult(
                    workspace_id=workspace.workspace_id,
                    status="retained",
                    reason="Force cleanup authorization has invalid disposition.",
                    force_used=False,
                )

            current_digest = _compute_workspace_dirty_state_digest(ws_path)
            if force_authorization.dirty_state_digest != current_digest:
                return CleanupResult(
                    workspace_id=workspace.workspace_id,
                    status="retained",
                    reason="Workspace dirty state changed since authorization. "
                    "Re-authorize before force cleanup.",
                    force_used=False,
                )

            # Validate persistence
            persisted = _load_force_cleanup_auth(
                self._support_root, force_authorization
            )
            if persisted is None:
                return CleanupResult(
                    workspace_id=workspace.workspace_id,
                    status="retained",
                    reason="Force cleanup authorization not found in app storage. "
                    "Persist authorization before cleanup.",
                    force_used=False,
                )

            use_force = True

        try:
            # git worktree remove refuses when cwd is the worktree itself.
            # Resolve the main repository root from the worktree's .git metadata.
            main_repo = _resolve_main_repo_from_worktree(ws_path) or ws_path.parent
            args: list[str] = ["worktree", "remove"]
            if use_force:
                args.append("--force")
            args.append(str(ws_path))
            _git_admin(main_repo, *args)
            return CleanupResult(
                workspace_id=workspace.workspace_id,
                status="removed",
                reason="Worktree and managed branch removed.",
                force_used=use_force,
            )
        except subprocess.CalledProcessError as e:
            return CleanupResult(
                workspace_id=workspace.workspace_id,
                status="retained",
                reason=f"Cleanup failed: {e}",
                force_used=use_force,
            )


# ── Helpers ──────────────────────────────────────────────────────


def _git_readonly(cwd: Path, *args: str) -> str:
    """Run a read-only git observation with --no-optional-locks."""
    try:
        return subprocess.check_output(
            ["git", "--no-optional-locks", *args],
            text=True,
            stderr=subprocess.PIPE,
            cwd=cwd,
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return ""


def _git_admin(cwd: Path, *args: str) -> None:
    """Run an explicitly authorized git administrative mutation."""
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def _resolve_git_common_dir(path: Path) -> str:
    """Resolve the Git common directory path. Returns empty string on failure."""
    try:
        raw = _git_readonly(path, "rev-parse", "--git-common-dir")
        if not raw:
            return ""
        return str((path / raw).resolve())
    except Exception:
        return ""


def _branch_exists(repo_root: Path, branch: str) -> bool:
    """Check whether a branch exists in the repository."""
    result = _git_readonly(repo_root, "branch", "--list", branch)
    return bool(result)


# ── Deferred risk: hook TOCTOU ──
# There is a time-of-check/time-of-use gap: a hook can appear or
# effective hook configuration can change after inspection but before
# git worktree add executes. This is acceptable for Phase 1 single-user
# local environments. Before public release, provisioning needs an
# execution mechanism that cannot run an unadmitted hook even if the
# repository changes between inspection and mutation.


def _inspect_hooks(repo_root: Path) -> str | None:
    """Inspect effective hook configuration for executable post-checkout hooks.

    Returns the path to the executable hook if found, None otherwise.
    """
    # Check core.hooksPath
    hooks_path = _git_readonly(repo_root, "config", "--get", "core.hooksPath")
    if hooks_path:
        hook_file = Path(hooks_path) / "post-checkout"
    else:
        hook_file = repo_root / ".git" / "hooks" / "post-checkout"

    if hook_file.is_file() and os.access(hook_file, os.X_OK):
        return str(hook_file)
    return None


def _resolve_main_repo_from_worktree(worktree_path: Path) -> Path | None:
    """Resolve the main repository root from a worktree's .git metadata.

    A worktree's .git file contains a line like:
        gitdir: /path/to/main/.git/worktrees/<name>
    The main repository root is three levels up from that path.
    Returns None if resolution fails.
    """
    git_file = worktree_path / ".git"
    if not git_file.is_file():
        return None
    try:
        content = git_file.read_text().strip()
        if not content.startswith("gitdir: "):
            return None
        gitdir_path = Path(content[8:].strip())
    except Exception:
        return None
    # gitdir_path is like /path/to/main/.git/worktrees/<name>
    # Go up 3 levels: worktrees/<name> → .git → main repo root
    return gitdir_path.parent.parent.parent


def _compute_provisioning_digest(input_: ProvisioningInput) -> str:
    """Recompute the plan digest from input fields for validation."""
    parts = [
        input_.repository_id,
        input_.source_checkout_id,
        input_.admitted_base_sha,
        input_.proposed_managed_branch,
        input_.proposed_worktree_location,
    ]
    return hashlib.sha256(":".join(parts).encode()).hexdigest()


def _compute_common_dir_digest_from_plan(input_: ProvisioningInput) -> str | None:
    """Return the admitted git-common-dir digest from the plan input.

    This digest was captured from the registered checkout record
    at plan time. It is compared against the current common-directory
    digest immediately before provisioning to detect repository
    replacement at the same path.
    """
    return input_.admitted_git_common_dir_digest


def _compute_workspace_clean_digest(ws_path: Path) -> str:
    """Compute a digest of the workspace's initial clean state.

    Used for baseline capture at admission time. Hashes HEAD + file list.
    """
    try:
        lst = _git_readonly(ws_path, "ls-files")
        head = _git_readonly(ws_path, "rev-parse", "HEAD")
        return hashlib.sha256(f"{head}:{lst}".encode()).hexdigest()
    except Exception:
        return ""


def _compute_workspace_dirty_state_digest(ws_path: Path) -> str:
    """Compute a digest bound to actual pending dirty output.

    Includes porcelain v2 status AND SHA256 digests of modified/untracked
    file contents. This ensures cleanup authorization binds to the actual
    output being destroyed, not merely file names and HEAD.
    """
    try:
        porcelain = _git_readonly(ws_path, "status", "--porcelain=v2")
        # Collect content digests of dirty files
        file_digests: list[str] = []
        for line in porcelain.splitlines():
            if line.startswith("#") or not line.strip():
                continue
            if line.startswith("?"):
                # Untracked file — path is after the first space
                path = line[2:] if len(line) > 2 else line[1:]
                fp = ws_path / path.strip()
                if fp.is_file():
                    try:
                        file_digests.append(hashlib.sha256(fp.read_bytes()).hexdigest())
                    except OSError:
                        file_digests.append("unreadable")
                continue
            if len(line) >= 4:
                # Regular entry — path is at position 8+ (varies)
                parts = line.split(None, 8)
                if len(parts) >= 9:
                    fp = ws_path / parts[8]
                    if fp.is_file():
                        try:
                            file_digests.append(
                                hashlib.sha256(fp.read_bytes()).hexdigest()
                            )
                        except OSError:
                            file_digests.append("unreadable")
        combined = porcelain + "\n".join(sorted(file_digests))
        return hashlib.sha256(combined.encode()).hexdigest()
    except Exception:
        return ""


_PORCELAIN_V2_MIN_LINE_LENGTH = 4


def _count_dirty_from_porcelain(porcelain: str) -> int:
    """Count dirty entries from porcelain v2 output."""
    count = 0
    for line in porcelain.splitlines():
        if line.startswith("#") or not line.strip():
            continue
        if line.startswith("?"):
            count += 1
            continue
        if len(line) >= _PORCELAIN_V2_MIN_LINE_LENGTH:
            x, y = line[2], line[3]
            if x != "." or y != ".":
                count += 1
    return count


def _digest_path(path: Path) -> str:
    return hashlib.sha256(str(path).encode()).hexdigest()


def _digest_common_dir_content(common_dir_path: str) -> str:
    """Compute a content-based digest of the Git common directory.

    Hashes HEAD, config, and the directory inode to detect
    repository replacement at the same filesystem path.
    A recreated .git directory receives a different inode,
    so destroying and reinitializing produces a different digest.
    Normal commits within the same repo do not change this digest.
    """
    try:
        common = Path(common_dir_path)
        parts: list[str] = []
        # 1. SHA256 of HEAD file
        head_fp = common / "HEAD"
        parts.append(
            hashlib.sha256(head_fp.read_bytes()).hexdigest()
            if head_fp.is_file()
            else "missing"
        )
        # 2. SHA256 of config file
        config_fp = common / "config"
        parts.append(
            hashlib.sha256(config_fp.read_bytes()).hexdigest()
            if config_fp.is_file()
            else "missing"
        )
        # 3. Filesystem inode — stable for the lifetime of this directory,
        #    changes when .git is destroyed and recreated.
        parts.append(str(common.stat().st_ino))
        return hashlib.sha256(":".join(parts).encode()).hexdigest()
    except Exception:
        return ""


def _utc_now_iso() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat()


def _persist_workspace_record(
    support_root: Path, workspace: ExecutionWorkspace
) -> None:
    """Persist the execution workspace record under app-owned storage."""
    record_dir = (
        support_root
        / "repositories"
        / workspace.repository_id
        / "execution-workspaces"
        / workspace.workspace_id
    )
    record_dir.mkdir(parents=True, exist_ok=True)
    (record_dir / "workspace-record.json").write_text(
        workspace.model_dump_json(indent=2)
    )


def _persist_force_cleanup_auth(
    support_root: Path, auth: ForceCleanupAuthorization
) -> None:
    auth_dir = (
        support_root
        / "repositories"
        / auth.execution_workspace_id
        / "cleanup-authorizations"
    )
    auth_dir.mkdir(parents=True, exist_ok=True)
    (auth_dir / f"{auth.authorization_id}.json").write_text(
        auth.model_dump_json(indent=2)
    )


def _load_force_cleanup_auth(
    support_root: Path, auth: ForceCleanupAuthorization
) -> ForceCleanupAuthorization | None:
    auth_path = (
        support_root
        / "repositories"
        / auth.execution_workspace_id
        / "cleanup-authorizations"
        / f"{auth.authorization_id}.json"
    )
    if not auth_path.is_file():
        return None
    try:
        return ForceCleanupAuthorization.model_validate(
            json.loads(auth_path.read_text())
        )
    except Exception:
        return None


def _refused(
    workspace_id: str,
    input_: ProvisioningInput,
    status: ProvisioningStatus,
    reason: str,
) -> ExecutionWorkspace:
    """Return a refused provisioning result."""
    return ExecutionWorkspace(
        workspace_id=workspace_id,
        repository_id=input_.repository_id,
        source_checkout_id=input_.source_checkout_id,
        provider_type=WorkspaceProviderType.GIT_WORKTREE,
        managed_root_path="",
        managed_branch="",
        base_commit_sha=input_.admitted_base_sha,
        created_at="",
        initial_clean_state_digest=f"{status.value}:{reason}",
    )
