"""Welcome screen — simple console-based onboarding intro."""

from __future__ import annotations

from rich import print as rprint
from rich.panel import Panel
from rich.text import Text


def show_welcome() -> str | None:
    """Show a welcome message and return the screen result."""
    rprint()
    welcome = Panel(
        Text.from_markup(
            "[bold cyan]Welcome to Rig Relay[/]\n\n"
            "Rig Relay is an agent-runtime product for governed local coding assistance.\n\n"
            "This quick setup will help you configure your API key.\n"
            "You can skip this and configure later in your config file."
        ),
        border_style="cyan",
    )
    rprint(welcome)
    rprint()
    rprint("[dim]Press Enter to continue, or type 'skip' to skip setup...[/]")
    choice = input().strip().lower()
    if choice == "skip":
        return None
    return "continue"
