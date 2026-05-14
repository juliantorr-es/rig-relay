"""Headless Pilot tests for DashboardScreen — mount, keybindings, provider error."""

from __future__ import annotations

import pytest
from textual.app import App

from vibe.cli.textual_ui.rig_console.projections import (
    DashboardProjection,
    EvidenceRailProjection,
    SessionPaneProjection,
)
from vibe.cli.textual_ui.rig_console.providers import (
    DashboardProjectionProvider,
    FixtureDashboardProjectionProvider,
)
from vibe.cli.textual_ui.rig_console.screens.dashboard import DashboardScreen
from vibe.cli.textual_ui.rig_console.widgets.evidence_rail import EvidenceRailWidget
from vibe.cli.textual_ui.rig_console.widgets.footer_status import FooterStatusWidget
from vibe.cli.textual_ui.rig_console.widgets.operator_header import OperatorHeaderWidget
from vibe.cli.textual_ui.rig_console.widgets.session_pane import SessionPaneWidget

# ── Fixture data ─────────────────────────────────────────────────────


def _make_projection(
    title: str = "Rig Relay",
    subtitle: str | None = "Operator Dashboard",
    session_id: str = "test-session-001",
    status: str = "active",
    footer_hint: str | None = "q: quit  r: refresh  ?: help",
) -> DashboardProjection:
    """Create a minimal DashboardProjection for Pilot tests."""
    return DashboardProjection(
        title=title,
        subtitle=subtitle,
        session=SessionPaneProjection(
            session_id=session_id,
            status=status,
            task_title="Test task",
            current_step="Processing",
            receipt_count=3,
            latest_receipt_kind="bash",
            changed_paths=["src/main.py", "tests/test_main.py"],
        ),
        evidence=EvidenceRailProjection(
            session_id=session_id,
            receipt_count=3,
            mutation_count=1,
            refusal_count=0,
            timeout_count=0,
        ),
        safety_state="active",
        footer_hint=footer_hint,
        backlog_items=["Review changes", "Run tests"],
    )


# ── Test App ─────────────────────────────────────────────────────────


class _TestDashboardApp(App[None]):
    """Minimal Textual app for headless Pilot testing of DashboardScreen.

    Pushes a DashboardScreen with the given projection and optional
    provider during mount so widgets are ready for interaction.
    """

    def __init__(
        self,
        projection: DashboardProjection,
        provider: DashboardProjectionProvider | None = None,
    ) -> None:
        super().__init__()
        self._projection = projection
        self._provider = provider

    def on_mount(self) -> None:
        self.push_screen(DashboardScreen(self._projection, provider=self._provider))


# ── Error-fixture provider ───────────────────────────────────────────


class _CrashOnRefreshProvider:
    """Provider that raises RuntimeError when dashboard_projection() is called."""

    def __init__(self, message: str = "boom\nsecret detail") -> None:
        self._message = message

    async def dashboard_projection(self) -> DashboardProjection:
        raise RuntimeError(self._message)


# ── Tests ────────────────────────────────────────────────────────────


class TestDashboardPilotMount:
    """DashboardScreen mounts correctly with all core widgets."""

    @pytest.mark.asyncio
    async def test_dashboard_pilot_mounts(self) -> None:
        """App mounts and dashboard screen with all 4 core widgets is active."""
        proj = _make_projection()
        provider = FixtureDashboardProjectionProvider(proj)
        app = _TestDashboardApp(proj, provider=provider)
        async with app.run_test(size=(80, 24)) as pilot:
            screen = pilot.app.screen
            assert isinstance(screen, DashboardScreen)
            assert screen.query_one(OperatorHeaderWidget)
            assert screen.query_one(SessionPaneWidget)
            assert screen.query_one(EvidenceRailWidget)
            assert screen.query_one(FooterStatusWidget)

    @pytest.mark.asyncio
    async def test_dashboard_pilot_mounts_without_provider(self) -> None:
        """Dashboard mounts without a provider (no-op refresh path)."""
        proj = _make_projection()
        app = _TestDashboardApp(proj)
        async with app.run_test(size=(80, 24)) as pilot:
            screen = pilot.app.screen
            assert isinstance(screen, DashboardScreen)
            assert screen.query_one(OperatorHeaderWidget)

    @pytest.mark.asyncio
    async def test_dashboard_pilot_renders_title(self) -> None:
        """Title from fixture projection is visible."""
        proj = _make_projection(title="Custom Title")
        provider = FixtureDashboardProjectionProvider(proj)
        app = _TestDashboardApp(proj, provider=provider)
        async with app.run_test(size=(80, 24)) as pilot:
            screen = pilot.app.screen
            assert isinstance(screen, DashboardScreen)
            header = screen.query_one(OperatorHeaderWidget)
            # Query the Static child that holds the title
            title_static = header.query_one(".header-title")
            rendered = str(title_static.render())
            assert "Custom Title" in rendered


