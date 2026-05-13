#!/usr/bin/env python3
"""Rig Relay Current State Analysis Tool — CLI wrapper.

The core implementation now lives in ``rig_relay.coordination.current_state``.
This script is a thin CLI wrapper for backward compatibility. All imports
of ``scripts.rig_relay_current_state`` continue to work.

Usage:
    uv run python scripts/rig_relay_current_state.py
    uv run python scripts/rig_relay_current_state.py \\
        --coordination-root .build/rig-relay/coordination \\
        --derived-dir .build/rig-relay/derived \\
        --output .build/rig-relay/current_state.json
"""

from __future__ import annotations

from rig_relay.coordination.current_state import (  # noqa: F401
    DEFAULT_COORD_ROOT,
    DEFAULT_DERIVED_DIR,
    DEFAULT_FORBIDDEN,
    DEFAULT_MAX_CHILDREN,
    REPO_ROOT,
    _count_jsonl_rows,
    _count_lines,
    _read_coordination_events,
    _read_coordination_leases,
    _read_coordination_sessions,
    _read_derived,
    _read_jsonl,
    generate_current_state,
    main,
)

if __name__ == "__main__":
    raise SystemExit(main())
