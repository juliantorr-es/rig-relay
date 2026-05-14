"""Dashboard screen — composes header, session pane, evidence rail, and footer."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any, ClassVar

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.screen import Screen

from rig_relay.desktop.execution_progress import ExecutionProgressProjection
from vibe.cli.textual_ui.rig_console.actions import RigConsoleAction
from vibe.cli.textual_ui.rig_console.intents import DashboardActionResult
from vibe.cli.textual_ui.rig_console.projections import DashboardProjection
from vibe.cli.textual_ui.rig_console.providers import DashboardProjectionProvider
from vibe.cli.textual_ui.rig_console.widgets.evidence_rail import EvidenceRailWidget
from vibe.cli.textual_ui.rig_console.widgets.footer_status import FooterStatusWidget
from vibe.cli.textual_ui.rig_console.widgets.operator_header import OperatorHeaderWidget
from vibe.cli.textual_ui.rig_console.widgets.progress_timeline import (
    ProgressTimelineWidget,
)
from vibe.cli.textual_ui.rig_console.widgets.session_pane import SessionPaneWidget


class DashboardScreen(Screen):
    """Compose header, activity zone, and footer from a DashboardProjection.

    Accepts an optional DashboardProjectionProvider for live refresh.
    Without a provider, keybound actions are no-op placeholders.

    Layout:
        ┌─ Header (OperatorHeaderWidget) ─────────────────┐
        ├─ Activity (SessionPaneWidget | EvidenceRailWidget) ─┤
        ├─ Footer (FooterStatusWidget) ──────────────────┘

    Keybindings:
        q — quit
        r — refresh projection from provider (no-op without provider)
        ? / h — show available actions in footer
        t — toggle detail hints
        e — focus evidence rail (placeholder, read-only)
        v — validate current status (placeholder, read-only)
    """

    DEFAULT_CSS = """
DashboardScreen {
    background: #06110B;
}

DashboardScreen > .dashboard-activity {
    width: 100%;
    height: auto;
}

DashboardScreen > .dashboard-activity > SessionPaneWidget {
    width: 50%;
    height: auto;
}

