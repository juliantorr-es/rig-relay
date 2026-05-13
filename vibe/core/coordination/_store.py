"""This module is a legacy compatibility adapter. New product code should import from rig_relay.coordination."""

from __future__ import annotations

from rig_relay.coordination.store import CoordinationStore, FileCoordinationStore

__all__ = ["CoordinationStore", "FileCoordinationStore"]
