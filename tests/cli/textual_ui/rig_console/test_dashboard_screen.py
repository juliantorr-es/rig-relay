"""Tests for DashboardScreen — dashboard screen composition with provider seam."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, Mock, patch

from rig_relay.runtime.tool_invocation_execution import (
    RuntimeToolExecutionResult,
    RuntimeToolExecutionStatus,
)
from vibe.cli.textual_ui.rig_console.actions import (
    ACTION_REFRESH,
    RigConsoleAction,
    build_validate_runtime_exec_intent,
)
from vibe.cli.textual_ui.rig_console.projections import (
    DashboardProjection,
    EvidenceRailProjection,
    InspectorItemProjection,
    InspectorProjection,
    QueueItemProjection,
    QueueProjection,
    SessionPaneProjection,
)
from vibe.cli.textual_ui.rig_console.screens.dashboard import DashboardScreen


def _make_projection(
    title: str = "Test Dashboard", footer_hint: str | None = None
) -> DashboardProjection:
    return DashboardProjection(
        title=title,
        session=SessionPaneProjection(session_id="s1"),
        evidence=EvidenceRailProjection(session_id="s1"),
        footer_hint=footer_hint,
        inspector=InspectorProjection(
            visible=False,
            items=[
                InspectorItemProjection(
                    item_id="aev-1",
                    source_kind="runtime_audit",
                    title="Audit validate",
                    status="completed",
                    tool_name="validate",
                    receipt_sha256="sha256:receipt",
                    runtime_result_sha256="sha256:result",
                )
            ],
        ),
    )


class TestDashboardScreen:
    """DashboardScreen structural and action tests."""

    def test_can_instantiate_without_provider(self) -> None:
        proj = _make_projection()
        screen = DashboardScreen(proj)
        assert screen._projection is proj
        assert screen._provider is None

    def test_can_instantiate_with_provider(self) -> None:
        proj = _make_projection()
        mock_provider = AsyncMock()
        mock_provider.dashboard_projection.return_value = proj
        screen = DashboardScreen(proj, provider=mock_provider)
        assert screen._projection is proj
        assert screen._provider is mock_provider

    def test_update_projection_replaces_data(self) -> None:
        proj1 = _make_projection(title="First")
        proj2 = _make_projection(title="Second")
        screen = DashboardScreen(proj1)
        assert screen._projection.title == "First"
        screen._projection = proj2
        assert screen._projection.title == "Second"

    def test_has_quit_action(self) -> None:
        screen = DashboardScreen(_make_projection())
        assert hasattr(screen, "action_quit")

    def test_has_refresh_action(self) -> None:
        screen = DashboardScreen(_make_projection())
        assert hasattr(screen, "action_refresh")

    def test_has_show_help_action(self) -> None:
        screen = DashboardScreen(_make_projection())
        assert hasattr(screen, "action_show_help")

    def test_has_focus_evidence_action(self) -> None:
        screen = DashboardScreen(_make_projection())
        assert hasattr(screen, "action_focus_evidence")

    def test_has_validate_current_action(self) -> None:
        screen = DashboardScreen(_make_projection())
        assert hasattr(screen, "action_validate_current")

    def test_has_run_validate_action(self) -> None:
        screen = DashboardScreen(_make_projection())
        assert hasattr(screen, "action_run_validate")

    def test_has_toggle_inspector_action(self) -> None:
        screen = DashboardScreen(_make_projection())
        assert hasattr(screen, "action_toggle_inspector")

    def test_has_next_previous_and_copy_ref_actions(self) -> None:
        screen = DashboardScreen(_make_projection())
        assert hasattr(screen, "action_next_item")
        assert hasattr(screen, "action_previous_item")
        assert hasattr(screen, "action_copy_selected_ref")

    def test_show_help_updates_footer_hint(self) -> None:
        screen = DashboardScreen(_make_projection())
        assert screen._projection.footer_hint is None
        with patch.object(screen, "_render_all"):
            screen.action_show_help()
        assert screen._projection.footer_hint is not None
        assert "Available:" in screen._projection.footer_hint
        assert "refresh" in screen._projection.footer_hint

    def test_show_help_adds_backlog(self) -> None:
        screen = DashboardScreen(_make_projection())
        with patch.object(screen, "_render_all"):
            screen.action_show_help()
        assert screen._projection.backlog_items == []

    def test_focus_evidence_sets_status(self) -> None:
        screen = DashboardScreen(_make_projection())
        with patch.object(screen, "_render_all"):
            screen.action_focus_evidence()
        assert screen._projection.footer_hint is not None
        assert "evidence" in screen._projection.footer_hint

    def test_validate_current_sets_status(self) -> None:
        screen = DashboardScreen(_make_projection())
        with patch.object(screen, "_render_all"):
            screen.action_validate_current()
        assert screen._projection.footer_hint is not None
        assert "validate" in screen._projection.footer_hint

    def test_refresh_without_provider_is_safe_noop(self) -> None:
        """Refresh without a provider should not raise."""
        proj = _make_projection(title="Original")
        screen = DashboardScreen(proj)
        asyncio.run(screen.action_refresh())
        assert screen._projection.title == "Original"

    def test_refresh_without_provider_no_footer_change(self) -> None:
        """Without provider, refresh reports the missing provider safely."""
        proj = _make_projection(title="Original")
        screen = DashboardScreen(proj)
        asyncio.run(screen.action_refresh())
        assert screen._projection.footer_hint is not None
        assert "No provider configured" in screen._projection.footer_hint

    def test_set_status_updates_footer(self) -> None:
        screen = DashboardScreen(_make_projection())
        with patch.object(screen, "_render_all"):
            screen._set_status("ok", "refresh", "Done")
        assert screen._projection.footer_hint is not None
        assert "[ok]" in screen._projection.footer_hint
        assert "refresh" in screen._projection.footer_hint

    def test_run_safe_action_dispatches_refresh(self) -> None:
        screen = DashboardScreen(_make_projection())
        with patch.object(
            screen, "action_refresh", new=Mock(return_value=None)
        ) as mock_refresh:
            screen.run_safe_action(ACTION_REFRESH)
        mock_refresh.assert_called_once()

    def test_run_safe_action_handles_unknown_action(self) -> None:
        screen = DashboardScreen(_make_projection())
        unknown = RigConsoleAction(
            name="unknown",
            title="Unknown",
            description="Unknown",
            callback_name="action_does_not_exist",
        )
        with patch.object(screen, "_render_all"):
            screen.run_safe_action(unknown)
        assert screen._projection.footer_hint is not None
        assert "Unknown action" in screen._projection.footer_hint

    def test_run_safe_action_does_not_expose_raw_fields(self) -> None:
        screen = DashboardScreen(_make_projection())
        with patch.object(screen, "action_refresh", new=Mock(return_value=None)):
            screen.run_safe_action(ACTION_REFRESH)
        footer_hint = screen._projection.footer_hint or ""
        forbidden = (
            "stdout",
            "stderr",
            "content",
            "file_contents",
            "chunk_text",
            "old_text",
            "new_text",
            "diff",
            "patch",
            "prompt",
            "secret",
            "argv",
            "snippet",
        )
        assert not any(name in footer_hint.lower() for name in forbidden)

    def test_build_validate_runtime_exec_intent_uses_runtime_exec(self) -> None:
        intent = build_validate_runtime_exec_intent(
            intent_id="intent-validate-1", changed_paths=["src/main.py"]
        )
        assert intent.tool_name.value == "runtime_exec"
        assert intent.payload["tool_name"] == "validate"
        assert intent.payload["paths"] == ["src/main.py"]

    def test_action_run_validate_without_provider_is_refused(self) -> None:
        screen = DashboardScreen(_make_projection())
        asyncio.run(screen.action_run_validate())
        assert "Validate unavailable" in (screen._projection.footer_hint or "")

    def test_action_run_validate_requests_provider_run_and_refresh(self) -> None:
        proj = _make_projection()

        class _Provider:
            async def run_validate(
                self, projection: DashboardProjection
            ) -> RuntimeToolExecutionResult:
                assert projection.session.session_id == "s1"
                return RuntimeToolExecutionResult(
                    status=RuntimeToolExecutionStatus.COMPLETED,
                    intent_id="intent-validate-1",
                    tool_name="runtime_exec",
                    tool_status="passed",
                    tool_receipt_kind="validate",
                    tool_receipt_schema_version="rig.relay.validate_receipt.v1",
                )

            async def dashboard_projection(self) -> DashboardProjection:
                return proj.model_copy(
                    update={"footer_hint": "refreshed after validate"}
                )

        screen = DashboardScreen(proj, provider=_Provider())
        with patch.object(screen, "_render_all"):
            asyncio.run(screen.action_run_validate())
        assert screen._projection.footer_hint is not None
        assert "Validate complete" in screen._projection.footer_hint

    def test_action_run_validate_sets_running_status(self) -> None:
        proj = _make_projection()

        class _Provider:
            async def run_validate(
                self, projection: DashboardProjection
            ) -> RuntimeToolExecutionResult:
                return RuntimeToolExecutionResult(
                    status=RuntimeToolExecutionStatus.COMPLETED,
                    intent_id="intent-validate-1",
                    tool_name="runtime_exec",
                    tool_status="passed",
                )

            async def dashboard_projection(self) -> DashboardProjection:
                return proj

        screen = DashboardScreen(proj, provider=_Provider())
        with patch.object(screen, "run_worker") as mock_run:
            with patch.object(screen, "_render_all"):
                asyncio.run(screen.action_run_validate())
        mock_run.assert_called_once()
        assert screen._projection.footer_hint is not None
        assert "Validate running" in screen._projection.footer_hint

    def test_toggle_inspector_flips_visibility(self) -> None:
        screen = DashboardScreen(_make_projection())
        initial = screen._projection.inspector.visible
        with patch.object(screen, "_render_all"):
            screen.action_toggle_inspector()
        assert screen._projection.inspector.visible is not initial

    def test_inspect_selected_queue_item_updates_inspector(self) -> None:
        proj = _make_projection()
        proj = proj.model_copy(
            update={
                "queue": QueueProjection(
                    visible=True,
                    items=[
                        QueueItemProjection(
                            queue_item_id="queue-1",
                            kind="message",
                            status="queued",
                            title="Queue one",
                        ),
                        QueueItemProjection(
                            queue_item_id="queue-2",
                            kind="validate",
                            status="running",
                            title="Validate now",
                        ),
                    ],
                    selected_index=1,
                ),
                "inspector": proj.inspector.model_copy(
                    update={
                        "items": [
                            InspectorItemProjection(
                                item_id="queue-1",
                                source_kind="queue_item",
                                title="Queue one",
                            ),
                            InspectorItemProjection(
                                item_id="queue-2",
                                source_kind="queue_item",
                                title="Validate now",
                            ),
                        ]
                    }
                ),
            }
        )
        screen = DashboardScreen(proj)
        with patch.object(screen, "_render_all"):
            screen.action_inspect_selected_queue_item()
        assert screen._projection.inspector.visible is True
        assert screen._projection.inspector.selected_index == 1

    def test_next_item_advances_inspector_selection(self) -> None:
        proj = _make_projection()
        proj = proj.model_copy(
            update={
                "inspector": proj.inspector.model_copy(
                    update={
                        "items": [
                            proj.inspector.items[0],
                            InspectorItemProjection(
                                item_id="receipt-2",
                                source_kind="receipt",
                                title="Receipt validate",
                            ),
                        ]
                    }
                )
            }
        )
        screen = DashboardScreen(proj)
        with patch.object(screen, "_render_all"):
            screen.action_next_item()
        assert screen._projection.inspector.selected_index == 1

    def test_copy_selected_ref_uses_safe_hash(self) -> None:
        screen = DashboardScreen(_make_projection())
        with patch("pyperclip.copy") as mock_copy:
            with patch.object(screen, "_render_all"):
                screen.action_copy_selected_ref()
        mock_copy.assert_called_once()
        assert mock_copy.call_args.args[0] == "sha256:receipt"

    def test_no_forbidden_raw_fields(self) -> None:
        screen = DashboardScreen(_make_projection())
        assert not hasattr(screen, "stdout")
        assert not hasattr(screen, "stderr")
        assert not hasattr(screen, "output")
        assert not hasattr(screen, "content")
        assert not hasattr(screen, "diff")

    # ── Refresh state initial ────────────────────────────────────

    def test_refresh_state_initial_values(self) -> None:
        screen = DashboardScreen(_make_projection())
        assert screen._refresh_in_progress is False
        assert screen._last_refresh_error is None
        assert screen._last_refresh_at is None

    # ── Refresh worker dispatch ──────────────────────────────────

    def test_action_refresh_with_provider_dispatches_worker(self) -> None:
        proj = _make_projection()
        mock_provider = AsyncMock()
        screen = DashboardScreen(proj, provider=mock_provider)
        with patch.object(screen, "_render_all"):
            with patch.object(screen, "run_worker") as mock_run:
                asyncio.run(screen.action_refresh())
        mock_run.assert_called_once()
        _args, kwargs = mock_run.call_args
        assert kwargs.get("exclusive") is True
        assert kwargs.get("exit_on_error") is False

    def test_action_refresh_without_provider_no_run_worker(self) -> None:
        screen = DashboardScreen(_make_projection())
        with patch.object(screen, "run_worker") as mock_run:
            asyncio.run(screen.action_refresh())
        mock_run.assert_not_called()

    def test_action_refresh_sets_status_started(self) -> None:
        proj = _make_projection(footer_hint="original")
        mock_provider = AsyncMock()
        screen = DashboardScreen(proj, provider=mock_provider)
        with patch.object(screen, "_render_all"):
            with patch.object(screen, "run_worker"):
                asyncio.run(screen.action_refresh())
        assert screen._projection.footer_hint is not None
        assert "Refresh started" in screen._projection.footer_hint

    # ── Refresh worker body (_do_refresh) ────────────────────────

    def test_refresh_worker_updates_projection_on_success(self) -> None:
        updated = _make_projection(title="Updated")
        mock_provider = AsyncMock()
        mock_provider.dashboard_projection.return_value = updated
        screen = DashboardScreen(
            _make_projection(title="Original"), provider=mock_provider
        )
        with patch.object(screen, "_render_all"):
            asyncio.run(screen._do_refresh())
        assert screen._projection.title == "Updated"

    def test_refresh_worker_sets_refresh_state_on_success(self) -> None:
        mock_provider = AsyncMock()
        mock_provider.dashboard_projection.return_value = _make_projection()
        screen = DashboardScreen(_make_projection(), provider=mock_provider)
        with patch.object(screen, "_render_all"):
            asyncio.run(screen._do_refresh())
        assert screen._last_refresh_at is not None
        assert screen._last_refresh_error is None
        assert screen._refresh_in_progress is False

    def test_refresh_worker_clears_previous_error(self) -> None:
        mock_provider = AsyncMock()
        mock_provider.dashboard_projection.return_value = _make_projection()
        screen = DashboardScreen(_make_projection(), provider=mock_provider)
        screen._last_refresh_error = "previous error"
        with patch.object(screen, "_render_all"):
            asyncio.run(screen._do_refresh())
        assert screen._last_refresh_error is None

    def test_refresh_worker_sets_error_on_exception(self) -> None:
        mock_provider = AsyncMock()
        mock_provider.dashboard_projection.side_effect = ValueError("Disk full")
        screen = DashboardScreen(_make_projection(), provider=mock_provider)
        with patch.object(screen, "_render_all"):
            asyncio.run(screen._do_refresh())
        assert screen._last_refresh_error is not None
        assert screen._last_refresh_error == "ValueError"
        assert screen._refresh_in_progress is False
        assert screen._projection.footer_hint is not None
        assert "Refresh failed" in screen._projection.footer_hint

    def test_refresh_worker_sanitizes_long_error(self) -> None:
        mock_provider = AsyncMock()
        long_msg = "x" * 200
        mock_provider.dashboard_projection.side_effect = RuntimeError(long_msg)
        screen = DashboardScreen(_make_projection(), provider=mock_provider)
        with patch.object(screen, "_render_all"):
            asyncio.run(screen._do_refresh())
        assert screen._last_refresh_error is not None
        assert len(screen._last_refresh_error) <= 100

    def test_refresh_worker_sanitizes_multiline_error(self) -> None:
        mock_provider = AsyncMock()
        mock_provider.dashboard_projection.side_effect = RuntimeError(
            "First line\nSecond line\nTraceback..."
        )
        screen = DashboardScreen(_make_projection(), provider=mock_provider)
        with patch.object(screen, "_render_all"):
            asyncio.run(screen._do_refresh())
        assert screen._last_refresh_error == "RuntimeError"

    def test_refresh_worker_cancelled_error_is_graceful(self) -> None:
        mock_provider = AsyncMock()
        mock_provider.dashboard_projection.side_effect = asyncio.CancelledError()
        screen = DashboardScreen(
            _make_projection(title="Original"), provider=mock_provider
        )
        with patch.object(screen, "_render_all"):
            asyncio.run(screen._do_refresh())
        assert screen._projection.title == "Original"
        assert screen._refresh_in_progress is False

    # ── Refresh worker warning regression (Slice 5.2) ────────────

    def test_action_refresh_no_coroutine_never_awaited_warning(self) -> None:
        """Passing _do_refresh as callable must not produce RuntimeWarning.

        Previously the test passed self._do_refresh() as a coroutine.
        When run_worker was patched to do nothing, the coroutine was
        never awaited, triggering RuntimeWarning. Now it's a callable.
        """
        import warnings as _warnings

        proj = _make_projection()
        mock_provider = AsyncMock()
        screen = DashboardScreen(proj, provider=mock_provider)
        with patch.object(screen, "_render_all"):
            with patch.object(screen, "run_worker") as mock_run:
                with _warnings.catch_warnings(record=True) as captured:
                    asyncio.run(screen.action_refresh())

        # Verify no RuntimeWarning was emitted
        runtime_warnings = [
            w for w in captured if issubclass(w.category, RuntimeWarning)
        ]
        assert not runtime_warnings, (
            f"Expected no RuntimeWarning, got: "
            f"{[str(w.message) for w in runtime_warnings]}"
        )

        # Verify callable was passed (not a coroutine)
        mock_run.assert_called_once()
        call_args, kwargs = mock_run.call_args
        assert callable(call_args[0]), (
            "Expected callable (self._do_refresh) as first arg, "
            f"got {type(call_args[0]).__name__}"
        )
        assert kwargs.get("exclusive") is True
        assert kwargs.get("exit_on_error") is False

    def test_action_refresh_cancelled_worker_no_warning(self) -> None:
        """CancelledError in _do_refresh must not produce RuntimeWarning
        when called through action_refresh with run_worker patched.
        """
        import warnings as _warnings

        proj = _make_projection(title="Original")
        mock_provider = AsyncMock()
        screen = DashboardScreen(proj, provider=mock_provider)

        with patch.object(screen, "_render_all"):
            with patch.object(
                screen, "run_worker", wraps=lambda coro_or_callable, **kw: None
            ):
                with _warnings.catch_warnings(record=True) as captured:
                    asyncio.run(screen.action_refresh())

        runtime_warnings = [
            w for w in captured if issubclass(w.category, RuntimeWarning)
        ]
        assert not runtime_warnings, (
            f"Expected no RuntimeWarning, got: "
            f"{[str(w.message) for w in runtime_warnings]}"
        )
