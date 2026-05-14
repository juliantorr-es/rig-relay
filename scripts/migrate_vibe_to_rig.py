#!/usr/bin/env python3
"""Bulk migrate vibe/core/ -> rig_relay/core/ with import path rewrites."""

from __future__ import annotations

from pathlib import Path
import re
import shutil

REPO = Path(__file__).resolve().parent.parent
VIBE_CORE = REPO / "vibe" / "core"
RIG_CORE = REPO / "rig_relay" / "core"

# Directories to SKIP (already ported or have conflicts)
SKIP_DIRS = {"__pycache__", "coordination", "context"}

# Files to SKIP (already migrated or special handling)
SKIP_FILES = {"__pycache__"}

# Import rewrites: (pattern, replacement)
REWRITES = [
    # Package-level imports (with dot: from vibe.core.xxx)
    (r'from vibe\.', 'from rig_relay.'),
    (r'import vibe\.', 'import rig_relay.'),
    # Direct vibe import (from vibe import __version__)
    (r'^from vibe import ', 'from rig_relay import '),
    # Logger name
    ('"vibe"', '"rig-relay"'),
    ("'vibe'", "'rig-relay'"),
    # VIBE_ROOT -> RIG_ROOT (must come after import rewrites)
    ('\bVIBE_ROOT\b', 'RIG_ROOT'),
]


def rewrite_source(source: str) -> str:
    for pattern, replacement in REWRITES:
        source = re.sub(pattern, replacement, source)
    return source


def migrate_file(src: Path, dst: Path) -> bool:
    """Copy and rewrite a single .py file. Returns True if changed."""
    source = src.read_text(encoding="utf-8")
    rewritten = rewrite_source(source)
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(rewritten, encoding="utf-8")
    return source != rewritten


def migrate_dir(src_dir: Path, dst_dir: Path) -> list[Path]:
    """Migrate all .py files from src_dir to dst_dir recursively."""
    migrated: list[Path] = []
    for item in src_dir.rglob("*.py"):
        rel = item.relative_to(src_dir)
        if any(part in SKIP_DIRS for part in rel.parts[:-1]):
            continue
        if rel.name in SKIP_FILES:
            continue
        dst = dst_dir / rel
        migrate_file(item, dst)
        migrated.append(dst)
    return migrated


def main() -> None:
    print(f"Migrating {VIBE_CORE} -> {RIG_CORE}")
    migrated = migrate_dir(VIBE_CORE, RIG_CORE)
    print(f"Migrated {len(migrated)} files")

    # Remove files in rig_relay/core/ that have no counterpart in vibe/core/
    # (these are stale from previous partial migrations)
    for f in sorted(RIG_CORE.rglob("*.py")):
        rel = f.relative_to(RIG_CORE)
        src = VIBE_CORE / rel
        if not src.exists() and rel.name != "__init__.py":
            # Only remove if not in an already-ported subsystem
            if rel.parts[0] not in ("context",):
                print(f"  Stale? {rel} (no source in vibe/core/)")

    print("Done.")


if __name__ == "__main__":
    main()