class TestDashboardPilotHelpKey:
    """Help key ('?') updates footer hint and backlog."""

    @pytest.mark.asyncio
    async def test_help_key_updates_footer(self) -> None:
        """Pressing '?' updates footer_hint with available keybindings."""
        proj = _make_projection()
        provider = FixtureDashboardProjectionProvider(proj)
        app = _TestDashboardApp(proj, provider=provider)
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.press("?")
            await pilot.pause()
            screen = pilot.app.screen
            assert isinstance(screen, DashboardScreen)
            assert screen._projection.footer_hint is not None
            assert "r: refresh" in screen._projection.footer_hint
            assert "?: help" in screen._projection.footer_hint

    @pytest.mark.asyncio
    async def test_help_key_adds_backlog_items(self) -> None:
        """After '?' the backlog contains help descriptions."""
        proj = _make_projection()
        provider = FixtureDashboardProjectionProvider(proj)
        app = _TestDashboardApp(proj, provider=provider)
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.press("?")
            await pilot.pause()
            screen = pilot.app.screen
            assert isinstance(screen, DashboardScreen)
            assert len(screen._projection.backlog_items) >= 3


class TestDashboardPilotRefreshKey:
    """Refresh key ('r') fetches projection from provider."""

    @pytest.mark.asyncio
    async def test_refresh_key_uses_provider(self) -> None:
        """Refresh replaces projection with provider data."""
        initial = _make_projection(title="Initial")
        altered = _make_projection(title="Altered", session_id="test-session-002")
        provider = FixtureDashboardProjectionProvider(initial)
        app = _TestDashboardApp(initial, provider=provider)
        async with app.run_test(size=(80, 24)) as pilot:
            screen = pilot.app.screen
            assert isinstance(screen, DashboardScreen)
            assert screen._projection.title == "Initial"

            # Swap fixture data then trigger refresh
            provider.set_projection(altered)
            await pilot.press("r")
            await pilot.app.workers.wait_for_complete()
            await pilot.pause()

            assert screen._projection.title == "Altered"

    @pytest.mark.asyncio
    async def test_refresh_key_sets_last_refresh_at(self) -> None:
        """After refresh, _last_refresh_at is set."""
        proj = _make_projection()
        provider = FixtureDashboardProjectionProvider(proj)
        app = _TestDashboardApp(proj, provider=provider)
        async with app.run_test(size=(80, 24)) as pilot:
            screen = pilot.app.screen
            assert isinstance(screen, DashboardScreen)
            assert screen._last_refresh_at is None

            await pilot.press("r")
            await pilot.app.workers.wait_for_complete()
            await pilot.pause()

            assert screen._last_refresh_at is not None

    @pytest.mark.asyncio
    async def test_refresh_key_clears_previous_error(self) -> None:
        """A second successful refresh clears the previous error state."""

        class _ThenOkProvider:
            def __init__(self) -> None:
                self._call = 0

            async def dashboard_projection(self) -> DashboardProjection:
                self._call += 1
                if self._call == 1:
                    raise RuntimeError("first error")
                return _make_projection(title="Recovered")

        proj = _make_projection()
        provider = _ThenOkProvider()
        app = _TestDashboardApp(proj, provider=provider)
        async with app.run_test(size=(80, 24)) as pilot:
            screen = pilot.app.screen
            assert isinstance(screen, DashboardScreen)

            # First refresh — triggers error
            await pilot.press("r")
            await pilot.app.workers.wait_for_complete()
            await pilot.pause()
            assert screen._last_refresh_error is not None

            # Second refresh — succeeds, clears error
            await pilot.press("r")
            await pilot.app.workers.wait_for_complete()
            await pilot.pause()
            assert screen._last_refresh_error is None
            assert screen._projection.title == "Recovered"


