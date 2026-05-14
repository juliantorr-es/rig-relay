#!/usr/bin/env python3
"""Rig Relay Receipt Index — read-only inspection of tool receipt events.

Reads a session's local observability JSONL and prints a content-light
receipt index. No raw output, file contents, diffs, or snippets are ever
loaded or exposed.

Usage:
    uv run python scripts/rig_relay_receipt_index.py <session_id>
    uv run python scripts/rig_relay_receipt_index.py --path /path/to/observability.jsonl
    uv run python scripts/rig_relay_receipt_index.py <session_id> --summary
    uv run python scripts/rig_relay_receipt_index.py <session_id> --json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from rig_relay.evidence.receipt_index import (
    ToolReceiptIndexRecord,
    build_receipt_index,
    summarize_receipt_index,
    validate_index_content_light,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Inspect tool receipt index from session observability events"
    )
    parser.add_argument(
        "session",
        nargs="?",
        default=None,
        help="Session ID (resolved via ~/.rig/sessions/<id>/observability.jsonl)",
    )
    parser.add_argument(
        "--path",
        type=Path,
        default=None,
        help="Explicit path to observability JSONL or session directory",
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Print human-readable summary instead of full JSON",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output full receipt index as JSON (default)",
    )
    parser.add_argument(
        "--validate",
        action="store_true",
        help="Run content-light validation on the index",
    )
    parser.add_argument(
        "--errors",
        action="store_true",
        help="Print build errors (skipped by default)",
    )
    return parser.parse_args(argv)


def _resolve_input(
    args: argparse.Namespace,
) -> str | Path | None:
    if args.path:
        return args.path
    if args.session:
        return args.session
    return None


def _print_json(data: object) -> None:
    print(json.dumps(data, indent=2, sort_keys=True, default=str))


def _print_summary(records: list[ToolReceiptIndexRecord], errors: list[str]) -> None:
    summary = summarize_receipt_index(records)
    d = summary.to_dict()
    print("Receipt Index Summary")
    print(f"  Total events:    {d['total_events']}")
    print(f"  Mutations:       {d['mutation_count']}")
    print(f"  Refusals:        {d['refusal_count']}")
    print(f"  Timeouts:        {d['timeout_count']}")
    print()
    print("  By tool:")
    for tool, count in d["by_tool"].items():
        print(f"    {tool}: {count}")
    print()
    print("  By status:")
    for st, count in d["by_status"].items():
        print(f"    {st}: {count}")
    print()
    if d["mutated_paths"]:
        print("  Mutated paths:")
        for path, hashes in d["mutated_paths"].items():
            before = hashes.get("before", "N/A")
            after = hashes.get("after", "N/A")
            print(f"    {path}")
            print(f"      before: {before}")
            print(f"      after:  {after}")
    print()
    print(f"  Tools with receipts: {', '.join(d['tools_with_receipts'])}")
    if errors:
        print()
        print(f"  Build errors ({len(errors)}):")
        for err in errors:
            print(f"    {err}")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    resolved = _resolve_input(args)

    if not resolved:
        print("ERROR: Provide a session ID or --path.", file=sys.stderr)
        return 1

    records, errors = build_receipt_index(resolved)

    if args.summary:
        _print_summary(records, errors if args.errors else [])
        return 0

    if args.validate:
        warnings = validate_index_content_light(records)
        if warnings:
            print(f"Content-light validation: FAILED ({len(warnings)} warnings)")
            for w in warnings:
                print(f"  {w}")
        else:
            print("Content-light validation: PASSED")
        return 0 if not warnings else 1

    # Default: full JSON output
    output: dict[str, object] = {
        "session": str(resolved),
        "total_records": len(records),
        "records": [r.model_dump(mode="json") for r in records],
    }
    if errors and args.errors:
        output["errors"] = errors
    _print_json(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
