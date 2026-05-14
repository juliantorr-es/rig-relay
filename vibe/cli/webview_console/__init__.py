"""Rig Console — pywebview desktop cockpit.

The webview frontend is a dumb projection renderer. Backend is authoritative.
All runtime communication goes through WebSocket (not the pywebview JS bridge).
"""
from __future__ import annotations

from vibe.cli.webview_console.app import main

__all__ = ["main"]
