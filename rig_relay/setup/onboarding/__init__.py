from __future__ import annotations

# Derived from mistralai/mistral-vibe. Modified for Rig Relay.
import sys
from typing import Any

from rich import print as rprint
from textual.app import App

from rig_relay.core.paths import GLOBAL_ENV_FILE
from rig_relay.core.telemetry.types import EntrypointMetadata
from rig_relay.setup.onboarding.screens import ApiKeyScreen, WelcomeScreen


class OnboardingApp(App[str | None]):
    CSS_PATH = "onboarding.tcss"

    def __init__(
        self, entrypoint_metadata: EntrypointMetadata | None = None, **kwargs: Any
    ) -> None:
        super().__init__(**kwargs)
        self._entrypoint_metadata = entrypoint_metadata

    def on_mount(self) -> None:
        self.theme = "textual-ansi"

        self.install_screen(WelcomeScreen(), "welcome")
        self.install_screen(
            ApiKeyScreen(entrypoint_metadata=self._entrypoint_metadata), "api_key"
        )
        self.push_screen("welcome")


def run_onboarding(
    app: App | None = None, *, entrypoint_metadata: EntrypointMetadata | None = None
) -> None:
    result = (app or OnboardingApp(entrypoint_metadata=entrypoint_metadata)).run()
    match result:
        case None:
            rprint("\n[yellow]Setup cancelled. See you next time![/]")
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
