"""Integration tests for rig.get_context digest mode wiring."""

from __future__ import annotations

from pathlib import Path

import pytest

from rig_relay.context.compiler import execute
from rig_relay.context.models import ContextMode, ContextRequest, ContextScope
from rig_relay.coordination import CoordinationStore, reset_path_salt_for_testing


@pytest.fixture
def coordination_store(tmp_path: Path) -> CoordinationStore:
    reset_path_salt_for_testing()
    store_root = tmp_path / ".build" / "rig-relay" / "coordination"
    store = CoordinationStore(store_root)
    return store


def _register_session_and_task(store: CoordinationStore) -> None:
    """Register a session and claim a write-mode task for test setup."""
    from rig_relay.coordination.models import CoordinationSession

    session = CoordinationSession(
        session_id="session-abc",
        task_id="task-001",
        agent_profile="agent-1",
        status="active",
    )
    store._write_json(
        store._session_path("session-abc"), session.model_dump(exclude_none=True)
    )

    result = store.claim_task(
        session_id="session-abc",
        task_id="task-001",
        claim_kind="edit",
        ttl_seconds=3600,
        scope={"allowed_paths": ["src/main.py"]},
    )
    assert result.allowed

    res_result = store.reserve_paths(
        session_id="session-abc",
        task_id="task-001",
        mode="write",
        paths=["src/main.py", "src/utils.py"],
        ttl_seconds=3600,
    )
    assert res_result.allowed


class TestGetContextDigestMode:
    def test_digest_mode_returns_packet(
        self, tmp_path: Path, coordination_store: CoordinationStore
    ) -> None:
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "main.py").write_text("# main")
        _register_session_and_task(coordination_store)

        request = ContextRequest(
            mode=ContextMode.DIGEST,
            scope=ContextScope(
                include_receipts=False, include_tests=False, include_docs=False
            ),
        )
        packet = execute(request, workspace_root=tmp_path)

        assert packet is not None
        assert packet.mode == ContextMode.DIGEST
        assert packet.repo is not None
        assert isinstance(packet.active_work, dict)

    def test_digest_has_active_lanes(
        self, tmp_path: Path, coordination_store: CoordinationStore
    ) -> None:
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "main.py").write_text("# main")
        _register_session_and_task(coordination_store)

        request = ContextRequest(
            mode=ContextMode.DIGEST,
            scope=ContextScope(
                include_receipts=False, include_tests=False, include_docs=False
            ),
        )
        packet = execute(request, workspace_root=tmp_path)

        lanes = packet.active_work.get("lanes", [])
        assert len(lanes) >= 1, f"Digest mode should include active lanes, got {lanes}"
        session_ids = {lane.get("agent_id", "") for lane in lanes}
        assert "session-abc" in session_ids

    def test_digest_has_do_not_touch(
        self, tmp_path: Path, coordination_store: CoordinationStore
    ) -> None:
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "main.py").write_text("# main")
        _register_session_and_task(coordination_store)

        request = ContextRequest(
            mode=ContextMode.DIGEST,
            scope=ContextScope(
                include_receipts=False, include_tests=False, include_docs=False
            ),
        )
        packet = execute(request, workspace_root=tmp_path)

        do_not_touch = packet.do_not_touch
        assert len(do_not_touch) >= 1, (
            f"Digest mode should include do_not_touch entries, got {do_not_touch}"
        )

        dnt_paths = {r.path for r in do_not_touch}
        assert "src/main.py" in dnt_paths or "src/utils.py" in dnt_paths

    def test_digest_cache_hit(
        self, tmp_path: Path, coordination_store: CoordinationStore
    ) -> None:
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "main.py").write_text("# main")
        _register_session_and_task(coordination_store)

        request = ContextRequest(
            mode=ContextMode.DIGEST,
            scope=ContextScope(
                include_receipts=False, include_tests=False, include_docs=False
            ),
        )
        p1 = execute(request, workspace_root=tmp_path)
        p2 = execute(request, workspace_root=tmp_path)

        assert p1.mode == ContextMode.DIGEST
        assert p2.mode == ContextMode.DIGEST
        assert p1.active_work == p2.active_work

    def test_digest_empty_store_returns_packet(self, tmp_path: Path) -> None:
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "main.py").write_text("# main")
        store_dir = tmp_path / ".build" / "rig-relay" / "coordination"
        store_dir.mkdir(parents=True, exist_ok=True)

        request = ContextRequest(
            mode=ContextMode.DIGEST,
            scope=ContextScope(
                include_receipts=False, include_tests=False, include_docs=False
            ),
        )
        packet = execute(request, workspace_root=tmp_path)

        assert packet is not None
        assert packet.mode == ContextMode.DIGEST
        lanes = packet.active_work.get("lanes", [])
        assert lanes == []

    def test_digest_with_include_receipts(
        self, tmp_path: Path, coordination_store: CoordinationStore
    ) -> None:
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "main.py").write_text("# main")
        _register_session_and_task(coordination_store)

        receipts_dir = tmp_path / ".build" / "rig-relay" / "coordination" / "receipts"
        receipts_dir.mkdir(parents=True, exist_ok=True)
        (receipts_dir / "test.receipt").write_text('{"kind": "test"}')

        request = ContextRequest(
            mode=ContextMode.DIGEST,
            scope=ContextScope(
                include_receipts=True, include_tests=False, include_docs=False
            ),
        )
        packet = execute(request, workspace_root=tmp_path)

        assert len(packet.receipts) >= 1
