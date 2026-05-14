"""Fleet panel widget — renders fleet coordination state from a FleetProjection.

This widget is projection-first: it only displays content-light projection
data. It never reads raw coordination artifacts, logs, or tool output
directly. It has no mutation keybindings.

Phase 0: read-only display. Shows empty state clearly when no fleet
data is available. Shows active lease/blocker/queue counts when present.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
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
    parts.append(f"[dim]{r.valid_events}/{r.total_lines} valid[/]")
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
    if p.revised:
        parts.append(f"[cyan]{p.revised} needs revision[/]")
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
    """

    DEFAULT_CSS = """
FleetPanelWidget {
    width: 35;
    height: 1fr;
    padding: 0 1;
    background: $surface;
    border-left: solid $border;
    display: none;
}

FleetPanelWidget.visible {
    display: block;
}

FleetPanelWidget > .fleet-header {
    width: 100%;
    height: auto;
    text-style: bold;
    color: $text;
    margin-bottom: 1;
}

FleetPanelWidget > .agent-row {
    width: 100%;
    height: auto;
    margin-bottom: 0;
}

FleetPanelWidget > .fleet-metrics {
    width: 100%;
    height: auto;
    margin-top: 1;
    border-top: solid $border;
    padding-top: 1;
}

FleetPanelWidget > .metric-row {
    width: 100%;
    height: auto;
    color: $text-muted;
}
"""

    def __init__(self, projection: FleetProjection | None = None) -> None:
        super().__init__()
        self._projection = projection

    def compose(self) -> ComposeResult:
        if self._projection:
            self.add_class("visible")
        yield Static("WORKFORCE", classes="fleet-header")
        yield from self._build_widgets()

    def update_projection(self, projection: FleetProjection | None) -> None:
        """Replace the projection and re-render."""
        self._projection = projection
        if projection:
            self.add_class("visible")
        else:
            self.remove_class("visible")
        self.remove_children()
        self.mount(Static("WORKFORCE", classes="fleet-header"))
        self.mount_all(self._build_widgets())

    def _build_widgets(self) -> list[Static | FleetMetricsWidget]:
        if self._projection is None:
            return [Static("[dim]no fleet data[/]", classes="agent-row")]

        proj = self._projection
        widgets: list[Static | FleetMetricsWidget] = []

        # 1. Individual Agent Strip
        if proj.agent_details:
            for agent in proj.agent_details:
                status_color = (
                    "green"
                    if agent.status == "READY"
                    else "cyan"
                    if agent.status == "RUNNING"
                    else "yellow"
                    if agent.status == "QUEUED"
                    else "dim"
                )
                row = f"{_cap(agent.agent_id, 16):18} [{status_color}]{agent.status:8}[/] "
                meta = []
                if agent.role:
                    meta.append(agent.role)
                if agent.last_heartbeat_age:
                    meta.append(agent.last_heartbeat_age)
                if meta:
                    row += f"[dim]{' · '.join(meta)}[/]"
                widgets.append(Static(row, classes="agent-row"))
        else:
            # Fallback to aggregate agents if no details available
            widgets.append(Static(_format_agents(proj), classes="agent-row"))

        # 2. Aggregate Metrics (Compact)
        widgets.append(FleetMetricsWidget(proj))

        return widgets


class FleetMetricsWidget(Vertical):
    """Internal widget for compact fleet metrics."""

    def __init__(self, projection: FleetProjection) -> None:
        super().__init__(classes="fleet-metrics")
        self._projection = projection

    def compose(self) -> ComposeResult:
        proj = self._projection
        yield Static(f"QUEUE:    {_format_queue(proj.queue)}", classes="metric-row")
        yield Static(f"LEASES:   {_format_leases(proj.leases)}", classes="metric-row")
        yield Static(
            f"BLOCKERS: {_format_blockers(proj.blockers)}", classes="metric-row"
        )
        yield Static(f"PATCHES:  {_format_patches(proj)}", classes="metric-row")

        next_text = _format_next_item(proj.queue)
        if next_text:
            yield Static(f"NEXT:     {next_text}", classes="metric-row")


__all__ = ["FleetPanelWidget"]
