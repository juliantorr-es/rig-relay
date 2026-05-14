#!/usr/bin/env python3
"""Rig Relay session storage compaction.

Dry-run first. Writes only when --confirm is passed.
"""

from __future__ import annotations

import argparse
import gzip
import json
from pathlib import Path

from rig_relay.evidence.redaction import redact_for_remote
from rig_relay.evidence.session_lifecycle import (
    audit_sessions_storage,
    find_session_compaction_candidates,
)

try:
    import duckdb  # type: ignore
except Exception:  # pragma: no cover
    duckdb = None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compact Rig Relay session storage")
    parser.add_argument(
        "--sessions-root", type=Path, default=Path.home() / ".rig" / "sessions"
    )
    parser.add_argument("--state-root", type=Path, default=None)
    parser.add_argument("--output-root", type=Path, default=None)
    parser.add_argument("--dry-run", action="store_true", default=True)
    parser.add_argument("--confirm", action="store_true")
    parser.add_argument("--format", choices=["parquet", "jsonl_gz"], default="parquet")
    return parser.parse_args()


def _compact_jsonl_to_parquet(source: Path, output_path: Path) -> None:
    if duckdb is None:
        raise RuntimeError("duckdb not available")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.execute(
        "COPY (SELECT * FROM read_json_auto(?)) TO ? (FORMAT PARQUET)",
        [str(source), str(output_path)],
    )
    con.close()


def _compact_jsonl_to_gz(source: Path, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with (
        source.open("rt", encoding="utf-8") as src,
        gzip.open(output_path, "wt", encoding="utf-8") as dst,
    ):
        for line in src:
            if not line.strip():
                continue
            redacted = redact_for_remote(json.loads(line)).payload
            dst.write(
                json.dumps(redacted, sort_keys=True, separators=(",", ":")) + "\n"
            )


def main() -> int:
    args = parse_args()
    output_root = args.output_root or (args.sessions_root / "rollups")
    candidates = find_session_compaction_candidates(args.sessions_root)
    summary = audit_sessions_storage(args.sessions_root, top_n=10)
    print(f"Sessions root: {summary.sessions_root}")
    print(f"Compaction candidates: {len(candidates)}")
    if not args.confirm:
        print("Dry run only. Pass --confirm to write rollups.")
        for item in candidates[:10]:
            print(f"  {item.path} [{item.category.value}]")
        return 0
    for item in candidates:
        rel_name = (
            item.path.relative_to(args.sessions_root).as_posix().replace("/", "__")
        )
        if args.format == "parquet":
            target = output_root / f"{rel_name}.parquet"
            try:
                _compact_jsonl_to_parquet(item.path, target)
            except Exception:
                target = output_root / f"{rel_name}.jsonl.gz"
                _compact_jsonl_to_gz(item.path, target)
        else:
            target = output_root / f"{rel_name}.jsonl.gz"
            _compact_jsonl_to_gz(item.path, target)
        print(f"Wrote {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
