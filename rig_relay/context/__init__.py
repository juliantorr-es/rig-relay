"""rig_relay.context — repository topology, active work map, symbol substitution.

This package provides the domain logic for the rig.get_context built-in tool.
It is deliberately separate from core/context/ (assembler.py, compiler.py) which
was designed for a different context model (Conversation context). This package
focuses on repository context: maps, work coordination, and symbol substitution.
"""
