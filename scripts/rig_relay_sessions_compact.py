#!/usr/bin/env python3
"""Rig Relay session storage compaction.

Dry-run first. Pass --execute to perform compaction operations.
"""

from __future__ import annotations

import argparse
import gzip
import json
from pathlib import Path

from rig_relay.cli.governance_guard import (
    emit_structured_result,
    require_governed_execution_with_evidence,
)
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
    parser.add_argument(
        "--execute",
        action="store_true",
        default=False,
        help="Execute compaction operations. Default is dry-run.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        default=False,
        help="Emit structured JSON output.",
    )
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
    with gzip.open(output_path, "wt", encoding="utf-8") as out_f:
        with source.open("r", encoding="utf-8") as in_f:
            for line in in_f:
                out_f.write(line)


def main() -> int:
    args = parse_args()
    summary = audit_sessions_storage(args.sessions_root, top_n=10)
    candidates = find_session_compaction_candidates(args.sessions_root)
    print(f"Compaction candidates: {len(candidates)}")

    execute = args.execute or args.confirm
    governed = require_governed_execution_with_evidence(
        script_name="rig_relay_sessions_compact",
        authority_tier="local_mutation",
        capability_id="session_compaction",
        execute_requested=execute,
    )

    if not execute:
        print("Dry run only. Pass --execute to compact.")
        for item in candidates:
            print(f"  {item.path}")
        if args.json:
            r = emit_structured_result(
                script_name="rig_relay_sessions_compact",
                authority_tier="local_mutation",
                capability_id="session_compaction",
                dry_run=True,
                execute_requested=False,
                decision=governed.decision,
                status="dry_run",
            )
            print(json.dumps(r, indent=2))
        return 0

    if not governed.can_execute:
        r = emit_structured_result(
            script_name="rig_relay_sessions_compact",
            authority_tier="local_mutation",
            capability_id="session_compaction",
            dry_run=False,
            execute_requested=True,
            decision=governed.decision,
            status="blocked_by_governance",
            can_execute=False,
            evidence_ref=governed.evidence_ref,
            evidence_status=governed.evidence_status,
        )
        if args.json:
            print(json.dumps(r, indent=2))
        else:
            print(f"BLOCKED: {governed.decision.decision.value}")
        return 1

    output_root = args.output_root or args.sessions_root / "rollups"
    fmt = args.format
    compacted = []
    for item in candidates:
        if fmt == "parquet":
            out = output_root / f"{item.path.stem}.parquet"
            _compact_jsonl_to_parquet(item.path, out)
        else:
            out = output_root / f"{item.path.stem}.jsonl.gz"
            _compact_jsonl_to_gz(item.path, out)
        compacted.append(str(out))
    print(f"Compacted to {output_root}: {len(compacted)} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
