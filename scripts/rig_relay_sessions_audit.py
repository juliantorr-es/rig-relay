#!/usr/bin/env python3
"""Rig Relay session storage audit.

Read-only report for ~/.rig/sessions.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from rig_relay.evidence.session_lifecycle import audit_sessions_storage


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit Rig Relay session storage")
    parser.add_argument(
        "--sessions-root", type=Path, default=Path.home() / ".rig" / "sessions"
    )
    parser.add_argument("--state-root", type=Path, default=None)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--top", type=int, default=20)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary = audit_sessions_storage(args.sessions_root, top_n=args.top)
    payload = {
        "sessions_root": str(summary.sessions_root),
        "total_bytes": summary.total_bytes,
        "file_count": summary.file_count,
        "categories": {
            key.value: value for key, value in summary.category_bytes.items()
        },
        "largest_files": summary.largest_files,
        "compaction_candidates": [
            {
                "path": str(item.path),
                "size_bytes": item.size_bytes,
                "category": item.category.value,
                "reason": item.reason,
            }
            for item in summary.compaction_candidates
        ],
        "prune_candidates": [
            {
                "path": str(item.path),
                "size_bytes": item.size_bytes,
                "category": item.category.value,
                "reason": item.reason,
            }
            for item in summary.prune_candidates
        ],
    }
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    print(f"Sessions root: {summary.sessions_root}")
    print(f"Total size: {summary.total_bytes / 1_048_576.0:.2f} MB")
    print(f"File count: {summary.file_count}")
    print("Category sizes:")
    for category, size in sorted(
        summary.category_bytes.items(), key=lambda item: item[1], reverse=True
    ):
        if size == 0:
            continue
        print(f"  {category.value}: {size / 1_048_576.0:.2f} MB")
    print("Largest files:")
    for item in summary.largest_files[: args.top]:
        print(f"  {item['path']} ({item['size_bytes']} bytes) [{item['category']}]")
    print("Compaction candidates:")
    for item in summary.compaction_candidates[: args.top]:
        print(f"  {item.path} ({item.size_bytes} bytes) [{item.category.value}]")
    print("Prune candidates:")
    for item in summary.prune_candidates[: args.top]:
        print(f"  {item.path} ({item.size_bytes} bytes) [{item.category.value}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
