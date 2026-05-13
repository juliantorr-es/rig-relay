"""Explicit state root helpers for identity and telemetry consent paths.

Prevents accidental reads from real ~/.rig/relay/ during tests and bundle
generation. All state roots are explicit — pass tmp_path in tests, use the
default production root in production.

Default production root: ~/.rig/relay/
"""

from __future__ import annotations

from pathlib import Path


def default_relay_state_root() -> Path:
    """Return the default production state root (~/.rig/relay/)."""
    return Path.home() / ".rig" / "relay"


def identity_state_root(root: Path | None = None) -> Path:
    """Return the identity provider state directory.

    Args:
        root: Explicit state root. If None, uses ~/.rig/relay/.

    Returns:
        Path to the identity state directory.
    """
    base = root if root is not None else default_relay_state_root()
    return base / "identity"


def consent_state_root(root: Path | None = None) -> Path:
    """Return the consent state directory.

    Args:
        root: Explicit state root. If None, uses ~/.rig/relay/.

    Returns:
        Path to the consent state directory.
    """
    base = root if root is not None else default_relay_state_root()
    return base / "consent"


def provider_state_root(root: Path | None = None) -> Path:
    """Return the provider state directory.

    Args:
        root: Explicit state root. If None, uses ~/.rig/relay/.

    Returns:
        Path to the provider state directory.
    """
    base = root if root is not None else default_relay_state_root()
    return base / "providers"
