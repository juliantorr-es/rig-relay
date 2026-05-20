"""Context compiler sub-package — handoff, collision, symbols.

Imports from the existing `rig_relay.context.*` modules for backward
compatibility. This package adds the 3 dead mode implementations:
HANDOFF, COLLISION, and SYMBOLS.
"""

from __future__ import annotations

from rig_relay.compiler.context.collision import compile_collision_report
from rig_relay.compiler.context.handoff import compile_handoff_packet
from rig_relay.compiler.context.symbols import compile_symbol_packet

__all__ = [
    "compile_collision_report",
    "compile_handoff_packet",
    "compile_symbol_packet",
]
