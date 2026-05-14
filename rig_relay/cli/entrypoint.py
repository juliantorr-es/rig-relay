"""rig_relay.cli.entrypoint — Relay-owned CLI entry point.

This module is the Rig Relay product entry point.
It delegates to the existing ``vibe.cli.entrypoint`` implementation.

Status: facade (Relay-owned call; delegates to ``vibe.*`` for runtime).
Target migration: ``rig_relay.cli.orchestrator``.
"""

from __future__ import annotations

from vibe.cli.entrypoint import main

__all__ = ["main"]
