#!/usr/bin/env python3
"""Rig Relay Release Evidence Gate v1 — CLI shim.

Delegates to ``rig_relay.release_gate.cli``.

Usage:
    uv run python scripts/rig_relay_release_evidence_gate.py --repo-root . --output .build/rig-relay/release-gate-test.json
    uv run python scripts/rig_relay_release_evidence_gate.py --repo-root . --strict
    uv run python scripts/rig_relay_release_evidence_gate.py --include-check runtime.ci.workflow_coverage
"""

from __future__ import annotations

from rig_relay.release_gate.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
