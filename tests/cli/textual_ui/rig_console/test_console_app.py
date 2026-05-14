"""Smoke tests for the Rig Console entry point and headless startup."""

from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest
from textual.app import SystemCommand

from vibe.cli.textual_ui.rig_console.commands import build_rig_console_commands
from vibe.cli.textual_ui.rig_console.console_app import RigConsoleApp, main
from vibe.cli.textual_ui.rig_console.providers import DashboardProjectionProvider
from vibe.cli.textual_ui.rig_console.screens.dashboard import DashboardScreen
from vibe.cli.textual_ui.rig_console.widgets.fleet_panel import FleetPanelWidget
from vibe.cli.textual_ui.rig_console.widgets.footer_status import FooterStatusWidget
from vibe.cli.textual_ui.rig_console.widgets.inspector_drawer import (
    InspectorDrawerWidget,
)
from vibe.cli.textual_ui.rig_console.widgets.prompt_bar import PromptBar
from vibe.cli.textual_ui.rig_console.widgets.queue_panel import QueuePanelWidget


class TestConsoleAppEntryPoint:
    """Entry-point and startup coverage."""

    def test_main_is_importable(self) -> None:
        assert callable(main)

    @pytest.mark.asyncio
    async def test_fixture_mode_mounts(self) -> None:
        app = RigConsoleApp(mode="fixture")
        async with app.run_test(size=(100, 30)) as pilot:
            assert isinstance(pilot.app.screen, DashboardScreen)
            assert pilot.app.screen.query_one(FooterStatusWidget)
            assert pilot.app.screen.query_one(FleetPanelWidget)
            assert pilot.app.screen.query_one(InspectorDrawerWidget)
            assert pilot.app.screen.query_one(QueuePanelWidget)
            assert pilot.app.screen.query_one(PromptBar)

    @pytest.mark.asyncio
    async def test_runtime_mode_mounts_with_empty_roots(self, tmp_path: Path) -> None:
        app = RigConsoleApp(
            mode="runtime",
            session_id="session-123",
            session_path=tmp_path / "missing",
            workspace_root=tmp_path / "workspace",
            coordination_root=tmp_path / "coordination",
            audit_root=tmp_path / "audit",
        )
        async with app.run_test(size=(100, 30)) as pilot:
            screen = pilot.app.screen
            assert isinstance(screen, DashboardScreen)
            assert screen._projection.session.session_id == "session-123"
            assert screen._projection.session.status == "idle"

    @pytest.mark.asyncio
    async def test_missing_roots_do_not_crash(self, tmp_path: Path) -> None:
        app = RigConsoleApp(mode="runtime", session_path=tmp_path / "missing")
        async with app.run_test(size=(100, 30)) as pilot:
            screen = pilot.app.screen
            assert isinstance(screen, DashboardScreen)
            assert screen._projection.session.receipt_count == 0

    @pytest.mark.asyncio
    async def test_refresh_does_not_mutate_files(self, tmp_path: Path) -> None:
        target = tmp_path / "sentinel.txt"
        target.write_text("sentinel", encoding="utf-8")
        before = target.read_text(encoding="utf-8")
        app = RigConsoleApp(mode="fixture")
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.press("r")
            await pilot.app.workers.wait_for_complete()
            await pilot.pause()
        after = target.read_text(encoding="utf-8")
        assert after == before

    @pytest.mark.asyncio
    async def test_help_and_quit_keys_work(self) -> None:
        app = RigConsoleApp(mode="fixture")
        async with app.run_test(size=(100, 30)) as pilot:
            screen = pilot.app.screen
            assert isinstance(screen, DashboardScreen)
            assert ("?", "show_help", "Help") in screen.BINDINGS
            assert ("q", "quit", "Quit") in screen.BINDINGS
            screen.action_show_help()
            assert screen._projection.footer_hint is not None
            assert "help" in screen._projection.footer_hint
            screen.action_quit()

    @pytest.mark.asyncio
    async def test_provider_errors_are_sanitized(self) -> None:
        class _CrashProvider:
            async def dashboard_projection(self) -> object:
                raise RuntimeError("boom secret payload")

        app = RigConsoleApp(mode="fixture")
        async with app.run_test(size=(100, 30)) as pilot:
            screen = pilot.app.screen
            assert isinstance(screen, DashboardScreen)
            screen._provider = cast(DashboardProjectionProvider, _CrashProvider())
            await screen._do_refresh()
            await pilot.pause()
            assert screen._last_refresh_error == "RuntimeError"
            assert "secret payload" not in (screen._projection.footer_hint or "")

    @pytest.mark.asyncio
    async def test_command_palette_entries_include_refresh(self) -> None:
        app = RigConsoleApp(mode="fixture")
        async with app.run_test(size=(100, 30)) as pilot:
            screen = pilot.app.screen
            assert isinstance(screen, DashboardScreen)
            commands = list(build_rig_console_commands(screen))
            assert any(command[0] == "Refresh" for command in commands)
            assert any(command[0] == "Queue Message" for command in commands)
            assert any(command[0] == "Steer Current Task" for command in commands)
            assert any(command[0] == "Toggle Queue Panel" for command in commands)
            assert all(isinstance(command, SystemCommand) for command in commands)

    @pytest.mark.asyncio
    async def test_toggle_details_changes_visible_state(self) -> None:
        app = RigConsoleApp(mode="fixture")
        async with app.run_test(size=(100, 30)) as pilot:
            screen = pilot.app.screen
            assert isinstance(screen, DashboardScreen)
            before = screen._details_visible
            assert ("t", "toggle_details", "Details") in screen.BINDINGS
            screen.action_toggle_details()
            assert screen._details_visible is not before

    @pytest.mark.asyncio
    async def test_toggle_inspector_opens_drawer(self) -> None:
        app = RigConsoleApp(mode="fixture")
        async with app.run_test(size=(100, 30)) as pilot:
            screen = pilot.app.screen
            assert isinstance(screen, DashboardScreen)
            assert screen._projection.inspector.visible is False
            assert ("i", "toggle_inspector", "Inspector") in screen.BINDINGS
            screen.action_toggle_inspector()
            assert screen._projection.inspector.visible is True

    @pytest.mark.asyncio
    async def test_toggle_queue_opens_panel(self) -> None:
        app = RigConsoleApp(mode="fixture")
        async with app.run_test(size=(100, 30)) as pilot:
            screen = pilot.app.screen
            assert isinstance(screen, DashboardScreen)
            assert screen._projection.queue.visible is False
            assert ("u", "toggle_queue_panel", "Queue") in screen.BINDINGS
            screen.action_toggle_queue_panel()
            assert screen._projection.queue.visible is True

    @pytest.mark.asyncio
    async def test_toggle_fleet_opens_panel(self) -> None:
        app = RigConsoleApp(mode="fixture")
        async with app.run_test(size=(100, 30)) as pilot:
            screen = pilot.app.screen
            assert isinstance(screen, DashboardScreen)
            assert ("f", "toggle_fleet_panel", "Fleet") in screen.BINDINGS
            assert (
                "shift+f",
                "inspect_selected_fleet_item",
                "Inspect Fleet",
            ) in screen.BINDINGS
            assert ("ctrl+f", "refresh_fleet_state", "Refresh Fleet") in screen.BINDINGS
            before = screen._fleet_visible
            screen.action_toggle_fleet_panel()
            assert screen._fleet_visible is not before
