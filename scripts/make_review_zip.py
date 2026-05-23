#!/usr/bin/env python3
"""Generate a code-review zip containing only source-critical files.

Operates on git-tracked files only (respects .gitignore automatically).
Excludes generated artifacts, large data files, and binary blobs.

Usage:
    uv run python scripts/make_review_zip.py
    uv run python scripts/make_review_zip.py --out ~/Desktop/rig-relay-review.zip
    uv run python scripts/make_review_zip.py --list          # dry-run: print included files
    uv run python scripts/make_review_zip.py --stats         # print category breakdown

Output filename default: rig-relay-<YYYYMMDD>.review.zip (gitignored pattern)
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
import subprocess
import zipfile

REPO_ROOT = Path(__file__).resolve().parent.parent

_ONE_MB = 1_048_576

# ---------------------------------------------------------------------------
# Exclude rules — applied on top of what git already filters via .gitignore.
# These are path prefix / suffix / glob patterns for files that ARE tracked
# but are not useful for a human or LLM code review.
# ---------------------------------------------------------------------------

# Prefixes of tracked paths to exclude (relative to repo root)
EXCLUDE_PREFIXES: tuple[str, ...] = (
    # Docs: auto-generated data dumps and large JSON blobs
    "docs/json/governance/",  # 324 machine-generated governance JSON files
    "docs/json/audits/",  # 122 audit JSON files
    "docs/artifacts/",  # Generated JSONL/JSON doc inventories (large)
    "docs/audits/",  # Large audit JSONL reports
    "docs/assets/og/",  # OG image assets (binary PNG/SVG)
    "docs/ui/",  # UI screenshots / binary assets
    "docs/demo/",  # Demo assets
    # Lock files and generated manifests that add noise without value for review
    "docs/json/site/",  # Site build manifests
)

# Exact file paths to exclude (relative to repo root)
EXCLUDE_EXACT: frozenset[str] = frozenset({
    "uv.lock",  # 520 KB dependency lock — useful for reproducibility, noise for review
    "extensions/vscodium-rig-relay/package-lock.json",  # 124 KB npm lock
    "docs/json/governance/codebase_evidence_graph_v1.v1.json",  # 5.3 MB blob
})

# File extensions to always exclude (binary / generated)
EXCLUDE_EXTENSIONS: frozenset[str] = frozenset({
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".ico",
    ".webp",  # images
    ".ttf",
    ".woff",
    ".woff2",
    ".eot",  # fonts
    ".zip",
    ".tar",
    ".gz",
    ".bz2",
    ".xz",  # archives
    ".vsix",  # extension packages
    ".node",  # native binaries
    ".map",  # source maps
    ".pyc",  # bytecode
    ".pdf",  # PDFs
})

# Paths that are always included regardless of other rules (never skip these)
ALWAYS_INCLUDE_PREFIXES: tuple[str, ...] = (
    "rig_relay/",
    "tests/",
    "extensions/vscodium-rig-relay/src/",
    ".github/",
)


def _get_tracked_files() -> list[str]:
    result = subprocess.run(
        ["git", "ls-files"], capture_output=True, text=True, cwd=REPO_ROOT, check=True
    )
    return result.stdout.splitlines()


def _should_include(rel: str) -> bool:
    path = Path(rel)
    suffix = path.suffix.lower()

    # Always include core source paths
    if rel.startswith(ALWAYS_INCLUDE_PREFIXES):
        return True

    # Always exclude binary/generated extensions
    if suffix in EXCLUDE_EXTENSIONS:
        return False

    # Always exclude exact files
    if rel in EXCLUDE_EXACT:
        return False

    # Exclude by prefix
    if rel.startswith(EXCLUDE_PREFIXES):
        return False

    return True


def _category(rel: str) -> str:
    parts = rel.split("/")
    top = parts[0]
    sub = parts[1] if len(parts) > 1 else ""
    match top:
        case "rig_relay":
            return f"src/{sub}" if sub else "src"
        case "tests" | "scripts" | ".github":
            return top
        case "docs":
            return f"docs/{sub}" if sub else "docs"
        case "extensions":
            return top
        case _:
            return top


def build_zip(out_path: Path, dry_run: bool = False, stats: bool = False) -> list[str]:
    tracked = _get_tracked_files()
    included = [f for f in tracked if _should_include(f)]

    if dry_run or stats:
        if stats:
            counts: dict[str, int] = defaultdict(int)
            sizes: dict[str, int] = defaultdict(int)
            for rel in included:
                cat = _category(rel)
                counts[cat] += 1
                full = REPO_ROOT / rel
                sizes[cat] += full.stat().st_size if full.exists() else 0

            print(f"\n{'Category':<35} {'Files':>6}  {'Size':>10}")
            print("-" * 55)
            for cat in sorted(counts, key=lambda c: -counts[c]):
                sz = sizes[cat]
                sz_str = (
                    f"{sz / 1024:.0f} KB" if sz < _ONE_MB else f"{sz / _ONE_MB:.1f} MB"
                )
                print(f"  {cat:<33} {counts[cat]:>6}  {sz_str:>10}")
            print("-" * 55)
            total_files = sum(counts.values())
            total_size = sum(sizes.values())
            total_str = (
                f"{total_size / 1024:.0f} KB"
                if total_size < _ONE_MB
                else f"{total_size / _ONE_MB:.1f} MB"
            )
            print(f"  {'TOTAL':<33} {total_files:>6}  {total_str:>10}\n")
        else:
            for rel in included:
                print(rel)
        return included

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for rel in included:
            full = REPO_ROOT / rel
            if full.exists():
                zf.write(full, arcname=rel)

    size_mb = out_path.stat().st_size / 1_048_576
    print(f"✓ {len(included)} files → {out_path}  ({size_mb:.1f} MB)")
    return included


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    today = datetime.now(UTC).strftime("%Y%m%d")
    default_out = REPO_ROOT / f"rig-relay-{today}.review.zip"
    parser.add_argument("--out", type=Path, default=default_out, help="Output zip path")
    parser.add_argument(
        "--list",
        action="store_true",
        dest="dry_run",
        help="Print included files without writing zip",
    )
    parser.add_argument(
        "--stats",
        action="store_true",
        help="Print category breakdown without writing zip",
    )
    args = parser.parse_args(argv)

    build_zip(args.out, dry_run=args.dry_run, stats=args.stats)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
