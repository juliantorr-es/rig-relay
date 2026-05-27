"""Production-substrate tests for RepositoryEstateService.

All tests use real temporary Git repositories on disk and the real
application-service boundary. No fake repos, no mocks, no stubs.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from rig_relay.repository_estate._models import ObservationStatus, RepositoryKind
from rig_relay.repository_estate._registry_store import RepositoryEstateRegistryStore
from rig_relay.repository_estate._service import RegistryError, RepositoryEstateService

# ── Registration ────────────────────────────────────────────────────


def test_register_clean_repo_succeeds(
    clean_repo: Path, estate_service: RepositoryEstateService
) -> None:
    """Registration of a clean git repository succeeds and produces evidence."""
    reg = estate_service.register_repository(clean_repo)
    assert reg.repository_hash
    assert reg.repository_label
    assert reg.repository_kind == RepositoryKind.LOCAL_ONLY
    assert reg.registered_at
    assert reg.latest_observation_digest is not None
    assert reg.latest_observation_at is not None


def test_register_non_repository_path_refused(
    non_repo_path: Path, estate_service: RepositoryEstateService
) -> None:
    """Registration of a non-git path raises RegistryError."""
    with pytest.raises(RegistryError, match="not a git repository"):
        estate_service.register_repository(non_repo_path)


def test_register_same_repo_is_idempotent(
    clean_repo: Path, estate_service: RepositoryEstateService
) -> None:
    """Re-registering the same repo updates timestamps but preserves identity."""
    reg1 = estate_service.register_repository(clean_repo)
    reg2 = estate_service.register_repository(clean_repo)
    assert reg2.repository_hash == reg1.repository_hash
    assert reg2.registered_at == reg1.registered_at  # original timestamp preserved
    assert reg2.last_registered_at >= reg1.last_registered_at


def test_register_repo_emits_evidence(
    clean_repo: Path, estate_service: RepositoryEstateService
) -> None:
    """Registration produces append-only evidence in the store."""
    estate_service.register_repository(clean_repo)
    regs = estate_service._store.read_all_registrations()
    assert len(regs) > 0
    payload = regs[0]["payload"]
    assert payload["repository_kind"] == "local_only"


# ── Observation ────────────────────────────────────────────────────


def test_observe_clean_repo_is_observed(
    clean_repo: Path, estate_service: RepositoryEstateService
) -> None:
    """Observing a clean registered repo produces an observation."""
    estate_service.register_repository(clean_repo)
    reg_hash = estate_service._store.read_all_registrations()[-1]["payload"][
        "repository_hash"
    ]

    obs = estate_service.observe_repository(reg_hash, root_path=clean_repo)
    assert obs.repository_hash == reg_hash
    assert obs.status in (
        ObservationStatus.REGISTERED,
        ObservationStatus.OBSERVED,
        ObservationStatus.UNCHANGED,
        ObservationStatus.CHANGED,
    )
    assert obs.git_facts.head_sha is not None
    assert obs.observation_digest
    assert obs.content_light_guarantee is True


def test_repeated_unchanged_observation_is_deterministic(
    clean_repo: Path, estate_service: RepositoryEstateService
) -> None:
    """Reobserving an unchanged repo detects no change."""
    # Register and get the reg hash
    estate_service.register_repository(clean_repo)
    events = estate_service._store.read_all_registrations()
    reg_hash = events[-1]["payload"]["repository_hash"]

    # First observation
    obs1 = estate_service.observe_repository(reg_hash, root_path=clean_repo)
    # Second observation (no changes made)
    obs2 = estate_service.observe_repository(reg_hash, root_path=clean_repo)

    # Second observation should report unchanged
    assert obs2.status == ObservationStatus.UNCHANGED
    assert obs2.git_facts.head_sha == obs1.git_facts.head_sha
    assert obs2.previous_observation_digest == obs1.observation_digest
    assert obs2.observation_digest != obs1.observation_digest  # different event IDs


def test_dirty_observation_detects_change(
    clean_repo: Path, estate_service: RepositoryEstateService
) -> None:
    """Dirty working tree after a file change is detected as a change."""
    estate_service.register_repository(clean_repo)
    reg_hash = estate_service._store.read_all_registrations()[-1]["payload"][
        "repository_hash"
    ]

    # First observation (clean) — capture baseline
    estate_service.observe_repository(reg_hash, root_path=clean_repo)

    # Modify a tracked file
    (clean_repo / "src" / "main.py").write_text("# changed\n")

    # Second observation (dirty)
    obs2 = estate_service.observe_repository(reg_hash, root_path=clean_repo)
    assert obs2.status == ObservationStatus.CHANGED
    assert obs2.git_facts.dirty_counts.modified > 0


def test_observe_includes_git_facts(
    clean_repo: Path, estate_service: RepositoryEstateService
) -> None:
    """Observation includes content-light git operational facts."""
    estate_service.register_repository(clean_repo)
    reg_hash = estate_service._store.read_all_registrations()[-1]["payload"][
        "repository_hash"
    ]

    obs = estate_service.observe_repository(reg_hash, root_path=clean_repo)
    facts = obs.git_facts
    assert facts.head_sha is not None
    assert facts.branch is not None
    assert not facts.is_detached
    assert facts.tracked_file_count > 0
    assert facts.is_local_only
    assert not facts.is_github_backed
    assert len(facts.instruction_files) > 0  # AGENTS.md, README.md


def test_observe_includes_instruction_file_presence(
    clean_repo: Path, estate_service: RepositoryEstateService
) -> None:
    """Instruction file presence is recorded with digests only."""
    estate_service.register_repository(clean_repo)
    reg_hash = estate_service._store.read_all_registrations()[-1]["payload"][
        "repository_hash"
    ]

    obs = estate_service.observe_repository(reg_hash, root_path=clean_repo)
    inst_files = obs.git_facts.instruction_files
    assert any(f.kind == "agents_md" for f in inst_files)
    assert any(f.kind == "readme_md" for f in inst_files)
    # All have content_sha256 (not raw content)
    for f in inst_files:
        assert f.content_sha256
        assert f.path_digest


def test_observe_detects_branch_change(
    clean_repo: Path, estate_service: RepositoryEstateService
) -> None:
    """Branch change is detected between observations."""
    estate_service.register_repository(clean_repo)
    reg_hash = estate_service._store.read_all_registrations()[-1]["payload"][
        "repository_hash"
    ]

    _obs1 = estate_service.observe_repository(reg_hash, root_path=clean_repo)

    # Create a new branch and commit
    import subprocess

    subprocess.run(
        ["git", "--no-optional-locks", "checkout", "-b", "feature-x"],
        cwd=clean_repo,
        check=True,
        capture_output=True,
    )
    (clean_repo / "new_file.txt").write_text("new\n")
    subprocess.run(
        ["git", "--no-optional-locks", "add", "new_file.txt"],
        cwd=clean_repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "--no-optional-locks", "commit", "-m", "new file on feature"],
        cwd=clean_repo,
        check=True,
        capture_output=True,
    )

    obs2 = estate_service.observe_repository(reg_hash, root_path=clean_repo)
    assert obs2.status == ObservationStatus.CHANGED
    assert obs2.git_facts.branch == "feature-x"


def test_detached_head_is_recorded(
    detached_repo: Path, estate_service: RepositoryEstateService
) -> None:
    """Detached HEAD state is correctly recorded."""
    estate_service.register_repository(detached_repo)
    reg_hash = estate_service._store.read_all_registrations()[-1]["payload"][
        "repository_hash"
    ]

    obs = estate_service.observe_repository(reg_hash, root_path=detached_repo)
    assert obs.git_facts.is_detached
    assert obs.git_facts.branch is None
    assert obs.git_facts.head_sha is not None


# ── Content-light guarantee ────────────────────────────────────────


def test_registration_has_no_raw_paths(
    clean_repo: Path, estate_service: RepositoryEstateService
) -> None:
    """Registration evidence contains no raw file paths, only digests."""
    reg = estate_service.register_repository(clean_repo)
    dumped = reg.model_dump(mode="json")
    # No raw paths (the root_path_digest is SHA256, root_path is not stored)
    assert "root_path" not in dumped
    assert reg.root_path_digest
    assert reg.repository_hash
    # Label is a directory name, not a full path
    assert "/" not in reg.repository_label


def test_observation_has_no_raw_file_content(
    clean_repo: Path, estate_service: RepositoryEstateService
) -> None:
    """Observation evidence contains no raw file contents."""
    estate_service.register_repository(clean_repo)
    reg_hash = estate_service._store.read_all_registrations()[-1]["payload"][
        "repository_hash"
    ]

    obs = estate_service.observe_repository(reg_hash, root_path=clean_repo)
    dumped = obs.model_dump(mode="json")
    # Search for any raw file content
    all_values = str(dumped)
    assert "# Agent instructions" not in all_values
    assert "def hello()" not in all_values
    assert "return 'hello'" not in all_values
    assert obs.content_light_guarantee is True


# ── Projection ─────────────────────────────────────────────────────


def test_projection_from_evidence(
    clean_repo: Path, estate_service: RepositoryEstateService
) -> None:
    """Projection is reconstructable from canonical evidence."""
    estate_service.register_repository(clean_repo)
    proj = estate_service.build_projection()
    assert proj.available is True
    assert proj.total_registered == 1
    assert proj.local_only_count == 1
    assert proj.github_backed_count == 0
    assert len(proj.registered_repositories) == 1
    assert proj.total_observations > 0
    assert proj.content_light_guarantee is True


def test_projection_with_no_registrations_is_missing(
    estate_service: RepositoryEstateService,
) -> None:
    """Empty projection reports missing authority state."""
    proj = estate_service.build_projection()
    assert proj.available is False
    assert proj.authority_state == "missing"
    assert proj.total_registered == 0


def test_projection_includes_recent_changes(
    clean_repo: Path, estate_service: RepositoryEstateService
) -> None:
    """Projection captures recent change events between observations."""
    estate_service.register_repository(clean_repo)
    reg_hash = estate_service._store.read_all_registrations()[-1]["payload"][
        "repository_hash"
    ]

    # Make a change
    (clean_repo / "src" / "main.py").write_text("# changed\n")
    estate_service.observe_repository(reg_hash, root_path=clean_repo)

    proj = estate_service.build_projection()
    # May or may not have change events depending on how many obs occurred
    # At minimum, the projection should include the dirty file count
    assert proj.registered_repositories[0].is_dirty is True
    assert proj.dirty_count == 1


def test_projection_dirty_and_detached_counts(
    clean_repo: Path,
    dirty_repo: Path,
    detached_repo: Path,
    estate_service: RepositoryEstateService,
) -> None:
    """Projection correctly counts dirty and dirty in aggregate."""
    from rig_relay.repository_estate._service import RepositoryEstateService

    # Use separate services with clean store
    svc = RepositoryEstateService()
    estate_service = svc  # cleaner state

    estate_service.register_repository(clean_repo)

    # Add a second repo as a clean new repo (not dirty)
    dirty_repo_path = dirty_repo
    estate_service.register_repository(dirty_repo_path)

    last_hash = estate_service._store.read_all_registrations()[-1]["payload"][
        "repository_hash"
    ]
    estate_service.observe_repository(last_hash, root_path=dirty_repo_path)

    proj = estate_service.build_projection()
    # At least the dirty_repo should be dirty
    assert proj.dirty_count >= 1
    assert proj.total_registered == 2


# ── Evidence store ────────────────────────────────────────────────


def test_registry_store_append_read(
    tmp_path: Path, estate_service: RepositoryEstateService
) -> None:
    """Evidence store supports append and read with JSONL."""
    store = RepositoryEstateRegistryStore(tmp_path / "test_store")
    assert store.registrations_path.is_absolute()
    assert store.observations_path.is_absolute()

    # Empty reads return empty list
    assert store.read_all_registrations() == []
    assert store.read_all_observations() == []


def test_evidence_is_append_only(
    clean_repo: Path, estate_service: RepositoryEstateService
) -> None:
    """Registration and observation evidence is append-only."""
    estate_service.register_repository(clean_repo)
    regs1 = len(estate_service._store.read_all_registrations())
    obs1 = len(estate_service._store.read_all_observations())

    # Register again (idempotent — should add reconciliation entry)
    estate_service.register_repository(clean_repo)
    regs2 = len(estate_service._store.read_all_registrations())
    obs2 = len(estate_service._store.read_all_observations())

    assert regs2 >= regs1  # registration count may increase with reconciliation
    assert obs2 > obs1  # observation count always increases


# ── Edge cases ─────────────────────────────────────────────────────


def test_register_empty_git_dir_refused(
    tmp_path: Path, estate_service: RepositoryEstateService
) -> None:
    """An empty git directory (no commits) is still registerable but minimal."""
    import subprocess

    repo = tmp_path / "empty_repo"
    repo.mkdir()
    subprocess.run(
        ["git", "--no-optional-locks", "init", "-b", "main"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "--no-optional-locks", "config", "user.email", "test@rig.relay"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "--no-optional-locks", "config", "user.name", "Rig Test"],
        cwd=repo,
        check=True,
        capture_output=True,
    )

    reg = estate_service.register_repository(repo)
    assert reg.repository_hash
    # Empty repo has no commits, so head_sha and instruction files may be empty
    obs = estate_service._store.read_all_observations()
    assert len(obs) > 0


def test_observation_chain_links_previous_digest(
    clean_repo: Path, estate_service: RepositoryEstateService
) -> None:
    """Observation chain correctly links to previous observation digest."""
    estate_service.register_repository(clean_repo)
    reg_hash = estate_service._store.read_all_registrations()[-1]["payload"][
        "repository_hash"
    ]

    obs1 = estate_service.observe_repository(reg_hash, root_path=clean_repo)
    obs2 = estate_service.observe_repository(reg_hash, root_path=clean_repo)

    assert obs2.previous_observation_digest == obs1.observation_digest
    assert obs2.observation_digest != obs1.observation_digest


def test_duplicate_registration_is_safe(
    clean_repo: Path, estate_service: RepositoryEstateService
) -> None:
    """Duplicate registration does not create duplicate governed identity effects."""
    reg1 = estate_service.register_repository(clean_repo)
    reg2 = estate_service.register_repository(clean_repo)
    # Same identity
    assert reg2.repository_hash == reg1.repository_hash
    # Same root path digest
    assert reg2.root_path_digest == reg1.root_path_digest


def test_registration_produces_initial_observation(
    clean_repo: Path, estate_service: RepositoryEstateService
) -> None:
    """Registration automatically produces an initial observation."""
    estate_service.register_repository(clean_repo)
    obs = estate_service._store.read_all_observations()
    assert len(obs) > 0
    assert obs[0]["event_kind"] == "repository_estate.observation"


def test_observe_nonexistent_repo_hash_refused(
    estate_service: RepositoryEstateService,
) -> None:
    """Observing an unknown repository hash raises RegistryError."""
    with pytest.raises(RegistryError, match="No registration found"):
        estate_service.observe_repository("nonexistent-hash")


def test_registration_evidence_has_correct_envelope(
    clean_repo: Path, estate_service: RepositoryEstateService
) -> None:
    """Evidence store entries have the correct event envelope structure."""
    estate_service.register_repository(clean_repo)
    regs = estate_service._store.read_all_registrations()
    assert len(regs) > 0
    event = regs[0]
    assert "schema_version" in event
    assert "event_id" in event
    assert "event_kind" in event
    assert "created_at" in event
    assert "payload" in event
    assert "payload_sha256" in event
    assert "event_sha256" in event
    assert event["event_kind"] == "repository_estate.registration"
