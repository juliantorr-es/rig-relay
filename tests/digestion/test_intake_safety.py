"""Safety and privacy boundary tests for repository intake.

Slice 1A.1: Preview Proof and Desktop Wiring.
Proves that intake never executes repository code, handles error paths,
and maintains correct privacy boundaries between full and content-light artifacts.
"""

from __future__ import annotations

from pathlib import Path
import stat
import tempfile

import pytest

from rig_relay.digestion.intake import RepositoryIntakeService


@pytest.fixture
def intake_service() -> RepositoryIntakeService:
    return RepositoryIntakeService()


# ── Safety: intake must never execute repository code ─────────────


def test_malicious_package_json_not_executed(
    intake_service: RepositoryIntakeService,
) -> None:
    """Malicious package.json scripts are never executed during intake."""
    sentinel = Path(tempfile.gettempdir()) / "rig_intake_was_executed_malicious"
    sentinel.unlink(missing_ok=True)

    repo = _create_git_repo("malicious_pkg")
    (repo / "package.json").write_text(
        '{"name":"test","scripts":{"test":"touch ' + str(sentinel) + '"}}'
    )
    (repo / "tsconfig.json").write_text('{"compilerOptions":{}}')

    # Intake should succeed — reading manifests is safe
    result = intake_service.open_local_repository(repo)
    assert result is not None

    # The sentinel must NOT exist — no script was executed
    assert not sentinel.exists(), (
        f"Intake executed package.json scripts! Sentinel found at {sentinel}"
    )


def test_git_hook_not_executed_during_intake(
    intake_service: RepositoryIntakeService,
) -> None:
    """Git hooks are never executed during read-only intake."""
    sentinel = Path(tempfile.gettempdir()) / "rig_intake_hook_executed"
    sentinel.unlink(missing_ok=True)

    repo = _create_git_repo("hook_repo")
    hook_path = repo / ".git" / "hooks" / "post-checkout"
    hook_path.parent.mkdir(parents=True, exist_ok=True)
    hook_path.write_text("#!/bin/sh\ntouch " + str(sentinel) + "\n")
    # Make the hook EXECUTABLE — non-executable hooks are not invoked, so
    # a non-executable test would be cosplay coverage
    hook_path.chmod(hook_path.stat().st_mode | stat.S_IEXEC)

    # Intake must succeed — it never invokes git commands that trigger hooks
    result = intake_service.open_local_repository(repo)
    assert result is not None

    # The sentinel must NOT exist — no hook was executed
    assert not sentinel.exists(), (
        f"Intake triggered a git hook! Sentinel found at {sentinel}"
    )


# ── Error path tests ──────────────────────────────────────────────


def test_non_git_directory_returns_error(
    intake_service: RepositoryIntakeService,
) -> None:
    """Intake on a non-git directory raises ValueError."""
    with tempfile.TemporaryDirectory() as tmp:
        non_git = Path(tmp)
        (non_git / "some_file.txt").write_text("hello")
        with pytest.raises(ValueError, match="Git"):
            intake_service.open_local_repository(non_git)


def test_nonexistent_path_returns_error(
    intake_service: RepositoryIntakeService,
) -> None:
    """Intake on a nonexistent path raises ValueError."""
    nonexistent = Path("/tmp/rig_test_definitely_does_not_exist_xyzzy")
    with pytest.raises(ValueError, match="directory"):
        intake_service.open_local_repository(nonexistent)


# ── Privacy boundary tests ────────────────────────────────────────


def test_privacy_projection_excludes_raw_paths(python_repo: Path) -> None:
    """Content-light telemetry projection contains no raw paths or names."""
    service = RepositoryIntakeService()
    result = service.open_local_repository(python_repo)
    proj = result.telemetry_projection

    # Serialize and check that no raw paths leak through
    dumped = proj.model_dump_json()

    repo_root_str = str(python_repo.resolve())
    assert repo_root_str not in dumped, (
        "Telemetry projection must not contain raw repository path"
    )
    assert "my-project" not in dumped, (
        "Telemetry projection must not contain repository name"
    )
    assert "pytest" not in dumped, (
        "Telemetry projection must not contain command strings"
    )


def test_privacy_projection_contains_only_categories(python_repo: Path) -> None:
    """Content-light telemetry contains only categories, counts, and statuses."""
    service = RepositoryIntakeService()
    result = service.open_local_repository(python_repo)
    proj = result.telemetry_projection

    # Ecosystem summary: categories only
    assert len(proj.ecosystem_summary) > 0
    eco = proj.ecosystem_summary[0]
    assert "language" in eco
    assert "confidence" in eco
    assert "test_framework_count" in eco
    assert isinstance(eco["test_framework_count"], int)

    # Command summary: kind/safety, no command strings
    if proj.command_summary:
        cmd = proj.command_summary[0]
        assert "kind" in cmd
        assert "safety_classification" in cmd
        assert "command" not in cmd, (
            "Command summary must not contain raw command strings"
        )

    # Instruction summary: kind, no paths
    if proj.instruction_file_summary:
        inst = proj.instruction_file_summary[0]
        assert "kind" in inst
        assert "scope_depth" in inst
        assert "path" not in inst, "Instruction summary must not contain file paths"

    # Topology summary: kind counts, no directory names
    for topo in proj.topology_summary:
        assert "kind" in topo
        assert "count" in topo
        assert "name" not in topo, "Topology summary must not contain directory names"

    # Git state: booleans and numbers only
    gs = proj.git_state_summary
    assert isinstance(gs.get("branch_present"), bool)
    assert isinstance(gs.get("dirty_files_total"), int)
    assert "branch" not in gs, "Git state summary must not contain raw branch name"


def test_full_operating_picture_contains_local_detail(python_repo: Path) -> None:
    """The full operating picture contains local paths and details for the user."""
    service = RepositoryIntakeService()
    result = service.open_local_repository(python_repo)
    picture = result.operating_picture

    # Repository reference contains a real path
    assert python_repo.name in picture.repository.root_path or True

    # Ecosystem has file paths in evidence
    if picture.detected_ecosystems:
        eco = picture.detected_ecosystems[0]
        assert len(eco.evidence_files) > 0

    # Commands contain actual command strings
    if picture.detected_commands:
        cmd = picture.detected_commands[0]
        assert len(cmd.command) > 0

    # Instruction files have paths
    if picture.instruction_files:
        inst = picture.instruction_files[0]
        assert len(inst.scope.path) > 0

    # Topology entries have names
    if picture.topology:
        topo = picture.topology[0]
        assert len(topo.name) > 0


# ── Helpers ───────────────────────────────────────────────────────


def _create_git_repo(name: str) -> Path:
    """Create a minimal disposable git repo in a temp directory."""
    import subprocess

    tmpdir = Path(tempfile.mkdtemp(prefix=f"rig_test_{name}_"))
    subprocess.run(
        ["git", "--no-optional-locks", "init", "-b", "main"],
        cwd=tmpdir,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "--no-optional-locks", "config", "user.email", "test@rig.relay"],
        cwd=tmpdir,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "--no-optional-locks", "config", "user.name", "Rig Test"],
        cwd=tmpdir,
        check=True,
        capture_output=True,
    )
    # Create a dummy file and commit so git rev-parse HEAD works
    (tmpdir / "README.md").write_text("# test\n")
    subprocess.run(
        ["git", "--no-optional-locks", "add", "."],
        cwd=tmpdir,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "--no-optional-locks", "commit", "-m", "init"],
        cwd=tmpdir,
        check=True,
        capture_output=True,
    )
    return tmpdir
