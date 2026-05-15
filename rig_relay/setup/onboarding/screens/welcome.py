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
            "[bold cyan]👋  Welcome to Rig Relay[/]\n\n"
            "Rig Relay is a governed local coding assistant.\n\n"
            "This quick setup will help you:\n"
            "  • Pick an LLM provider (DeepSeek, OpenAI, Claude, Gemini, ...)\n"
            "  • Get an API key from their dashboard\n"
            "  • Save it so Rig Relay can start helping you code\n\n"
            "Your key stays local in ~/.rig/relay/.env — never leaves your machine."
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
