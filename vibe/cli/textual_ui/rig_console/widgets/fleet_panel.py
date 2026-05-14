"""Fleet panel widget — renders fleet coordination state from a FleetProjection.

This widget is projection-first: it only displays content-light projection
data. It never reads raw coordination artifacts, logs, or tool output
directly. It has no mutation keybindings.

Phase 0: read-only display. Shows empty state clearly when no fleet
data is available. Shows active lease/blocker/queue counts when present.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Static

from rig_relay.coordination.fleet_projection import (
    FleetBlockerSummary,
    FleetLeaseSummary,
    FleetProjection,
    FleetQueueSummary,
)

# ── Constants ──────────────────────────────────────────────────────────

_MAX_LABEL_LENGTH = 25


def _cap(text: str, max_chars: int = _MAX_LABEL_LENGTH) -> str:
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3] + "..."


def _format_queue(queue: FleetQueueSummary) -> str:
    """Format queue summary as a compact status line."""
    parts: list[str] = []
    if queue.queued:
        parts.append(f"[blue]{queue.queued} queued[/]")
    if queue.running:
        parts.append(f"[green]{queue.running} running[/]")
    if queue.blocked:
        parts.append(f"[red]{queue.blocked} blocked[/]")
    if queue.completed:
        parts.append(f"[dim]{queue.completed} done[/]")
    if queue.failed:
        parts.append(f"[red]{queue.failed} failed[/]")
    if not parts:
        return "[dim]queue empty[/]"
    return "  ".join(parts)


def _format_next_item(queue: FleetQueueSummary) -> str:
    """Format next runnable item summary."""
    ni = queue.next_item
    if ni is None:
        return ""
    kind = ni.kind or "?"
    return f"next: {kind} (pri {ni.priority})"


def _format_replay(queue: FleetQueueSummary) -> str:
    """Format replay diagnostics."""
    r = queue.replay
    if r is None:
        return ""
    parts: list[str] = []
    if r.total_skipped:
        parts.append(f"[yellow]{r.malformed_lines} malformed[/]")
        parts.append(f"[yellow]{r.invalid_events} invalid[/]")
        parts.append(f"[yellow]{r.skipped_unknown_kind} unknown[/]")
    return "  ".join(parts) if parts else ""


def _format_leases(leases: FleetLeaseSummary) -> str:
    """Format lease summary."""
    parts: list[str] = []
    if leases.total_active:
        parts.append(f"[green]{leases.total_active} active[/]")
    if leases.exclusive_write:
        parts.append(f"[yellow]{leases.exclusive_write} write[/]")
    if leases.shared_read:
        parts.append(f"[cyan]{leases.shared_read} read[/]")
    if leases.stale:
        parts.append(f"[red]{leases.stale} stale[/]")
    if leases.expired:
        parts.append(f"[dim]{leases.expired} expired[/]")
    if not parts:
        return "[dim]no leases[/]"
    return "  ".join(parts)


def _format_blockers(blockers: FleetBlockerSummary) -> str:
    """Format blocker summary."""
    if not blockers.total_blockers:
        return "[dim]no blockers[/]"
    parts: list[str] = []
    for kind, count in sorted(blockers.blocker_kinds.items()):
        parts.append(f"[red]{count} {_cap(kind)}[/]")
    if blockers.oldest_blocked_at:
        parts.append(f"since {blockers.oldest_blocked_at[:19]}")
    return "  ".join(parts)


def _format_patches(patches: FleetProjection) -> str:
    """Format patch proposal summary."""
    p = patches.patches
    if not p.total:
        return "[dim]no patches[/]"
    parts: list[str] = []
    if p.pending:
        parts.append(f"[yellow]{p.pending} pending[/]")
    if p.applied:
        parts.append(f"[green]{p.applied} applied[/]")
    if p.rejected:
        parts.append(f"[dim]{p.rejected} rejected[/]")
    return "  ".join(parts)


def _format_agents(agents: FleetProjection) -> str:
    """Format agent/session summary."""
    a = agents.agents
    if not a.total_agents:
        return "[dim]no agents[/]"
    parts: list[str] = [f"{a.total_agents} agents"]
    if a.active_sessions:
        parts.append(f"[green]{a.active_sessions} active[/]")
    if a.stale_sessions:
        parts.append(f"[red]{a.stale_sessions} stale[/]")
    return "  ".join(parts)


class FleetPanelWidget(Vertical):
    """Render fleet coordination state from a FleetProjection.

    Read-only display. No keybindings for mutation.

    States:
    - Empty: projection is None → single line "Fleet panel: no data"
    - All zero: all summaries show dim "no X" labels
    - Active data: colored counts per subsystem
    """

    DEFAULT_CSS = """
