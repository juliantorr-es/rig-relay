#!/usr/bin/env python3
"""Thin backwards-compatible wrapper — delegates to the canonical CLI module.

Legacy one-shot wrapper used by older scripts and tests.
Use `rig-relay steward` for the looping dispatcher.

Usage:
  uv run python scripts/rig_opencode_idle_steward.py --project-root . --worktree default --dry-run
"""

from __future__ import annotations

import sys

from rig_relay.cli.steward import main

if __name__ == "__main__":
    sys.exit(main())
