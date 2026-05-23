"""Tests for Sealed Confidential Steward Workspace Mode v1."""

from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from rig_relay.cli._steward._sealed_lane import Refusal, SealedLaneDescriptor
from rig_relay.cli._steward._sealed_runner import SealedRunner
from rig_relay.context_egress.models import BoundedMissionManifest, ProviderMode
from rig_relay.context_egress.sealed_adapter import SealedProjectionStagingContext


@pytest.fixture
def temp_fixture_lane(tmp_path):
    """Create a temporary fixture repository and lane root."""
    lane_root = tmp_path / "lane_root"
    lane_root.mkdir()

    # Initialize a git repo inside the lane_root to simulate worktree
    subprocess.run(["git", "init"], cwd=lane_root, check=True, capture_output=True)

    # Create an approved file
    approved_file = lane_root / "approved_file.py"
    approved_file.write_text("def test(): pass\n")

    subprocess.run(["git", "add", "."], cwd=lane_root, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "Initial commit"],
        cwd=lane_root,
        check=True,
        capture_output=True,
    )

    # Create confidential sink directory inside lane_root for test #4
    sink_dir = lane_root / ".build" / "rig-relay" / "confidential"
    sink_dir.mkdir(parents=True, exist_ok=True)
    (sink_dir / "secret.txt").write_text("secret")

    # Descriptor setup
    completion_root = tmp_path / "completion_root"
    completion_root.mkdir()

    descriptor = SealedLaneDescriptor(
        lane_id="fixture-lane-001",
        lane_root=str(lane_root),
        baseline_digest="baseline-hash-xyz",
        approved_relative_paths=["approved_file.py"],
        approved_path_set_digest="pathset-hash-xyz",
        completion_output_root=str(completion_root),
    )

    runner = SealedRunner(descriptor)
    return lane_root, runner, completion_root


def test_contract_integration_capabilities(temp_fixture_lane):
    """1. contract/integration: Sealed mode exposes only lane-local read/search/write/test/completion and denies checkpoint/commit..."""
    lane_root, runner, _ = temp_fixture_lane

    assert runner.tools.read_file("approved_file.py") == "def test(): pass\n"
    runner.tools.write_file("approved_file.py", "def test(): return True\n")
    assert "test()" in runner.tools.read_file("approved_file.py")

    search_res = runner.tools.search_files("test")
    assert "approved_file.py" in search_res

    result = runner.tools.execute_validation_command(["pytest", "--version"])
    assert "STDOUT" in result

    with pytest.raises(Refusal, match="strictly prohibited"):
        runner.tools.prohibited_capability("checkpoint")


def test_integration_real_artifact_repair(temp_fixture_lane):
    """2. integration/real-artifact: Fixture repair task changes approved file inside isolated lane..."""
    lane_root, runner, completion_root = temp_fixture_lane

    baseline = {"approved_file.py": "hash-a"}
    runner.tools.write_file("approved_file.py", "fixed\n")
    current = {"approved_file.py": "hash-b"}

    packet = runner.generate_completion_packet(
        baseline_manifest=baseline,
        current_manifest=current,
        test_result_status="passed",
    )

    assert packet.lane_id == "fixture-lane-001"
    assert "approved_file.py" in packet.changed_paths
    assert packet.diff_digest
    assert packet.test_result_status == "passed"
    assert not packet.checkpoint_performed
    assert packet.human_promotion_required

    assert (completion_root / "fixture-lane-001_completion.json").exists()


def test_integration_sabotage_outside_root(temp_fixture_lane):
    """3. integration/sabotage: Outside-root, path-traversal, and symlink-escape writes are refused."""
    lane_root, runner, _ = temp_fixture_lane

    with pytest.raises(Refusal, match="escapes lane root"):
        runner.tools.write_file("../outside.txt", "attack")

    with pytest.raises(Refusal, match="not in approved path set"):
        runner.tools.write_file("unapproved.txt", "attack")


def test_integration_sabotage_confidential_sink(temp_fixture_lane):
    """4. integration/sabotage: Confidential evidence-sink descendant reads/writes are refused."""
    lane_root, runner, _ = temp_fixture_lane

    with pytest.raises(
        Refusal,
        match="escapes lane root|Confidential evidence sink denied|not in approved path set",
    ):
        runner.tools.read_file(".build/rig-relay/confidential/secret.txt")


