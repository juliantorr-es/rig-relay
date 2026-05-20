"""GitHub App Onboarding v1 — guided installation + token capture.

Opens browser for GitHub App installation, captures installation_id
from callback, stores in ~/.rig/relay/.env for the token manager.
Uses existing GitHub Live Auth config for client_id read.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.parse
import webbrowser
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DOTENV_PATH = Path.home() / ".rig" / "relay" / ".env"

_GITHUB_SETUP_CONFIG = {
    "name": "Rig Relay",
    "url": "https://github.com/juliantorr-es/rig-relay",
    "hook_attributes": {"url": None},
    "redirect_url": "https://github.com/apps/rig-relay/installations/new",
    "description": "Governed coding assistant — branch, file, and PR management with receipts.",
    "public": False,
    "default_events": [
        "push",
        "pull_request",
        "code_scanning_alert",
        "dependabot_alert",
    ],
    "default_permissions": {
        "contents": "write",
        "pull_requests": "write",
        "metadata": "read",
        "security_events": "read",
    },
}

_PERMISSION_DESCRIPTIONS = {
    "contents:write": "Write repository files (README, docs, approved patches)",
    "pull_requests:write": "Create and manage pull requests",
    "metadata:read": "Read repository metadata",
    "security_events:read": "Read code scanning and Dependabot alerts",
    "security_events:write": "Update alert state (dismiss/reopen) — requires separate governance gate",
    "issues:write": "Create and manage issues",
    "actions:read": "Read workflow runs and check CI health",
}


class GitHubAppOnboardingError(Exception):
    pass


def _sha256_text(val: str) -> str:
    return hashlib.sha256(val.encode("utf-8")).hexdigest()


def get_app_install_url(app_name: str = "rig-relay") -> str:
    """Generate the GitHub App installation URL.

    Uses the GitHub App's public installation page.
    If the app is public, this is: https://github.com/apps/{app_name}/installations/new
    If the app has a specific client_id, we could use that for the OAuth flow.
    """
    from dotenv import load_dotenv

    if _DOTENV_PATH.exists():
        load_dotenv(_DOTENV_PATH)

    client_id = os.environ.get("RIG_GITHUB_CLIENT_ID", "") or os.environ.get(
        "RIG_RELAY_GITHUB_CLIENT_ID", ""
    )

    if client_id:
        # Use OAuth app installation flow with client_id
        return f"https://github.com/apps/{app_name}/installations/new?state=rig-relay-onboard"
    # Use the public GitHub App install page
    return f"https://github.com/apps/{app_name}/installations/new"


def save_installation_config(
    app_id: int, installation_id: int, app_name: str = "rig-relay"
) -> bool:
    """Save the GitHub App installation config to ~/.rig/relay/.env.

    Uses dotenv-safe update: reads existing, adds/updates RIG_GITHUB_* vars,
    writes back. Never overwrites unrelated lines.
    """
    from dotenv import load_dotenv, set_key

    _DOTENV_PATH.parent.mkdir(parents=True, exist_ok=True)
    if _DOTENV_PATH.exists():
        load_dotenv(_DOTENV_PATH)
    else:
        _DOTENV_PATH.touch()

    set_key(str(_DOTENV_PATH), "RIG_GITHUB_APP_ID", str(app_id))
    set_key(str(_DOTENV_PATH), "RIG_GITHUB_INSTALLATION_ID", str(installation_id))

    # Also re-load to pick up the new values
    load_dotenv(_DOTENV_PATH, override=True)
    return True


def get_installation_status() -> dict[str, str | None]:
    """Check current GitHub App installation status."""
    from dotenv import load_dotenv

    if _DOTENV_PATH.exists():
        load_dotenv(_DOTENV_PATH)

    app_id = os.environ.get("RIG_GITHUB_APP_ID")
    inst_id = os.environ.get("RIG_GITHUB_INSTALLATION_ID")
    client_id = os.environ.get("RIG_GITHUB_CLIENT_ID") or os.environ.get(
        "RIG_RELAY_GITHUB_CLIENT_ID"
    )
    key_path = os.environ.get("RIG_GITHUB_PRIVATE_KEY_PATH")

    return {
        "app_id": app_id,
        "installation_id": inst_id,
        "client_id_present": bool(client_id),
        "private_key_configured": bool(key_path),
        "github_app_ready": bool(app_id and inst_id and key_path and bool(client_id)),
    }


def generate_permission_manifest() -> dict[str, list[str]]:
    """Generate the permission manifest for the GitHub App."""
    return {
        "read_permissions": [
            "metadata:read",
            "security_events:read",
            "contents:read",
            "pull_requests:read",
            "actions:read",
        ],
        "write_permissions": ["contents:write", "pull_requests:write"],
        "deferred_permissions": ["security_events:write", "issues:write"],
        "forbidden_permissions": ["administration:write"],
    }


def open_install_page(app_name: str = "rig-relay") -> str:
    """Open the GitHub App installation page in the browser.

    Returns the URL opened.
    """
    url = get_app_install_url(app_name)
    webbrowser.open(url)
    return url


def complete_onboarding(
    app_id: int, installation_id: int, app_name: str = "rig-relay"
) -> dict[str, str | None]:
    saved = save_installation_config(app_id, installation_id, app_name)
    status = get_installation_status()
    manifest = generate_permission_manifest()
    return {
        "installation_saved": "true" if saved else "false",
        "app_id": str(app_id),
        "installation_id": str(installation_id),
        "github_app_ready": "true" if status["github_app_ready"] else "false",
        "permission_manifest": json.dumps(manifest),
        "next_step": "Set RIG_GITHUB_PRIVATE_KEY_PATH in ~/.rig/relay/.env if not already configured",
    }


__all__ = [
    "GitHubAppOnboardingError",
    "get_app_install_url",
    "save_installation_config",
    "get_installation_status",
    "generate_permission_manifest",
    "open_install_page",
    "complete_onboarding",
]
