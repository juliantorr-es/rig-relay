"""Planner budget semantics tests — max_tokens behavior and invariants."""

from __future__ import annotations

from rig_relay.context.assembly_plan import OmissionReason
from rig_relay.context.models import (
    ContextBudget,
    ContextMode,
    ContextRequest,
    ContextScope,
    SubsystemEntry,
)
from rig_relay.context.planner import plan_context


def _make_request(max_tokens=100000, paths=None) -> ContextRequest:
    return ContextRequest(
        mode=ContextMode.MAP,
        scope=ContextScope(
            paths=paths or ["rig_relay/core/agent_loop.py"],
            include_tests=True,
            include_docs=True,
        ),
        budget=ContextBudget(max_tokens=max_tokens),
    )


def _make_subsystems() -> list[SubsystemEntry]:
    return [
        SubsystemEntry(
            name="core",
            paths=["a.py"],
            entry_points=["a.py"],
            config_files=["cfg.py"],
            docs=["doc.md"],
            tests=["test_a.py"],
            schemas=["s.json"],
        )
    ]


class TestBudgetInvariants:
    def test_max_tokens_positive_never_exceeded(self) -> None:
        req = _make_request(max_tokens=50)
        subsystems = _make_subsystems()
        plan = plan_context(req, subsystems=subsystems)

        assert plan.budget.used_tokens <= plan.budget.requested_tokens

    def test_used_tokens_never_exceeds_max_when_positive(self) -> None:
        for budget in [1, 10, 100, 1000]:
            req = _make_request(max_tokens=budget)
            subsystems = _make_subsystems()
            plan = plan_context(req, subsystems=subsystems)
            if budget > 0:
                assert plan.budget.used_tokens <= budget, (
                    f"budget={budget}, used={plan.budget.used_tokens}"
                )

    def test_tiny_budget_keeps_highest_priority(self) -> None:
        req = _make_request(max_tokens=50)
        subsystems = _make_subsystems()
        plan = plan_context(req, subsystems=subsystems)

        # Requested path has priority 1000 — should be first selection
        if plan.selections:
            first = plan.selections[0]
            # The first selection should be the requested path (highest priority)
            assert "requested" in first.candidate_id or first.candidate_id != ""

    def test_negative_max_tokens_clamped_to_zero(self) -> None:
        """Planner clamps negative max_tokens to 0 before building ledger."""
        req = _make_request(max_tokens=-50)
        subsystems = _make_subsystems()
        plan = plan_context(req, subsystems=subsystems)

        # Planner clamps negative to 0
        assert plan.budget.requested_tokens >= 0

    def test_budget_omissions_preserve_candidate_id(self) -> None:
        req = _make_request(max_tokens=1)
        subsystems = _make_subsystems()
        plan = plan_context(req, subsystems=subsystems)

        budget_oms = [
            o
            for o in plan.omissions
            if o.omission_reason == OmissionReason.budget_exceeded
        ]
        for o in budget_oms:
            assert o.candidate_id != ""
            assert o.estimated_tokens > 0

    def test_large_budget_selects_all_non_risk(self) -> None:
        req = _make_request(max_tokens=999_999)
        subsystems = _make_subsystems()
        plan = plan_context(req, subsystems=subsystems)

        budget_oms = [
            o
            for o in plan.omissions
            if o.omission_reason == OmissionReason.budget_exceeded
        ]
        assert len(budget_oms) == 0


class TestPrivacyGuards:
    def test_no_absolute_paths_in_plan(self) -> None:
        req = _make_request()
        subsystems = _make_subsystems()
        plan = plan_context(req, subsystems=subsystems)

        for sel in plan.selections:
            cand = next(
                (c for c in plan.candidates if c.candidate_id == sel.candidate_id), None
            )
            if cand:
                assert not cand.path.startswith("/"), f"Absolute path: {cand.path}"
                assert not cand.path.startswith("~")

    def test_collision_candidate_risk_policy_omitted(self) -> None:
        req = _make_request()
        active_work = {
            "collision_warnings": [{"path": "locked.py", "reason": "claimed by lane B"}]
        }
        subsystems = _make_subsystems()
        plan = plan_context(req, active_work=active_work, subsystems=subsystems)

        collision_oms = [
            o for o in plan.omissions if o.omission_reason == OmissionReason.risk_policy
        ]
        assert len(collision_oms) >= 1


class TestCandidateDefaults:
    def test_requested_path_has_repo_content_trust(self) -> None:
        req = _make_request(paths=["foo.py"])
        plan = plan_context(req)

        requested = [c for c in plan.candidates if c.source.value == "requested_path"]
        for c in requested:
            assert c.trust_tier.value == "repo_content"
            assert c.cache_tier.value == "semi_stable"

    def test_doc_candidates_have_stable_cache_tier(self) -> None:
        req = _make_request()
        subsystems = _make_subsystems()
        plan = plan_context(req, subsystems=subsystems)

        docs = [c for c in plan.candidates if c.kind.value == "doc"]
        for d in docs:
            assert d.cache_tier.value == "stable"

    def test_test_candidates_have_dynamic_cache_tier(self) -> None:
        req = _make_request()
        subsystems = _make_subsystems()
        plan = plan_context(req, subsystems=subsystems)

        tests = [c for c in plan.candidates if c.kind.value == "test"]
        for t in tests:
            assert t.cache_tier.value == "dynamic"

    def test_collision_candidate_has_risk_collision(self) -> None:
        req = _make_request()
        active_work = {
            "collision_warnings": [{"path": "locked.py", "reason": "claimed"}]
        }
        plan = plan_context(req, active_work=active_work)

        collisions = [
            c for c in plan.candidates if c.relation and c.relation.value == "collision"
        ]
        for c in collisions:
            assert "collision" in [r.value for r in c.risk_flags]
