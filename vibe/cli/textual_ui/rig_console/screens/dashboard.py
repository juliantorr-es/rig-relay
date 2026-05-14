# ruff: noqa: PLR0904, PLR0915
"""Dashboard screen — composes header, session pane, evidence rail, and footer."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, ClassVar, cast

from textual._context import NoActiveAppError
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.css.query import NoMatches
from textual.screen import Screen

from rig_relay.context.compiler import ContextCompiler
from rig_relay.context.models import ContextEnvelopeReceipt
from rig_relay.coordination.fleet_queue_runner import FleetQueueRunnerResult
from rig_relay.desktop.execution_progress import ExecutionProgressProjection
from vibe.cli.textual_ui.rig_console.actions import RigConsoleAction
from vibe.cli.textual_ui.rig_console.doctor import DoctorResult
from vibe.cli.textual_ui.rig_console.intents import DashboardActionResult
from vibe.cli.textual_ui.rig_console.projections import DashboardProjection
from vibe.cli.textual_ui.rig_console.providers import DashboardProjectionProvider
from vibe.cli.textual_ui.rig_console.session_bridge import _POLL_INTERVAL
from vibe.cli.textual_ui.rig_console.session_events import (
    CodingTranscriptItemProjection,
    SubmitPromptResult,
)
from vibe.cli.textual_ui.rig_console.widgets.activity_log import ActivityLogWidget
from vibe.cli.textual_ui.rig_console.widgets.evidence_rail import EvidenceRailWidget
from vibe.cli.textual_ui.rig_console.widgets.fleet_panel import FleetPanelWidget
from vibe.cli.textual_ui.rig_console.widgets.footer_status import FooterStatusWidget
from vibe.cli.textual_ui.rig_console.widgets.help_overlay import HelpOverlayWidget
from vibe.cli.textual_ui.rig_console.widgets.inspector_drawer import (
    InspectorDrawerWidget,
)
from vibe.cli.textual_ui.rig_console.widgets.mission_router_panel import (
    MissionRouterPanelWidget,
)
from vibe.cli.textual_ui.rig_console.widgets.notification_panel import (
    NotificationPanelWidget,
)
from vibe.cli.textual_ui.rig_console.widgets.operator_header import OperatorHeaderWidget
from vibe.cli.textual_ui.rig_console.widgets.progress_timeline import (
    ProgressTimelineWidget,
)
from vibe.cli.textual_ui.rig_console.widgets.prompt_bar import PromptBar
from vibe.cli.textual_ui.rig_console.widgets.queue_panel import QueuePanelWidget
from vibe.cli.textual_ui.rig_console.widgets.session_pane import SessionPaneWidget
from vibe.cli.textual_ui.rig_console.widgets.status_bar import StatusBarWidget
from vibe.cli.textual_ui.rig_console.widgets.transcript import TranscriptWidget


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
    background: $surface;
    color: $text;
    layers: base help;
}

DashboardScreen > .dashboard-activity {
    height: 1fr;
    width: 100%;
}

DashboardScreen > .dashboard-activity > SessionPaneWidget {
    width: 1fr;
    height: 1fr;
    border-right: solid $border;
}

DashboardScreen > .dashboard-activity > EvidenceRailWidget {
    width: 35;
    height: 1fr;
}

PromptBar {
    height: 3;
    margin: 0 1;
}

StatusBarWidget {
    height: 1;
}

ActivityLogWidget {
    height: 5;
    border-top: solid $border;
}

FooterStatusWidget {
    height: auto;
}

/* Optional panels as overlays/drawers */
FleetPanelWidget, QueuePanelWidget, InspectorDrawerWidget, MissionRouterPanelWidget, ProgressTimelineWidget {
    display: none;
}

FleetPanelWidget.visible, QueuePanelWidget.visible, InspectorDrawerWidget.visible, MissionRouterPanelWidget.visible, ProgressTimelineWidget.visible {
    display: block;
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
        ("f", "toggle_fleet_panel", "Fleet"),
        ("shift+f", "inspect_selected_fleet_item", "Inspect Fleet"),
        ("ctrl+f", "refresh_fleet_state", "Refresh Fleet"),
        ("Enter", "focus_prompt", "Focus Prompt"),
        ("a", "approve_mission_plan", "Approve Plan"),
        ("escape", "cancel_or_discard", "Cancel / Discard"),
        ("x", "queue_run_next", "Run Next"),
        ("ctrl+x", "queue_run_next", "Run Next"),
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
        self._fleet_visible: bool = False
        self._turn_active: bool = False
        self._context_envelope: ContextEnvelopeReceipt | None = None
        self._local_queue_payloads: dict[str, str] = {}

    def compose(self) -> ComposeResult:
        proj = self._projection

        yield OperatorHeaderWidget(proj)
        yield StatusBarWidget(proj)

        with Horizontal(classes="dashboard-activity"):
            yield SessionPaneWidget(proj.session)
            yield EvidenceRailWidget(proj.evidence)

        yield ActivityLogWidget()
        yield TranscriptWidget(proj.transcript)
        yield PromptBar(on_submit=self._handle_prompt_submit)
        yield FooterStatusWidget(proj)

        # Optional / Hidden by default
        yield MissionRouterPanelWidget(proj.mission_router)
        yield ProgressTimelineWidget(proj.execution_progress or None)
        yield FleetPanelWidget(proj.fleet)
        yield QueuePanelWidget(proj.queue)
        yield InspectorDrawerWidget(proj.inspector)

        # Overlays
        yield HelpOverlayWidget()
        yield NotificationPanelWidget()

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

    def action_toggle_fleet_panel(self) -> None:
        self._fleet_visible = not self._fleet_visible
        self._set_status("info", "fleet", "open" if self._fleet_visible else "closed")

    async def action_refresh_fleet_state(self) -> None:
        await self.action_refresh()

    def action_inspect_selected_fleet_item(self) -> None:
        fleet = self._projection.fleet
        inspector = self._projection.inspector
        if fleet is None or not inspector.items:
            self._set_status("info", "fleet", "No fleet item selected")
            return
        for index, item in enumerate(inspector.items):
            if item.source_kind == "fleet_summary":
                self._projection = self._projection.model_copy(
                    update={
                        "inspector": inspector.model_copy(
                            update={"selected_index": index, "visible": True}
                        )
                    }
                )
                self._set_status("info", "inspector", "open")
                return
        self._set_status("info", "fleet", "No fleet item selected")

    def action_queue_message(self) -> None:
        widget = self._prompt_bar_widget()
        if widget is None:
            self._set_status("error", "queue_message", "PromptBar unavailable")
            return
        self._set_status("info", "queue_message", "Use Enter in PromptBar to send")

    def action_clear_input(self) -> None:
        widget = self._prompt_bar_widget()
        if widget is None:
            self._set_status("error", "clear_input", "PromptBar unavailable")
            return
        widget.clear_input()
        self._set_status("info", "clear_input", "PromptBar cleared")

    def action_steer_current_task(self) -> None:
        self._set_status("info", "steer", "STEER mode not implemented yet")

    def action_focus_prompt(self) -> None:
        """Focus the PromptBar input field."""
        prompt = self._prompt_bar_widget()
        if prompt is not None:
            prompt.focus_input()
            self._set_status("info", "focus_prompt", "Prompt focused")
        else:
            self._set_status("error", "focus_prompt", "PromptBar unavailable")

    async def action_approve_mission_plan(self) -> None:
        """Approve and enqueue the active mission plan."""
        if not self._projection.mission_router.visible:
            return

        if self._provider is None:
            self._set_status("error", "approve_mission", "No provider configured")
            return

        self._set_status("info", "approve_mission", "Approving mission plan...")
        res = await self._provider.approve_mission_plan(self._projection.mission_router)
        if res.decision == "completed":
            self._set_status("ok", "approve_mission", "Mission plan enqueued")
            await self.action_refresh()
        else:
            self._set_status(
                "error", "approve_mission", f"Failed: {res.reason or 'unknown'}"
            )

    def action_cancel_or_discard(self) -> None:
        """Cancel active turn or discard overlays/plan.

        Priority order:
        1. Cancel active turn
        2. Close help overlay
        3. Close notification
        4. Close inspector
        5. Discard mission plan
        """
        if self._turn_active:
            self.run_worker(self._cancel_active_turn(), exclusive=True)
            return
        try:
            help_overlay = self.query_one(HelpOverlayWidget)
            if help_overlay.has_class("visible"):
                help_overlay.toggle()
                return
        except NoMatches:
            pass

        try:
            notif = self.query_one(NotificationPanelWidget)
            if notif.has_class("visible"):
                notif.clear()
                return
        except NoMatches:
            pass

        if self._projection.inspector.visible:
            self.action_toggle_inspector()
            return

        if not self._projection.mission_router.visible:
            return

        self._projection.mission_router.visible = False
        self._render_all()
        self._set_status("info", "discard_mission", "Mission plan discarded")

    async def _cancel_active_turn(self) -> None:
        if self._provider is None:
            return
        self._set_status("info", "session", "Cancelling turn...")
        prompt_bar = self._prompt_bar_widget()
        if prompt_bar:
            prompt_bar.set_status("Cancelling")
        await self._provider.cancel_turn()
        self._turn_active = False
        self._set_status("info", "session", "Turn cancelled")

    async def _run_doctor(self) -> None:
        result = DoctorResult.default()
        summary = result.run_all()
        self._set_status("info", "doctor", summary.to_text().replace("\n", " | ")[:200])

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
        """Toggle the help overlay."""
        try:
            self.query_one(HelpOverlayWidget).toggle()
            self._set_status("info", "help", "Help toggled")
        except NoMatches:
            self._set_status("error", "help", "Help overlay unavailable")

        # Compatibility footer hint for existing tests
        # Always update this so unmounted unit tests can verify the hint string
        self._projection = self._projection.model_copy(
            update={"footer_hint": "Available: quit, refresh, help, details"}
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

    def _handle_prompt_submit(self, text: str) -> object | None:
        if text.startswith("//"):
            self.run_worker(lambda: self._do_turn(text[1:]), exclusive=True)
            return None
        if text.startswith("/"):
            return self._handle_slash_command(text)
        self.run_worker(lambda: self._do_turn(text), exclusive=True)
        return None

    def _handle_queue_input(self, text: str) -> object | None:
        return self._handle_prompt_submit(text)

    def _handle_slash_command(self, text: str) -> object | None:
        command, _, remainder = text.partition(" ")
        result: object | None = None
        match command:
            case "/validate":
                validate_task = self.action_run_validate()
                self.run_worker(cast(Any, validate_task), exclusive=True)
            case "/queue":
                self.action_toggle_queue_panel()
            case "/fleet":
                self.action_toggle_fleet_panel()
            case "/router" | "/plan" | "/mission":
                if remainder.strip():
                    self.run_worker(
                        cast(Any, self._route_mission_batch(remainder.strip())),
                        exclusive=True,
                    )
            case "/inspect":
                self.action_toggle_inspector()
            case "/doctor":
                self.run_worker(self._run_doctor(), exclusive=True)
            case "/help":
                self.action_show_help()
        return result

    async def _do_turn(self, text: str) -> None:
        provider = cast(Any, self._provider)
        if provider is None or not hasattr(provider, "submit_user_message"):
            return

        prompt_bar = self._prompt_bar_widget()
        self._set_turn_starting(prompt_bar)
        turn_result: str | None = None

        try:
            snapshot = (
                await provider.snapshot() if hasattr(provider, "snapshot") else None
            )
        except Exception:
            snapshot = None
        store = getattr(provider, "receipt_store", None) if provider else None
        repo_index = getattr(self, "_repo_index", None)
        if repo_index is None:
            from rig_relay.context.repo_index import RepoContextIndex

            try:
                ri = RepoContextIndex(workspace_root=Path.cwd())
                if ri.is_available:
                    ri.populate()
                    self._repo_index = ri
                    repo_index = ri
            except Exception:
                self._repo_index = None
        compiler = ContextCompiler(
            session_id=self._projection.session.session_id,
            receipt_store=store,
            repo_index=repo_index,
        )
        envelope = compiler.build_envelope(user_text=text, snapshot=snapshot)
        self._context_envelope = envelope
        try:
            status_bar = self.query_one(StatusBarWidget)
            status_bar.set_context_envelope(envelope)
        except Exception:
            pass

        try:
            result = await provider.submit_user_message(text, context_envelope=envelope)
            if not result.accepted:
                self._set_turn_refused(prompt_bar, result)
                return

            self._set_turn_accepted(prompt_bar)
            turn_result = await self._consume_turn_stream(provider)
        except asyncio.CancelledError:
            turn_result = "cancelled"
            await provider.cancel_turn()
            self._set_status("info", "session", "Turn cancelled")
        except Exception as exc:
            turn_result = "failed"
            self._set_status("error", "session", type(exc).__name__)
        finally:
            self._turn_active = False
            if prompt_bar:
                prompt_bar.set_disabled(False)
                if turn_result == "cancelled":
                    prompt_bar.set_status("Cancelled")
                elif turn_result == "failed":
                    prompt_bar.set_status("Failed")
                else:
                    prompt_bar.set_status("Ready")
            if turn_result == "completed":
                self._set_status("ok", "session", "Turn completed")

    async def _consume_turn_stream(self, provider: Any) -> str:
        """Consume events from the bridge event stream. Returns final status."""
        turn_id = getattr(provider, "active_turn_id", "")
        if not turn_id:
            return "failed"
        try:
            async for item in provider.stream_events(turn_id):
                self._on_session_event(item)
                if item.kind == "turn_status":
                    return item.status or "completed"
            return "completed"
        except AttributeError:
            return await self._fallback_poll(provider)

    async def _fallback_poll(self, provider: Any) -> str:
        """Fallback polling path for providers without stream_events."""
        cursor: str | None = None
        while self._turn_active:
            try:
                events = await provider.events_since(cursor)
            except AttributeError:
                return "failed"
            for item in events.items:
                self._on_session_event(item)
                if item.kind == "turn_status":
                    return item.status or "completed"
            if events.cursor:
                cursor = events.cursor
            if self._turn_active:
                await asyncio.sleep(_POLL_INTERVAL)
        return "completed"

    def _set_turn_starting(self, prompt_bar: PromptBar | None) -> None:
        if prompt_bar:
            prompt_bar.set_disabled(True, "Starting")
        self._turn_active = True
        self._set_status("running", "session", "Turn running")

    def _set_turn_refused(
        self, prompt_bar: PromptBar | None, result: SubmitPromptResult
    ) -> None:
        self._turn_active = False
        if prompt_bar:
            prompt_bar.set_disabled(False)
            prompt_bar.set_status(result.refusal_reason or result.status)
        self._set_status("refused", "session", result.refusal_reason or result.status)
        self._render_all()

    def _set_turn_accepted(self, prompt_bar: PromptBar | None) -> None:
        if prompt_bar:
            prompt_bar.clear_input()
            prompt_bar.set_status("Running")

    def _on_session_event(self, item: CodingTranscriptItemProjection) -> None:
        match item.kind:
            case "user_message":
                self._set_status("running", "session", "User message received")
                self._update_transcript_incremental(item)
            case "assistant_message":
                self._set_status("running", "session", "Assistant responding")
                self._update_transcript_incremental(item)
            case "tool_activity":
                name = item.tool_name or "?"
                self._set_status("running", "tool", f"Running {name}")
                self._set_status("running", "session", "Tool running")
                self._update_transcript_incremental(item)
            case "tool_result":
                name = item.tool_name or "?"
                status = item.status or "done"
                self._set_status(status, "tool", f"{name} {status}")
                self._update_transcript_incremental(item)
            case "turn_status":
                if item.status == "completed":
                    self._set_status("ok", "session", "Turn completed")
                elif item.status == "cancelled":
                    self._set_status("info", "session", "Turn cancelled")
                elif item.status == "failed":
                    self._set_status("error", "session", "Turn failed")
            case "error":
                kind = item.error_kind or "Error"
                self._set_status("error", "session", kind)

    def _update_transcript_incremental(
        self, item: CodingTranscriptItemProjection
    ) -> None:
        try:
            transcript = self.query_one(TranscriptWidget)
            transcript.append_item(item)
        except NoMatches:
            pass

    async def _route_mission_batch(self, text: str) -> None:
        """Worker to route a mission batch via provider."""
        if self._provider is None:
            self._set_status("error", "mission_router", "No provider configured")
            return

        try:
            projection = await self._provider.route_mission_batch(text)
            self._projection.mission_router = projection
            self.action_clear_input()
            self._render_all()
            self._set_status("ok", "mission_router", "Mission plan ready")
        except Exception as e:
            self._set_status("error", "mission_router", f"Routing failed: {e!s}")

    def _prompt_bar_widget(self) -> PromptBar | None:
        try:
            return self.query_one(PromptBar)
        except NoMatches:
            return None

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
            queue_panel.display = proj.queue.visible

            router_panel = self.query_one(MissionRouterPanelWidget)
            router_panel.update_projection(proj.mission_router)

            fleet_panel = self.query_one(FleetPanelWidget)
            fleet_panel.update_projection(proj.fleet)
            fleet_panel.display = self._fleet_visible

            ep = proj.execution_progress or ExecutionProgressProjection()
            timeline = self.query_one(ProgressTimelineWidget)
            timeline.update_projection(ep)

            transcript = self.query_one(TranscriptWidget)
            transcript.update_projection(proj.transcript)

            inspector = self.query_one(InspectorDrawerWidget)
            inspector.update_projection(proj.inspector)

            status_bar = self.query_one(StatusBarWidget)
            status_bar.update_projection(proj)

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
        try:
            self.query_one(ActivityLogWidget).add_log(status, action_name, message)
        except NoMatches:
            pass

        if status in {"error", "blocked", "refused"}:
            self._show_recovery_hint(action_name, message)

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
        except (AttributeError, Exception):
            pass

    def _show_recovery_hint(self, action: str, message: str | None) -> None:
        """Show a recovery hint for common error patterns."""
        hint = None
        title = "RECOVERY HINT"

        msg = (message or "").lower()
        if "coordination_root" in msg or "root missing" in msg:
            hint = "Check your coordination root configuration. Ensure the directory exists and is writable."
        elif "runtime" in msg and "unavailable" in msg:
            hint = "The runtime executor is not configured or the session is invalid."
        elif "lease" in msg and "conflict" in msg:
            hint = "A lease conflict was detected. Inspect the Fleet panel for active leases on these paths."
        elif "validation" in msg and "failed" in msg:
            hint = "Validation failed. Inspect the latest receipt in the Evidence rail for details."
        elif "mission" in msg and "blocked" in msg:
            hint = "Mission is blocked by conflicts. Inspect the Mission Router panel for dependency/path conflicts."
        elif "audit" in msg and "unavailable" in msg:
            hint = "Audit persistence failed. The action completed but history was not saved."

        if hint:
            try:
                self.query_one(NotificationPanelWidget).notify(title, hint)
            except NoMatches:
                pass
