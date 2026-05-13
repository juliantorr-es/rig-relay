"""Legacy compatibility adapter for authorization receipts.

New product code should import from ``rig_relay.governance.auth_receipts``.
This module re-exports the implementation to preserve backward compatibility
for ``from vibe.core.auth.receipt import ...`` during the alpha period.
"""

from __future__ import annotations

from rig_relay.governance.auth_receipts import (
    DEFAULT_POLICY,
    READ_ONLY_ACTIONS,
    action_requires_authorization,
    generate_dev_receipt,
    is_read_only_action,
    validate_receipt,
)

__all__ = [
    "DEFAULT_POLICY",
    "READ_ONLY_ACTIONS",
    "action_requires_authorization",
    "generate_dev_receipt",
    "is_read_only_action",
    "validate_receipt",
]