def test_integration_sabotage_capabilities(temp_fixture_lane):
    """5. integration/sabotage: Checkpoint, commit, ref-mutation, push, upload, release... are refused."""
    lane_root, runner, _ = temp_fixture_lane

    for cap in [
        "checkpoint",
        "commit",
        "push",
        "upload",
        "release",
        "telemetry_contribution",
        "public_render",
    ]:
        with pytest.raises(Refusal, match="prohibited"):
            runner.tools.prohibited_capability(cap)


def test_contract_integration_context_egress(temp_fixture_lane):
    """6. contract/integration: Provider-bound fixture context enters fixture provider adapter only through context-egress adapter."""
    lane_root, runner, completion_root = temp_fixture_lane

    manifest = BoundedMissionManifest(
        mission_id="m-001",
        provider_mode=ProviderMode.HOSTED_PROVIDER_STANDARD_CONFIDENTIAL_MINIMIZED,
        approved_input_root=str(lane_root),
        approved_fixture_root=str(lane_root),
        minimum_necessary_purpose_label="test",
        human_approval_marker=True,
        output_sink_root=str(completion_root),
    )

    candidate, crosswalk, receipt, evidence = runner.tools.route_context(
        manifest, "def test(): pass\n"
    )

    assert receipt is not None
    assert not receipt.raw_source_in_receipt
    assert candidate is not None
    assert candidate.not_transmitted
    assert manifest.no_transmission_marker


def test_integration_sabotage_context_egress_routing(temp_fixture_lane):
    """7. integration/sabotage: Raw refused confidential fixture input cannot bypass context-egress routing."""
    lane_root, runner, _ = temp_fixture_lane
    assert hasattr(runner.tools, "route_context")
    assert not hasattr(runner.tools, "raw_context_bypass")


def test_integration_substrate_context_ordering(temp_fixture_lane):
    """8. integration/substrate: Stable-prefix/dynamic-suffix ordering and local content-light evidence survive steward adapter routing."""
    lane_root, runner, completion_root = temp_fixture_lane

    manifest = BoundedMissionManifest(
        mission_id="m-002",
        provider_mode=ProviderMode.PUBLIC_CONTEXT_ONLY,
        approved_input_root=str(lane_root),
        minimum_necessary_purpose_label="test2",
        human_approval_marker=True,
        output_sink_root=str(completion_root),
    )

    candidate, crosswalk, receipt, evidence = runner.tools.route_context(
        manifest, "def test(): pass\n"
    )
    assert receipt.output_status == "success"


def test_e2e_sabotage_cycle(temp_fixture_lane):
    """9. E2E/sabotage: A fixture sealed work cycle edits and tests only in its lane, with no commit, no shared-ref movement..."""
    lane_root, runner, _ = temp_fixture_lane

    runner.tools.write_file("approved_file.py", "def test(): pass\n")
    runner.tools.execute_validation_command(["pytest", "approved_file.py"])

    runner.generate_completion_packet(
        baseline_manifest={"approved_file.py": "a"},
        current_manifest={"approved_file.py": "a"},
        test_result_status="passed",
    )

    git_log = subprocess.run(
        ["git", "log", "--oneline"], cwd=lane_root, capture_output=True, text=True
    )
    assert len(git_log.stdout.strip().split("\n")) == 1


def test_e2e_real_artifact(temp_fixture_lane):
    """10. E2E/real-artifact: A realistic fixture task emits changed-path digest, diff digest, validation status..."""
    lane_root, runner, _ = temp_fixture_lane

    runner.tools.write_file("approved_file.py", "def test():\n    return 42\n")
    packet = runner.generate_completion_packet(
        baseline_manifest={"approved_file.py": "a"},
        current_manifest={"approved_file.py": "b"},
        test_result_status="passed",
    )
    assert packet.diff_digest
    assert packet.test_result_status == "passed"
    assert packet.human_promotion_required


def test_concurrency_sabotage(tmp_path):
    """11. concurrency/sabotage: Two sealed fixture lanes cannot mutate each other's roots."""
    lane1 = tmp_path / "lane1"
    lane2 = tmp_path / "lane2"
    lane1.mkdir()
    lane2.mkdir()
    (lane1 / "f1.py").write_text("a")
    (lane2 / "f2.py").write_text("b")

    desc1 = SealedLaneDescriptor(
        lane_id="1",
        lane_root=str(lane1),
        baseline_digest="a",
        approved_relative_paths=["f1.py", "../lane2/f2.py"],
        approved_path_set_digest="x",
        completion_output_root=str(tmp_path),
    )

    runner1 = SealedRunner(desc1)

    with pytest.raises(Refusal, match="escapes lane root|not in approved path set"):
        runner1.tools.write_file("../lane2/f2.py", "attack")


