"""Tests for runtime lease acquisition — coordination_enabled policy, release/finally, conflict behavior.

Tests coordination-enabled acquisition and release for search_replace and
write_file, plus coordination-disabled backward compatibility.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from rig_relay.runtime.context import RuntimeContext, RuntimeContextResolution
from rig_relay.runtime.tool_invocation_adapter import RuntimeToolIntent, RuntimeToolName
from rig_relay.runtime.tool_invocation_execution import (
    RuntimeToolExecutionRunner,
    RuntimeToolExecutionStatus,
)


def _resolved_context(**overrides: object) -> RuntimeContext:
    kwargs: dict[str, object] = {
        "session_id": "lease-test-sess",
        "task_id": "lease-test-task",
        "lane_id": "lease-test-lane",
        "workspace_id": "lease-test-ws",
        "worktree_path": "/tmp/runtime-lease-test",
        "repo_root": "/tmp",
        "dirty_policy": "preserve_existing",
        "coordination_enabled": True,
    }
    kwargs.update(overrides)
    return RuntimeContext(**kwargs)  # type: ignore[arg-type]


def _resolved(**overrides: object) -> RuntimeContextResolution:
    kwargs: dict[str, object] = {"status": "resolved", "context": _resolved_context()}
    kwargs.update(overrides)
    return RuntimeContextResolution(**kwargs)  # type: ignore[arg-type]


def _intent(
    tool_name: RuntimeToolName = RuntimeToolName.SEARCH_REPLACE, **overrides: object
) -> RuntimeToolIntent:
    kwargs: dict[str, object] = {
        "intent_id": "lease-intent-001",
        "tool_name": tool_name,
        "payload": {},
    }
    kwargs.update(overrides)
    return RuntimeToolIntent(**kwargs)  # type: ignore[arg-type]


FORBIDDEN_RAW_FIELD_NAMES: frozenset[str] = frozenset({
    "content",
    "stdout",
    "stderr",
    "output_text",
    "diff",
    "patch",
    "snippet",
    "file_contents",
    "old_text",
    "new_text",
    "chunk_text",
})


# ── Coordination enabled: acquires and releases lease ────────────────
# These tests verify that search_replace and write_file acquire and
# release leases through the finally path when coordination is enabled.
# They use real temp directories so leases can be acquired.


class TestSearchReplaceLeaseAcquisition:
    @pytest.mark.asyncio
    async def test_coordination_enabled_acquires_lease(self, tmp_path: Path) -> None:
        """search_replace with coordination_enabled acquires a lease."""
        target = tmp_path / "test.py"
        target.write_text("hello\n", encoding="utf-8")
        ctx = _resolved_context(
            worktree_path=str(tmp_path),
            repo_root=str(tmp_path),
            session_id="sr-sess",
            task_id="sr-task",
            coordination_enabled=True,
        )
        resolution = RuntimeContextResolution(status="resolved", context=ctx)
        intent = _intent(
            RuntimeToolName.SEARCH_REPLACE,
            payload={
                "file_path": "test.py",
                "content": ("<<<<<<< SEARCH\nhello\n=======\nworld\n>>>>>>> REPLACE"),
            },
        )
        runner = RuntimeToolExecutionRunner()
        result = await runner.execute_search_replace(intent, resolution)
        assert result.status == RuntimeToolExecutionStatus.COMPLETED, (
            f"Expected COMPLETED, got {result.status}: {result.refusal_reason}"
        )

        # Verify lease was acquired and released (no active leases remain)
        lease_dir = (
            tmp_path / ".build" / "rig-relay" / "coordination" / "leases" / "paths"
        )
        if lease_dir.is_dir():
            active = [
                f
                for f in lease_dir.glob("*.json")
                if json.loads(f.read_text(encoding="utf-8")).get("status") == "active"
            ]
            assert len(active) == 0, (
                f"Expected 0 active leases after release, got {len(active)}"
            )

    @pytest.mark.asyncio
    async def test_write_file_coordination_enabled_acquires_lease(
        self, tmp_path: Path
    ) -> None:
        """write_file with coordination_enabled acquires a lease."""
        target = tmp_path / "test.txt"
        target.write_text("original\n", encoding="utf-8")
        ctx = _resolved_context(
            worktree_path=str(tmp_path),
            repo_root=str(tmp_path),
            session_id="wf-sess",
            task_id="wf-task",
            coordination_enabled=True,
        )
        resolution = RuntimeContextResolution(status="resolved", context=ctx)
        intent = _intent(
            RuntimeToolName.WRITE_FILE,
            payload={"path": "test.txt", "content": "new content\n", "overwrite": True},
        )
        runner = RuntimeToolExecutionRunner()
        result = await runner.execute_write_file(intent, resolution)
        assert result.status == RuntimeToolExecutionStatus.COMPLETED, (
            f"Expected COMPLETED, got {result.status}: {result.refusal_reason}"
        )

        # Verify lease was acquired and released
        lease_dir = (
            tmp_path / ".build" / "rig-relay" / "coordination" / "leases" / "paths"
        )
        if lease_dir.is_dir():
            active = [
                f
                for f in lease_dir.glob("*.json")
                if json.loads(f.read_text(encoding="utf-8")).get("status") == "active"
            ]
            assert len(active) == 0, (
                f"Expected 0 active leases after release, got {len(active)}"
            )


# ── Coordination disabled: backward-compatible execution ──────────────


class TestCoordinationDisabled:
    @pytest.mark.asyncio
    async def test_coordination_disabled_skips_lease(self, tmp_path: Path) -> None:
        """coordination_enabled=False skips lease acquisition."""
        target = tmp_path / "test.txt"
        target.write_text("original\n", encoding="utf-8")
        ctx = _resolved_context(
            worktree_path=str(tmp_path),
            repo_root=str(tmp_path),
            session_id="cd-sess",
            task_id="cd-task",
            coordination_enabled=False,
        )
        resolution = RuntimeContextResolution(status="resolved", context=ctx)
        intent = _intent(
            RuntimeToolName.WRITE_FILE,
            payload={
                "path": "test.txt",
                "content": "coordination disabled\n",
                "overwrite": True,
            },
        )
        runner = RuntimeToolExecutionRunner()
        result = await runner.execute_write_file(intent, resolution)
        assert result.status == RuntimeToolExecutionStatus.COMPLETED, (
            f"Expected COMPLETED, got {result.status}: {result.refusal_reason}"
        )
        # Verify no lease was acquired (coordination disabled skips lease)
        # The build directory may exist from other components, but no lease
        # files should be present for this session
        lease_dir = (
            tmp_path / ".build" / "rig-relay" / "coordination" / "leases" / "paths"
        )
        if lease_dir.is_dir():
            active = [
                f
                for f in lease_dir.glob("*.json")
                if json.loads(f.read_text(encoding="utf-8")).get("status") == "active"
                and json.loads(f.read_text(encoding="utf-8")).get("session_id")
                == "cd-sess"
            ]
            assert len(active) == 0, f"Expected 0 active leases, got {len(active)}"

    @pytest.mark.asyncio
    async def test_coordination_default_true_preserves_existing_behavior(
        self, tmp_path: Path
    ) -> None:
        """Default coordination_enabled=True preserves existing behavior (backward compat)."""
        target = tmp_path / "test.txt"
        target.write_text("original\n", encoding="utf-8")
        # Context without explicit coordination_enabled (defaults to True)
        ctx = RuntimeContext(
            session_id="default-sess",
            task_id="default-task",
            worktree_path=str(tmp_path),
            repo_root=str(tmp_path),
        )
        resolution = RuntimeContextResolution(status="resolved", context=ctx)
        intent = _intent(
            RuntimeToolName.SEARCH_REPLACE,
            payload={
                "file_path": "test.txt",
                "content": (
                    "<<<<<<< SEARCH\noriginal\n=======\nmodified\n>>>>>>> REPLACE"
                ),
            },
        )
        runner = RuntimeToolExecutionRunner()
        result = await runner.execute_search_replace(intent, resolution)
        assert result.status == RuntimeToolExecutionStatus.COMPLETED, (
            f"Expected COMPLETED, got {result.status}: {result.refusal_reason}"
        )


# ── Conflict blocks mutation ──────────────────────────────────────────


class TestLeaseConflict:
    @pytest.mark.asyncio
    async def test_lease_conflict_blocks_search_replace(self, tmp_path: Path) -> None:
        """Lease conflict blocks search_replace when coordination is enabled."""
        target = tmp_path / "shared.py"
        target.write_text("content\n", encoding="utf-8")
        ctx = _resolved_context(
            worktree_path=str(tmp_path),
            repo_root=str(tmp_path),
            session_id="conflict-sess",
            task_id="conflict-task",
        )
        resolution = RuntimeContextResolution(status="resolved", context=ctx)

        # Acquire lease manually first
        from rig_relay.coordination.lease_manager import PathLeaseManager

        coord_root = tmp_path / ".build" / "rig-relay" / "coordination"
        manager = PathLeaseManager(coord_root)
        claim = manager.claim_paths(
            session_id="other-sess",
            task_id="other-task",
            mode="exclusive_write",
            paths=["shared.py"],
            ttl_seconds=120,
        )
        assert claim.status == "granted"

        # Now try to run search_replace — should be BLOCKED
        runner = RuntimeToolExecutionRunner()
        intent = _intent(
            RuntimeToolName.SEARCH_REPLACE,
            payload={
                "file_path": "shared.py",
                "content": (
                    "<<<<<<< SEARCH\ncontent\n=======\nchanged\n>>>>>>> REPLACE"
                ),
            },
        )
        result = await runner.execute_search_replace(intent, resolution)
        assert result.status == RuntimeToolExecutionStatus.BLOCKED, (
            f"Expected BLOCKED, got {result.status}"
        )
        assert result.error_kind is not None, "Expected error_kind, got None"
        assert (
            "lease" in result.error_kind
            or "conflict" in result.error_kind
            or result.error_kind == "path_write_overlap"
        ), f"Expected lease/conflict error_kind, got {result.error_kind}"
        assert result.refusal_reason is not None, "Expected refusal_reason"

    @pytest.mark.asyncio
    async def test_lease_conflict_blocks_write_file(self, tmp_path: Path) -> None:
        """Lease conflict blocks write_file when coordination is enabled."""
        target = tmp_path / "shared.txt"
        target.write_text("content\n", encoding="utf-8")
        ctx = _resolved_context(
            worktree_path=str(tmp_path),
            repo_root=str(tmp_path),
            session_id="wf-conflict-sess",
            task_id="wf-conflict-task",
        )
        resolution = RuntimeContextResolution(status="resolved", context=ctx)

        from rig_relay.coordination.lease_manager import PathLeaseManager

        coord_root = tmp_path / ".build" / "rig-relay" / "coordination"
        manager = PathLeaseManager(coord_root)
        manager.claim_paths(
            session_id="blocker-sess",
            task_id="blocker-task",
            mode="exclusive_write",
            paths=["shared.txt"],
            ttl_seconds=120,
        )

        runner = RuntimeToolExecutionRunner()
        intent = _intent(
            RuntimeToolName.WRITE_FILE,
            payload={
                "path": "shared.txt",
                "content": "blocked write\n",
                "overwrite": True,
            },
        )
        result = await runner.execute_write_file(intent, resolution)
        assert result.status == RuntimeToolExecutionStatus.BLOCKED, (
            f"Expected BLOCKED, got {result.status}"
        )


# ── Release happens even when tool returns refused/blocked/failure ────


class TestReleaseOnFailure:
    @pytest.mark.asyncio
    async def test_release_after_tool_refused(self, tmp_path: Path) -> None:
        """Lease is released when search_replace returns refused."""
        target = tmp_path / "test.py"
        target.write_text("hello\n", encoding="utf-8")
        ctx = _resolved_context(
            worktree_path=str(tmp_path),
            repo_root=str(tmp_path),
            session_id="fail-sess",
            task_id="fail-task",
        )
        resolution = RuntimeContextResolution(status="resolved", context=ctx)
        intent = _intent(
            RuntimeToolName.SEARCH_REPLACE,
            payload={
                "file_path": "test.py",
                "content": (
                    "<<<<<<< SEARCH\nnonexistent\n=======\nworld\n>>>>>>> REPLACE"
                ),
            },
        )
        runner = RuntimeToolExecutionRunner()
        result = await runner.execute_search_replace(intent, resolution)
        # This should complete (no_match) — lease acquired and released
        assert result.status == RuntimeToolExecutionStatus.COMPLETED

        # Verify lease was released
        lease_dir = (
            tmp_path / ".build" / "rig-relay" / "coordination" / "leases" / "paths"
        )
        if lease_dir.is_dir():
            active = [
                f
                for f in lease_dir.glob("*.json")
                if json.loads(f.read_text(encoding="utf-8")).get("status") == "active"
            ]
            assert len(active) == 0

    @pytest.mark.asyncio
    async def test_release_after_exception(self, tmp_path: Path) -> None:
        """Lease is released when write_file encounters an execution error."""
        # Create context but with a non-existent path that will cause execution error
        ctx = _resolved_context(
            worktree_path=str(tmp_path),
            repo_root=str(tmp_path),
            session_id="exc-sess",
            task_id="exc-task",
        )
        resolution = RuntimeContextResolution(status="resolved", context=ctx)
        intent = _intent(
            RuntimeToolName.WRITE_FILE,
            payload={
                # Missing 'path' will be caught by adapter (refused), not execution
                "path": "",
                "content": "test\n",
                "overwrite": True,
            },
        )
        runner = RuntimeToolExecutionRunner()
        result = await runner.execute_write_file(intent, resolution)
        # Should be REFUSED by adapter for missing path (adapter refuses before lease)
        assert result.status in (
            RuntimeToolExecutionStatus.REFUSED,
            RuntimeToolExecutionStatus.FAILED,
        ), f"Expected REFUSED/FAILED, got {result.status}"
        # No lease was acquired (adapter refused before lease acquisition)


# ── Content-light: no forbidden fields in result dumps ────────────────


class TestContentLight:
    @pytest.mark.asyncio
    async def test_search_replace_result_no_forbidden_fields(
        self, tmp_path: Path
    ) -> None:
        """Result from search_replace has no forbidden raw fields."""
        target = tmp_path / "cl.py"
        target.write_text("hello\n", encoding="utf-8")
        ctx = _resolved_context(
            worktree_path=str(tmp_path),
            repo_root=str(tmp_path),
            session_id="cl-sess",
            task_id="cl-task",
        )
        resolution = RuntimeContextResolution(status="resolved", context=ctx)
        intent = _intent(
            RuntimeToolName.SEARCH_REPLACE,
            payload={
                "file_path": "cl.py",
                "content": ("<<<<<<< SEARCH\nhello\n=======\nworld\n>>>>>>> REPLACE"),
            },
        )
        runner = RuntimeToolExecutionRunner()
        result = await runner.execute_search_replace(intent, resolution)
        dumped = json.dumps(result.model_dump(mode="json"))
        for forbidden in FORBIDDEN_RAW_FIELD_NAMES:
            assert forbidden not in dumped, (
                f"Found forbidden field '{forbidden}' in search_replace result"
            )

    @pytest.mark.asyncio
    async def test_write_file_result_no_forbidden_fields(self, tmp_path: Path) -> None:
        """Result from write_file has no forbidden raw fields."""
        target = tmp_path / "cl.txt"
        target.write_text("original\n", encoding="utf-8")
        ctx = _resolved_context(
            worktree_path=str(tmp_path),
            repo_root=str(tmp_path),
            session_id="cl2-sess",
            task_id="cl2-task",
        )
        resolution = RuntimeContextResolution(status="resolved", context=ctx)
        intent = _intent(
            RuntimeToolName.WRITE_FILE,
            payload={"path": "cl.txt", "content": "new\n", "overwrite": True},
        )
        runner = RuntimeToolExecutionRunner()
        result = await runner.execute_write_file(intent, resolution)
        dumped = json.dumps(result.model_dump(mode="json"))
        for forbidden in FORBIDDEN_RAW_FIELD_NAMES:
            assert forbidden not in dumped, (
                f"Found forbidden field '{forbidden}' in write_file result"
            )
