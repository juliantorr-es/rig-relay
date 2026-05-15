"""Console-based onboarding flow — triggered when no API key is configured."""

from __future__ import annotations

from rich import print as rprint

from rig_relay.core.paths import GLOBAL_ENV_FILE
from rig_relay.setup.onboarding.screens.api_key import run_api_key_screen
from rig_relay.setup.onboarding.screens.welcome import show_welcome


def run_onboarding() -> bool:
    result = show_welcome()
    if result is None:
        rprint("\n[yellow]Setup skipped. You can always configure keys later.[/]")
        rprint(f"[dim]Set your API key env var in {GLOBAL_ENV_FILE.path}[/]")
        return False

    result = run_api_key_screen()

    match result:
        case None:
            rprint("\n[yellow]Setup skipped. See you later![/]")
        case str() as s if s.startswith("completed:"):
            parts = s.split(":")
            provider_name = parts[1] if len(parts) > 1 else "unknown"
            rprint(
                f"\n✅  [green]Setup complete! {provider_name} is now configured.[/]"
                "\n   Let's start Rig Relay..."
            )
            return True
        case str() as s if s.startswith("provider_selected:"):
            provider = s.removeprefix("provider_selected:")
            rprint(f"\n✅  [green]{provider} selected — no API key needed.[/]")
            return True
        case str() as s if s.startswith("save_error:"):
            err = s.removeprefix("save_error:")
            rprint(
                f"\n[yellow]Warning: Could not save provider key: {err}[/]\n"
                "[dim]The key is set for this session only. "
                f"Set it manually in {GLOBAL_ENV_FILE.path}[/]"
            )
            return True
        case _:
            rprint("\n[yellow]Setup incomplete. Try again or configure manually.[/]")
            rprint(f"[dim]Set your API key env var in {GLOBAL_ENV_FILE.path}[/]")

    return False


__all__ = ["run_onboarding"]
