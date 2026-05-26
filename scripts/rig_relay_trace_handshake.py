#!/usr/bin/env python3
"""Rig Relay Trace Handshake — thin CLI wrapper.

Core implementation is in ``rig_relay.tracing._handshake``.

Usage:
    uv run python scripts/rig_relay_trace_handshake.py <handshake_id>
"""

from __future__ import annotations

import argparse
from pathlib import Path

from rig_relay.tracing._handshake import (
    format_handshake_trace,
    load_events,
    select_handshake_id,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Print correlated handshake trace events."
    )
    parser.add_argument("handshake_id", help="Handshake correlation id")
    parser.add_argument(
        "--path",
        type=Path,
        default=Path.home()
        / "Library"
        / "Application Support"
        / "Rig Relay"
        / "traces"
        / "trace_events.jsonl",
        help="Trace JSONL path",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    events = load_events(args.path)
    selected = select_handshake_id(events, args.handshake_id)
    if selected is None:
        print("Handshake trace: none found")
        return 0
    print(format_handshake_trace(events, selected))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
