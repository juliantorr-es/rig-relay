"""Rig Relay replay subsystem — session-centric deterministic reconstruction.

Facilities for replaying session state from observability JSONL or receipt
indexes, producing typed event chains with integrity verification and
time-travel navigation.
"""

from __future__ import annotations

from rig_relay.replay.engine import (
    replay_session_from_observability,
    replay_session_from_receipt_index,
)
from rig_relay.replay.models import (
    ReplayConflictType,
    ReplayCursor,
    ReplayEvent,
    ReplayEventKind,
    ReplayFrame,
    ReplayIntegrityFinding,
    ReplayIntegritySeverity,
    ReplayResult,
    ReplayState,
)

__all__ = [
    "ReplayConflictType",
    "ReplayCursor",
    "ReplayEvent",
    "ReplayEventKind",
    "ReplayFrame",
    "ReplayIntegrityFinding",
    "ReplayIntegritySeverity",
    "ReplayResult",
    "ReplayState",
    "replay_session_from_observability",
    "replay_session_from_receipt_index",
]
