#!/usr/bin/env python3
"""Audit ~/.rig for quarantine-safe clutter and produce a cleanup receipt."""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import shutil
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_RIG_ROOT = Path.home() / ".rig"
DEFAULT_OUT_DIR = REPO_ROOT / "docs" / "audits" / "global-rig-declutter"
DEFAULT_QUARANTINE_ROOT = DEFAULT_RIG_ROOT / "quarantine"

PROTECTED_NAMES = {
    "consent",
    "config.toml",
    "trusted_folders.toml",
    "sessions",
    "receipts.jsonl",
    "manifest.json",
    "observability.jsonl",
    "signed",
    "schema",
}

QUARANTINE_EXTENSIONS = {".DS_Store", ".log", ".tmp", ".zip", ".bak"}


@dataclass
class Entry:
    path: str
    kind: str
    size_bytes: int
    classification: str


def _hash_path(path: Path) -> str:
    return hashlib.sha256(str(path).encode("utf-8")).hexdigest()


def _iter_top_level(root: Path) -> list[Path]:
    if not root.exists():
        return []
    paths: list[Path] = []
    for child in sorted(root.iterdir()):
        if child.name == "quarantine":
            continue
        paths.append(child)
        if child.is_dir():
            for grandchild in sorted(child.iterdir()):
                paths.append(grandchild)
                if grandchild.is_dir():
                    paths.extend(sorted(grandgrand for grandgrand in grandchild.iterdir()))
    return paths


def _classify(path: Path) -> str:
    name = path.name.lower()
    suffix = path.suffix.lower()
    parent_names = {part.lower() for part in path.parts}
    classification = "manual-review"
    if path.is_dir():
        match name:
            case "relay" | "relay-smoke":
                classification = "preserve-for-history"
            case "quarantine":
                classification = "protected"
    elif {"consent", "receipts", "manifest", "schema", "signed"} & parent_names:
        classification = "protected"
    elif name in PROTECTED_NAMES:
        classification = "protected"
    elif suffix in QUARANTINE_EXTENSIONS or name.endswith(".log") or name in {"relay.zip", "sessions.zip"}:
        classification = "quarantine-candidate"
    elif suffix == ".jsonl" and "session" in str(path.parent):
        classification = "preserve-for-history"
    elif path.is_file() and suffix not in {".json", ".jsonl", ".toml", ".zip", ".log", ".tmp", ".bak"} and name not in {"relay", "relay-smoke"}:
        classification = "manual-review"
    elif suffix in {".toml", ".json"} and ("config" in name or "trusted" in name):
        classification = "protected"
    elif path.exists() and path.stat().st_size == 0:
        classification = "quarantine-candidate"
    return classification


def _summary_kind(classification: str) -> str:
    match classification:
        case "protected":
            return "protected"
        case "preserve-for-history":
            return "preserve-for-history"
        case "quarantine-candidate":
            return "quarantine-candidate"
        case _:
            return "manual-review"


def inventory_rig(root: Path) -> dict[str, Any]:
    entries: list[Entry] = []
    totals = Counter()
    by_class = Counter()
    by_kind = Counter()
    for path in _iter_top_level(root):
        classification = _classify(path)
        size_bytes = (
            path.stat().st_size
            if path.is_file()
            else sum(
                child.stat().st_size for child in path.rglob("*") if child.is_file()
            )
        )
        kind = "dir" if path.is_dir() else "file"
        entry = Entry(str(path), kind, size_bytes, classification)
        entries.append(entry)
        totals["entries"] += 1
        by_class[classification] += 1
        by_kind[kind] += 1
    return {
        "rig_root": str(root),
        "exists": root.exists(),
        "total_entries": totals["entries"],
        "total_bytes": sum(entry.size_bytes for entry in entries),
        "entries": [asdict(entry) for entry in entries],
        "counts_by_class": dict(by_class),
        "counts_by_kind": dict(by_kind),
    }


def quarantine_candidates(inventory: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        entry
        for entry in inventory["entries"]
        if entry["classification"] == "quarantine-candidate"
    ]


