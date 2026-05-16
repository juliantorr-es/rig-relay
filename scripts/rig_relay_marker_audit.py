#!/usr/bin/env python3
"""Marker audit — reports marker definitions, usage counts, and gaps.

Usage:
    uv run python scripts/rig_relay_marker_audit.py
    uv run python scripts/rig_relay_marker_audit.py --json
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import sys

from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent if __file__ else Path.cwd()

REQUIRED_MARKERS = [
    "smoke",
    "contract",
    "integration",
    "e2e",
    "packaging",
    "slow",
    "legacy",
    "quarantine",
    "flaky",
    "network",
    "provider",
    "destructive",
    "migration",
]


def scan_markers() -> dict[str, Any]:
    """Count @pytest.mark.<name> usage across all test files."""
    marker_counts: dict[str, int] = {}
    pyproject = REPO_ROOT / "pyproject.toml"
    defined = set()

    if pyproject.is_file():
        content = pyproject.read_text()
        in_markers = False
        for line in content.split("\n"):
            if line.strip().startswith("markers"):
                in_markers = True
                continue
            if in_markers and line.strip() == "]":
                in_markers = False
            if in_markers:
                m = re.match(r'\s*"([a-z_0-9]+):', line)
                if m:
                    defined.add(m.group(1))

    tests_dir = REPO_ROOT / "tests"
    for py_file in tests_dir.rglob("test_*.py"):
        if "__pycache__" in str(py_file):
            continue
        text = py_file.read_text()
        for marker in REQUIRED_MARKERS:
            if f"@pytest.mark.{marker}" in text:
                marker_counts[marker] = marker_counts.get(marker, 0) + 1

    return {
        "defined_markers": sorted(defined),
        "marker_usage": marker_counts,
        "unused_defined": sorted(defined - set(marker_counts.keys())),
        "smoke_count": marker_counts.get("smoke", 0),
        "total_test_files": sum(
            1 for f in tests_dir.rglob("test_*.py") if "__pycache__" not in str(f)
        ),
    }


def main() -> None:
    result = scan_markers()
    output_json = "--json" in sys.argv

    if output_json:
        print(json.dumps(result, indent=2))
        return

    print("=== Marker Audit ===")
    print(f"  Test files: {result['total_test_files']}")
    print(f"  Defined markers: {len(result['defined_markers'])}")
    print(f"  Unused defined: {len(result['unused_defined'])}")
    print(f"  Smoke count: {result['smoke_count']}")
    print()
    print("  Marker usage:")
    for marker in sorted(result["marker_usage"].keys()):
        count = result["marker_usage"][marker]
        print(f"    {marker}: {count}")

    smoke_empty = result["smoke_count"] == 0
    if smoke_empty:
        print("\n  WARNING: Smoke suite is empty!")

    missing = sorted(set(REQUIRED_MARKERS) - set(result["defined_markers"]))
    if missing:
        print(f"\n  WARNING: Missing marker definitions: {missing}")

    print("\n  ✅ Audit complete.")


if __name__ == "__main__":
    main()
