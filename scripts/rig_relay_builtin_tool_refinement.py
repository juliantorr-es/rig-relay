#!/usr/bin/env python3
"""Rig Relay built-in tool refinement — thin CLI wrapper.

Core implementation in ``rig_relay.operational.refinement``.

Usage:
    uv run python scripts/rig_relay_builtin_tool_refinement.py
"""

from __future__ import annotations

from rig_relay.operational.refinement import run_refinement_report


def main() -> int:
    return run_refinement_report()


if __name__ == "__main__":
    raise SystemExit(main())
