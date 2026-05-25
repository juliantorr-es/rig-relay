"""Repository registration — durable app-owned repository records.

Slice 1B: Durable Registration and Workspace Planning.
Creates app-owned state under Application Support. Zero writes to the user repository.
Registration is idempotent; workspace planning produces only a plan.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import TYPE_CHECKING
import uuid

from rig_relay.digestion.app_paths import RigApplicationPaths
from rig_relay.digestion.identity import (
    is_github_backed,
    resolve_git_common_dir,
    resolve_git_worktree_root,
)
from rig_relay.digestion.intake import IntakeResult
from rig_relay.digestion.models import LocalRepositoryOperatingPicture

if TYPE_CHECKING:
    from rig_relay.digestion.registration_models import (
        RegisteredRepository,
        SourceCheckoutRecord,
        WorkspacePreparationPlan,
    )


class RepositoryRegistrationService:
    """Durable repository registration and workspace planning.

    All state is stored under RigApplicationPaths, never in the user repository.
    Registration is idempotent. Workspace planning produces only a plan —
    no workspace is created until Slice 1C.
    """

    def __init__(self, app_paths: RigApplicationPaths) -> None:
        self._app_paths = app_paths

    def register_repository(self, intake_result: IntakeResult) -> RegisteredRepository:
        """Register a repository from a preview intake result.

        Creates a durable RegisteredRepository and SourceCheckoutRecord
        under Application Support. Idempotent — re-registering the same
        recognized checkout returns the existing record.

        Args:
            intake_result: The preview intake result from RepositoryIntakeService.

        Returns:
            The registered repository record.
        """
        from rig_relay.digestion.registration_models import (
            RegisteredRepository,
            SourceCheckoutRecord,
            generate_checkout_id,
            generate_stable_repository_id,
            utc_now_iso,
        )

        repo = intake_result.repository
        picture = intake_result.operating_picture
        identity = picture.identity_candidate

        # Determine repository identity
        github_backed = is_github_backed(repo.remotes)
        remote_digest = identity.remote_identity_digest
        repo_id = generate_stable_repository_id(
            github_backed, remote_digest, identity.worktree_root_digest
        )

        # Check for existing registration
        existing = self._load_repository(repo_id)
        now = utc_now_iso()

        # Checkout identity — path-based matching signal + git common dir
        checkout_id = generate_checkout_id()
        path_digest = identity.worktree_root_digest or _digest_text(str(repo.root_path))
        git_root = resolve_git_worktree_root(Path(repo.root_path))
        common_dir_digest = None
        if git_root is not None:
            common_dir_digest = resolve_git_common_dir(git_root)

        # Check if this exact checkout is already registered (idempotency)
        if existing is not None:
            for checkout_record in self._list_checkouts(repo_id):
                if checkout_record.last_observed_path_digest == path_digest:
                    # Idempotent re-registration — update freshness only
                    checkout_record.last_observed_head_sha = repo.head_sha
                    checkout_record.last_reconciled_at = now
                    self._save_checkout(repo_id, checkout_record)
                    existing.latest_preview_freshness = _freshness_summary(picture)
                    existing.last_updated_at = now
                    self._save_repository(existing)
                    return existing

        # Build checkout record
        checkout = SourceCheckoutRecord(
            checkout_id=checkout_id,
            repository_id=repo_id,
            last_observed_path_digest=path_digest or "",
            git_common_dir_digest=common_dir_digest,
            last_observed_branch=repo.branch,
            last_observed_head_sha=repo.head_sha,
            is_primary_checkout=True,
            registered_at=now,
            last_reconciled_at=now,
            requires_reassociation=False,
        )

        # Derive a human-readable label
        repo_name = Path(repo.root_path).name
        if remote_digest:
            repo_name = f"{repo_name} (GitHub)"

        repository = RegisteredRepository(
            repository_id=repo_id,
            repository_label=repo_name,
            remote_identity_digest=remote_digest,
            is_github_backed=github_backed,
            is_local_only=repo.is_local_only,
            registered_at=now,
            last_updated_at=now,
            latest_preview_freshness=_freshness_summary(picture),
        )

        self._save_repository(repository)
        self._save_checkout(repo_id, checkout)
        return repository

    def plan_workspace(self, intake_result: IntakeResult) -> WorkspacePreparationPlan:
        """Produce a workspace preparation plan. No workspace is created.

        The plan is consumed by Slice 1C which revalidates it before
        provisioning. For Git repos: proposes branch name, base SHA,
        and app-owned worktree location. For non-Git repos: returns
        unsupported_in_current_phase eligibility.

        Args:
            intake_result: The preview intake result.

        Returns:
            A WorkspacePreparationPlan — no files are created, no git commands run.
        """
        from rig_relay.digestion.registration_models import (
            WorkspacePreparationPlan,
            utc_now_iso,
        )

        repo = intake_result.repository
        picture = intake_result.operating_picture

        plan_id = str(uuid.uuid4())
        identity = picture.identity_candidate
        github_backed = is_github_backed(repo.remotes)
        remote_digest = identity.remote_identity_digest
        repo_id = _derive_repo_id_from_candidate(
            github_backed, remote_digest, identity.worktree_root_digest
        )

        now = utc_now_iso()

        # Non-Git repos: unsupported in Phase 1
        if not repo.is_git_repo:
            return WorkspacePreparationPlan(
                plan_id=plan_id,
                repository_id=repo_id,
                checkout_id="",
                provider_eligibility="unsupported_in_current_phase",
                admitted_base_sha=None,
                proposed_managed_branch="",
                proposed_worktree_location="",
                source_checkout_is_dirty=False,
                warnings=[
                    "Governed editing currently requires a Git repository. "
                    "Non-Git managed imports are planned for a later release."
                ],
                generated_at=now,
            )

        # Git-backed repos: propose a managed worktree
        base_sha = repo.head_sha
        if base_sha is None:
            return WorkspacePreparationPlan(
                plan_id=plan_id,
                repository_id=repo_id,
                checkout_id="",
                provider_eligibility="git_worktree_available",
                admitted_base_sha=None,
                proposed_managed_branch="",
                proposed_worktree_location="",
                source_checkout_is_dirty=False,
                warnings=[
                    "No HEAD commit found. Cannot determine base SHA for worktree."
                ],
                generated_at=now,
            )

        short_id = plan_id[:12]
        branch_prefix = "rig-mission"
        proposed_branch = f"{branch_prefix}-{short_id}"
        proposed_location = str(
            self._app_paths.support_root
            / "repositories"
            / repo_id
            / "execution-workspaces"
            / plan_id
            / "checkout"
        )

        ds = picture.dirty_state
        is_dirty = (ds.modified + ds.staged + ds.untracked + ds.deleted) > 0

        warnings: list[str] = []
        if is_dirty:
            warnings.append(
                "The source checkout has uncommitted changes. "
                "These changes will NOT be included in the managed workspace. "
                "The workspace will be created from the committed HEAD state only."
            )
        warnings.append(
            "Creating a managed workspace will perform a Git administrative mutation "
            "(linked worktree + managed branch). This is an explicitly authorized "
            "operation and does not modify source checkout working-tree content."
        )

        # Build the plan digest for cross-slice revalidation
        digest = _digest_text(
            f"{repo_id}:{base_sha}:{proposed_branch}:{proposed_location}"
        )

        return WorkspacePreparationPlan(
            plan_id=plan_id,
            repository_id=repo_id,
            checkout_id="",
            provider_eligibility="git_worktree_available",
            admitted_base_sha=base_sha,
            proposed_managed_branch=proposed_branch,
            proposed_worktree_location=proposed_location,
            branch_prefix=branch_prefix,
            source_checkout_is_dirty=is_dirty,
            warnings=warnings,
            generated_at=now,
            digest=digest,
        )

    # ── Private persistence helpers ──

    def _repository_record_path(self, repo_id: str) -> Path:
        return (
            self._app_paths.support_root
            / "repositories"
            / repo_id
            / "repository-record.json"
        )

    def _checkout_record_path(self, repo_id: str, checkout_id: str) -> Path:
        return (
            self._app_paths.support_root
            / "repositories"
            / repo_id
            / "checkouts"
            / checkout_id
            / "checkout-record.json"
        )

    def _checkouts_dir(self, repo_id: str) -> Path:
        return self._app_paths.support_root / "repositories" / repo_id / "checkouts"

    def _load_repository(self, repo_id: str) -> RegisteredRepository | None:
        from rig_relay.digestion.registration_models import RegisteredRepository

        path = self._repository_record_path(repo_id)
        if not path.is_file():
            return None
        try:
            return RegisteredRepository.model_validate(json.loads(path.read_text()))
        except Exception:
            return None

    def _save_repository(self, record: RegisteredRepository) -> None:
        path = self._repository_record_path(record.repository_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(record.model_dump_json(indent=2))

    def _list_checkouts(self, repo_id: str) -> list[SourceCheckoutRecord]:
        from rig_relay.digestion.registration_models import SourceCheckoutRecord

        checkouts_dir = self._checkouts_dir(repo_id)
        if not checkouts_dir.is_dir():
            return []
        records: list[SourceCheckoutRecord] = []
        for checkout_dir in checkouts_dir.iterdir():
            record_path = checkout_dir / "checkout-record.json"
            if record_path.is_file():
                try:
                    records.append(
                        SourceCheckoutRecord.model_validate(
                            json.loads(record_path.read_text())
                        )
                    )
                except Exception:
                    pass
        return records

    def _save_checkout(self, repo_id: str, record: SourceCheckoutRecord) -> None:
        path = self._checkout_record_path(repo_id, record.checkout_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(record.model_dump_json(indent=2))


def _freshness_summary(picture: LocalRepositoryOperatingPicture) -> dict:
    """Build a lightweight freshness summary from an operating picture."""
    ds = picture.dirty_state
    return {
        "head_sha": picture.repository.head_sha,
        "branch": picture.repository.branch,
        "dirty_total": ds.modified + ds.staged + ds.untracked + ds.deleted,
        "ecosystem_count": len(picture.detected_ecosystems),
        "topology_source_count": sum(1 for t in picture.topology if t.kind == "source"),
        "detected_command_count": len(picture.detected_commands),
        "generated_at": picture.freshness.generated_at,
    }


def _derive_repo_id_from_candidate(
    is_github_backed: bool,
    remote_identity_digest: str | None,
    worktree_root_digest: str | None = None,
) -> str:
    """Derive a repository_id from an identity candidate."""
    from rig_relay.digestion.registration_models import generate_stable_repository_id

    return generate_stable_repository_id(
        is_github_backed, remote_identity_digest, worktree_root_digest
    )


def _digest_text(text: str) -> str:
    """SHA256 hex digest of a text string."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
