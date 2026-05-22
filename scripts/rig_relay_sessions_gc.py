#!/usr/bin/env python3
"""Rig Relay session storage garbage collection.

Dry-run first, conservative by default. Pass --execute to perform
actual deletion. Governance gating required for destructive operations.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
import shutil

from rig_relay.cli.governance_guard import (
    emit_structured_result,
    require_governed_execution_with_evidence,
)
from rig_relay.evidence.session_lifecycle import (
    SessionStorageCategory,
    audit_sessions_storage,
    find_session_prune_candidates,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="GC Rig Relay session storage")
    parser.add_argument(
        "--sessions-root", type=Path, default=Path.home() / ".rig" / "sessions"
    )
    parser.add_argument("--state-root", type=Path, default=None)
    parser.add_argument("--dry-run", action="store_true", default=True)
    parser.add_argument("--confirm", action="store_true")
    parser.add_argument(
        "--execute",
        action="store_true",
        default=False,
        help="Execute destructive GC operations. Default is dry-run.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        default=False,
        help="Emit structured JSON output.",
    )
    parser.add_argument("--archive-dir", type=Path, default=None)
    parser.add_argument("--older-than-days", type=int, default=30)
    parser.add_argument("--max-delete-mb", type=float, default=256.0)
    return parser.parse_args()


def _dry_run_output(
    args: argparse.Namespace, governed: object, candidates: list
) -> None:
    print("Dry run only. Pass --execute to archive/delete candidates.")
    for item in candidates[:20]:
        print(f"  {item.path} [{item.category.value}] {item.size_bytes} bytes")
    if args.json:
        d = governed.decision
        r = emit_structured_result(
            script_name="rig_relay_sessions_gc",
            authority_tier="local_mutation",
            capability_id="session_gc",
            dry_run=True,
            execute_requested=False,
            decision=d,
            status="dry_run",
        )
        print(json.dumps(r, indent=2))


def _receipt_path(root: Path) -> Path:
    return (
        root
        / "gc"
        / f"session_gc_receipt_{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.json"
    )


def _write_receipt(root: Path, payload: dict[str, object]) -> None:
    path = _receipt_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def main() -> int:
    args = parse_args()
    summary = audit_sessions_storage(args.sessions_root, top_n=10)
    candidates = find_session_prune_candidates(
        args.sessions_root, older_than_days=args.older_than_days
    )
    print(f"Sessions root: {summary.sessions_root}")
    print(f"Prune candidates: {len(candidates)}")

    execute = args.execute or args.confirm
    governed = require_governed_execution_with_evidence(
        script_name="rig_relay_sessions_gc",
        authority_tier="local_mutation",
        capability_id="session_gc",
        execute_requested=execute,
    )

    if not args.confirm and not args.execute:
        _dry_run_output(args, governed, candidates)
        return 0

    if not governed.can_execute:
        r = emit_structured_result(
            script_name="rig_relay_sessions_gc",
            authority_tier="local_mutation",
            capability_id="session_gc",
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
            if governed.evidence_status == "persistence_failed":
                print("  EVIDENCE: persistence failed — GC blocked (fail-closed)")
        return 1

    total_delete_mb = 0.0
    deleted: list[str] = []
    archived: list[str] = []
    for item in candidates:
        size_mb = item.size_bytes / 1_048_576.0
        if total_delete_mb + size_mb > args.max_delete_mb:
            break
        if item.category in {
            SessionStorageCategory.RECEIPTS,
            SessionStorageCategory.CONSENT,
            SessionStorageCategory.UPLOAD_RECEIPTS,
            SessionStorageCategory.SIGNED_ENVELOPES,
        }:
            continue
        if args.archive_dir is not None:
            dest = args.archive_dir / item.path.name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(item.path), str(dest))
            archived.append(str(dest))
        else:
            item.path.unlink(missing_ok=True)
            deleted.append(str(item.path))
        total_delete_mb += size_mb
    _write_receipt(
        args.sessions_root,
        {
            "deleted": deleted,
            "archived": archived,
            "total_delete_mb": round(total_delete_mb, 3),
            "max_delete_mb": args.max_delete_mb,
        },
    )
    for path in deleted:
        print(f"Deleted {path}")
    for path in archived:
        print(f"Archived {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
