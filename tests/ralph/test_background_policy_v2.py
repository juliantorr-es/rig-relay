from rig_relay.ralph.background_policy import demo_policy, default_policy


def test_default_all_disabled():
    p = default_policy()
    assert p.enabled is False
    assert p.allow_isolated_worktree_creation is False
    assert p.allow_isolated_lane_execution is False
    assert p.allow_ralph_branch_commits is False
    assert p.allow_adoption_merge is False
    assert p.allow_push_to_preproduction is False


def test_demo_enables_lane_work_not_merge():
    p = demo_policy()
    assert p.enabled is True
    assert p.allow_isolated_worktree_creation is True
    assert p.allow_isolated_lane_execution is True
    assert p.allow_ralph_branch_commits is True
    assert p.allow_adoption_merge is False
    assert p.allow_push_to_preproduction is False


def test_can_create_worktree_gated():
    assert default_policy().can_create_worktree() is False
    assert demo_policy().can_create_worktree() is True


def test_can_execute_in_lane_gated():
    assert default_policy().can_execute_in_lane() is False
    assert demo_policy().can_execute_in_lane() is True


def test_can_commit_to_lane_gated():
    assert default_policy().can_commit_to_lane() is False
    assert demo_policy().can_commit_to_lane() is True


def test_can_merge_gated():
    assert default_policy().can_merge_adoption() is False
    assert demo_policy().can_merge_adoption() is False


def test_can_push_gated():
    assert default_policy().can_push_preproduction() is False
    assert demo_policy().can_push_preproduction() is False


def test_max_active_lanes():
    p = demo_policy()
    assert p.active_lanes_allowed(0) is True
    assert p.active_lanes_allowed(2) is False


def test_disabled_policy_rejects_all():
    p = default_policy()
    assert p.active_lanes_allowed(0) is False
    assert p.can_create_worktree() is False
    assert p.can_execute_in_lane() is False
