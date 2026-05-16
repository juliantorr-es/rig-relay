"""ContextPlanner tests — discovery, expansion, scoring, budget enforcement.

Uses Lane A's assembly_plan.py models.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from rig_relay.context.assembly_plan import (
    CandidateKind,
    CandidateSource,
    ContextAssemblyPlan,
    ContextCandidate,
    OmissionReason,
)
from rig_relay.context.models import (
    ContextBudget,
    ContextMode,
    ContextRequest,
    ContextScope,
    SubsystemEntry,
)
from rig_relay.context.planner import plan_context


def _make_request(**kwargs) -> ContextRequest:
    defaults = {
        "mode": ContextMode.MAP,
        "scope": ContextScope(
            paths=["rig_relay/core/agent_loop.py"],
            include_tests=True,
            include_docs=True,
            include_receipts=False,
        ),
        "budget": ContextBudget(max_tokens=100000),
    }
    defaults.update(kwargs)
    return ContextRequest(**defaults)


def _make_subsystems() -> list[SubsystemEntry]:
    return [
        SubsystemEntry(
            name="core",
            paths=["rig_relay/core/agent_loop.py"],
            entry_points=["rig_relay/core/agent_loop.py"],
            config_files=["rig_relay/core/config/_settings.py"],
            docs=["docs/governance/agent-loop-boundary.md"],
            tests=["tests/core/test_agent.py"],
            schemas=["docs/schemas/rig.context_request.v1.schema.json"],
        ),
        SubsystemEntry(
            name="desktop",
            paths=["rig_relay/desktop/websocket_server.py"],
            entry_points=["rig_relay/desktop/websocket_server.py"],
            config_files=["rig_relay/desktop/config.py"],
            docs=["docs/desktop/architecture.md"],
            tests=["tests/desktop/test_websocket.py"],
            schemas=[],
        ),
    ]


def _make_repo_index():
    idx = MagicMock()
    idx.find_tests = MagicMock(
        return_value=["tests/core/test_agent.py", "tests/more/test_extra.py"]
    )
    idx.find_docs = MagicMock(return_value=["docs/governance/agent-loop-boundary.md"])
    idx.find_schemas = MagicMock(
        return_value=["docs/schemas/rig.context_request.v1.schema.json"]
    )
    idx.find_related = MagicMock(
        return_value={
            "same_package": ["rig_relay/core/tool_runtime.py"],
            "doc": ["docs/core/README.md"],
        }
    )
    return idx


# ── Discovery tests ─────────────────────────────────────────────


class TestCandidateDiscovery:
    def test_requested_path_selected_first(self) -> None:
        req = _make_request()
        subsystems = _make_subsystems()
        plan = plan_context(req, subsystems=subsystems)

        assert len(plan.candidates) > 0
        requested = [
            c for c in plan.candidates if c.source == CandidateSource.requested_path
        ]
        assert len(requested) >= 1
        assert requested[0].priority == 1000

    def test_subsystem_config_discovered(self) -> None:
        req = _make_request()
        subsystems = _make_subsystems()
        plan = plan_context(req, subsystems=subsystems)

        configs = [c for c in plan.candidates if c.kind == CandidateKind.config]
        assert len(configs) >= 1

    def test_subsystem_docs_discovered(self) -> None:
        req = _make_request()
        subsystems = _make_subsystems()
        plan = plan_context(req, subsystems=subsystems)

        docs = [c for c in plan.candidates if c.kind == CandidateKind.doc]
        assert len(docs) >= 1

    def test_subsystem_tests_discovered(self) -> None:
        req = _make_request()
        subsystems = _make_subsystems()
        plan = plan_context(req, subsystems=subsystems)

        tests = [c for c in plan.candidates if c.kind == CandidateKind.test]
        assert len(tests) >= 1


# ── Scope tests ─────────────────────────────────────────────────


class TestScopeFlags:
    def test_include_tests_false_omits_tests(self) -> None:
        req = _make_request(
            scope=ContextScope(
                paths=["rig_relay/core/agent_loop.py"], include_tests=False
            )
        )
        subsystems = _make_subsystems()
        plan = plan_context(req, subsystems=subsystems)

        test_omissions = [
            o
            for o in plan.omissions
            if o.omission_reason == OmissionReason.disabled_by_scope
        ]
        assert len(test_omissions) >= 1

    def test_include_docs_false_omits_docs(self) -> None:
        req = _make_request(
            scope=ContextScope(
                paths=["rig_relay/core/agent_loop.py"], include_docs=False
            )
        )
        subsystems = _make_subsystems()
        plan = plan_context(req, subsystems=subsystems)

        doc_omissions = [
            o
            for o in plan.omissions
            if o.omission_reason == OmissionReason.disabled_by_scope
        ]
        assert len(doc_omissions) >= 1

    def test_include_tests_true_selects_tests(self) -> None:
        req = _make_request(
            scope=ContextScope(
                paths=["rig_relay/core/agent_loop.py"], include_tests=True
            )
        )
        subsystems = _make_subsystems()
        plan = plan_context(req, subsystems=subsystems)

        test_ids = {s.candidate_id for s in plan.selections}
        test_candidates = [
            c
            for c in plan.candidates
            if c.kind == CandidateKind.test and c.candidate_id in test_ids
        ]
        assert len(test_candidates) >= 1


# ── RepoIndex tests ─────────────────────────────────────────────


class TestRepoIndexExpansion:
    def test_repo_index_expands_tests(self) -> None:
        req = _make_request(
            scope=ContextScope(
                paths=["rig_relay/core/agent_loop.py"], include_tests=True
            )
        )
        idx = _make_repo_index()
        plan = plan_context(req, repo_index=idx)

        idx_tests = [
            c
            for c in plan.candidates
            if c.source == CandidateSource.repo_index and c.kind == CandidateKind.test
        ]
        assert len(idx_tests) >= 1

    def test_repo_index_expands_docs(self) -> None:
        req = _make_request(
            scope=ContextScope(
                paths=["rig_relay/core/agent_loop.py"], include_docs=True
            )
        )
        idx = _make_repo_index()
        plan = plan_context(req, repo_index=idx)

        idx_docs = [
            c
            for c in plan.candidates
            if c.source == CandidateSource.repo_index and c.kind == CandidateKind.doc
        ]
        assert len(idx_docs) >= 1

    def test_repo_index_expands_schemas(self) -> None:
        req = _make_request(scope=ContextScope(paths=["rig_relay/core/agent_loop.py"]))
        idx = _make_repo_index()
        plan = plan_context(req, repo_index=idx)

        idx_schemas = [
            c
            for c in plan.candidates
            if c.source == CandidateSource.repo_index and c.kind == CandidateKind.schema
        ]
        assert len(idx_schemas) >= 1

    def test_repo_index_expands_related(self) -> None:
        req = _make_request(scope=ContextScope(paths=["rig_relay/core/agent_loop.py"]))
        idx = _make_repo_index()
        plan = plan_context(req, repo_index=idx)

        related = [
            c
            for c in plan.candidates
            if c.relation and c.relation.value == "same_package"
        ]
        assert len(related) >= 1

    def test_repo_index_unavailable_emits_warning(self) -> None:
        req = _make_request(scope=ContextScope(paths=["rig_relay/core/agent_loop.py"]))
        plan = plan_context(req)

        warnings = [w for w in plan.warnings if w.code == "repo_index_unavailable"]
        assert len(warnings) >= 1


# ── Budget tests ────────────────────────────────────────────────


class TestBudgetEnforcement:
    def test_budget_exceeded_records_omissions(self) -> None:
        req = _make_request(budget=ContextBudget(max_tokens=1))
        subsystems = _make_subsystems()
        plan = plan_context(req, subsystems=subsystems)

        budget_oms = [
            o
            for o in plan.omissions
            if o.omission_reason == OmissionReason.budget_exceeded
        ]
        assert len(budget_oms) >= 1

    def test_large_budget_selects_all(self) -> None:
        req = _make_request(budget=ContextBudget(max_tokens=999_999))
        subsystems = _make_subsystems()
        plan = plan_context(req, subsystems=subsystems)

        budget_oms = [
            o
            for o in plan.omissions
            if o.omission_reason == OmissionReason.budget_exceeded
        ]
        assert len(budget_oms) == 0

    def test_budget_ledger_consistent(self) -> None:
        req = _make_request(budget=ContextBudget(max_tokens=500))
        subsystems = _make_subsystems()
        plan = plan_context(req, subsystems=subsystems)

        assert plan.budget.requested_tokens == 500
        assert plan.budget.used_tokens <= 500 + 50
        assert plan.budget.remaining_tokens >= 0


# ── Collision tests ─────────────────────────────────────────────


class TestCollisionHandling:
    def test_collision_creates_omission(self) -> None:
        req = _make_request()
        active_work = {
            "collision_warnings": [
                {"path": "rig_relay/core/agent_loop.py", "reason": "claimed by lane B"}
            ]
        }
        plan = plan_context(req, active_work=active_work, subsystems=_make_subsystems())

        collision_oms = [
            o for o in plan.omissions if o.omission_reason == OmissionReason.risk_policy
        ]
        assert len(collision_oms) >= 1


# ── Determinism tests ───────────────────────────────────────────


class TestDeterminism:
    def test_same_input_same_plan_hash(self) -> None:
        req = _make_request()
        subsystems = _make_subsystems()

        plan1 = plan_context(req, subsystems=subsystems)
        plan2 = plan_context(req, subsystems=subsystems)

        assert plan1.plan_sha256 == plan2.plan_sha256

    def test_different_paths_different_hash(self) -> None:
        req1 = _make_request(scope=ContextScope(paths=["rig_relay/core/agent_loop.py"]))
        req2 = _make_request(
            scope=ContextScope(paths=["rig_relay/desktop/websocket_server.py"])
        )
        subsystems = _make_subsystems()

        plan1 = plan_context(req1, subsystems=subsystems)
        plan2 = plan_context(req2, subsystems=subsystems)

        assert plan1.plan_sha256 != plan2.plan_sha256


# ── Privacy tests ───────────────────────────────────────────────


class TestPlanPrivacy:
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

    def test_no_raw_file_contents_in_plan(self) -> None:
        req = _make_request()
        subsystems = _make_subsystems()
        plan = plan_context(req, subsystems=subsystems)

        plan_dict = plan.model_dump_json()
        assert "raw_content" not in plan_dict
        assert "file_body" not in plan_dict

    def test_plan_is_json_safe(self) -> None:
        req = _make_request()
        subsystems = _make_subsystems()
        plan = plan_context(req, subsystems=subsystems)

        assert json.dumps(plan.model_dump(mode="json"))


# ── Model tests ─────────────────────────────────────────────────


class TestAssemblyPlanModels:
    def test_candidate_extra_forbid(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            ContextCandidate(
                path="test.py",
                kind=CandidateKind.source,
                source=CandidateSource.requested_path,
                relation="direct",  # type: ignore[arg-type]
                secret_field="leaked",  # type: ignore[call-arg]
            )

    def test_plan_extra_forbid(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            ContextAssemblyPlan(
                raw_messages="leaked"  # type: ignore[call-arg]
            )

    def test_candidate_id_is_deterministic(self) -> None:
        c1 = ContextCandidate(
            path="a.py",
            kind=CandidateKind.source,
            source=CandidateSource.requested_path,
            relation="direct",  # type: ignore[arg-type]
        )
        c2 = ContextCandidate(
            path="a.py",
            kind=CandidateKind.source,
            source=CandidateSource.requested_path,
            relation="direct",  # type: ignore[arg-type]
        )
        assert c1.candidate_id == c2.candidate_id