FleetPanelWidget {
    width: 100%;
    height: auto;
    padding: 0 1;
    margin: 0 0 1 0;
    background: $surface;
    border: solid $border;
}

FleetPanelWidget > .fleet-header {
    width: 100%;
    height: auto;
    text-style: bold;
    color: $text;
}

FleetPanelWidget > .fleet-row {
    width: 100%;
    height: auto;
}

FleetPanelWidget > .fleet-row > Static {
    width: 1fr;
    height: auto;
}
"""

    def __init__(self, projection: FleetProjection | None = None) -> None:
        super().__init__()
        self._projection = projection

    def compose(self) -> ComposeResult:
        yield Static("Fleet Panel", classes="fleet-header")
        if self._projection is None:
            yield Static("[dim]no fleet data[/]", classes="fleet-row")
            return

        proj = self._projection

        with Horizontal(classes="fleet-row"):
            yield Static(f"Queue: {_format_queue(proj.queue)}")
        with Horizontal(classes="fleet-row"):
            yield Static(f"Leases: {_format_leases(proj.leases)}")
        with Horizontal(classes="fleet-row"):
            yield Static(f"Blockers: {_format_blockers(proj.blockers)}")
        with Horizontal(classes="fleet-row"):
            yield Static(f"Patches: {_format_patches(proj)}")
        with Horizontal(classes="fleet-row"):
            yield Static(f"Agents: {_format_agents(proj)}")
        next_text = _format_next_item(proj.queue)
        if next_text:
            with Horizontal(classes="fleet-row"):
                yield Static(f"Next: {next_text}")
        replay_text = _format_replay(proj.queue)
        if replay_text:
            with Horizontal(classes="fleet-row"):
                yield Static(f"Replay: {replay_text}")
        if proj.recent_event_count:
            yield Static(
                f"Recent events: {proj.recent_event_count}", classes="fleet-row"
            )

    def update_projection(self, projection: FleetProjection | None) -> None:
        """Replace the projection and re-render."""
        self._projection = projection
        self.remove_children()
        self.mount_all(self.compose() if False else [])
        # Rebuild via compose
        for widget in list(self.children):
            widget.remove()
        for child in self._build_widgets():
            self.mount(child)

    def _build_widgets(self) -> list:
        """Build widget list from current projection.

        Returns flat list of Static widgets. The with Horizontal(...)
        wrappers used in compose() are omitted here because they require
        an active Textual app context. update_projection() mounts these
        widgets directly.
        """
        widgets: list = [Static("Fleet Panel", classes="fleet-header")]
        if self._projection is None:
            widgets.append(Static("[dim]no fleet data[/]", classes="fleet-row"))
            return widgets

        proj = self._projection
        widgets.append(
            Static(f"Queue: {_format_queue(proj.queue)}", classes="fleet-row")
        )
        widgets.append(
            Static(f"Leases: {_format_leases(proj.leases)}", classes="fleet-row")
        )
        widgets.append(
            Static(f"Blockers: {_format_blockers(proj.blockers)}", classes="fleet-row")
        )
        widgets.append(Static(f"Patches: {_format_patches(proj)}", classes="fleet-row"))
        widgets.append(Static(f"Agents: {_format_agents(proj)}", classes="fleet-row"))
        next_text = _format_next_item(proj.queue)
        if next_text:
            widgets.append(Static(f"Next: {next_text}", classes="fleet-row"))
        replay_text = _format_replay(proj.queue)
        if replay_text:
            widgets.append(Static(f"Replay: {replay_text}", classes="fleet-row"))
        if proj.recent_event_count:
            widgets.append(
                Static(f"Recent events: {proj.recent_event_count}", classes="fleet-row")
            )
        return widgets
