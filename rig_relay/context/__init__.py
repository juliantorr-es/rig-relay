"""rig_relay.context — repository topology, active work map, symbol substitution.

This package provides the domain logic for the rig.get_context built-in tool.
It is deliberately separate from core/context/ (assembler.py, compiler.py) which
was designed for a different context model (Conversation context). This package
focuses on repository context: maps, work coordination, and symbol substitution.
"""

from __future__ import annotations

from rig_relay.context.cache import ContextCache
from rig_relay.context.digester import ContextDigester, ContextDigestionResult

__all__ = ["ContextCache", "ContextDigester", "ContextDigestionResult"]
