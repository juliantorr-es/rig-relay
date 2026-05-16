from __future__ import annotations

import ast
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]

from rig_relay.ralph.background_policy import (
    ALLOWED_CAPABILITIES,
    FORBIDDEN_CAPABILITIES,
    RalphBackgroundPolicy,
    default_policy,
    demo_policy,
)


def test_default_policy_disabled():
    policy = default_policy()
    assert policy.enabled is False
    assert policy.allow_isolated_worktree_creation is False
    assert policy.allow_adoption_merge is False
    assert policy.allow_push_to_preproduction is False


def test_enabled_policy_still_disallows_merge():
    policy = RalphBackgroundPolicy(enabled=True)
    assert policy.enabled is True
    assert policy.allow_adoption_merge is False
    assert policy.allow_push_to_preproduction is False


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
    assert policy.active_lanes_allowed(1) is True
    assert policy.active_lanes_allowed(2) is False


def test_no_forbidden_caps_in_allowed_set():
    overlap = set(ALLOWED_CAPABILITIES) & set(FORBIDDEN_CAPABILITIES)
    assert overlap == set(), f"Capabilities in both allowed and forbidden: {overlap}"


def test_boundary_guard_no_git_or_execution():
    paths = [
        _REPO_ROOT / "rig_relay/ralph/background_policy.py",
        _REPO_ROOT / "rig_relay/ralph/lane_contracts.py",
        _REPO_ROOT / "rig_relay/ralph/lane_store.py",
        _REPO_ROOT / "rig_relay/ralph/lane_events.py",
        _REPO_ROOT / "rig_relay/ralph/lane_proposal.py",
        _REPO_ROOT / "rig_relay/ralph/adoption.py",
    ]
    forbidden = {
        "subprocess",
        "git",
        "AgentLoop",
        "ToolRuntime",
        "bash",
        "merge",
        "push",
    }
    for p in paths:
        with open(p) as f:
            tree = ast.parse(f.read())
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                name = ast.dump(node.func)
                for f_item in forbidden:
                    assert f_item not in name.lower(), (
                        f"{p} calls {f_item}: {name[:120]}"
                    )


# ── demo_policy convenience tests ────────────────────────────────


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


def test_disabled_policy_rejects_all():
    p = default_policy()
    assert p.can_create_worktree() is False
    assert p.can_execute_in_lane() is False
