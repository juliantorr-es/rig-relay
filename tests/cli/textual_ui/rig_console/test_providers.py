"""Tests for RuntimeDashboardProjectionProvider — reads local evidence."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from vibe.cli.textual_ui.rig_console.projections import DashboardProjection
from vibe.cli.textual_ui.rig_console.providers import RuntimeDashboardProjectionProvider
from vibe.cli.textual_ui.rig_console.screens.dashboard import DashboardScreen

# ── Helpers ─────────────────────────────────────────────────────────────


def _receipt_event(
    tool_name: str,
    status: str = "success",
    *,
    event_id: str | None = None,
    path: str | None = None,
    changed: bool | None = None,
    error_kind: str | None = None,
    duration_ms: float | None = None,
    refusal_reason: str | None = None,
    captured_at: str | None = None,
) -> dict:
    """Build a minimal rig.relay.tool_receipt.captured event dict."""
    receipt: dict = {"status": status}
    if error_kind:
        receipt["error_kind"] = error_kind
    if refusal_reason:
        receipt["refusal_reason"] = refusal_reason
    if duration_ms is not None:
        receipt["duration_ms"] = duration_ms
    if path:
        receipt["path" if tool_name == "write_file" else "file"] = path
    if changed is not None:
        if tool_name == "search_replace":
            receipt["changed_files"] = [path] if path and changed else []
        else:
            receipt["status"] = status

    payload: dict = {"tool_name": tool_name, "receipt": receipt}

    event: dict = {
        "event_name": "rig.relay.tool_receipt.captured",
        "session_id": "test-session-001",
        "payload": payload,
    }
    if event_id:
        event["event_id"] = event_id
    if captured_at:
        event["created_at"] = captured_at

    return event


def _write_observability(tmp_path: Path, events: list[dict]) -> Path:
    """Write synthetic JSONL observability file, return its path."""
    obs_path = tmp_path / "observability.jsonl"
    with obs_path.open("w", encoding="utf-8") as f:
        for event in events:
            f.write(json.dumps(event) + "\n")
    return obs_path


def _make_synthetic_session(tmp_path: Path) -> Path:
    """Write a set of synthetic receipt events and return session dir."""
    events = [
        _receipt_event(
            "bash",
            "success",
            event_id="evt-001",
            captured_at="2026-06-01T10:00:00",
            duration_ms=500.0,
        ),
        _receipt_event(
            "search_replace",
            "success",
            event_id="evt-002",
            path="src/main.py",
            changed=True,
            captured_at="2026-06-01T10:01:00",
            duration_ms=1200.0,
        ),
        _receipt_event(
            "validate",
            "passed",
            event_id="evt-003",
            captured_at="2026-06-01T10:02:00",
            duration_ms=300.0,
        ),
        _receipt_event(
            "write_file",
            "refused",
            event_id="evt-004",
            path="src/config.py",
            error_kind="dirty_file_guard",
            refusal_reason="File has uncommitted changes",
            captured_at="2026-06-01T10:03:00",
        ),
        _receipt_event(
            "search_replace",
            "success",
            event_id="evt-005",
            path="src/utils.py",
            changed=True,
            captured_at="2026-06-01T10:04:00",
            duration_ms=800.0,
        ),
    ]
    _write_observability(tmp_path, events)
    return tmp_path


# ── Tests ────────────────────────────────────────────────────────────────


class TestRuntimeDashboardProjectionProvider:
    """RuntimeDashboardProjectionProvider tests."""

    async def _projection(
        self, tmp_path: Path, session_id: str = "test-session-001"
    ) -> DashboardProjection:
        provider = RuntimeDashboardProjectionProvider(
            session_id=session_id, session_path=tmp_path
        )
        return await provider.dashboard_projection()

    def test_missing_session_returns_empty(self, tmp_path: Path) -> None:
        """Missing session path should return a clean empty projection."""
        missing = tmp_path / "nonexistent"
        provider = RuntimeDashboardProjectionProvider(
            session_id="missing-session", session_path=missing
        )
        proj = asyncio.run(provider.dashboard_projection())
        assert proj.title == "Rig Console"
        assert proj.session.status == "idle"
        assert proj.session.receipt_count == 0
        assert proj.evidence.receipt_count == 0
        assert proj.evidence.items == []
        assert proj.safety_state == "read-only"

    @pytest.mark.asyncio
    async def test_builds_from_synthetic_session(self, tmp_path: Path) -> None:
        """Provider builds DashboardProjection from synthetic JSONL."""
        session_dir = _make_synthetic_session(tmp_path)
        proj = await self._projection(session_dir)

        assert proj.title == "Rig Console"
        assert proj.session.status == "active"
        assert proj.session.receipt_count == 5
        assert proj.session.current_step == "No active session data"
        assert proj.safety_state == "read-only"

    @pytest.mark.asyncio
    async def test_builds_evidence_rail(self, tmp_path: Path) -> None:
        """EvidenceRailProjection has correct items and counts."""
        session_dir = _make_synthetic_session(tmp_path)
        proj = await self._projection(session_dir)

        ev = proj.evidence
        assert ev.session_id == "test-session-001"
        assert ev.receipt_count == 5
        assert ev.mutation_count == 2  # 2 search_replace with changed=True
        assert ev.refusal_count == 1  # 1 write_file refused
        assert ev.timeout_count == 0

        # Items ordered by captured_at descending
        # Note: paths are resolved to absolute by receipt index builder
        assert ev.items[0].tool_name == "search_replace"
        assert ev.items[0].path is not None
        assert "src/utils.py" in ev.items[0].path
        assert ev.items[1].tool_name == "write_file"
        assert ev.items[1].path is not None
        assert "src/config.py" in ev.items[1].path
        assert ev.items[2].tool_name == "validate"
        assert ev.items[3].tool_name == "search_replace"
        assert ev.items[4].tool_name == "bash"

    @pytest.mark.asyncio
    async def test_maps_validate_status(self, tmp_path: Path) -> None:
        """Provider extracts validate_status from latest validate receipt."""
        session_dir = _make_synthetic_session(tmp_path)
        proj = await self._projection(session_dir)

        assert proj.session.validate_status == "passed"

    @pytest.mark.asyncio
    async def test_maps_latest_receipt_kind(self, tmp_path: Path) -> None:
        """Provider maps latest receipt tool_name into latest_receipt_kind."""
        session_dir = _make_synthetic_session(tmp_path)
        proj = await self._projection(session_dir)

        assert proj.session.latest_receipt_kind == "search_replace"

    @pytest.mark.asyncio
    async def test_maps_changed_paths(self, tmp_path: Path) -> None:
        """Provider deduplicates and caps changed_paths from evidence."""
        # Create session with many paths
        events = []
        for i in range(15):
            events.append(
                _receipt_event(
                    "search_replace",
                    "success",
                    event_id=f"evt-{i:03d}",
                    path=f"src/path_{i}.py",
                    changed=True,
                    captured_at=f"2026-06-01T10:{i:02d}:00",
                )
            )
        _write_observability(tmp_path, events)

        proj = await self._projection(tmp_path)
        # _PROVIDER_PATH_CAP = 10
        assert len(proj.session.changed_paths) <= 10

    @pytest.mark.asyncio
    async def test_validate_without_validate_receipt(self, tmp_path: Path) -> None:
        """When no validate receipt exists, validate_status is None."""
        events = [
            _receipt_event(
                "bash", "success", event_id="evt-001", captured_at="2026-06-01T10:00:00"
            ),
            _receipt_event(
                "search_replace",
                "success",
                event_id="evt-002",
                path="src/main.py",
                changed=True,
                captured_at="2026-06-01T10:01:00",
            ),
        ]
        _write_observability(tmp_path, events)
        proj = await self._projection(tmp_path)

        assert proj.session.validate_status is None
        assert proj.session.receipt_count == 2

    @pytest.mark.asyncio
    async def test_tolerates_malformed_events(self, tmp_path: Path) -> None:
        """Malformed JSON lines should not crash the provider."""
        obs_path = tmp_path / "observability.jsonl"
        with obs_path.open("w", encoding="utf-8") as f:
            # Valid event
            f.write(
                json.dumps(
                    _receipt_event(
                        "bash",
                        "success",
                        event_id="evt-001",
                        captured_at="2026-06-01T10:00:00",
                    )
                )
                + "\n"
            )
            # Malformed line
            f.write("not valid json\n")
            # Another valid event
            f.write(
                json.dumps(
                    _receipt_event(
                        "validate",
                        "passed",
                        event_id="evt-002",
                        captured_at="2026-06-01T10:01:00",
                    )
                )
                + "\n"
            )

        proj = await self._projection(tmp_path)

        assert proj.session.receipt_count == 2
        assert proj.session.status == "active"
        assert "read errors" in (proj.footer_hint or "")

    @pytest.mark.asyncio
    async def test_no_forbidden_raw_fields(self, tmp_path: Path) -> None:
        """Provider output must not contain forbidden raw field names."""
        session_dir = _make_synthetic_session(tmp_path)
        proj = await self._projection(session_dir)

        assert not hasattr(proj, "stdout")
        assert not hasattr(proj, "stderr")
        assert not hasattr(proj, "output")
        assert not hasattr(proj, "content")
        assert not hasattr(proj, "diff")

    @pytest.mark.asyncio
    async def test_session_projection_no_raw_fields(self, tmp_path: Path) -> None:
        """SessionPaneProjection within provider output must be content-light."""
        session_dir = _make_synthetic_session(tmp_path)
        proj = await self._projection(session_dir)

        session = proj.session
        assert not hasattr(session, "stdout")
        assert not hasattr(session, "stderr")
        assert not hasattr(session, "output")
        assert not hasattr(session, "content")
        assert not hasattr(session, "diff")

    def test_dashboard_screen_with_runtime_provider(self, tmp_path: Path) -> None:
        """DashboardScreen can be instantiated with RuntimeDashboardProjectionProvider."""
        session_dir = _make_synthetic_session(tmp_path)
        provider = RuntimeDashboardProjectionProvider(
            session_id="test-session-001", session_path=session_dir
        )
        initial = asyncio.run(provider.dashboard_projection())
        screen = DashboardScreen(initial, provider=provider)

        assert screen._provider is provider
        assert screen._projection.title == "Rig Console"
        assert screen._projection.session.receipt_count == 5

    @pytest.mark.asyncio
    async def test_workspace_root_appears_in_worktree(self, tmp_path: Path) -> None:
        """When workspace_root is provided, worktree_path is set."""
        session_dir = _make_synthetic_session(tmp_path)
        provider = RuntimeDashboardProjectionProvider(
            session_id="test-session-001",
            session_path=session_dir,
            workspace_root=tmp_path,
        )
        proj = await provider.dashboard_projection()

        assert proj.session.worktree_path == str(tmp_path)

    @pytest.mark.asyncio
    async def test_blank_blocker_summary(self, tmp_path: Path) -> None:
        """blocker_summary should be empty dict (not populated from receipts)."""
        session_dir = _make_synthetic_session(tmp_path)
        proj = await self._projection(session_dir)

        assert proj.session.blocker_summary == {}


# ── Coordination helpers ──────────────────────────────────────────────


def _write_coordination_session(
    coordination_root: Path,
    session_id: str,
    *,
    task_id: str | None = "coord-lane-default",
    status: str = "active",
    updated_at: str | None = None,
    warnings: list[str] | None = None,
) -> Path:
    """Write a synthetic CoordinationSession JSON file into a coordination store."""
    session_dir = coordination_root / "sessions"
    session_dir.mkdir(parents=True, exist_ok=True)
    session_file = session_dir / f"{session_id}.json"

    data: dict[str, object] = {
        "schema_version": "rig.relay.coordination.session.v1",
        "session_id": session_id,
        "task_id": task_id,
        "status": status,
        "updated_at": updated_at or "2026-06-01T12:00:00",
    }
    if warnings:
        data["warnings"] = warnings

    session_file.write_text(json.dumps(data), encoding="utf-8")
    return session_file


# ── Coordination enrichment tests ─────────────────────────────────────


class TestCoordinationEnrichment:
    """RuntimeDashboardProjectionProvider coordination/session enrichment tests."""

    @pytest.mark.asyncio
    async def test_missing_coordination_root_returns_clean_projection(
        self, tmp_path: Path
    ) -> None:
        """When coordination_root is None, fields stay None/default."""
        session_dir = _make_synthetic_session(tmp_path)
        provider = RuntimeDashboardProjectionProvider(
            session_id="test-session-001",
            session_path=session_dir,
            coordination_root=None,
        )
        proj = await provider.dashboard_projection()

        assert proj.session.lane_id is None
        assert proj.session.task_title is None
        assert proj.session.last_heartbeat_at is None

    @pytest.mark.asyncio
    async def test_missing_coordination_dir_returns_clean_projection(
        self, tmp_path: Path
    ) -> None:
        """When coordination_root points to a dir with no sessions subdir, no crash."""
        session_dir = _make_synthetic_session(tmp_path)
        coord_root = tmp_path / "coordination"  # does not exist
        provider = RuntimeDashboardProjectionProvider(
            session_id="test-session-001",
            session_path=session_dir,
            coordination_root=coord_root,
        )
        proj = await provider.dashboard_projection()

        assert proj.session.lane_id is None
        assert proj.session.current_step == "No active session data"

    @pytest.mark.asyncio
    async def test_missing_session_file_is_tolerated(self, tmp_path: Path) -> None:
        """When coordination session file does not exist, no crash."""
        session_dir = _make_synthetic_session(tmp_path)
        coord_root = tmp_path / "coordination"
        (coord_root / "sessions").mkdir(parents=True, exist_ok=True)
        # No session file for "test-session-001"
        provider = RuntimeDashboardProjectionProvider(
            session_id="test-session-001",
            session_path=session_dir,
            coordination_root=coord_root,
        )
        proj = await provider.dashboard_projection()

        assert proj.session.lane_id is None
        assert proj.session.last_heartbeat_at is None
        assert proj.session.current_step == "No active session data"
        assert proj.session.receipt_count == 5  # receipt data still works

    @pytest.mark.asyncio
    async def test_malformed_coordination_json_is_tolerated(
        self, tmp_path: Path
    ) -> None:
        """Malformed JSON in coordination session file returns empty summary."""
        session_dir = _make_synthetic_session(tmp_path)
        coord_root = tmp_path / "coordination"
        session_file = coord_root / "sessions" / "test-session-001.json"
        session_file.parent.mkdir(parents=True, exist_ok=True)
        session_file.write_text("this is not valid json", encoding="utf-8")

        provider = RuntimeDashboardProjectionProvider(
            session_id="test-session-001",
            session_path=session_dir,
            coordination_root=coord_root,
        )
        proj = await provider.dashboard_projection()

        assert proj.session.lane_id is None
        assert proj.session.last_heartbeat_at is None
        assert proj.session.current_step == "No active session data"
        assert proj.session.receipt_count == 5  # receipt data still works

    @pytest.mark.asyncio
    async def test_lane_id_from_coordination_propagates(self, tmp_path: Path) -> None:
        """When coordination has task_id, lane_id is populated."""
        session_dir = _make_synthetic_session(tmp_path)
        coord_root = tmp_path / "coordination"
        _write_coordination_session(
            coord_root, "test-session-001", task_id="coord-lane-007", status="active"
        )

        provider = RuntimeDashboardProjectionProvider(
            session_id="test-session-001",
            session_path=session_dir,
            coordination_root=coord_root,
        )
        proj = await provider.dashboard_projection()

        assert proj.session.lane_id == "coord-lane-007"

    @pytest.mark.asyncio
    async def test_explicit_lane_id_overrides_coordination(
        self, tmp_path: Path
    ) -> None:
        """When constructor provides lane_id, it overrides coordination value."""
        session_dir = _make_synthetic_session(tmp_path)
        coord_root = tmp_path / "coordination"
        _write_coordination_session(
            coord_root, "test-session-001", task_id="coord-lane-default"
        )

        provider = RuntimeDashboardProjectionProvider(
            session_id="test-session-001",
            session_path=session_dir,
            coordination_root=coord_root,
            lane_id="explicit-lane-42",
        )
        proj = await provider.dashboard_projection()

        assert proj.session.lane_id == "explicit-lane-42"

    @pytest.mark.asyncio
    async def test_explicit_task_title_propagates(self, tmp_path: Path) -> None:
        """When constructor provides task_title, it appears in projection."""
        session_dir = _make_synthetic_session(tmp_path)
        provider = RuntimeDashboardProjectionProvider(
            session_id="test-session-001",
            session_path=session_dir,
            task_title="Implement auth middleware",
        )
        proj = await provider.dashboard_projection()

        assert proj.session.task_title == "Implement auth middleware"

    @pytest.mark.asyncio
    async def test_last_heartbeat_at_from_coordination(self, tmp_path: Path) -> None:
        """Coordination session updated_at maps to last_heartbeat_at."""
        session_dir = _make_synthetic_session(tmp_path)
        coord_root = tmp_path / "coordination"
        _write_coordination_session(
            coord_root, "test-session-001", updated_at="2026-07-15T14:30:00"
        )

        provider = RuntimeDashboardProjectionProvider(
            session_id="test-session-001",
            session_path=session_dir,
            coordination_root=coord_root,
        )
        proj = await provider.dashboard_projection()

        assert proj.session.last_heartbeat_at == "2026-07-15T14:30:00"

    @pytest.mark.asyncio
    async def test_current_step_from_coordination(self, tmp_path: Path) -> None:
        """Coordination session status maps to current_step."""
        session_dir = _make_synthetic_session(tmp_path)
        coord_root = tmp_path / "coordination"
        _write_coordination_session(
            coord_root, "test-session-001", status="running_tool:validate"
        )

        provider = RuntimeDashboardProjectionProvider(
            session_id="test-session-001",
            session_path=session_dir,
            coordination_root=coord_root,
        )
        proj = await provider.dashboard_projection()

        assert proj.session.current_step == "running_tool:validate"

    @pytest.mark.asyncio
    async def test_workspace_root_still_propagates_with_coordination(
        self, tmp_path: Path
    ) -> None:
        """workspace_root -> worktree_path works alongside coordination."""
        session_dir = _make_synthetic_session(tmp_path)
        coord_root = tmp_path / "coordination"
        _write_coordination_session(coord_root, "test-session-001")

        provider = RuntimeDashboardProjectionProvider(
            session_id="test-session-001",
            session_path=session_dir,
            workspace_root=tmp_path,
            coordination_root=coord_root,
        )
        proj = await provider.dashboard_projection()

        assert proj.session.worktree_path == str(tmp_path)

    @pytest.mark.asyncio
    async def test_no_forbidden_raw_fields_with_coordination(
        self, tmp_path: Path
    ) -> None:
        """Coordination enrichment does not leak raw fields."""
        session_dir = _make_synthetic_session(tmp_path)
        coord_root = tmp_path / "coordination"
        _write_coordination_session(coord_root, "test-session-001")

        provider = RuntimeDashboardProjectionProvider(
            session_id="test-session-001",
            session_path=session_dir,
            coordination_root=coord_root,
        )
        proj = await provider.dashboard_projection()

        assert not hasattr(proj, "stdout")
        assert not hasattr(proj, "stderr")
        assert not hasattr(proj, "output")
        assert not hasattr(proj, "content")
        assert not hasattr(proj, "diff")

    @pytest.mark.asyncio
    async def test_receipt_data_survives_with_coordination(
        self, tmp_path: Path
    ) -> None:
        """Receipt-derived fields survive when coordination is active."""
        session_dir = _make_synthetic_session(tmp_path)
        coord_root = tmp_path / "coordination"
        _write_coordination_session(coord_root, "test-session-001")

        provider = RuntimeDashboardProjectionProvider(
            session_id="test-session-001",
            session_path=session_dir,
            coordination_root=coord_root,
        )
        proj = await provider.dashboard_projection()

        assert proj.session.validate_status == "passed"
        assert proj.session.receipt_count == 5
        assert proj.session.status == "active"


# ── Execution progress ────────────────────────────────────────────────


def _runtime_event(kind: str, **overrides: object) -> dict[str, object]:
    """Build a dict-shaped RuntimeStreamEvent for execution progress tests."""
    base: dict[str, object] = {
        "schema_version": "rig.relay.runtime_stream_event.v1",
        "event_id": f"evt-{kind}-test",
        "lease_id": "lease-exec-001",
        "request_id": "req-exec-001",
        "event_kind": kind,
        "captured_at": "2026-07-20T10:00:00Z",
    }
    base.update(overrides)
    return base


class TestExecutionProgressInProvider:
    """RuntimeDashboardProjectionProvider execution progress propagation tests."""

    @pytest.mark.asyncio
    async def test_execution_progress_none_when_no_runtime_events(
        self, tmp_path: Path
    ) -> None:
        """Without runtime_events, execution_progress is None."""
        session_dir = _make_synthetic_session(tmp_path)
        provider = RuntimeDashboardProjectionProvider(
            session_id="test-session-001", session_path=session_dir
        )
        proj = await provider.dashboard_projection()

        assert proj.execution_progress is None

    @pytest.mark.asyncio
    async def test_execution_progress_empty_when_empty_runtime_events(
        self, tmp_path: Path
    ) -> None:
        """Empty runtime_events list produces a valid empty projection."""
        session_dir = _make_synthetic_session(tmp_path)
        provider = RuntimeDashboardProjectionProvider(
            session_id="test-session-001", session_path=session_dir, runtime_events=[]
        )
        proj = await provider.dashboard_projection()

        assert proj.execution_progress is not None
        assert proj.execution_progress.status == "pending"
        assert proj.execution_progress.heartbeat_count == 0

    @pytest.mark.asyncio
    async def test_execution_progress_populated_from_runtime_events(
        self, tmp_path: Path
    ) -> None:
        """Runtime events produce a populated execution_progress."""
        session_dir = _make_synthetic_session(tmp_path)
        events = [
            _runtime_event("status", status="starting"),
            _runtime_event("heartbeat", elapsed_ms=500.0),
            _runtime_event(
                "completion",
                status="succeeded",
                exit_code=0,
                duration_ms=1500.0,
                stdout_bytes=1024,
                stderr_bytes=50,
                stdout_truncated=False,
                stderr_truncated=False,
                stdout_sha256="abc",
                stderr_sha256="def",
            ),
        ]
        provider = RuntimeDashboardProjectionProvider(
            session_id="test-session-001",
            session_path=session_dir,
            runtime_events=events,
        )
        proj = await provider.dashboard_projection()

        assert proj.execution_progress is not None
        assert proj.execution_progress.status == "succeeded"
        assert proj.execution_progress.exit_code == 0
        assert proj.execution_progress.stdout_bytes == 1024
        assert proj.execution_progress.stderr_bytes == 50
        assert proj.execution_progress.stdout_truncated is False

    @pytest.mark.asyncio
    async def test_execution_progress_byte_counts_only(self, tmp_path: Path) -> None:
        """Byte counts propagate as integers, never raw content."""
        session_dir = _make_synthetic_session(tmp_path)
        events = [
            _runtime_event("status", status="starting"),
            _runtime_event(
                "completion",
                status="succeeded",
                exit_code=0,
                duration_ms=1000.0,
                stdout_bytes=2048,
                stderr_bytes=128,
                stdout_truncated=True,
                stderr_truncated=False,
                stdout_sha256="abc",
                stderr_sha256="def",
            ),
        ]
        provider = RuntimeDashboardProjectionProvider(
            session_id="test-session-001",
            session_path=session_dir,
            runtime_events=events,
        )
        proj = await provider.dashboard_projection()

        assert proj.execution_progress is not None
        assert isinstance(proj.execution_progress.stdout_bytes, int)
        assert isinstance(proj.execution_progress.stderr_bytes, int)
        assert proj.execution_progress.stdout_bytes == 2048
        assert proj.execution_progress.stderr_bytes == 128
        assert proj.execution_progress.stdout_truncated is True
        # No raw output fields
        assert not hasattr(proj.execution_progress, "chunk_text")
        assert not hasattr(proj.execution_progress, "stdout")
        assert not hasattr(proj.execution_progress, "stderr")

    @pytest.mark.asyncio
    async def test_execution_progress_warning_metadata_without_raw_content(
        self, tmp_path: Path
    ) -> None:
        """Warning metadata propagates without raw content."""
        session_dir = _make_synthetic_session(tmp_path)
        events = [
            _runtime_event("status", status="running"),
            _runtime_event(
                "warning",
                warning_kind="stall_detected",
                message="Process stalled for 30s",
            ),
            _runtime_event(
                "completion",
                status="succeeded",
                exit_code=0,
                duration_ms=5000.0,
                stdout_bytes=0,
                stderr_bytes=0,
                stdout_sha256="abc",
                stderr_sha256="def",
            ),
        ]
        provider = RuntimeDashboardProjectionProvider(
            session_id="test-session-001",
            session_path=session_dir,
            runtime_events=events,
        )
        proj = await provider.dashboard_projection()

        assert proj.execution_progress is not None
        assert proj.execution_progress.warning_count == 1
        assert proj.execution_progress.latest_warning_kind == "stall_detected"
        assert (
            proj.execution_progress.latest_warning_message == "Process stalled for 30s"
        )

    @pytest.mark.asyncio
    async def test_execution_progress_terminal_metadata_without_raw_content(
        self, tmp_path: Path
    ) -> None:
        """Terminal error/refusal metadata propagates without raw content."""
        session_dir = _make_synthetic_session(tmp_path)
        events = [
            _runtime_event("status", status="running"),
            _runtime_event(
                "failure",
                status="failed",
                error_kind="timeout",
                refusal_reason="Execution exceeded 30s limit",
                duration_ms=30000.0,
                exit_code=1,
                stdout_bytes=500,
                stderr_bytes=200,
            ),
        ]
        provider = RuntimeDashboardProjectionProvider(
            session_id="test-session-001",
            session_path=session_dir,
            runtime_events=events,
        )
        proj = await provider.dashboard_projection()

        assert proj.execution_progress is not None
        assert proj.execution_progress.status == "failed"
        assert proj.execution_progress.error_kind == "timeout"
        assert proj.execution_progress.refusal_reason == "Execution exceeded 30s limit"
        assert proj.execution_progress.exit_code == 1
        assert proj.execution_progress.elapsed_ms == 30000.0

    @pytest.mark.asyncio
    async def test_execution_progress_does_not_break_existing_fields(
        self, tmp_path: Path
    ) -> None:
        """Setting execution_progress does not break session/evidence fields."""
        session_dir = _make_synthetic_session(tmp_path)
        events = [
            _runtime_event("status", status="starting"),
            _runtime_event(
                "completion",
                status="succeeded",
                exit_code=0,
                duration_ms=1000.0,
                stdout_bytes=100,
                stderr_bytes=0,
                stdout_sha256="abc",
                stderr_sha256="def",
            ),
        ]
        provider = RuntimeDashboardProjectionProvider(
            session_id="test-session-001",
            session_path=session_dir,
            runtime_events=events,
        )
        proj = await provider.dashboard_projection()

        # Existing fields must remain intact
        assert proj.title == "Rig Console"
        assert proj.session.receipt_count == 5
        assert proj.session.validate_status == "passed"
        assert proj.evidence.receipt_count == 5
        assert proj.execution_progress is not None
        assert proj.execution_progress.status == "succeeded"
