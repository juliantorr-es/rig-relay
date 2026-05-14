"""Legacy compatibility adapter for dirty-file guard.

New product code should import from ``rig_relay.governance.dirty_guard``.
This module re-exports the implementation to preserve backward compatibility
for ``from rig_relay.core.guard import ...`` during the alpha period.
"""

from __future__ import annotations

from rig_relay.governance.dirty_guard import (
    DirtyFileGuard,
    DirtyFileSnapshot,
    DirtyGuardFailurePolicy,
    GuardCaptureReason,
    WriteGuardResult,
    get_guard,
    reset_guard,
)

__all__ = [
    "DirtyFileGuard",
    "DirtyFileSnapshot",
    "DirtyGuardFailurePolicy",
    "GuardCaptureReason",
    "WriteGuardResult",
    "get_guard",
    "reset_guard",
]
