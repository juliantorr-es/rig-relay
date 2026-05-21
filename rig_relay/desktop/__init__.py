"""rig_relay.desktop — Projection, pywebview shell, WebSocket stream, intent API.

Target package for migrating:
  scripts/rig_relay_desktop_projection.py
  scripts/rig_relay_desktop_cockpit.py
  frontend/desktop/
"""

from __future__ import annotations

from rig_relay.desktop.analytics_projection import (
    ALL_WIDGET_IDS,
    build_analytics_projection,
)
from rig_relay.desktop.bridge_runtime_state import (
    BridgeRuntimeState,
    BridgeRuntimeStateTracker,
)

__all__ = [
    "ALL_WIDGET_IDS",
    "BridgeRuntimeState",
    "BridgeRuntimeStateTracker",
    "build_analytics_projection",
]
