import ast

from rig_relay.ralph.background_policy import (
    ALLOWED_CAPABILITIES,
    FORBIDDEN_CAPABILITIES,
    RalphBackgroundPolicy,
    default_policy,
)


def test_default_policy_disabled():
    policy = default_policy()
    assert policy.enabled is False
    assert policy.execution_enabled is False
    assert policy.merge_enabled is False
    assert policy.push_enabled is False


def test_enabled_policy_still_disallows_merge():
    policy = RalphBackgroundPolicy(enabled=True)
    assert policy.enabled is True
    assert policy.merge_enabled is False
    assert policy.execution_enabled is False


def test_forbidden_capabilities_not_in_allowed():
    policy = RalphBackgroundPolicy(allowed_capabilities=list(FORBIDDEN_CAPABILITIES))
    violations = policy.validate_capabilities()
    assert len(violations) == len(FORBIDDEN_CAPABILITIES)


def test_valid_capabilities_pass():
    policy = RalphBackgroundPolicy(
        allowed_capabilities=["read_all_lane_projections", "create_isolated_worktree"]
    )
    violations = policy.validate_capabilities()
    assert violations == []


def test_max_active_lanes_enforced():
    policy = RalphBackgroundPolicy(enabled=True, max_active_lanes=2)
    assert policy.active_lanes_allowed(0) is True
    assert policy.active_lanes_allowed(1) is True
    assert policy.active_lanes_allowed(2) is False


def test_pending_review_limit_enforced():
    policy = RalphBackgroundPolicy(enabled=True, max_pending_review_lanes=5)
    assert policy.pending_review_allowed(4) is True
    assert policy.pending_review_allowed(5) is False


def test_disabled_policy_rejects_all_lanes():
    policy = default_policy()
    assert policy.active_lanes_allowed(0) is False
    assert policy.pending_review_allowed(0) is False


def test_no_forbidden_caps_in_allowed_set():
    overlap = set(ALLOWED_CAPABILITIES) & set(FORBIDDEN_CAPABILITIES)
    assert overlap == set(), f"Capabilities in both allowed and forbidden: {overlap}"


def test_boundary_guard_no_git_or_execution():
    paths = [
        "rig_relay/ralph/background_policy.py",
        "rig_relay/ralph/lane_contracts.py",
        "rig_relay/ralph/lane_store.py",
        "rig_relay/ralph/lane_events.py",
        "rig_relay/ralph/lane_proposal.py",
        "rig_relay/ralph/adoption.py",
    ]
    forbidden = {"subprocess", "git", "AgentLoop", "ToolRuntime", "bash", "merge", "push"}
    for p in paths:
        with open(p) as f:
            tree = ast.parse(f.read())
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                name = ast.dump(node.func)
                for f_item in forbidden:
                    assert f_item not in name.lower(), f"{p} calls {f_item}: {name[:120]}"
