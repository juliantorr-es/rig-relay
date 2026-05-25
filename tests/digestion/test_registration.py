"""Registration acceptance tests for Slice 1B.

Slice 1B: Durable Registration and Workspace Planning.
Proves that registration creates only app-owned state and leaves
the user repository untouched.
"""

from __future__ import annotations

from pathlib import Path
import subprocess
import tempfile

import pytest

from rig_relay.digestion.app_paths import RigApplicationPaths
from rig_relay.digestion.intake import IntakeResult, RepositoryIntakeService
from rig_relay.digestion.registration import RepositoryRegistrationService
from rig_relay.digestion.registration_models import generate_stable_repository_id
from tests.digestion.conftest import assert_no_filesystem_mutation, snapshot_dir


@pytest.fixture
def app_paths() -> RigApplicationPaths:
    """Create isolated app paths for testing — never touches real Application Support."""
    support = Path(tempfile.mkdtemp(prefix="rig_test_support_"))
    cache = Path(tempfile.mkdtemp(prefix="rig_test_cache_"))
    return RigApplicationPaths.for_test(support, cache)


@pytest.fixture
def registration_service(
    app_paths: RigApplicationPaths,
) -> RepositoryRegistrationService:
    return RepositoryRegistrationService(app_paths)


def _preview(repo: Path) -> IntakeResult:
    """Run preview intake on a repo."""
    service = RepositoryIntakeService()
    return service.open_local_repository(repo)


# ── Registration tests ───────────────────────────────────────────


def test_registration_creates_app_state_only(
    python_repo: Path,
    registration_service: RepositoryRegistrationService,
    app_paths: RigApplicationPaths,
) -> None:
    """Registration creates app-owned state and leaves the user repo untouched."""
    before = snapshot_dir(python_repo)
    result = _preview(python_repo)
    registered = registration_service.register_repository(result)
    after = snapshot_dir(python_repo)

    assert_no_filesystem_mutation(before, after, "python_repo registration")

    repo_record = (
        app_paths.support_root
        / "repositories"
        / registered.repository_id
        / "repository-record.json"
    )
    assert repo_record.is_file(), f"Repository record not found at {repo_record}"

    assert registered.repository_id is not None


def test_registration_is_idempotent(
    python_repo: Path, registration_service: RepositoryRegistrationService
) -> None:
    """Re-registering the same checkout returns the same repository_id."""
    result = _preview(python_repo)
    first = registration_service.register_repository(result)
    second = registration_service.register_repository(result)

    assert first.repository_id == second.repository_id, (
        f"Expected same repository_id on re-registration. "
        f"Got {first.repository_id} != {second.repository_id}"
    )
    assert second.last_updated_at >= first.registered_at


def test_github_backed_repo_identity_is_stable() -> None:
    """generate_stable_repository_id produces stable output for same digest."""
    digest = "abc123def456"
    first = generate_stable_repository_id(True, digest)
    second = generate_stable_repository_id(True, digest)

    assert first == second, (
        "GitHub-backed identity must be stable for same remote digest"
    )
    assert len(first) == 64, "Expected SHA256 hex digest (64 chars)"


def test_local_only_repo_gets_uuid(
    python_repo: Path, registration_service: RepositoryRegistrationService
) -> None:
    """Local-only repos get app-assigned UUID."""
    result = _preview(python_repo)
    registered = registration_service.register_repository(result)

    assert len(registered.repository_id) >= 32, "Expected UUID-length repository_id"


def test_head_change_does_not_change_identity(
    python_repo: Path, registration_service: RepositoryRegistrationService
) -> None:
    """HEAD changes update freshness but not repository identity."""
    result = _preview(python_repo)
    registered = registration_service.register_repository(result)

    (python_repo / "new_file.txt").write_text("new content\n")
    subprocess.run(
        ["git", "--no-optional-locks", "add", "new_file.txt"],
        cwd=python_repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "--no-optional-locks", "commit", "-m", "second commit"],
        cwd=python_repo,
        check=True,
        capture_output=True,
    )

    result2 = _preview(python_repo)
    registered2 = registration_service.register_repository(result2)

    assert registered.repository_id == registered2.repository_id, (
        "Repository identity must not change when HEAD changes"
    )
    assert (registered2.latest_preview_freshness) is not None, (
        "latest_preview_freshness must be set after re-registration"
    )
    assert (registered.latest_preview_freshness) is not None, (
        "latest_preview_freshness must be set after initial registration"
    )
    assert (
        registered2.latest_preview_freshness["head_sha"]
        != registered.latest_preview_freshness["head_sha"]
    ), "HEAD SHA must differ after commit"


# ── Workspace planning tests ──────────────────────────────────────


def test_dirty_state_in_workspace_plan(
    dirty_repo: Path, registration_service: RepositoryRegistrationService
) -> None:
    """Workspace plan detects dirty source checkout state."""
    result = _preview(dirty_repo)
    registration_service.register_repository(result)
    plan = registration_service.plan_workspace(result)

    assert plan.source_checkout_is_dirty, "Plan must detect dirty source checkout"
    assert any("uncommitted" in w.lower() for w in plan.warnings), (
        "Plan must warn about uncommitted changes"
    )


@pytest.mark.skip(reason="Non-git intake not yet supported by RepositoryIntakeService")
def test_non_git_workspace_plan_returns_unsupported(
    registration_service: RepositoryRegistrationService,
) -> None:
    """Non-git directories get unsupported_in_current_phase.

    Not yet testable because RepositoryIntakeService.open_local_repository
    raises ValueError for non-git directories. When non-git intake is
    supported, this test should create a synthetic IntakeResult with
    is_git_repo=False and verify provider_eligibility returns
    "unsupported_in_current_phase".
    """


def test_workspace_plan_for_git_repo(
    python_repo: Path, registration_service: RepositoryRegistrationService
) -> None:
    """Workspace plan for git repo produces valid proposal."""
    result = _preview(python_repo)
    registration_service.register_repository(result)
    plan = registration_service.plan_workspace(result)

    assert plan.provider_eligibility == "git_worktree_available"
    assert plan.admitted_base_sha is not None
    assert plan.admitted_base_sha == result.operating_picture.repository.head_sha
    assert plan.proposed_managed_branch.startswith("rig-mission-")
    assert len(plan.proposed_worktree_location) > 0
    assert plan.digest is not None
    assert len(plan.digest) > 0


def test_registration_zero_writes_to_user_repo(
    python_repo: Path, registration_service: RepositoryRegistrationService
) -> None:
    """Gate 0: Registration creates zero filesystem mutations in user repo."""
    before = snapshot_dir(python_repo)
    result = _preview(python_repo)
    registration_service.register_repository(result)
    after = snapshot_dir(python_repo)

    assert_no_filesystem_mutation(before, after, "python_repo registration")
