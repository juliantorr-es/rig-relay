"""Identity-match enforcement, corruption degradation, and chain-tampering tests.

Tests for Lane T3.1 authority closures:
- Identity-match gate prevents path poisoning
- Corrupt evidence degrades projection reconstruction
- Broken observation-chain linkage degrades reconstruction
- No false workspace-policy claims
"""

from __future__ import annotations

from pathlib import Path

from rig_relay.repository_estate._models import AuthorityState, ObservationStatus
from rig_relay.repository_estate._service import RepositoryEstateService

# ── Identity-match enforcement ───────────────────────────────────────


def test_identity_mismatch_refuses_different_repo(
    clean_repo: Path, dirty_repo: Path, estate_service: RepositoryEstateService
) -> None:
    """Observing repo B with repo A's hash produces IDENTITY_MISMATCH."""
    # Register repo A
    estate_service.register_repository(clean_repo)
    reg_hash_a = estate_service._store.read_all_registrations()[-1]["payload"][
        "repository_hash"
    ]

    # Try to observe repo B using repo A's hash
    obs = estate_service.observe_repository(reg_hash_a, root_path=dirty_repo)
    assert obs.status == ObservationStatus.IDENTITY_MISMATCH
    assert obs.repository_hash == reg_hash_a
    # No false git facts from repo B should be recorded under A's identity
    assert obs.git_facts.head_sha is None
    assert obs.git_facts.tracked_file_count == 0


def test_identity_mismatch_no_false_evidence_appended(
    clean_repo: Path, dirty_repo: Path, estate_service: RepositoryEstateService
) -> None:
    """IDENTITY_MISMATCH observation has empty facts — no leaked data."""
    estate_service.register_repository(clean_repo)
    reg_hash_a = estate_service._store.read_all_registrations()[-1]["payload"][
        "repository_hash"
    ]

    obs = estate_service.observe_repository(reg_hash_a, root_path=dirty_repo)
    # Verify git_facts are empty for IDENTITY_MISMATCH — no leaked data
    assert obs.git_facts.dirty_counts.modified == 0
    assert obs.git_facts.dirty_counts.untracked == 0
    assert obs.git_facts.dirty_counts.staged == 0
    assert obs.git_facts.dirty_counts.deleted == 0
    assert obs.git_facts.dirty_counts.conflicted == 0
    # No instruction file data from repo B
    assert obs.git_facts.instruction_files == []
    assert obs.git_facts.remotes == []


def test_correct_identity_match_passes(
    clean_repo: Path, estate_service: RepositoryEstateService
) -> None:
    """Observing the correct repo with the correct path succeeds."""
    estate_service.register_repository(clean_repo)
    reg_hash = estate_service._store.read_all_registrations()[-1]["payload"][
        "repository_hash"
    ]

    obs = estate_service.observe_repository(reg_hash, root_path=clean_repo)
    assert obs.status in (
        ObservationStatus.REGISTERED,
        ObservationStatus.OBSERVED,
        ObservationStatus.UNCHANGED,
        ObservationStatus.CHANGED,
    )
    assert obs.git_facts.head_sha is not None


def test_local_only_identity_match_uses_root_path_digest(
    clean_repo: Path, estate_service: RepositoryEstateService
) -> None:
    """Local-only repos match on root_path_digest even after branch changes."""
    import subprocess

    estate_service.register_repository(clean_repo)
    reg_hash = estate_service._store.read_all_registrations()[-1]["payload"][
        "repository_hash"
    ]

    # Create a new branch and commit — changes git_common_dir_digest but same path
    subprocess.run(
        ["git", "--no-optional-locks", "checkout", "-b", "topic"],
        cwd=clean_repo,
        check=True,
        capture_output=True,
    )
    (clean_repo / "new.md").write_text("# topic\n")
    subprocess.run(
        ["git", "--no-optional-locks", "add", "new.md"],
        cwd=clean_repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "--no-optional-locks", "commit", "-m", "topic commit"],
        cwd=clean_repo,
        check=True,
        capture_output=True,
    )

    obs = estate_service.observe_repository(reg_hash, root_path=clean_repo)
    # Should match identity (same path) and detect changes
    assert obs.status == ObservationStatus.CHANGED
    assert obs.git_facts.branch == "topic"


