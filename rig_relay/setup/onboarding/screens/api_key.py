"""API key screen — console-based provider selection and API key input.

Opens the browser so the user can grab an API key from the provider's dashboard.
"""

from __future__ import annotations

import os
import webbrowser

from dotenv import set_key
from rich import print as rprint
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table

from rig_relay.core.paths import GLOBAL_ENV_FILE

console = Console()

PROVIDER_REGISTRY: list[dict[str, str]] = [
    {
        "slug": "deepseek",
        "display": "DeepSeek",
        "key_url": "https://platform.deepseek.com/api_keys",
        "key_label": "DeepSeek Platform",
        "env_var": "DEEPSEEK_API_KEY",
        "description": "DeepSeek V3 — 685B MoE, strong reasoning, generous free tier",
    },
    {
        "slug": "mistral",
        "display": "Mistral AI",
        "key_url": "https://console.mistral.ai/api-keys/",
        "key_label": "Mistral AI Console",
        "env_var": "MISTRAL_API_KEY",
        "description": "Mistral Large 2 — frontier European LLM, la Plateforme",
    },
    {
        "slug": "openai",
        "display": "OpenAI",
        "key_url": "https://platform.openai.com/api-keys",
        "key_label": "OpenAI Platform",
        "env_var": "OPENAI_API_KEY",
        "description": "GPT-4o — multimodal frontier model from OpenAI",
    },
    {
        "slug": "anthropic",
        "display": "Anthropic",
        "key_url": "https://console.anthropic.com/settings/keys",
        "key_label": "Anthropic Console",
        "env_var": "ANTHROPIC_API_KEY",
        "description": "Claude 3.5 Sonnet / Claude 4 — safety-focused reasoning",
    },
    {
        "slug": "google",
        "display": "Google Gemini",
        "key_url": "https://aistudio.google.com/apikey",
        "key_label": "Google AI Studio",
        "env_var": "GOOGLE_API_KEY",
        "description": "Gemini 2.5 Flash/Pro — Google's multimodal models, free tier available",
    },
    {
        "slug": "openrouter",
        "display": "OpenRouter",
        "key_url": "https://openrouter.ai/keys",
        "key_label": "OpenRouter",
        "env_var": "OPENROUTER_API_KEY",
        "description": "OpenRouter — unified API for 300+ models. Pay-per-token, no subscriptions",
    },
    {
        "slug": "llamacpp",
        "display": "Local (llama.cpp)",
        "key_url": "",
        "key_label": "",
        "env_var": "",
        "description": "Run models locally via llama.cpp server. No API key needed.",
    },
]


def show_provider_picker() -> dict[str, str] | None:
    rprint()
    rprint(
        Panel.fit(
            "[bold cyan]Choose Your LLM Provider[/]\n\n"
            "Rig Relay needs an API key to talk to an LLM.\n"
            "Pick a provider below and paste your API key when prompted.",
            border_style="cyan",
        )
    )

    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("#", style="dim", width=3)
    table.add_column("Provider", style="bold")
    table.add_column("Description")

    for i, p in enumerate(PROVIDER_REGISTRY, 1):
        table.add_row(str(i), p["display"], p["description"])

    console.print(table)
    rprint()

    while True:
        choice = Prompt.ask(
            "[bold]Choose a provider[/] (1-7, or 'q' to quit)",
            choices=["1", "2", "3", "4", "5", "6", "7", "q"],
            default="1",
        )
        if choice == "q":
            return None

        idx = int(choice) - 1
        provider = PROVIDER_REGISTRY[idx]

        if provider["slug"] == "llamacpp":
            rprint("\n[green]Local llama.cpp — no API key needed.[/]")
            return provider

        return provider


def run_api_key_screen() -> str | None:
    provider = show_provider_picker()
    if provider is None:
        rprint(
            "\n[yellow]Setup skipped. You can configure keys manually in ~/.rig/relay/.env[/]"
        )
        return None

    slug = provider.get("slug", "")
    env_var = provider.get("env_var", "")
    key_url = provider.get("key_url", "")
    key_label = provider.get("key_label", "")

    if not env_var:
        return f"provider_selected:{slug}"

    rprint()
    rprint(
        Panel.fit(
            f"[bold]Get Your {provider['display']} API Key[/]\n\n"
            f"→ [link={key_url}]{key_label}[/]\n\n"
            "We'll open this page in your browser.\n"
            "Copy the API key, then come back and paste it here.",
            border_style="cyan",
        )
    )

    if Prompt.ask("[bold]Open browser?[/]", choices=["y", "n"], default="y") == "y":
        webbrowser.open(key_url)
        rprint(f"\n[dim]Opening {key_label} in your browser...[/]")

    rprint(
        f"\n[bold]Paste your {provider['display']} API key[/] (or press Enter to skip):"
    )
    api_key = Prompt.ask("", password=True).strip()

    if not api_key:
        rprint("[yellow]Setup skipped.[/]")
        return None

    try:
        env_path = GLOBAL_ENV_FILE.path
        env_path.parent.mkdir(parents=True, exist_ok=True)
        set_key(str(env_path), env_var, api_key)
        os.environ[env_var] = api_key
    except OSError as e:
        os.environ[env_var] = api_key
        rprint(
            f"\n[yellow]Warning: Could not save key to .env file: {e}[/]\n"
            "[dim]The key is set for this session only. "
            f"Set {env_var} in {GLOBAL_ENV_FILE.path} manually.[/]"
        )
        return f"save_error:{e}"

    _update_config_for_provider(slug)

    rprint(
        f"\n[green]✅  {provider['display']} API key saved to {GLOBAL_ENV_FILE.path}[/]"
    )
    return f"completed:{slug}:{env_var}"


def _update_config_for_provider(slug: str) -> None:
    provider_to_default_model = {
        "deepseek": "deepseek-v4-flash",
        "mistral": "mistral-medium-3.5",
        "openai": "gpt-4o",
        "anthropic": "claude-sonnet-4",
        "google": "gemini-2.0-flash",
        "openrouter": "openrouter-gpt-4o",
        "llamacpp": "local",
    }

    model_alias = provider_to_default_model.get(slug)
    if not model_alias:
        return

    from pathlib import Path

    config_dir = Path(os.path.expanduser("~/.rig/relay"))
    config_path = config_dir / "config.toml"
    config_dir.mkdir(parents=True, exist_ok=True)

    lines = ["[rig_relay]\n"]
    lines.append(f'active_model = "{model_alias}"\n')
    config_path.write_text("".join(lines))
