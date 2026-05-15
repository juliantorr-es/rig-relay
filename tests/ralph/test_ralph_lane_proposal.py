from rig_relay.ralph.background_policy import RalphBackgroundPolicy
from rig_relay.ralph.lane_proposal import build_lane_proposal


def test_proposal_from_candidate_succeeds():
    policy = RalphBackgroundPolicy(enabled=True, max_active_lanes=2)
    candidate = {
        "candidate_id": "ralph_f1",
        "title": "Fix DirtyFileGuard singleton",
        "source_kind": "architecture_seam",
    }
    lane, violations = build_lane_proposal(candidate=candidate, background_policy=policy)

    assert lane is not None
    assert violations == []
    assert lane.status == "proposed"
    assert lane.branch_name.startswith("ralph/")
    assert lane.worktree_path.startswith(".rig/worktrees/ralph/")
    assert lane.execution_enabled is False
    assert lane.merge_enabled is False


def test_policy_disabled_refuses():
    policy = RalphBackgroundPolicy(enabled=False)
    candidate = {"candidate_id": "r1", "title": "Test"}
    lane, violations = build_lane_proposal(candidate=candidate, background_policy=policy)

    assert lane is None
    assert "disabled" in violations[0]


def test_missing_candidate_refuses():
    policy = RalphBackgroundPolicy(enabled=True)
    lane, violations = build_lane_proposal(candidate=None, background_policy=policy)
    assert lane is None


def test_missing_candidate_id_refuses():
    policy = RalphBackgroundPolicy(enabled=True)
    lane, violations = build_lane_proposal(candidate={"title": "no id"}, background_policy=policy)
    assert lane is None


def test_source_refs_preserved():
    policy = RalphBackgroundPolicy(enabled=True)
    candidate = {"candidate_id": "r1", "title": "Test"}
    lane, _ = build_lane_proposal(
        candidate=candidate,
        background_policy=policy,
        source_report_ids=["rep-1"],
        source_finding_ids=["f1"],
    )
    assert "rep-1" in lane.source_report_ids
    assert "f1" in lane.source_finding_ids


def test_run_state_preserved():
    policy = RalphBackgroundPolicy(enabled=True)
    candidate = {"candidate_id": "r1", "title": "Test"}
    run_state = {"run_id": "run-42", "scan_id": "scan-7"}
    lane, _ = build_lane_proposal(candidate=candidate, background_policy=policy, run_state=run_state)

    assert lane.source_run_id == "run-42"
    assert lane.source_scan_id == "scan-7"


def test_no_git_commands_in_proposal_builder():
    import ast
    with open("rig_relay/ralph/lane_proposal.py") as f:
        tree = ast.parse(f.read())
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)]
    for call in calls:
        name = ast.dump(call.func)
        assert "subprocess" not in name, f"subprocess call found: {name}"
        assert "git" not in name.lower(), f"git call found: {name}"
