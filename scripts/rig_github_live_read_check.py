#!/usr/bin/env python3
"""GitHub live read-only check script.

Usage:
  uv run python scripts/rig_github_live_read_check.py --live --repo owner/repo [--all]
  uv run python scripts/rig_github_live_read_check.py --dry-run

Requires RIG_LIVE_PROVIDER_TESTS=1 for --live.
Default is --dry-run (no network).
Outputs JSON evidence only.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from rig_relay.integrations.github_provider._adapter import run_local_read_operation
from rig_relay.integrations.github_provider._live_adapter import (
    _API_PATHS,
    _REQUIRED_SCOPES,
    run_live_read_operation,
)
from rig_relay.integrations.github_provider._models import GitHubProviderAuthState
from rig_relay.integrations.github_provider._redaction import hash_identifier

REPO_ROOT = Path(__file__).resolve().parent.parent

_READ_CAPABILITIES = [
    "github.repo.metadata.read",
    "github.repo.branches.read",
    "github.repo.commits.read",
    "github.repo.issues.read",
    "github.repo.pull_requests.read",
    "github.actions.runs.read",
    "github.actions.artifacts.read",
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _build_dry_run_receipt(capability_id: str, repo_hash: str) -> dict:
    receipt = run_local_read_operation(
        operation_id=f"live-check-dry-{capability_id}",
        capability_id=capability_id,
        auth_state=GitHubProviderAuthState(),
        repository_hash=repo_hash,
    )
    d = receipt.to_dict()
    d["live"] = False
    d["dry_run"] = True
    return d


def _build_refusal_receipt(capability_id: str, refusal_code: str, reason: str) -> dict:
    return {
        "verdict": "refused",
        "refusal_code": refusal_code,
        "reason": reason,
        "capability_id": capability_id,
        "live": False,
        "content_light": True,
    }


async def _run_live_check(
    capability_id: str, token: str, repo_owner: str, repo_name: str, trace_id: str
) -> dict:
    result = await run_live_read_operation(
        capability_id=capability_id,
        token=token,
        repository_owner=repo_owner,
        repository_name=repo_name,
        trace_id=trace_id,
    )
    result.pop("receipt", None)
    result.pop("response_hash", None)
    if "response_sha" in result:
        result["response_hash_prefix"] = result.pop("response_sha")
    result["live"] = True
    result["capability_id"] = capability_id
    result["content_light"] = True
    return result


async def _run_checks(
    live: bool,
    token: str,
    repo_owner: str,
    repo_name: str,
    all_caps: bool,
    single_capability: str | None,
) -> list[dict]:
    repo_hash = ""
    if repo_owner and repo_name:
        repo_hash = hash_identifier(f"{repo_owner}/{repo_name}")

    trace_id = hashlib.sha256((token[:8] if token else "dry").encode()).hexdigest()[:16]

    results: list[dict] = []

    if single_capability:
        if live:
            result = await _run_live_check(
                single_capability, token, repo_owner, repo_name, trace_id
            )
        elif single_capability in _API_PATHS:
            result = _build_dry_run_receipt(single_capability, repo_hash)
        else:
            result = _build_refusal_receipt(
                single_capability,
                "github.capability.no_live_path",
                f"No live API path for {single_capability}",
            )
        results.append(result)

    if all_caps:
        for cap_id in _READ_CAPABILITIES:
            if cap_id == single_capability:
                continue
            if live:
                try:
                    result = await _run_live_check(
                        cap_id, token, repo_owner, repo_name, trace_id
                    )
                except Exception as e:
                    result = {
                        "verdict": "failed",
                        "error": str(e),
                        "capability_id": cap_id,
                        "live": True,
                        "content_light": True,
                    }
            else:
                result = _build_dry_run_receipt(cap_id, repo_hash)
            results.append(result)

    if not results:
        for cap_id in _READ_CAPABILITIES:
            if live:
                try:
                    result = await _run_live_check(
                        cap_id, token, repo_owner, repo_name, trace_id
                    )
                except Exception as e:
                    result = {
                        "verdict": "failed",
                        "error": str(e),
                        "capability_id": cap_id,
                        "live": True,
                        "content_light": True,
                    }
            else:
                result = _build_dry_run_receipt(cap_id, repo_hash)
            results.append(result)

    return results


async def main() -> None:
    parser = argparse.ArgumentParser(description="GitHub live read-only check")
    parser.add_argument(
        "--live",
        action="store_true",
        help="Execute live API calls (requires RIG_LIVE_PROVIDER_TESTS=1)",
    )
    parser.add_argument("--repo", type=str, help="Repository as owner/name")
    parser.add_argument("--all", action="store_true", help="Run all read operations")
    parser.add_argument(
        "--dry-run", action="store_true", help="Dry run only, no network (default)"
    )
    parser.add_argument(
        "--output",
        type=str,
        default=str(REPO_ROOT / ".build" / "rig-relay" / "github-live-check.json"),
    )
    parser.add_argument("--capability", type=str, help="Single capability to test")
    args = parser.parse_args()

    if not args.live and not args.dry_run:
        args.dry_run = True

    if args.live and os.environ.get("RIG_LIVE_PROVIDER_TESTS") != "1":
        print(
            json.dumps({
                "verdict": "refused",
                "refusal_code": "live_network_disabled",
                "reason": "Set RIG_LIVE_PROVIDER_TESTS=1 to enable live provider tests",
                "content_light": True,
            })
        )
        sys.exit(2)

    token = os.environ.get("GITHUB_TOKEN", "")
    if args.live and not token:
        print(
            json.dumps({
                "verdict": "refused",
                "refusal_code": "missing_github_token",
                "reason": "Set GITHUB_TOKEN for live operations",
                "content_light": True,
            })
        )
        sys.exit(2)

    repo_owner = ""
    repo_name = ""
    if args.repo and "/" in args.repo:
        repo_owner, repo_name = args.repo.split("/", 1)
        repo_owner = repo_owner.strip()
        repo_name = repo_name.strip()

    results = await _run_checks(
        live=args.live,
        token=token,
        repo_owner=repo_owner,
        repo_name=repo_name,
        all_caps=args.all,
        single_capability=args.capability,
    )

    any_refused = any(r.get("verdict") == "refused" for r in results)

    output: dict = {
        "generated_at": _now_iso(),
        "live": args.live,
        "dry_run": args.dry_run,
        "repository": args.repo or "",
        "capabilities_checked": len(results),
        "verdicts": {},
        "overall_verdict": "refused" if any_refused else "completed",
        "content_light": True,
        "results": results,
    }

    output_dir = Path(args.output).parent
    output_dir.mkdir(parents=True, exist_ok=True)
    output_json = json.dumps(output, indent=2, ensure_ascii=False)
    Path(args.output).write_text(output_json + "\n", encoding="utf-8")

    print(output_json)

    if any_refused:
        sys.exit(2)
    sys.exit(0)


if __name__ == "__main__":
    asyncio.run(main())