DashboardScreen > .dashboard-activity > EvidenceRailWidget {
    width: 50%;
    height: auto;
}
"""

    BINDINGS: ClassVar[list[tuple[str, str, str]]] = [
        ("q", "quit", "Quit"),
        ("r", "refresh", "Refresh"),
        ("?", "show_help", "Help"),
        ("h", "show_help", "Help"),
        ("t", "toggle_details", "Details"),
        ("e", "focus_evidence", "Evidence"),
        ("v", "validate_current", "Validate"),
    ]

    def __init__(
        self,
        projection: DashboardProjection,
        provider: DashboardProjectionProvider | None = None,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._projection = projection
        self._provider = provider
        self._refresh_in_progress: bool = False
        self._last_refresh_error: str | None = None
        self._last_refresh_at: str | None = None
        self._details_visible: bool = False

    def compose(self) -> ComposeResult:
        proj = self._projection

        yield OperatorHeaderWidget(proj)
        yield Horizontal(
            SessionPaneWidget(proj.session),
            EvidenceRailWidget(proj.evidence),
            classes="dashboard-activity",
        )
        yield ProgressTimelineWidget(proj.execution_progress or None)
        yield FooterStatusWidget(proj)

    def action_quit(self) -> None:
        self.app.exit()

    async def action_refresh(self) -> None:
        """Start a background refresh worker. Returns immediately.

        Without a provider, refresh is a safe no-op.
        With a provider, schedules a deferred worker via run_worker()
        so receipt/session reads don't block the UI event loop.
        """
        if self._provider is None:
            self._set_feedback("refresh", "No provider configured")
            return
        self._set_status("info", "refresh", "Refresh started")
        self._refresh_in_progress = True
        self.run_worker(self._do_refresh, exclusive=True, exit_on_error=False)

    async def _do_refresh(self) -> None:
        """Worker body: call provider and update projection.

        Runs in a Textual worker — the UI remains responsive.
        Cancelled workers (via exclusive=True) are handled gracefully.
        Exceptions are caught, sanitized, and displayed in footer.
        """
        if self._provider is None:
            self._refresh_in_progress = False
            return
        self._refresh_in_progress = True
        try:
            new_proj = await self._provider.dashboard_projection()
            self.update_projection(new_proj)
            self._last_refresh_at = datetime.now(UTC).isoformat()
            self._last_refresh_error = None
            self._set_status("ok", "refresh", "Refresh complete")
        except asyncio.CancelledError:
            pass  # Exclusive worker replaced by newer refresh
        except Exception as e:
            sanitized = type(e).__name__
            self._last_refresh_error = sanitized
            self._set_status("error", "refresh", f"Refresh failed: {sanitized}")
        finally:
            self._refresh_in_progress = False

    def action_show_help(self) -> None:
        """Show available keybindings in the footer."""
        self._details_visible = True
        self._set_feedback(
            "show_help",
            "Available: refresh, help, details, runtime, leases, audit, copy",
        )

    def action_toggle_details(self) -> None:
        """Toggle the detail hint state without mutating backend data."""
        self._details_visible = not self._details_visible
        footer = "details: on" if self._details_visible else "details: off"
        self._set_status("info", "details", footer)

    def action_show_runtime_status(self) -> None:
        """Show runtime adapter status."""
        status = self._projection.session.status or "unknown"
        self._set_feedback("runtime_status", f"Runtime status: {status}")

    def action_show_leases(self) -> None:
        """Show blocker summary as a lease/status snapshot."""
        blockers = self._projection.session.blocker_summary
        if not blockers:
            self._set_feedback("leases", "No active leases or blockers")
            return
        parts = ", ".join(f"{count} {key}" for key, count in blockers.items())
        self._set_feedback("leases", f"Leases/blockers: {parts}")

    def action_show_audit_timeline(self) -> None:
        """Show a safe audit timeline summary."""
        count = self._projection.evidence.receipt_count
        self._set_feedback("audit_timeline", f"Audit receipts: {count}")

    def action_copy_latest_receipt_ref(self) -> None:
        """Copy the latest receipt ref if clipboard support is available."""
        latest = self._projection.session.latest_receipt_kind
        if not latest:
            self._set_feedback("copy_receipt", "No receipt reference available")
            return
        try:
            import pyperclip

            pyperclip.copy(latest)
        except Exception:
            self._set_feedback("copy_receipt", "Clipboard unavailable")
            return
        self._set_feedback("copy_receipt", "Latest receipt reference copied")

    def action_focus_evidence(self) -> None:
        """Placeholder: focus/evidence action. Read-only, no mutation."""
        self._set_status(
            "info", "evidence", "Evidence action: placeholder (not wired yet)"
        )

    def action_validate_current(self) -> None:
        """Placeholder: validate-status action. Read-only, no tool execution."""
        self._set_status(
            "info", "validate", "Validate action: placeholder (read-only, not wired)"
        )

    def update_projection(self, projection: DashboardProjection) -> None:
        """Replace the projection and re-render all widgets."""
        self._projection = projection
        self._render_all()

    def _render_all(self) -> None:
        proj = self._projection

        header = self.query_one(OperatorHeaderWidget)
        header.update_projection(proj)

        session_pane = self.query_one(SessionPaneWidget)
        session_pane.update_projection(proj.session)

        evidence_rail = self.query_one(EvidenceRailWidget)
        evidence_rail.update_projection(proj.evidence)

        ep = proj.execution_progress or ExecutionProgressProjection()
        timeline = self.query_one(ProgressTimelineWidget)
        timeline.update_projection(ep)

        footer = self.query_one(FooterStatusWidget)
        footer.update_projection(proj)

    def _set_status(
        self, status: str, action_name: str, message: str | None = None
    ) -> None:
        """Update footer hint with action status without losing other state."""
        result = DashboardActionResult(
            action_name=action_name, status=status, message=message
        )
        hint_parts = [f"[{result.status}] {result.action_name}"]
        if result.message:
            hint_parts.append(result.message)
        self._projection = self._projection.model_copy(
            update={"footer_hint": "  ".join(hint_parts)}
        )
        self._render_all()

    def run_safe_action(self, action: RigConsoleAction) -> None:
        handler = getattr(self, action.callback_name, None)
        if handler is None:
            self._set_status("error", action.name, "Unknown action")
            return
        try:
            result = handler()
            if asyncio.iscoroutine(result):
                self.run_worker(result, exclusive=True, exit_on_error=False)
        except Exception as exc:
            self._set_status("error", action.name, type(exc).__name__)

    def _set_feedback(self, action_name: str, message: str) -> None:
        self._set_status("info", action_name, message)
        try:
            self.app.notify(message, title="Rig Console", severity="information")
        except Exception:
            pass