# ── Corrupt evidence degradation ─────────────────────────────────────


def test_corrupt_registration_degrades_projection(
    clean_repo: Path, estate_service: RepositoryEstateService
) -> None:
    """Writing corrupt JSON to the registration evidence degrades the projection."""
    estate_service.register_repository(clean_repo)

    # Append corrupt JSON to the registrations file
    corrupt_path = estate_service._store.registrations_path
    with open(corrupt_path, "a") as f:
        f.write('{"schema_version": "corrupt", "broken": true\n')

    proj = estate_service.build_projection()
    assert proj.authority_state == AuthorityState.CORRUPT
    assert proj.corrupt_registration_count >= 1
    assert len(proj.corruption_events) >= 1
    assert any(
        ce.event_kind == "registration"
        and ce.reason in ("model_validation_failed", "malformed_json")
        for ce in proj.corruption_events
    )


def test_corrupt_observation_degrades_projection(
    clean_repo: Path, estate_service: RepositoryEstateService
) -> None:
    """Writing corrupt JSON to the observation evidence degrades the projection."""
    estate_service.register_repository(clean_repo)

    # Append corrupt JSON to the observations file
    corrupt_path = estate_service._store.observations_path
    with open(corrupt_path, "a") as f:
        f.write('{"schema_version": "corrupt", "bad": null\n')

    proj = estate_service.build_projection()
    assert proj.authority_state == AuthorityState.CORRUPT
    assert proj.corrupt_observation_count >= 1


def test_clean_evidence_remains_canonical_live(
    clean_repo: Path, estate_service: RepositoryEstateService
) -> None:
    """Clean evidence (no corruption) reports CANONICAL_LIVE."""
    estate_service.register_repository(clean_repo)
    proj = estate_service.build_projection()
    assert proj.authority_state == AuthorityState.CANONICAL_LIVE
    assert proj.corrupt_registration_count == 0
    assert proj.corrupt_observation_count == 0
    assert proj.corrupt_chain_links == 0


def test_corrupt_projection_still_includes_valid_data(
    clean_repo: Path, estate_service: RepositoryEstateService
) -> None:
    """Even with corrupt evidence, valid registrations still appear in the projection."""
    estate_service.register_repository(clean_repo)

    with open(estate_service._store.observations_path, "a") as f:
        f.write('{"schema_version": "corrupt", "bad": null\n')

    proj = estate_service.build_projection()
    # Corrupt, but the valid repo summary still appears
    assert proj.authority_state == AuthorityState.CORRUPT
    assert proj.total_registered >= 1
    assert len(proj.registered_repositories) >= 1


# ── Chain-link tampering ────────────────────────────────────────────


def test_broken_observation_chain_degrades_projection(
    clean_repo: Path, estate_service: RepositoryEstateService, tmp_path: Path
) -> None:
    """Manually tampering with observation_digest chain causes CORRUPT."""
    import json

    estate_service.register_repository(clean_repo)
    estate_service.observe_repository(
        estate_service._store.read_all_registrations()[-1]["payload"][
            "repository_hash"
        ],
        root_path=clean_repo,
    )

    # Read the observations, tamper with the chain
    obs_path = estate_service._store.observations_path
    with open(obs_path) as f:
        lines = [json.loads(l.strip()) for l in f if l.strip()]

    if len(lines) >= 2:
        # Break the chain: set previous_observation_digest to a bogus value
        lines[-1]["payload"]["previous_observation_digest"] = "sha256:deadbeef"
        # Rewrite the observations file
        with open(obs_path, "w") as f:
            for line in lines:
                f.write(json.dumps(line, separators=(",", ":")) + "\n")

        proj = estate_service.build_projection()
        assert proj.authority_state == AuthorityState.CORRUPT
        assert proj.corrupt_chain_links >= 1
        assert any(ce.reason == "chain_broken" for ce in proj.corruption_events)


# ── Workspace policy claim ──────────────────────────────────────────


