"""Console-based onboarding flow — replacement for deleted Textual TUI version."""

from __future__ import annotations

import sys

from rich import print as rprint

from rig_relay.core.paths import GLOBAL_ENV_FILE
from rig_relay.core.telemetry.types import EntrypointMetadata
from rig_relay.setup.onboarding.screens.api_key import run_api_key_screen
from rig_relay.setup.onboarding.screens.welcome import show_welcome


def run_onboarding(
    app: object | None = None,
    *,
    entrypoint_metadata: EntrypointMetadata | None = None,
) -> None:
    """Run the onboarding flow using console-based prompts."""
    if app is not None:
        rprint("[yellow]Warning: Textual App passed to console-based onboarding, ignoring.[/]")

    result = show_welcome()
    if result is None:
        rprint("\n[yellow]Setup skipped. See you next time![/]")
        sys.exit(0)

    result = run_api_key_screen()
    match result:
        case None:
            rprint("\n[yellow]Setup skipped. See you next time![/]")
            sys.exit(0)
        case str() as s if s.startswith("env_var_error:"):
            env_key = s.removeprefix("env_var_error:")
            rprint(
                "\n[yellow]Could not save the provider key because the configured "
                f"environment variable name is invalid: {env_key}.[/]"
                "\n[dim]The key was not saved for this session. "
                "Update the provider's `api_key_env_var` setting in your config and try again.[/]\n"
            )
            sys.exit(1)
        case str() as s if s.startswith("save_error:"):
            err = s.removeprefix("save_error:")
            rprint(
                f"\n[yellow]Warning: Could not save provider key to .env file: {err}[/]"
                "\n[dim]The key is set for this session only. "
                f"You may need to set it manually in {GLOBAL_ENV_FILE.path}[/]\n"
            )
        case "completed":
            rprint('\nSetup complete. Run "rig-relay" to start using Rig Relay.\n')