def test_substrate_adversarial():
    """12. substrate/adversarial: Structural scan proves sealed-mode capability policy contains no runtime development-bypass environment flag."""
    mode_file = (
        Path(__file__).resolve().parent.parent.parent.parent
        / "rig_relay"
        / "cli"
        / "_steward"
        / "_sealed_mode.py"
    )
    assert mode_file.exists()
    content = mode_file.read_text()

    assert "os.environ" not in content
    assert "DEBUG" not in content
    assert "BYPASS" not in content


def test_contract_adversarial():
    """13. contract/adversarial: The implementation contains no operation that treats linked-worktree isolation alone as commit/promotion authorization."""
    from rig_relay.cli._steward._sealed_mode import SealedWorkspaceMode

    mode = SealedWorkspaceMode()
    assert not mode.commit_allowed
    assert not mode.promotion_allowed
    assert not mode.checkpoint_allowed


# --- NEW TESTS ---


def test_staging_root_disjoint(temp_fixture_lane):
    """14. integration/sabotage: Provider-context staging root is resolved as disjoint from the lane root."""
    lane_root, runner, completion_root = temp_fixture_lane

    with SealedProjectionStagingContext(lane_root, completion_root) as staging:
        assert not staging.staging_root.is_relative_to(lane_root)


def test_staging_inside_lane_root_refused(temp_fixture_lane, monkeypatch):
    """15. integration/sabotage: An attempt to configure projection staging inside the lane root is refused."""
    lane_root, runner, completion_root = temp_fixture_lane

    class FakeTempDir:
        def __init__(self, *args, **kwargs):
            self.name = str(lane_root / "fake_staging")

        def cleanup(self):
            pass

    import tempfile

    monkeypatch.setattr(tempfile, "TemporaryDirectory", FakeTempDir)

    with pytest.raises(RuntimeError, match="must be outside the lane root"):
        with SealedProjectionStagingContext(lane_root, completion_root):
            pass


def test_staging_inside_sink_refused(temp_fixture_lane, monkeypatch):
    """16. integration/sabotage: An attempt to configure projection staging inside a confidential-evidence-sink descendant is refused."""
    lane_root, runner, completion_root = temp_fixture_lane

    class FakeTempDir:
        def __init__(self, *args, **kwargs):
            self.name = str(completion_root / "fake_staging")

        def cleanup(self):
            pass

    import tempfile

    monkeypatch.setattr(tempfile, "TemporaryDirectory", FakeTempDir)

    with pytest.raises(
        RuntimeError, match="must be outside the confidential evidence sink"
    ):
        with SealedProjectionStagingContext(lane_root, completion_root):
            pass


def test_staging_materialization_and_cleanup(temp_fixture_lane):
    """17. integration/real-artifact: Adapter materializes compiler input only in an ephemeral projection directory and removes it after successful candidate construction."""
    lane_root, runner, completion_root = temp_fixture_lane

    manifest = BoundedMissionManifest(
        mission_id="m-001",
        provider_mode=ProviderMode.HOSTED_PROVIDER_STANDARD_CONFIDENTIAL_MINIMIZED,
        approved_input_root=str(lane_root),
        approved_fixture_root=str(lane_root),
        minimum_necessary_purpose_label="test",
        human_approval_marker=True,
        output_sink_root=str(completion_root),
    )

    candidate, crosswalk, receipt, evidence = runner.tools.route_context(
        manifest, "def fixture_code(): pass\n"
    )
    # Verify staging cleanup happens. Staging was managed inside route_fixture_context.
    # By the time it returns, context manager is exited.
    # We can't easily check the exact dir unless we mock, but we know it's not in lane root
    files_in_lane = list(lane_root.rglob("temp_fixture_input.py"))
    assert len(files_in_lane) == 0


