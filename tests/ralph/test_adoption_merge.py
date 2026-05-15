from rig_relay.ralph.background_policy import demo_policy, default_policy
from rig_relay.ralph.adoption_merge import execute_adoption_merge


def test_merge_refused_when_policy_disabled():
    result = execute_adoption_merge(
        source_branch="ralph/test",
        target_branch="feature/target",
        source_head_sha="abc123",
        policy=default_policy(),
    )
    assert result.status == "refused"
    assert result.merge_enabled is False


def test_merge_refused_without_human_approval():
    p = demo_policy()
    p.allow_adoption_merge = True
    result = execute_adoption_merge(
        source_branch="ralph/test",
        target_branch="feature/target",
        source_head_sha="abc123",
        policy=p,
    )
    assert result.status == "refused"
    assert "approval" in result.error.lower()


def test_merge_refused_for_non_ralph_branch():
    p = demo_policy()
    p.allow_adoption_merge = True
    result = execute_adoption_merge(
        source_branch="feature/not-ralph",
        target_branch="feature/target",
        source_head_sha="abc",
        policy=p,
        human_approval_id="approval-1",
    )
    assert result.status == "refused"
    assert "not Ralph" in result.error


def test_merge_to_main_requires_preproduction():
    p = demo_policy()
    p.allow_adoption_merge = True
    result = execute_adoption_merge(
        source_branch="ralph/test",
        target_branch="main",
        source_head_sha="abc",
        policy=p,
        human_approval_id="approval-1",
    )
    assert result.status == "refused"
    assert "preproduction" in result.error.lower()


def test_merge_succeeds_in_temp_repo():
    import tempfile, subprocess
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "repo"
        root.mkdir()
        subprocess.run(["git", "-C", str(root), "init"], capture_output=True)
        subprocess.run(["git", "-C", str(root), "config", "user.email", "test@test"], capture_output=True)
        subprocess.run(["git", "-C", str(root), "config", "user.name", "Test"], capture_output=True)
        subprocess.run(["git", "-C", str(root), "commit", "--allow-empty", "-m", "init"], capture_output=True)
        subprocess.run(["git", "-C", str(root), "checkout", "-b", "feature/target"], capture_output=True)
        subprocess.run(["git", "-C", str(root), "commit", "--allow-empty", "-m", "target"], capture_output=True)
        subprocess.run(["git", "-C", str(root), "checkout", "-b", "ralph/test-source"], capture_output=True)
        (root / "src").mkdir()
        (root / "src" / "patch.py").write_text("# ralph patch")
        subprocess.run(["git", "-C", str(root), "add", "."], capture_output=True)
        subprocess.run(["git", "-C", str(root), "commit", "-m", "ralph work"], capture_output=True)
        sha = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True, text=True,
        ).stdout.strip()

        p = demo_policy()
        p.allow_adoption_merge = True
        result = execute_adoption_merge(
            source_branch="ralph/test-source",
            target_branch="feature/target",
            source_head_sha=sha,
            policy=p,
            human_approval_id="approval-1",
            repo_root=root,
        )
        assert result.status == "merged"
        assert result.merge_sha != ""
        assert result.merge_enabled is False
        assert len(result.receipt_sha256) == 64