def test_register_repository_has_no_false_workspace_policy_claim() -> None:
    """The service docstring must not claim workspace-policy enforcement."""
    import inspect

    from rig_relay.repository_estate._service import RepositoryEstateService

    doc = inspect.getdoc(RepositoryEstateService.register_repository) or ""
    assert "workspace" not in doc.lower(), (
        f"register_repository docstring must not claim workspace policy: {doc[:200]}"
    )


# ── Content-light persistence ───────────────────────────────────────


def test_no_raw_path_in_identity_mismatch_observation(
    clean_repo: Path, dirty_repo: Path, estate_service: RepositoryEstateService
) -> None:
    """IDENTITY_MISMATCH observation still enforces content-light guarantee."""
    estate_service.register_repository(clean_repo)
    reg_hash = estate_service._store.read_all_registrations()[-1]["payload"][
        "repository_hash"
    ]

    obs = estate_service.observe_repository(reg_hash, root_path=dirty_repo)
    dumped = obs.model_dump(mode="json")
    # root_path_digest is present, but no raw "root_path" field
    assert "root_path" not in dumped
    assert obs.root_path_digest
    assert obs.content_light_guarantee is True


def test_no_raw_remote_url_in_projection(
    clean_repo: Path, estate_service: RepositoryEstateService
) -> None:
    """Projection never contains raw remote URLs, only url_digest."""
    estate_service.register_repository(clean_repo)
    proj = estate_service.build_projection()
    dumped = proj.model_dump(mode="json")
    all_text = str(dumped)
    assert "github.com" not in all_text
    assert "gitlab.com" not in all_text
    assert "bitbucket.org" not in all_text


# ── GitHub-backed identity matching ──────────────────────────────────


def test_github_backed_identity_match_with_remote(
    tmp_path: Path, estate_service: RepositoryEstateService
) -> None:
    """A GitHub-backed repo matches via remote_identity_digest at same path."""
    import subprocess

    repo = tmp_path / "github_repo"
    repo.mkdir()
    (repo / "README.md").write_text("# GitHub Repo\n")
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
    subprocess.run(
        ["git", "--no-optional-locks", "add", "."],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "--no-optional-locks", "commit", "-m", "initial"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            "git",
            "--no-optional-locks",
            "remote",
            "add",
            "origin",
            "https://github.com/org/repo.git",
        ],
        cwd=repo,
        check=True,
        capture_output=True,
    )

    reg = estate_service.register_repository(repo)
    assert reg.repository_kind == "github_backed"
    assert reg.remote_identity_digest is not None

    # Re-observe the same repo — identity matches via root_path_digest
    obs = estate_service.observe_repository(reg.repository_hash, root_path=repo)
    # After adding remote and re-registering (which triggers re-registration),
    # the observation should succeed with a normal status
    assert obs.status in (
        ObservationStatus.REGISTERED,
        ObservationStatus.OBSERVED,
        ObservationStatus.UNCHANGED,
        ObservationStatus.CHANGED,
    ), f"Expected normal status, got {obs.status}"


# ── Refactored collaborator structure ───────────────────────────────


def test_service_uses_collaborators_not_monolith() -> None:
    """The service has extracted collaborators, not a single monolith."""
    import inspect

    from rig_relay.repository_estate._service import RepositoryEstateService

    source = inspect.getsource(RepositoryEstateService)
    # The service should be thin — ~100-120 lines, not 800+
    line_count = len(source.splitlines())
    assert line_count < 150, (
        f"Service should be thin orchestrator, got {line_count} lines. "
        "Extract to collaborators."
    )


def test_collaborators_are_independently_importable() -> None:
    """Each collaborator module is independently importable."""
    from rig_relay.repository_estate._change_detector import ChangeDetector
    from rig_relay.repository_estate._observation_engine import ObservationEngine
    from rig_relay.repository_estate._projection_builder import ProjectionBuilder
    from rig_relay.repository_estate._registration import RegistrationAuthority

    assert RegistrationAuthority
    assert ObservationEngine
    assert ChangeDetector
    assert ProjectionBuilder
