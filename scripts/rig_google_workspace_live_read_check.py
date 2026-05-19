#!/usr/bin/env python3
"""Google Workspace live read-only check script.

Usage:
  uv run python scripts/rig_google_workspace_live_read_check.py --live --service gmail [--all]
  uv run python scripts/rig_google_workspace_live_read_check.py --dry-run

Requires RIG_LIVE_PROVIDER_TESTS=1 for --live.
Default is --dry-run (no network).
Reads token from GOOGLE_ACCESS_TOKEN or GOOGLE_TOKEN.

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

from rig_relay.integrations.google_workspace._adapter import run_local_workspace_read
from rig_relay.integrations.google_workspace._live_adapter import (
    _API_ENDPOINTS,
    _REQUIRED_API_SCOPES,
    run_live_workspace_read,
)
from rig_relay.integrations.google_workspace._models import (
    GoogleWorkspaceAuthMode,
    GoogleWorkspaceAuthState,
    GoogleWorkspaceAuthStatus,
    GoogleWorkspaceScopeGrant,
    GoogleWorkspaceScopeSensitivity,
)
from rig_relay.integrations.google_workspace._redaction import _hash_identifier

REPO_ROOT = Path(__file__).resolve().parent.parent

_CAPABILITIES_BY_SERVICE: dict[str, list[str]] = {
    "gmail": [
        "google_workspace.gmail.labels.list",
        "google_workspace.gmail.profile.get",
    ],
    "calendar": ["google_workspace.calendar.calendarList.list"],
    "drive": ["google_workspace.drive.files.list"],
    "tasks": ["google_workspace.tasks.tasklists.list"],
    "contacts": ["google_workspace.contacts.list"],
}

_ALL_READ_CAPABILITIES: list[str] = []
for _caps in _CAPABILITIES_BY_SERVICE.values():
    _ALL_READ_CAPABILITIES.extend(_caps)
_ALL_READ_CAPABILITIES.append("google_workspace.admin.directory.users.list")


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _build_dry_run_receipt(capability_id: str) -> dict:
    auth = GoogleWorkspaceAuthState()
    receipt = run_local_workspace_read(
        operation_id=f"live-check-dry-{capability_id}",
        capability_id=capability_id,
        auth=auth,
    )
    d = receipt.to_dict()
    d["live"] = False
    d["dry_run"] = True
    return d


def _build_auth_state(
    token: str,
    capability_id: str,
    scope_grants: list[GoogleWorkspaceScopeGrant] | None = None,
) -> GoogleWorkspaceAuthState:
    account_hash = hashlib.sha256(token.encode()).hexdigest() if token else ""
    grants = scope_grants or []
    if not grants:
        req_scopes = _REQUIRED_API_SCOPES.get(capability_id, [])
        for scope_id in req_scopes:
            grants.append(
                GoogleWorkspaceScopeGrant(
                    scope_id=scope_id,
                    scope_sensitivity=GoogleWorkspaceScopeSensitivity.NON_SENSITIVE
                    if "readonly" in scope_id
                    else GoogleWorkspaceScopeSensitivity.SENSITIVE,
                )
            )
    return GoogleWorkspaceAuthState(
        auth_mode=GoogleWorkspaceAuthMode.OAUTH_USER,
        auth_status=GoogleWorkspaceAuthStatus.AUTHENTICATED,
        account_hash=account_hash,
        scope_grants=grants,
        token_material_present=True,
    )


async def _run_live_workspace_check(
    capability_id: str, token: str, trace_id: str, domain: str = ""
) -> dict:
    auth = _build_auth_state(token, capability_id)
    receipt = await run_live_workspace_read(
        operation_id=f"live-check-{capability_id}-{trace_id[:8]}",
        capability_id=capability_id,
        auth=auth,
        access_token=token,
        domain=domain,
        trace_id=trace_id,
    )
    d = receipt.to_dict()
    d["live"] = True
    d["content_light"] = True
    return d


async def _run_checks(
    live: bool, token: str, capability_ids: list[str], trace_id: str, domain: str = ""
) -> list[dict]:
    results: list[dict] = []
    for cap_id in capability_ids:
        if live:
            try:
                result = await _run_live_workspace_check(
                    cap_id, token, trace_id, domain
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
            result = _build_dry_run_receipt(cap_id)
        results.append(result)
    return results


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Google Workspace live read-only check"
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Execute live API calls (requires RIG_LIVE_PROVIDER_TESTS=1)",
    )
    parser.add_argument(
        "--service",
        type=str,
        help="Google service to check (gmail, calendar, drive, tasks, contacts)",
    )
    parser.add_argument(
        "--all", action="store_true", help="Run all read operations across all services"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Dry run only, no network (default)"
    )
    parser.add_argument(
        "--output",
        type=str,
        default=str(
            REPO_ROOT / ".build" / "rig-relay" / "google-workspace-live-check.json"
        ),
    )
    parser.add_argument("--capability", type=str, help="Single capability to test")
    parser.add_argument(
        "--domain", type=str, default="", help="Domain for admin directory operations"
    )
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

    token = os.environ.get("GOOGLE_ACCESS_TOKEN") or os.environ.get("GOOGLE_TOKEN", "")
    if args.live and not token:
        print(
            json.dumps({
                "verdict": "refused",
                "refusal_code": "missing_google_token",
                "reason": "Set GOOGLE_ACCESS_TOKEN or GOOGLE_TOKEN for live operations",
                "content_light": True,
            })
        )
        sys.exit(2)

    trace_id = hashlib.sha256((token[:8] if token else "dry").encode()).hexdigest()[:16]

    capability_ids: list[str] = []

    if args.capability:
        capability_ids.append(args.capability)

    if args.service:
        service_caps = _CAPABILITIES_BY_SERVICE.get(args.service, [])
        for cap_id in service_caps:
            if cap_id not in capability_ids:
                capability_ids.append(cap_id)

    if args.all:
        for cap_id in _ALL_READ_CAPABILITIES:
            if cap_id not in capability_ids:
                capability_ids.append(cap_id)

    if not capability_ids:
        capability_ids = _ALL_READ_CAPABILITIES

    results = await _run_checks(
        live=args.live,
        token=token,
        capability_ids=capability_ids,
        trace_id=trace_id,
        domain=args.domain,
    )

    any_refused = any(r.get("verdict") == "refused" for r in results)

    output: dict = {
        "generated_at": _now_iso(),
        "live": args.live,
        "dry_run": args.dry_run,
        "service": args.service or "",
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