def write_reports(inventory: dict[str, Any], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    candidates = quarantine_candidates(inventory)
    (out_dir / "inventory.md").write_text(render_inventory(inventory), encoding="utf-8")
    (out_dir / "declutter-plan.md").write_text(render_plan(inventory), encoding="utf-8")
    (out_dir / "declutter-aggregate.json").write_text(
        json.dumps(inventory, indent=2, sort_keys=True), encoding="utf-8"
    )
    if candidates:
        receipt = {
            "timestamp": datetime.now(UTC).isoformat(),
            "source_root": inventory["rig_root"],
            "source_root_hash": _hash_path(Path(inventory["rig_root"])),
            "quarantine_root": str(Path(inventory["rig_root"]) / "quarantine"),
            "file_count": len(candidates),
            "byte_count": sum(entry["size_bytes"] for entry in candidates),
            "candidate_paths": [entry["path"] for entry in candidates],
            "script_version": "rig_global_declutter_audit.v1",
        }
        (out_dir / "declutter-quarantine-receipt.json").write_text(
            json.dumps(receipt, indent=2, sort_keys=True), encoding="utf-8"
        )


def render_inventory(inventory: dict[str, Any]) -> str:
    lines = [
        "# Global Rig Declutter Inventory",
        "",
        f"- Rig root: `{inventory['rig_root']}`",
        f"- Exists: `{inventory['exists']}`",
        f"- Total entries: `{inventory['total_entries']}`",
        f"- Total bytes: `{inventory['total_bytes']}`",
        "",
        "## Top-Level Summary",
    ]
    for entry in inventory["entries"]:
        lines.append(
            f"- `{entry['path']}`: `{entry['classification']}` `{entry['size_bytes']}` bytes"
        )
    lines.extend(["", "## Protected Classes Found"])
    for name, count in sorted(inventory["counts_by_class"].items()):
        lines.append(f"- `{name}`: `{count}`")
    return "\n".join(lines)


def render_plan(inventory: dict[str, Any]) -> str:
    lines = [
        "# Declutter Plan",
        "",
        "## Quarantine Strategy",
        "- Move only explicit quarantine candidates into a timestamped quarantine directory.",
        "- Leave protected, preserve-for-history, and manual-review items in place.",
        "- No permanent deletion in this mission.",
        "",
        "## What Will Not Be Touched",
        "- consent records",
        "- receipts and signed envelopes",
        "- active session markers",
        "- canonical audit outputs",
        "- configs and trust state",
        "",
        "## Manual Review Needed",
    ]
    for entry in inventory["entries"]:
        if entry["classification"] == "manual-review":
            lines.append(f"- `{entry['path']}`")
    return "\n".join(lines)


def quarantine(
    root: Path, candidates: list[dict[str, Any]], quarantine_root: Path
) -> dict[str, Any]:
    quarantine_root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    destination = quarantine_root / f"declutter-{stamp}"
    destination.mkdir(parents=True, exist_ok=True)
    moved: list[dict[str, Any]] = []
    for entry in candidates:
        source = Path(entry["path"])
        target = destination / source.relative_to(root)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(target))
        moved.append(
            {
                "source": str(source),
                "source_hash": _hash_path(source),
                "destination": str(target),
                "size_bytes": entry["size_bytes"],
            }
        )
    receipt = {
        "timestamp": datetime.now(UTC).isoformat(),
        "source_root": str(root),
        "quarantine_root": str(destination),
        "moved_count": len(moved),
        "moved_bytes": sum(item["size_bytes"] for item in moved),
        "moved": moved,
        "script_version": "rig_global_declutter_audit.v1",
    }
    (destination / "declutter-quarantine-receipt.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True), encoding="utf-8"
    )
    return receipt


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rig-root", type=Path, default=DEFAULT_RIG_ROOT)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--quarantine", action="store_true")
    parser.add_argument("--quarantine-root", type=Path, default=DEFAULT_QUARANTINE_ROOT)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    inventory = inventory_rig(args.rig_root)
    write_reports(inventory, args.out)
    if args.quarantine:
        quarantine(
            args.rig_root, quarantine_candidates(inventory), args.quarantine_root
        )
    print(
        json.dumps(
            {
                "exists": inventory["exists"],
                "entries": inventory["total_entries"],
                "bytes": inventory["total_bytes"],
                "quarantine_candidates": len(quarantine_candidates(inventory)),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
