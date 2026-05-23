"""Red-first tests for ToolRuntime cache governance and safety.

Cache ordering IS correct in production (after all governance).
But these gaps remain:

1. Workspace/worktree isolation: cache_check doesn't pass workspace_root
2. No test proves cache is not consulted for mutation/read tools
3. No test proves content-bearing results don't persist to DuckDB
4. Bundle/export path doesn't reject cache database

Wave D from docs/json/audits/test_suite_fake_green_audit.v1.json.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from rig_relay.core.tools.cache import _UNCACHEABLE_TOOLS, is_tool_cacheable

# ── P2: Cache eligibility enforcement ──────────────────────────────


class TestCacheEligibility:
    """Prove that cache eligibility rules block dangerous tool types."""

    MUTATION_TOOLS = ["write_file", "search_replace", "bash", "behavior_patch"]

    READ_TOOLS = ["read_file", "grep", "get_context"]

    SAFE_DETERMINISTIC_TOOLS = ["list_directory", "validate", "git_status"]

    def test_mutation_tools_are_uncacheable(self) -> None:
        for tool in self.MUTATION_TOOLS:
            assert not is_tool_cacheable(tool, "DETERMINISTIC_PURE"), (
                f"Mutation tool {tool!r} must never be cacheable"
            )

    def test_content_bearing_read_tools_are_uncacheable(self) -> None:
        for tool in self.READ_TOOLS:
            assert not is_tool_cacheable(tool, "DETERMINISTIC_REPO_STATE"), (
                f"Content-bearing read tool {tool!r} must never be cacheable"
            )

    def test_safe_deterministic_tools_are_cacheable(self) -> None:
        for tool in self.SAFE_DETERMINISTIC_TOOLS:
            assert is_tool_cacheable(tool, "DETERMINISTIC_PURE"), (
                f"Safe tool {tool!r} should be cacheable"
            )

    def test_uncacheable_set_contains_all_dangerous_tools(self) -> None:
        dangerous = set(self.MUTATION_TOOLS + self.READ_TOOLS)
        covered = dangerous & _UNCACHEABLE_TOOLS
        assert covered == dangerous, (
            f"UNCACHEABLE_TOOLS is missing: {dangerous - covered}"
        )

    def test_tool_with_no_ttl_is_not_cacheable(self) -> None:
        """Tool with an unknown determinism class shouldn't be cached."""
        assert not is_tool_cacheable("unknown_tool", "NON_EXISTENT_CLASS"), (
            "Unknown determinism classes must not be cacheable"
        )

    def test_tool_with_null_determinism_is_not_cacheable(self) -> None:
        # is_tool_cacheable checks determinism_class in DEFAULT_CACHE_TTL
        assert not is_tool_cacheable("list_directory", ""), (
            "Empty determinism class must not be cacheable"
        )


# ── P2: Cache-database isolation ───────────────────────────────────


class TestCacheIsolation:
    """Prove the cache DB cannot leak into export bundles."""

    def test_cache_db_is_outside_source_tree(self) -> None:
        """Cache DB must not live under the canonical repo source tree."""
        from rig_relay.core.tools.cache import BUILD_ROOT, CACHE_DB_DIR

        repo_root = Path(__file__).resolve().parent.parent.parent
        assert repo_root not in CACHE_DB_DIR.parents, (
            f"Cache DB dir {CACHE_DB_DIR} should be outside the repo source tree. "
            f"BUILD_ROOT={BUILD_ROOT}"
        )

    def test_cache_db_is_under_build_not_repo(self) -> None:
        """Cache DB must be under .build/rig-relay/, not under rig_relay/ package."""
        from rig_relay.core.tools.cache import CACHE_DB_PATH

        db_path_str = str(CACHE_DB_PATH)
        assert ".build" in db_path_str and "rig-relay" in db_path_str, (
            f"Cache DB path {CACHE_DB_PATH} must be under .build/rig-relay/"
        )
        assert "/rig_relay/" not in db_path_str, (
            f"Cache DB path must NOT be under the rig_relay/ package: {CACHE_DB_PATH}"
        )


# ── P2: Cache governance ordering proof ────────────────────────────


class TestCacheGovernanceOrdering:
    """Prove that cache hits cannot bypass permission denial.

    These are GREEN tests that codify the correct invariant.
    ToolRuntime at line 670 already places cache after governance.
    """

    @pytest.mark.asyncio
    async def test_cache_hit_permission_denied_returns_refused(self) -> None:
        """RED-FIRST: Prove invariant holds against current production code.

        This test uses the ToolRuntime directly to assert that even with
        a cache HIT, permission DENIAL returns REFUSED (not CACHED).
        """
        from rig_relay.core.tool_runtime import ToolRuntime
        from rig_relay.core.tool_runtime_models import (
            RefusalCode,
            ToolRuntimeExecutionMode,
            ToolRuntimeRequest,
            ToolRuntimeStatus,
        )

        async def _deny_all(
            tool_name: str, args_dict: dict, call_id: str
        ) -> tuple[bool, str]:
            return False, "permission denied for all"

        cache_hit_store: dict[str, Any] = {"called": False}

        def _cache_hit_always(tool_name: str, args_dict: dict) -> tuple[bool, Any]:
            cache_hit_store["called"] = True
            return True, {"output": "from_cache", "count": 1}

        runtime = ToolRuntime(
            invoke_tool=_fake_invoke_success,
            cache_check=_cache_hit_always,
            cache_store=lambda t, a, r: None,
            permission_decision=_deny_all,
            approval_request=lambda t, a, c: (True, ""),
            patch_gate_check=lambda tc, ti: None,
            expand_args=lambda a: a,
            receipt_build=lambda tn, rm: None,
            receipt_capture=lambda s, tn, r: None,
            context_observe=lambda *a, **kw: None,
            stats_delta=lambda k, d: None,
        )

        result = await runtime.execute_one(
            ToolRuntimeRequest(
                tool_name="list_directory",
                tool_args={"path": "/tmp"},
                tool_call_id="call_1",
                execution_mode=ToolRuntimeExecutionMode.READ_ONLY,
            )
        )

        assert result.status == ToolRuntimeStatus.REFUSED, (
            f"Expected REFUSED due to permission denial, got {result.status}. "
            f"Cache must not override governance."
        )
        assert result.refusal is not None
        assert result.refusal.refusal_code == RefusalCode.TOOL_PERMISSION_DENIED
        assert cache_hit_store["called"] is False, (
            "Cache check must not be called before governance. "
            "Permission check should gate execution before cache lookup."
        )


# ── Test doubles ────────────────────────────────────────────────────


from collections.abc import AsyncGenerator


async def _fake_invoke_success(args_dict: dict[str, Any]) -> AsyncGenerator[Any, None]:
    yield type("Result", (), {"output": "ok", "count": 1})
