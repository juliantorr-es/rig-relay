"""Planner failure hardening tests — RepoIndex query-level warnings."""

from __future__ import annotations

from unittest.mock import MagicMock

from rig_relay.context.models import (
    ContextBudget,
    ContextMode,
    ContextRequest,
    ContextScope,
)
from rig_relay.context.planner import plan_context


def _make_request(paths=None) -> ContextRequest:
    resolved_paths = paths if paths is not None else ["rig_relay/core/agent_loop.py"]
    return ContextRequest(
        mode=ContextMode.MAP,
        scope=ContextScope(paths=resolved_paths, include_tests=True, include_docs=True),
        budget=ContextBudget(max_tokens=100000),
    )


class TestRepoIndexQueryWarnings:
    def test_find_tests_failure_warns_planning_continues(self) -> None:
        idx = MagicMock()
        idx.find_tests = MagicMock(side_effect=RuntimeError("db down"))
        idx.find_docs = MagicMock(return_value=[])
        idx.find_schemas = MagicMock(return_value=[])
        idx.find_related = MagicMock(return_value={})

        req = _make_request()
        plan = plan_context(req, repo_index=idx)

        warnings = [w for w in plan.warnings if w.code == "repo_index_query_failed"]
        assert len(warnings) >= 1
        assert any("find_tests" in w.detail for w in warnings)

    def test_find_docs_failure_warns_planning_continues(self) -> None:
        idx = MagicMock()
        idx.find_tests = MagicMock(return_value=[])
        idx.find_docs = MagicMock(side_effect=ValueError("bad query"))
        idx.find_schemas = MagicMock(return_value=[])
        idx.find_related = MagicMock(return_value={})

        req = _make_request()
        plan = plan_context(req, repo_index=idx)

        warnings = [w for w in plan.warnings if w.code == "repo_index_query_failed"]
        assert any("find_docs" in w.detail for w in warnings)

    def test_find_schemas_failure_warns_planning_continues(self) -> None:
        idx = MagicMock()
        idx.find_tests = MagicMock(return_value=[])
        idx.find_docs = MagicMock(return_value=[])
        idx.find_schemas = MagicMock(side_effect=RuntimeError("schema fail"))
        idx.find_related = MagicMock(return_value={})

        req = _make_request()
        plan = plan_context(req, repo_index=idx)

        warnings = [w for w in plan.warnings if w.code == "repo_index_query_failed"]
        assert any("find_schemas" in w.detail for w in warnings)

    def test_find_related_failure_warns_planning_continues(self) -> None:
        idx = MagicMock()
        idx.find_tests = MagicMock(return_value=[])
        idx.find_docs = MagicMock(return_value=[])
        idx.find_schemas = MagicMock(return_value=[])
        idx.find_related = MagicMock(side_effect=RuntimeError("related fail"))

        req = _make_request()
        plan = plan_context(req, repo_index=idx)

        warnings = [w for w in plan.warnings if w.code == "repo_index_query_failed"]
        assert any("find_related" in w.detail for w in warnings)

    def test_repo_index_none_warns_when_paths_requested(self) -> None:
        req = _make_request()
        plan = plan_context(req)

        warnings = [w for w in plan.warnings if w.code == "repo_index_unavailable"]
        assert len(warnings) >= 1

    def test_repo_index_none_no_warning_when_no_paths(self) -> None:
        req = _make_request(paths=[])
        plan = plan_context(req)

        # Without paths, RepoIndex expansion is skipped
        warnings = [w for w in plan.warnings if w.code == "repo_index_unavailable"]
        assert len(warnings) == 0

    def test_error_messages_are_content_light(self) -> None:
        idx = MagicMock()
        idx.find_tests = MagicMock(
            side_effect=RuntimeError("secret db at /Users/leak/path")
        )
        idx.find_docs = MagicMock(return_value=[])
        idx.find_schemas = MagicMock(return_value=[])
        idx.find_related = MagicMock(return_value={})

        req = _make_request()
        plan = plan_context(req, repo_index=idx)

        warnings = [w for w in plan.warnings if w.code == "repo_index_query_failed"]
        for w in warnings:
            # Error strings are truncated to 200 chars
            assert len(w.detail) <= 210
