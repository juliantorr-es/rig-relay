#!/usr/bin/env python3
"""Seed a bridge lifecycle event sequence into Event Fabric JSONL."""

from __future__ import annotations

import argparse
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="rig-seed-bridge-lifecycle")
    parser.add_argument("--output", type=Path, default=None, help="Output JSONL path")
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)

    from rig_relay.events.seed_bridge_lifecycle import build_seed_events

    result = build_seed_events(seed_output_path=args.output)
    if args.summary:
        for k, v in result.items():
            print(f"{k}: {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