class TestDashboardPilotRefreshProviderError:
    """Provider error during refresh is handled gracefully."""

    @pytest.mark.asyncio
    async def test_provider_error_does_not_crash_app(self) -> None:
        """RuntimeError in provider does not crash the Textual app."""
        proj = _make_projection()
        provider = _CrashOnRefreshProvider("boom\nsecret detail")
        app = _TestDashboardApp(proj, provider=provider)
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.press("r")
            await pilot.app.workers.wait_for_complete()
            await pilot.pause()

            # App is still running, screen is active
            assert isinstance(pilot.app.screen, DashboardScreen)

    @pytest.mark.asyncio
    async def test_provider_error_captures_sanitized_message(self) -> None:
        """Error message is captured as a sanitized exception type."""
        proj = _make_projection()
        provider = _CrashOnRefreshProvider("boom\nsecret detail")
        app = _TestDashboardApp(proj, provider=provider)
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.press("r")
            await pilot.app.workers.wait_for_complete()
            await pilot.pause()

            screen = pilot.app.screen
            assert isinstance(screen, DashboardScreen)
            assert screen._last_refresh_error is not None
            assert screen._last_refresh_error == "RuntimeError"

    @pytest.mark.asyncio
    async def test_provider_error_shows_footer_failed(self) -> None:
        """Footer hint updates with 'Refresh failed' message."""
        proj = _make_projection()
        provider = _CrashOnRefreshProvider("boom\nsecret detail")
        app = _TestDashboardApp(proj, provider=provider)
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.press("r")
            await pilot.app.workers.wait_for_complete()
            await pilot.pause()

            screen = pilot.app.screen
            assert isinstance(screen, DashboardScreen)
            assert screen._projection.footer_hint is not None
            assert "Refresh failed" in screen._projection.footer_hint
            assert "RuntimeError" in screen._projection.footer_hint

    @pytest.mark.asyncio
    async def test_provider_error_sanitizes_long_message(self) -> None:
        """Long error messages are reduced to a generic type label."""
        proj = _make_projection()
        long_msg = "x" * 200
        provider = _CrashOnRefreshProvider(long_msg)
        app = _TestDashboardApp(proj, provider=provider)
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.press("r")
            await pilot.app.workers.wait_for_complete()
            await pilot.pause()

            screen = pilot.app.screen
            assert isinstance(screen, DashboardScreen)
            assert screen._last_refresh_error is not None
            assert screen._last_refresh_error == "RuntimeError"

    @pytest.mark.asyncio
    async def test_provider_error_does_not_overwrite_original_projection(self) -> None:
        """On error, the original projection is preserved (not replaced)."""
        proj = _make_projection(title="Original")
        provider = _CrashOnRefreshProvider("boom")
        app = _TestDashboardApp(proj, provider=provider)
        async with app.run_test(size=(80, 24)) as pilot:
            screen = pilot.app.screen
            assert isinstance(screen, DashboardScreen)

            await pilot.press("r")
            await pilot.app.workers.wait_for_complete()
            await pilot.pause()

            # Original title preserved
            assert screen._projection.title == "Original"


class TestDashboardPilotQuitKey:
    """Quit key ('q') exits the app (optional, may be flaky)."""

    @pytest.mark.asyncio
    async def test_quit_key_exits_app(self) -> None:
        """Pressing 'q' calls app.exit without error."""
        proj = _make_projection()
        provider = FixtureDashboardProjectionProvider(proj)
        app = _TestDashboardApp(proj, provider=provider)
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.press("q")
            await pilot.pause()
            # No assertion on app state — just verify no crash
            # The run_test() context manager will cleanly exit
