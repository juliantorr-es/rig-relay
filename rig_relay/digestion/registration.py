"""Repository registration — durable app-owned repository records.

Slice 1B: Durable Registration and Workspace Planning.
Creates app-owned state under Application Support. Zero writes to the user repository.
Registration is idempotent; workspace planning produces only a plan.
"""

from __future__ import annotations

from dataclasses import dataclass
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
from rig_relay.digestion.registration_models import (
    RegisteredRepository,
    SourceCheckoutRecord,
    WorkspacePreparationPlan,
    generate_checkout_id,
    generate_stable_repository_id,
    utc_now_iso,
)

if TYPE_CHECKING:
    pass


@dataclass(frozen=True)
class RegistrationResult:
    """Result of repository registration — repository and source checkout records."""

    repository: RegisteredRepository
    source_checkout: SourceCheckoutRecord


class RepositoryRegistrationService:
    """Durable repository registration and workspace planning.

    All state is stored under RigApplicationPaths, never in the user repository.
    Registration is idempotent. Workspace planning produces only a plan —
    no workspace is created until Slice 1C.
    """

    def __init__(self, app_paths: RigApplicationPaths) -> None:
        self._app_paths = app_paths

    def register_repository(self, intake_result: IntakeResult) -> RegistrationResult:
        """Register a repository from a preview intake result.

        Creates a durable RegisteredRepository and SourceCheckoutRecord
        under Application Support. Idempotent — re-registering the same
        recognized checkout returns the existing record.

        For GitHub-backed repos: identity is derived from remote digest.
        For local-only repos: correlation signals (path_digest,
        git_common_dir_digest) are used to rediscover existing registrations.
        New UUIDs are generated only when no correlation match is found.

        Args:
            intake_result: The preview intake result from RepositoryIntakeService.

        Returns:
            A RegistrationResult with the repository and source checkout records.
        """
        repo = intake_result.repository
        picture = intake_result.operating_picture
        identity = picture.identity_candidate

        github_backed = is_github_backed(repo.remotes)
        remote_digest = identity.remote_identity_digest

        # Correlation signals for checkout rediscovery
        path_digest = identity.worktree_root_digest or _digest_text(str(repo.root_path))
        git_root = resolve_git_worktree_root(Path(repo.root_path))
        common_dir_digest = resolve_git_common_dir(git_root) if git_root else None

        now = utc_now_iso()
        repo_record: RegisteredRepository | None = None

        # Resolve repository identity
        if github_backed:
            repo_id = generate_stable_repository_id(True, remote_digest)
            repo_record = self._load_repository(repo_id)
            if repo_record is not None:
                # Idempotent: check for matching checkout
                for c in self._list_checkouts(repo_id):
                    if c.last_observed_path_digest == path_digest:
                        c.last_observed_head_sha = repo.head_sha
                        c.last_reconciled_at = now
                        self._save_checkout(repo_id, c)
                        repo_record.latest_preview_freshness = _freshness_summary(
                            picture
                        )
                        repo_record.last_updated_at = now
                        self._save_repository(repo_record)
                        return RegistrationResult(
                            repository=repo_record, source_checkout=c
                        )
        else:
            # Local-only: search by correlation signals for rediscovery
            repo_id = ""  # placeholder
            repo_record = self.find_repository_by_correlation(
                path_digest, common_dir_digest
            )
            if repo_record is not None:
                repo_id = repo_record.repository_id
                # Idempotent: check for matching checkout
                for c in self._list_checkouts(repo_id):
                    if c.last_observed_path_digest == path_digest:
                        c.last_observed_head_sha = repo.head_sha
                        c.last_reconciled_at = now
                        self._save_checkout(repo_id, c)
                        repo_record.latest_preview_freshness = _freshness_summary(
                            picture
                        )
                        repo_record.last_updated_at = now
                        self._save_repository(repo_record)
                        return RegistrationResult(
                            repository=repo_record, source_checkout=c
                        )

        # No existing matching checkout found — create or update records
        if repo_record is None:
            repo_id = (
                generate_stable_repository_id(True, remote_digest)
                if github_backed
                else generate_stable_repository_id(False, None)
            )
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
        else:
            repo_record.latest_preview_freshness = _freshness_summary(picture)
            repo_record.last_updated_at = now
            self._save_repository(repo_record)

        checkout = SourceCheckoutRecord(
            checkout_id=generate_checkout_id(),
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
        self._save_checkout(repo_id, checkout)

        result = self._load_repository(repo_id)
        if result is None:
            raise RuntimeError(
                f"Failed to load repository record for {repo_id} after saving"
            )
        return RegistrationResult(repository=result, source_checkout=checkout)

    def find_repository_by_correlation(
        self, path_digest: str, common_dir_digest: str | None
    ) -> RegisteredRepository | None:
        """Find an existing registered repository by checkout correlation signals.

        Searches all registered repositories for a checkout record matching
        the given path_digest (same checkout by location) or common_dir_digest
        (linked worktree sharing the same Git administrative directory).

        Returns None if no matching checkout is found.
        """
        repos_root = self._app_paths.support_root / "repositories"
        if not repos_root.is_dir():
            return None
        for repo_dir in repos_root.iterdir():
            repo_id = repo_dir.name
            checkouts = self._list_checkouts(repo_id)
            for c in checkouts:
                if c.last_observed_path_digest == path_digest:
                    return self._load_repository(repo_id)
                if common_dir_digest and c.git_common_dir_digest == common_dir_digest:
                    return self._load_repository(repo_id)
        return None

    def plan_workspace(
        self, intake_result: IntakeResult, source_checkout_id: str
    ) -> WorkspacePreparationPlan:
        """Produce a workspace preparation plan bound to registered state.

        The plan is consumed by Slice 1C which revalidates it before
        provisioning. Requires a registered repository and source checkout.
        Returns repository_registration_required if not yet registered.

        Args:
            intake_result: The preview intake result.
            source_checkout_id: Required checkout ID from registration.
                Plan identity is derived exclusively from the registered checkout.

        Returns:
            A WorkspacePreparationPlan — no files are created, no git commands run.
        """
        repo = intake_result.repository
        picture = intake_result.operating_picture
        identity = picture.identity_candidate

        plan_id = str(uuid.uuid4())
        now = utc_now_iso()

        # Non-Git repos: unsupported in Phase 1
        if not repo.is_git_repo:
            return WorkspacePreparationPlan(
                plan_id=plan_id,
                repository_id="",
                checkout_id="",
                provider_eligibility="unsupported_in_current_phase",
                branch_prefix="",
                generated_at=now,
                warnings=[
                    "Governed editing currently requires a Git repository. "
                    "Non-Git managed imports are planned for a later release."
                ],
            )

        # Compute path digest from current intake for staleness check
        path_digest = identity.worktree_root_digest or _digest_text(str(repo.root_path))

        # Load the registered checkout
        checkout_record = self._load_checkout_from_any_repo(source_checkout_id)
        if checkout_record is None:
            return WorkspacePreparationPlan(
                plan_id=plan_id,
                repository_id="",
                checkout_id=source_checkout_id,
                provider_eligibility="repository_registration_required",
                branch_prefix="rig-mission",
                generated_at=now,
                warnings=["Source checkout not found. Register this checkout first."],
            )

        repo_id = checkout_record.repository_id
        repo_record = self._load_repository(repo_id)
        if repo_record is None:
            return WorkspacePreparationPlan(
                plan_id=plan_id,
                repository_id=repo_id,
                checkout_id=source_checkout_id,
                provider_eligibility="repository_registration_required",
                branch_prefix="rig-mission",
                generated_at=now,
                warnings=[
                    "Registered repository not found. Re-register the repository."
                ],
            )

        # Verify path digest match — guard against stale/moved checkouts
        if checkout_record.last_observed_path_digest != path_digest:
            return WorkspacePreparationPlan(
                plan_id=plan_id,
                repository_id=repo_id,
                checkout_id=source_checkout_id,
                provider_eligibility="stale_checkout_reference",
                branch_prefix="rig-mission",
                generated_at=now,
                warnings=[
                    "The current checkout path does not match the registered checkout. "
                    "Re-register this checkout before planning."
                ],
            )

        # Git-backed repos: propose a managed worktree
        base_sha = repo.head_sha
        if base_sha is None:
            return WorkspacePreparationPlan(
                plan_id=plan_id,
                repository_id=repo_id,
                checkout_id=checkout_record.checkout_id,
                provider_eligibility="git_worktree_available",
                admitted_base_sha=None,
                proposed_managed_branch="",
                proposed_worktree_location="",
                branch_prefix="rig-mission",
                source_checkout_is_dirty=False,
                generated_at=now,
                warnings=[
                    "No HEAD commit found. Cannot determine base SHA for worktree."
                ],
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
            "Creating a managed workspace will perform a Git administrative "
            "mutation (linked worktree + managed branch). This is an explicitly "
            "authorized operation and does not modify source checkout "
            "working-tree content."
        )

        digest = _digest_text(
            f"{repo_id}:{checkout_record.checkout_id}:{base_sha}:{proposed_branch}:{proposed_location}"
        )

        return WorkspacePreparationPlan(
            plan_id=plan_id,
            repository_id=repo_id,
            checkout_id=checkout_record.checkout_id,
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
        path = self._repository_record_path(repo_id)
        if not path.is_file():
            return None
        try:
            return RegisteredRepository.model_validate(json.loads(path.read_text()))
        except Exception:
            return None

    def _load_checkout(
        self, repo_id: str, checkout_id: str
    ) -> SourceCheckoutRecord | None:
        """Load a single checkout record by ID.

        Returns None if the record does not exist or cannot be parsed.
        """
        path = self._checkout_record_path(repo_id, checkout_id)
        if not path.is_file():
            return None
        try:
            return SourceCheckoutRecord.model_validate(json.loads(path.read_text()))
        except Exception:
            return None

    def _load_checkout_from_any_repo(
        self, checkout_id: str
    ) -> SourceCheckoutRecord | None:
        """Load a checkout record from any repository directory."""
        repos_root = self._app_paths.support_root / "repositories"
        if not repos_root.is_dir():
            return None
        for repo_dir in repos_root.iterdir():
            record = self._load_checkout(repo_dir.name, checkout_id)
            if record is not None:
                return record
        return None

    def _save_repository(self, record: RegisteredRepository) -> None:
        path = self._repository_record_path(record.repository_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(record.model_dump_json(indent=2))

    def _list_checkouts(self, repo_id: str) -> list[SourceCheckoutRecord]:
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


def _digest_text(text: str) -> str:
    """SHA256 hex digest of a text string."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
