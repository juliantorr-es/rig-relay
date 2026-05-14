"""rig_relay.cli.acp_entrypoint — Relay-owned ACP entry point.

This module is the Rig Relay ACP product entry point.
It delegates to the existing ``vibe.acp.entrypoint`` implementation.

Status: facade (Relay-owned call; delegates to ``vibe.*`` for runtime).
Target migration: ``rig_relay.cli.acp_orchestrator``.
"""

from __future__ import annotations

from rig_relay.acp.entrypoint import main

__all__ = ["main"]
