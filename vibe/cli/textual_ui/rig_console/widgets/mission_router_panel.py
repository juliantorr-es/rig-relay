"""Mission router panel widget — preview and approve mission plans.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Static

from vibe.cli.textual_ui.rig_console.projections import MissionRouterProjection


class MissionRouterPanelWidget(Vertical):
    """Render a mission plan preview from a MissionRouterProjection."""

    DEFAULT_CSS = """
MissionRouterPanelWidget {
    width: 100%;
    height: auto;
    padding: 0 1;
    margin: 0 0 1 0;
    background: $surface;
    border: solid $accent;
    display: none;
}

MissionRouterPanelWidget.visible {
    display: block;
}

MissionRouterPanelWidget > .router-header {
    width: 100%;
    height: auto;
    text-style: bold;
    color: $accent;
}

MissionRouterPanelWidget > .router-row {
    width: 100%;
    height: auto;
}
"""

    def __init__(self, projection: MissionRouterProjection | None = None) -> None:
        super().__init__()
        self._projection = projection or MissionRouterProjection()
        if self._projection.visible:
            self.add_class("visible")

    def compose(self) -> ComposeResult:
        yield Static("Mission Router Plan", classes="router-header")
        for line in self._render_lines():
            yield Static(line, classes="router-row")

    def update_projection(self, projection: MissionRouterProjection) -> None:
        self._projection = projection
        if projection.visible:
            self.add_class("visible")
        else:
            self.remove_class("visible")

        self.remove_children()
        self.mount(Static("Mission Router Plan", classes="router-header"))
        for line in self._render_lines():
            self.mount(Static(line, classes="router-row"))

    def _render_lines(self) -> list[str]:
        proj = self._projection
        if not proj.nodes:
            return [f"[dim]{proj.empty_state}[/]"]

        lines = [
            f"Plan ID: {proj.plan_id[:12] if proj.plan_id else 'None'}",
            f"Nodes: {proj.node_count}  Conflicts: {proj.conflict_count}",
        ]

        if proj.route_counts:
            routes = "  ".join(f"{k}: {v}" for k, v in sorted(proj.route_counts.items()))
            lines.append(f"Routes: {routes}")

        lines.append("")
        lines.append("Proposed Nodes:")
        for node in proj.nodes[:10]:
            # [R] runtime, [A] delegated agent, [F] fleet, [P] patch proposal, [H] human review
            prefix = "[R]"
            if node.route == "delegated_agent":
                prefix = "[A]"
            elif node.route == "fleet":
                prefix = "[F]"
            elif node.route == "patch_proposal":
                prefix = "[P]"
            elif node.route == "human_review":
                prefix = "[H]"

            risk = f"[{'red' if node.risk_level in ('high', 'critical') else 'green'}]{node.risk_level}[/]"
            lines.append(f"• {prefix} {node.title} -> [cyan]{node.route}[/] ({risk})")

        if len(proj.nodes) > 10:
            lines.append(f"... and {len(proj.nodes) - 10} more")

        lines.append("")
        lines.append("[bold]Press 'A' to approve and enqueue all nodes[/]")
        lines.append("[bold]Press 'Esc' to discard plan[/]")

        return lines


__all__ = ["MissionRouterPanelWidget"]