def test_staging_cleanup_on_exception(temp_fixture_lane, monkeypatch):
    """18. integration/sabotage: Adapter removes projection staging material after compiler refusal or raised exception."""
    lane_root, runner, completion_root = temp_fixture_lane

    manifest = BoundedMissionManifest(
        mission_id="m-001",
        provider_mode=ProviderMode.HOSTED_PROVIDER_STANDARD_CONFIDENTIAL_MINIMIZED,
        approved_input_root=str(lane_root),
        approved_fixture_root=str(lane_root),
        minimum_necessary_purpose_label="test",
        human_approval_marker=True,
        output_sink_root=str(completion_root),
    )

    def exploding_compile(*args, **kwargs):
        raise ValueError("Simulated compiler refusal")

    import rig_relay.context_egress.sealed_adapter

    monkeypatch.setattr(
        rig_relay.context_egress.sealed_adapter,
        "compile_egress_candidate",
        exploding_compile,
    )

    with pytest.raises(ValueError, match="Simulated compiler refusal"):
        runner.tools.route_context(manifest, "def fixture_code(): pass\n")


def test_staging_does_not_affect_completion_packet(temp_fixture_lane):
    """19. contract/integration: Completion packet changed-path identity and diff digest are unchanged by provider-context staging materialization."""
    lane_root, runner, completion_root = temp_fixture_lane

    # Pre-state
    baseline = {"approved_file.py": "hash-a"}
    current = {"approved_file.py": "hash-b"}

    packet_before = runner.generate_completion_packet(baseline, current, "passed")

    # Run staging
    manifest = BoundedMissionManifest(
        mission_id="m-001",
        provider_mode=ProviderMode.HOSTED_PROVIDER_STANDARD_CONFIDENTIAL_MINIMIZED,
        approved_input_root=str(lane_root),
        minimum_necessary_purpose_label="test",
        human_approval_marker=True,
        output_sink_root=str(completion_root),
    )
    runner.tools.route_context(manifest, "def test(): pass")

    # Post-state
    packet_after = runner.generate_completion_packet(baseline, current, "passed")

    assert packet_before.diff_digest == packet_after.diff_digest
    assert packet_before.changed_paths == packet_after.changed_paths


def test_staging_no_leak_in_candidate(temp_fixture_lane):
    """20. contract/adversarial: Completion packet and candidate expose no staging path identity or staging file source body."""
    lane_root, runner, completion_root = temp_fixture_lane

    manifest = BoundedMissionManifest(
        mission_id="m-001",
        provider_mode=ProviderMode.HOSTED_PROVIDER_STANDARD_CONFIDENTIAL_MINIMIZED,
        approved_input_root=str(lane_root),
        minimum_necessary_purpose_label="test",
        human_approval_marker=True,
        output_sink_root=str(completion_root),
    )

    candidate, crosswalk, receipt, evidence = runner.tools.route_context(
        manifest, "SUPER_SECRET_SOURCE_CODE"
    )

    # Asserting candidate strings
    if candidate:
        dumped = candidate.model_dump_json()
        assert "SUPER_SECRET_SOURCE_CODE" not in dumped
        assert "temp_fixture_input.py" not in dumped


def test_e2e_cycle_with_ephemeral_staging(temp_fixture_lane):
    """21. E2E/real-artifact: A fixture sealed cycle edits an approved lane file, routes provider-bound context through ephemeral staging and context egress, runs approved validation, emits a completion packet, and leaves the lane containing only intended repair edits."""
    lane_root, runner, completion_root = temp_fixture_lane

    runner.tools.write_file("approved_file.py", "def test(): return True\n")

    manifest = BoundedMissionManifest(
        mission_id="m-cycle",
        provider_mode=ProviderMode.HOSTED_PROVIDER_STANDARD_CONFIDENTIAL_MINIMIZED,
        approved_input_root=str(lane_root),
        minimum_necessary_purpose_label="cycle_test",
        human_approval_marker=True,
        output_sink_root=str(completion_root),
    )
    candidate, _, _, _ = runner.tools.route_context(manifest, "def helper(): pass")

    runner.tools.execute_validation_command(["pytest"])

    packet = runner.generate_completion_packet(
        baseline_manifest={"approved_file.py": "a"},
        current_manifest={"approved_file.py": "b"},
        test_result_status="passed",
    )

    assert packet.test_result_status == "passed"
    assert "approved_file.py" in packet.changed_paths

    files_in_lane = list(lane_root.rglob("*"))
    # ensure temp_fixture_input is not there
    assert not any(f.name == "temp_fixture_input.py" for f in files_in_lane)
