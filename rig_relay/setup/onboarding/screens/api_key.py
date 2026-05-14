"""API key screen — simple console-based API key input."""

from __future__ import annotations

import os

from dotenv import set_key
from rich import print as rprint
from rich.panel import Panel

from rig_relay.core.config import VibeConfig
from rig_relay.core.paths import GLOBAL_ENV_FILE

PROVIDER_HELP = {
    "deepseek": ("https://platform.deepseek.com/api_keys", "DeepSeek Platform"),
    "mistral": ("https://console.mistral.ai/codestral/cli", "Mistral AI Studio"),
}


def run_api_key_screen() -> str | None:
    """Run a simple console-based API key setup."""
    config = VibeConfig.load()
    provider = config.get_active_provider()

    rprint()
    rprint(Panel(f"[bold]Configure {provider.name} API Key[/]", border_style="cyan"))
    rprint()

    if provider.name in PROVIDER_HELP:
        url, label = PROVIDER_HELP[provider.name]
        rprint(f"Get your API key from: [link={url}]{label}[/]")
        rprint()

    rprint(f"Enter your [bold]{provider.name}[/] API key (or press Enter to skip):")
    api_key = input().strip()

    if not api_key:
        rprint("[yellow]Setup skipped.[/]")
        return None

    env_var = provider.api_key_env_var
    if not env_var:
        return f"env_var_error:{provider.name}"

    try:
        env_path = GLOBAL_ENV_FILE.path
        env_path.parent.mkdir(parents=True, exist_ok=True)
        set_key(str(env_path), env_var, api_key)
        os.environ[env_var] = api_key
    except OSError as e:
        os.environ[env_var] = api_key
        return f"save_error:{e}"

    rprint(f"[green]API key for {provider.name} saved to {GLOBAL_ENV_FILE.path}[/]")
    return "completed"
