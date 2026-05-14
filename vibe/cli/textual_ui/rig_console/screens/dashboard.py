"""Dashboard screen — composes header, session pane, evidence rail, and footer."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any, ClassVar, cast
from uuid import uuid4

from textual._context import NoActiveAppError
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.css.query import NoMatches
from textual.screen import Screen

from rig_relay.coordination.fleet_queue_runner import FleetQueueRunnerResult
from rig_relay.desktop.execution_progress import ExecutionProgressProjection
from vibe.cli.textual_ui.rig_console.actions import RigConsoleAction
from vibe.cli.textual_ui.rig_console.intents import DashboardActionResult
from vibe.cli.textual_ui.rig_console.projections import (
    DashboardProjection,
    QueueItemProjection,
)
from vibe.cli.textual_ui.rig_console.providers import DashboardProjectionProvider
from vibe.cli.textual_ui.rig_console.widgets.evidence_rail import EvidenceRailWidget
from vibe.cli.textual_ui.rig_console.widgets.fleet_panel import FleetPanelWidget
from vibe.cli.textual_ui.rig_console.widgets.footer_status import FooterStatusWidget
from vibe.cli.textual_ui.rig_console.widgets.inspector_drawer import (
    InspectorDrawerWidget,
)
from vibe.cli.textual_ui.rig_console.widgets.operator_header import OperatorHeaderWidget
from vibe.cli.textual_ui.rig_console.widgets.progress_timeline import (
    ProgressTimelineWidget,
)
from vibe.cli.textual_ui.rig_console.widgets.queue_input import QueueInputWidget
from vibe.cli.textual_ui.rig_console.widgets.queue_panel import QueuePanelWidget
from vibe.cli.textual_ui.rig_console.widgets.session_pane import SessionPaneWidget


class DashboardStatusActions:
    def action_show_runtime_status(self: Any) -> None:
        """Show runtime adapter status."""
        status = self._projection.session.status or "unknown"
        self._set_feedback("runtime_status", f"Runtime status: {status}")

    def action_show_leases(self: Any) -> None:
        """Show blocker summary as a lease/status snapshot."""
        blockers = self._projection.session.blocker_summary
        if not blockers:
            self._set_feedback("leases", "No active leases or blockers")
            return
        parts = ", ".join(f"{count} {key}" for key, count in blockers.items())
        self._set_feedback("leases", f"Leases/blockers: {parts}")

    def action_show_audit_timeline(self: Any) -> None:
        """Show a safe audit timeline summary."""
        count = self._projection.evidence.receipt_count
        self._set_feedback("audit_timeline", f"Audit receipts: {count}")

    def action_copy_latest_receipt_ref(self: Any) -> None:
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


class DashboardScreen(DashboardStatusActions, Screen):
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
        i — toggle inspector
        n / p — next / previous inspector item
        c — copy selected inspector hash/ref
        u — toggle queue panel
        j / k — next / previous queue item
        o — inspect selected queue item
        ctrl+enter — steer current task (safe placeholder)
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

DashboardScreen > InspectorDrawerWidget {
    width: 100%;
    height: auto;
}
"""

    BINDINGS: ClassVar[list[tuple[str, str, str]]] = [
        ("q", "quit", "Quit"),
        ("r", "refresh", "Refresh"),
        ("?", "show_help", "Help"),
        ("h", "show_help", "Help"),
        ("t", "toggle_details", "Details"),
        ("v", "run_validate", "Run Validate"),
        ("i", "toggle_inspector", "Inspector"),
        ("u", "toggle_queue_panel", "Queue"),
        ("j", "next_queue_item", "Next Queue"),
        ("k", "previous_queue_item", "Previous Queue"),
        ("o", "inspect_selected_queue_item", "Inspect Queue"),
        ("ctrl+enter", "steer_current_task", "Steer Current"),
        ("n", "next_item", "Next Item"),
        ("p", "previous_item", "Previous Item"),
        ("c", "copy_selected_ref", "Copy Ref"),
        ("e", "focus_evidence", "Evidence"),
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
        self._validate_in_progress: bool = False
        self._last_refresh_error: str | None = None
        self._last_refresh_at: str | None = None
        self._details_visible: bool = False
        self._local_queue_payloads: dict[str, str] = {}

    def compose(self) -> ComposeResult:
        proj = self._projection

        yield OperatorHeaderWidget(proj)
        yield Horizontal(
            SessionPaneWidget(proj.session),
            EvidenceRailWidget(proj.evidence),
            classes="dashboard-activity",
        )
        yield QueuePanelWidget(proj.queue)
        yield QueueInputWidget(
            on_queue=self._handle_queue_input, on_steer=self._handle_steer_input
        )
        yield FleetPanelWidget(proj.fleet)
        yield ProgressTimelineWidget(proj.execution_progress or None)
        yield InspectorDrawerWidget(proj.inspector)
        yield FooterStatusWidget(proj)

    def on_mount(self) -> None:
        self.focus()

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

    async def action_run_validate(self) -> None:
        provider = self._provider
        if provider is None or not hasattr(provider, "run_validate"):
            self._set_feedback("validate", "Validate unavailable: no runtime provider")
            return
        self._set_status("info", "validate", "Validate running")
        self._validate_in_progress = True
        try:
            self.run_worker(self._do_validate, exclusive=True, exit_on_error=False)
        except NoActiveAppError:
            await self._do_validate()

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

    async def _do_validate(self) -> None:
        provider = self._provider
        if provider is None or not hasattr(provider, "run_validate"):
            self._validate_in_progress = False
            return
        self._validate_in_progress = True
        try:
            result = await provider.run_validate(self._projection)
            self._set_validate_result(result)
            refreshed = await provider.dashboard_projection()
            self.update_projection(refreshed)
            self._set_status("ok", "validate", "Validate complete")
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            self._set_status("error", "validate", type(exc).__name__)
        finally:
            self._validate_in_progress = False

    def action_toggle_queue_panel(self) -> None:
        queue = self._projection.queue.model_copy(
            update={"visible": not self._projection.queue.visible}
        )
        self._projection = self._projection.model_copy(update={"queue": queue})
        self._set_status("info", "queue", "open" if queue.visible else "closed")

    def action_queue_message(self) -> None:
        widget = self._queue_input_widget()
        if widget is None:
            self._set_status("error", "queue_message", "Queue input unavailable")
            return
        widget.set_mode("QUEUE")
        widget.queue_current()

    def action_clear_input(self) -> None:
        widget = self._queue_input_widget()
        if widget is None:
            self._set_status("error", "clear_input", "Queue input unavailable")
            return
        widget.clear()
        self._set_status("info", "clear_input", "Queue input cleared")

    def action_steer_current_task(self) -> None:
        widget = self._queue_input_widget()
        if widget is not None:
            widget.set_mode("STEER")
            widget.request_steer()
            return
        self._set_status("info", "steer", "STEER mode not implemented yet")

    def action_next_queue_item(self) -> None:
        queue = self._projection.queue
        if not queue.items:
            self._set_status("info", "queue", queue.empty_state)
            return
        selected_index = (queue.selected_index + 1) % len(queue.items)
        self._sync_queue_selection(selected_index)

    def action_previous_queue_item(self) -> None:
        queue = self._projection.queue
        if not queue.items:
            self._set_status("info", "queue", queue.empty_state)
            return
        selected_index = (queue.selected_index - 1) % len(queue.items)
        self._sync_queue_selection(selected_index)

    async def action_queue_run_next(self) -> None:
        provider = self._provider
        if provider is None or not hasattr(provider, "run_next_queue_item"):
            self._set_status("error", "queue_run_next", "No provider configured")
            return
        self._set_status("info", "queue_run_next", "Running next queue item...")
        self.run_worker(self._do_queue_run_next, exclusive=True, exit_on_error=False)

    async def _do_queue_run_next(self) -> None:
        provider = cast(Any, self._provider)
        if provider is None:
            return
        try:
            result = await provider.run_next_queue_item()
            self._set_queue_runner_result(result)
            # Refresh projection after runner completes
            if hasattr(provider, "dashboard_projection"):
                refreshed = await provider.dashboard_projection()
                self.update_projection(refreshed)
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            self._set_status("error", "queue_run_next", type(exc).__name__)

    def action_queue_validate(self) -> None:
        provider = cast(Any, self._provider)
        if provider is None or not hasattr(provider, "enqueue_validate"):
            self._set_status("error", "queue_validate", "No provider configured")
            return
        result = provider.enqueue_validate()
        self._set_queue_runner_result(result)
        self._set_status("info", "queue_validate", "Validate enqueued")

    async def action_queue_refresh(self) -> None:
        provider = cast(Any, self._provider)
        if provider is None or not hasattr(provider, "dashboard_projection"):
            self._set_status("error", "queue_refresh", "No provider configured")
            return
        try:
            refreshed = await provider.dashboard_projection()
            self.update_projection(refreshed)
            self._set_status("ok", "queue_refresh", "Queue refreshed")
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            self._set_status("error", "queue_refresh", type(exc).__name__)

    def _set_queue_runner_result(self, result: FleetQueueRunnerResult) -> None:
        if result.decision == "completed":
            self._set_status("ok", "queue", f"Queue: {result.reason or 'completed'}")
        elif result.decision == "idle":
            self._set_status("info", "queue", "No runnable queue item")
        elif result.decision == "blocked":
            reason = result.reason or result.error_kind or "blocked"
            self._set_status("blocked", "queue", f"Queue blocked: {reason}")
        elif result.decision == "failed":
            reason = result.reason or result.error_kind or "failed"
            self._set_status("error", "queue", f"Queue failed: {reason}")

    def action_inspect_selected_queue_item(self) -> None:
        queue = self._projection.queue
        if not queue.items:
            self._set_status("info", "queue", queue.empty_state)
            return
        selected = queue.selected_item
        if selected is not None:
            inspector = self._projection.inspector
            for index, item in enumerate(inspector.items):
                if item.item_id == selected.queue_item_id:
                    self._projection = self._projection.model_copy(
                        update={
                            "inspector": inspector.model_copy(
                                update={"selected_index": index, "visible": True}
                            )
                        }
                    )
                    self._set_status("info", "inspector", "open")
                    break
            else:
                self.action_toggle_inspector()
        else:
            self.action_toggle_inspector()
        self._set_status("info", "queue", "selected item sent to inspector")

    def action_show_help(self) -> None:
        """Show available keybindings in the footer."""
        self._details_visible = True
        self._set_feedback(
            "show_help",
            "Available: refresh, help, details, inspector, next, prev, copy, runtime, leases, audit",
        )

    def action_toggle_details(self) -> None:
        """Toggle the detail hint state without mutating backend data."""
        self._details_visible = not self._details_visible
        footer = "details: on" if self._details_visible else "details: off"
        self._set_status("info", "details", footer)

    def _set_validate_result(self, result: object) -> None:
        status = getattr(result, "status", "failed")
        refusal_reason = getattr(result, "refusal_reason", None)
        error_kind = getattr(result, "error_kind", None)
        if status == "completed":
            self._set_status("ok", "validate", "Validate completed")
            return
        if status == "blocked":
            message = refusal_reason or error_kind or "Validate blocked"
            self._set_status("blocked", "validate", str(message))
            return
        if status == "refused":
            message = refusal_reason or error_kind or "Validate refused"
            self._set_status("refused", "validate", str(message))
            return
        message = refusal_reason or error_kind or "Validate failed"
        self._set_status("error", "validate", str(message))

    def action_toggle_inspector(self) -> None:
        inspector = self._projection.inspector.model_copy(
            update={"visible": not self._projection.inspector.visible}
        )
        self._projection = self._projection.model_copy(update={"inspector": inspector})
        self._set_status("info", "inspector", "open" if inspector.visible else "closed")

    def _sync_queue_selection(self, selected_index: int) -> None:
        queue = self._projection.queue.model_copy(
            update={"selected_index": selected_index}
        )
        self._projection = self._projection.model_copy(update={"queue": queue})
        selected = queue.selected_item
        if selected is not None:
            inspector = self._projection.inspector
            for index, item in enumerate(inspector.items):
                if item.item_id == selected.queue_item_id:
                    self._projection = self._projection.model_copy(
                        update={
                            "inspector": inspector.model_copy(
                                update={"selected_index": index}
                            )
                        }
                    )
                    break
            self._set_status("info", "queue", f"item {selected_index + 1}")

    def action_next_item(self) -> None:
        inspector = self._projection.inspector
        if not inspector.items:
            self._set_status("info", "inspector", inspector.empty_state)
            return
        selected_index = (inspector.selected_index + 1) % len(inspector.items)
        self._projection = self._projection.model_copy(
            update={
                "inspector": inspector.model_copy(
                    update={"selected_index": selected_index}
                )
            }
        )
        self._set_status("info", "inspector", f"item {selected_index + 1}")

    def action_previous_item(self) -> None:
        inspector = self._projection.inspector
        if not inspector.items:
            self._set_status("info", "inspector", inspector.empty_state)
            return
        selected_index = (inspector.selected_index - 1) % len(inspector.items)
        self._projection = self._projection.model_copy(
            update={
                "inspector": inspector.model_copy(
                    update={"selected_index": selected_index}
                )
            }
        )
        self._set_status("info", "inspector", f"item {selected_index + 1}")

    def action_copy_selected_ref(self) -> None:
        inspector = self._projection.inspector
        item = inspector.selected_item
        if item is None:
            self._set_feedback("copy_ref", inspector.empty_state)
            return
        ref = item.receipt_sha256 or item.runtime_result_sha256 or item.item_id
        try:
            import pyperclip

            pyperclip.copy(ref)
        except Exception:
            self._set_feedback("copy_ref", "Clipboard unavailable")
            return
        self._set_feedback("copy_ref", "Selected reference copied")

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

    def _queue_input_widget(self) -> QueueInputWidget | None:
        try:
            return self.query_one(QueueInputWidget)
        except NoMatches:
            return None

    def _handle_queue_input(self, text: str) -> None:
        self._queue_message(text)

    def _handle_steer_input(self, text: str) -> None:
        self._set_feedback("steer", "STEER mode requested — not implemented yet")

    def _queue_message(self, text: str) -> None:
        message = text.strip()
        if not message:
            self._set_status("info", "queue_message", "Queue input is empty")
            return
        queue_input = self._queue_input_widget()
        if queue_input is not None:
            queue_input.set_mode("QUEUE")
            queue_input.clear()
        queue = self._projection.queue
        payload_ref = f"local://queue/{uuid4().hex}"
        self._local_queue_payloads[payload_ref] = message
        item = QueueItemProjection(
            queue_item_id=f"queue-{uuid4().hex[:8]}",
            kind="message",
            status="queued",
            title="Queue message",
            summary="local payload stored",
            payload_ref=payload_ref,
            created_at=datetime.now(UTC).isoformat(),
        )
        updated_items = [*queue.items, item]
        updated_queue = queue.model_copy(
            update={
                "items": updated_items,
                "queued_count": queue.queued_count + 1,
                "selected_index": len(updated_items) - 1,
            }
        )
        self._projection = self._projection.model_copy(update={"queue": updated_queue})
        self._sync_queue_selection(updated_queue.selected_index)
        self._set_feedback("queue_message", "Queued message")

    def update_projection(self, projection: DashboardProjection) -> None:
        """Replace the projection and re-render all widgets."""
        self._projection = projection
        self._render_all()

    def _render_all(self) -> None:
        proj = self._projection
        try:
            header = self.query_one(OperatorHeaderWidget)
            header.update_projection(proj)

            session_pane = self.query_one(SessionPaneWidget)
            session_pane.update_projection(proj.session)

            evidence_rail = self.query_one(EvidenceRailWidget)
            evidence_rail.update_projection(proj.evidence)

            queue_panel = self.query_one(QueuePanelWidget)
            queue_panel.update_projection(proj.queue)

            fleet_panel = self.query_one(FleetPanelWidget)
            fleet_panel.update_projection(proj.fleet)

            ep = proj.execution_progress or ExecutionProgressProjection()
            timeline = self.query_one(ProgressTimelineWidget)
            timeline.update_projection(ep)

            inspector = self.query_one(InspectorDrawerWidget)
            inspector.update_projection(proj.inspector)

            footer = self.query_one(FooterStatusWidget)
            footer.update_projection(proj)
        except NoMatches:
            return

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
