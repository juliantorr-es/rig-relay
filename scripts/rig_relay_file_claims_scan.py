#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from rig_relay.coordination.file_markers import scan_file_claims


def _collect(paths: list[Path]) -> list[Path]:
    collected: list[Path] = []
    for path in paths:
        if path.is_dir():
            collected.extend(sorted(p for p in path.rglob("*") if p.is_file()))
        else:
            collected.append(path)
    return collected


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", nargs="+", type=Path)
    args = parser.parse_args()
    print(json.dumps(scan_file_claims(_collect(args.paths)), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

