"""Rig Relay Update Status Generator — core module.

Generates structured update_status JSON without making network calls.
Supports CLI argument or fixture input for latest_version.

Provenance (Rig-to-Relay porting doctrine):
  Porting status: relay_native (designed for Relay — no Rig origin).
  See docs/governance/rig-to-relay-pattern-inventory.md for pattern map.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

UPDATE_COMMANDS: dict[str, str] = {
    "uv_tool": "uv tool upgrade rig-relay",
    "pipx": "pipx upgrade rig-relay",
    "pip": "pip install --upgrade rig-relay",
    "homebrew": "brew upgrade rig-relay",
    "npm": "npm update -g rig-relay",
    "source": "git pull && uv sync",
    "unknown": "pip install --upgrade rig-relay  # or check your install source",
}

VALID_STATES = frozenset({
    "up_to_date",
    "update_available",
    "update_downloaded",
    "restart_pending",
    "restart_blocked_active_sessions",
    "restart_ready",
    "restart_completed",
})


def _get_current_version() -> str:
    """Read current version from vibe/__init__.py."""
    init_path = REPO_ROOT / "vibe" / "__init__.py"
    if not init_path.is_file():
        return "unknown"
    for line in init_path.read_text("utf-8").splitlines():
        if line.startswith("__version__"):
            parts = line.split("=", 1)
            PARTS_EXPECTED = 2
            if len(parts) == PARTS_EXPECTED:
                return parts[1].strip().strip('"').strip("'")
    return "unknown"


def _compare_versions(current: str, latest: str) -> bool:
    """Simple string comparison adequate for PEP 440 alpha/beta format."""
    if current == "unknown" or latest == "unknown":
        return False
    return latest > current


def generate_update_status(
    latest_version: str | None = None,
    current_version: str | None = None,
    install_source: str = "unknown",
    active_sessions: int = 0,
    update_state: str | None = None,
) -> dict:
    """Generate a structured update_status dict.

    Args:
        latest_version: Latest available version string (PEP 440).
        current_version: Current installed version. Auto-detected if None.
        install_source: Install channel identifier.
        active_sessions: Number of currently active child sessions.
        update_state: Override update state. Auto-computed if None.

    Returns:
        dict matching rig.relay.update_status.v1 schema.
    """
    if current_version is None:
        current_version = _get_current_version()

    if latest_version is None:
        latest_version = current_version

    update_available = _compare_versions(current_version, latest_version)
    recommended = UPDATE_COMMANDS.get(install_source, UPDATE_COMMANDS["unknown"])

    if update_state is None:
        if not update_available:
            update_state = "up_to_date"
        elif active_sessions > 0:
            update_state = "restart_blocked_active_sessions"
        else:
            update_state = "update_available"

    restart_safe = active_sessions == 0
    blocked = max(0, active_sessions)

    return {
        "schema_version": "rig.relay.update_status.v1",
        "current_version": current_version,
        "latest_version": latest_version,
        "update_available": update_available,
        "install_source": install_source,
        "recommended_update_command": recommended,
        "restart_required": update_available,
        "restart_safe": restart_safe,
        "blocked_by_active_sessions": blocked,
        "update_state": update_state if update_state in VALID_STATES else "up_to_date",
        "checked_at": datetime.now(UTC).isoformat(),
        "warnings": None,
    }


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Emit structured update_status JSON.")
    parser.add_argument(
        "--latest",
        type=str,
        default=None,
        help="Latest available version (PEP 440 format, e.g. 0.1.0a2).",
    )
    parser.add_argument(
        "--current",
        type=str,
        default=None,
        help="Override current version (auto-detected if not provided).",
    )
    parser.add_argument(
        "--install-source",
        type=str,
        default="unknown",
        choices=list(UPDATE_COMMANDS.keys()),
        help="Install channel (affects recommended update command).",
    )
    parser.add_argument(
        "--active-sessions",
        type=int,
        default=0,
        help="Number of active child sessions blocking restart.",
    )
    parser.add_argument(
        "--update-state",
        type=str,
        default=None,
        choices=sorted(VALID_STATES),
        help="Override update state (auto-computed if not provided).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    status = generate_update_status(
        latest_version=args.latest,
        current_version=args.current,
        install_source=args.install_source,
        active_sessions=args.active_sessions,
        update_state=args.update_state,
    )
    print(json.dumps(status, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
