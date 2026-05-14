"""Command palette provider for the Rig Console."""

from __future__ import annotations

from collections.abc import Iterable

from textual.app import SystemCommand

from vibe.cli.textual_ui.rig_console.actions import SAFE_ACTIONS, RigConsoleActionHost


def build_rig_console_commands(screen: RigConsoleActionHost) -> Iterable[SystemCommand]:
    """Yield safe command palette entries for the current dashboard screen."""
    for action in SAFE_ACTIONS:
        yield SystemCommand(
            action.title,
            action.description,
            lambda action=action: screen.run_safe_action(action),
        )
