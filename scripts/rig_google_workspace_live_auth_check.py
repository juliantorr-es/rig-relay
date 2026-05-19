#!/usr/bin/env python3
"""Rig Relay Google Workspace Live Auth Check — dry-run config validation and live smoke tests.

Content-light by design: never prints or stores raw tokens, secrets, or private keys.
All identifiers are SHA-256 hashed.

Usage:
    uv run python scripts/rig_google_workspace_live_auth_check.py --dry-run
    uv run python scripts/rig_google_workspace_live_auth_check.py --live
    uv run python scripts/rig_google_workspace_live_auth_check.py --output-json result.json
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import sys
from typing import Any
import uuid

REPO_ROOT = Path(__file__).resolve().parent.parent
LIVE_ENV_KEY = "RIG_LIVE_AUTH_TESTS"


def _sha256_hex(data: str) -> str:
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def _lift_run_live_google() -> dict[str, Any]:
    """Execute live read-only smoke tests against Google APIs.

    Lazily imports httpx. Requires an access token via GOOGLE_ACCESS_TOKEN
    env var (content-light: the token itself is never printed).
    Content-light output only.
    """
    access_token = os.environ.get("GOOGLE_ACCESS_TOKEN", "")
    if not access_token:
        return {
            "schema_version": "rig.google_workspace.live_auth_refusal.v1",
            "error": "missing_access_token",
            "error_description": (
                "Set GOOGLE_ACCESS_TOKEN to a valid OAuth access token "
                "to run live smoke tests"
            ),
        }

    from rig_relay.integrations.github_provider._redaction import safe_summary
    from rig_relay.integrations.google_workspace._live_auth import (
        GoogleLiveReadOnlySmoke,
    )

    token_scope = os.environ.get("GOOGLE_TOKEN_SCOPE", "")
    smoke = GoogleLiveReadOnlySmoke()

    results: dict[str, Any] = {}

    identity = smoke.inspect_identity(access_token)
    results["inspect_identity"] = identity
    if identity.get("error"):
        results["list_gmail_profile"] = {
            "schema_version": "rig.google_workspace.live_auth_refusal.v1",
            "error": "skipped_identity_failed",
            "error_description": "Skipped: inspect_identity failed",
        }
        results["list_calendar_list"] = {
            "schema_version": "rig.google_workspace.live_auth_refusal.v1",
            "error": "skipped_identity_failed",
            "error_description": "Skipped: inspect_identity failed",
        }
        results["list_drive_metadata"] = {
            "schema_version": "rig.google_workspace.live_auth_refusal.v1",
            "error": "skipped_identity_failed",
            "error_description": "Skipped: inspect_identity failed",
        }
        return results

    gmail = smoke.list_gmail_profile(access_token, token_scope)
    results["list_gmail_profile"] = gmail

    calendar = smoke.list_calendar_list(access_token, token_scope)
    results["list_calendar_list"] = calendar

    drive = smoke.list_drive_metadata(access_token, token_scope)
    results["list_drive_metadata"] = drive

    return results


def _dry_run_output(config: Any, issues_report: dict[str, Any]) -> None:
    print("=== Rig Relay Google Workspace Live Auth Check (dry-run) ===\n")
    summary = config.config_summary()
    print("Configuration:")
    print(f"  OAuth configured:                  {summary['oauth_configured']}")
    print(f"  Redirect URI configured:           {summary['redirect_uri_configured']}")
    print(
        f"  Service account configured:        {summary['service_account_configured']}"
    )
    print(
        f"  Domain-wide delegation configured: {summary['domain_wide_delegation_configured']}"
    )
    print(f"  Client ID hash:                    {summary['client_id_hash'] or 'N/A'}")
    print(
        f"  Service account email hash:        {summary['service_account_email_hash'] or 'N/A'}"
    )
    print(
        f"  Admin email hash:                  {summary['admin_email_hash'] or 'N/A'}"
    )
    print()
    print("Issues:")
    if issues_report["issues"]:
        for issue in issues_report["issues"]:
            print(f"  - [{issue['kind']}] {issue['detail']}")
    else:
        print("  (none)")
    print()
    print("Live mode would:")
    print("  1. Inspect identity via oauth2/v1/userinfo")
    print("  2. List Gmail profile (scope check → gmail.readonly)")
    print("  3. List calendar list (scope check → calendar.readonly)")
    print("  4. List Drive metadata (scope check → drive.metadata.readonly)")
    print()
    print("To use --live: set GOOGLE_ACCESS_TOKEN to a valid OAuth access token.")
    print(f"Run with --live (and {LIVE_ENV_KEY}=1) to execute live calls.")
    print(f"Receipt ID: {issues_report['receipt_id']}")
    print(f"Trace ID:   {issues_report['trace_id']}")
    config_hash = _sha256_hex(json.dumps(issues_report, sort_keys=True))
    print(f"Auth state hash: {config_hash}")


def _print_smoke_result(label: str, result: dict[str, Any]) -> None:
    if result.get("error"):
        print(f"  {label}: REFUSED ({result.get('error')})")
        desc = result.get("error_description", "")
        if desc:
            print(f"    {desc}")
        return

    if label == "inspect_identity":
        print(f"  {label}: OK")
        print(f"    email_hash:    {result.get('email_hash', 'N/A')}")
        print(f"    verified_email:{result.get('verified_email', 'N/A')}")
        print(f"    has_name:      {result.get('has_name', 'N/A')}")
    elif label == "list_gmail_profile":
        print(f"  {label}: OK")
        print(f"    messages_total: {result.get('messages_total', 'N/A')}")
        print(f"    threads_total:  {result.get('threads_total', 'N/A')}")
    elif label == "list_calendar_list":
        print(f"  {label}: OK")
        print(f"    calendar_count: {result.get('calendar_count', 0)}")
    elif label == "list_drive_metadata":
        print(f"  {label}: OK")
        print(f"    file_count:     {result.get('file_count', 0)}")
        for f in result.get("files", []):
            print(
                f"      name_hash={f.get('name_hash', '')}  mime={f.get('mime_type', '')}"
            )


def _live_output(results: dict[str, Any], issues_report: dict[str, Any]) -> None:
    print("=== Rig Relay Google Workspace Live Auth Check (live) ===\n")

    _print_smoke_result("inspect_identity", results.get("inspect_identity", {}))
    print()
    _print_smoke_result("list_gmail_profile", results.get("list_gmail_profile", {}))
    print()
    _print_smoke_result("list_calendar_list", results.get("list_calendar_list", {}))
    print()
    _print_smoke_result("list_drive_metadata", results.get("list_drive_metadata", {}))
    print()

    print(f"Receipt ID: {issues_report['receipt_id']}")
    print(f"Trace ID:   {issues_report['trace_id']}")
    config_hash = _sha256_hex(json.dumps(safe_summary(results), sort_keys=True))
    print(f"Auth state hash: {config_hash}")


def _build_issues_report(config: Any, receipt_id: str, trace_id: str) -> dict[str, Any]:
    summary = config.config_summary()
    issues: list[dict[str, str]] = []

    if not config.is_configured():
        issues.append({
            "kind": "no_auth_configured",
            "detail": "Neither OAuth nor service account auth is configured",
        })

    if summary["oauth_configured"] and not summary["redirect_uri_configured"]:
        issues.append({
            "kind": "oauth_missing_redirect_uri",
            "detail": "OAuth is configured but RIG_GOOGLE_REDIRECT_URI is not set",
        })

    if (
        summary["service_account_email_hash"]
        and not summary["service_account_configured"]
    ):
        issues.append({
            "kind": "service_account_key_missing",
            "detail": "RIG_GOOGLE_SERVICE_ACCOUNT_EMAIL is set but the key file does not exist",
        })

    return {
        "receipt_id": receipt_id,
        "trace_id": trace_id,
        "configured": config.is_configured(),
        "auth_mode": (
            "oauth"
            if summary["oauth_configured"]
            else "service_account"
            if summary["service_account_configured"]
            else "none"
        ),
        "credential_store_available": False,
        "issues": issues,
        "timestamp_utc": datetime.now(UTC).isoformat(),
    }


def _write_json(output_path: Path, data: dict[str, Any]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="rig-google-workspace-live-auth-check",
        description="Dry-run config validation and live smoke tests for Google Workspace auth.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Validate config only, no network calls (default)",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        default=False,
        help=f"Execute live API calls (requires {LIVE_ENV_KEY}=1)",
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=None,
        help="Write content-light JSON result to PATH",
    )
    args = parser.parse_args(argv)

    from rig_relay.integrations.google_workspace import GoogleLiveAuthConfig

    receipt_id = str(uuid.uuid4())
    trace_id = str(uuid.uuid4())

    config = GoogleLiveAuthConfig()
    issues_report = _build_issues_report(config, receipt_id, trace_id)

    if args.live:
        if os.environ.get(LIVE_ENV_KEY) != "1":
            print(
                f"ERROR: {LIVE_ENV_KEY}=1 is required for --live mode.", file=sys.stderr
            )
            return 1

        results = _lift_run_live_google()
        _live_output(results, issues_report)

        if args.output_json:
            _write_json(
                args.output_json,
                {
                    "receipt_id": receipt_id,
                    "trace_id": trace_id,
                    "dry_run": False,
                    "config_summary": config.config_summary(),
                    "issues": issues_report["issues"],
                    "live_results": safe_summary(results),
                    "timestamp_utc": datetime.now(UTC).isoformat(),
                },
            )

        has_errors = any(
            isinstance(v, dict) and v.get("error")
            for v in results.values()
            if isinstance(v, dict)
        )
        return 1 if has_errors else 0

    _dry_run_output(config, issues_report)

    if args.output_json:
        _write_json(
            args.output_json,
            {
                "receipt_id": receipt_id,
                "trace_id": trace_id,
                "dry_run": True,
                "config_summary": config.config_summary(),
                "issues": issues_report["issues"],
                "timestamp_utc": datetime.now(UTC).isoformat(),
            },
        )

    return 0 if not issues_report["issues"] else 1


__all__: list[str] = []

if __name__ == "__main__":
    raise SystemExit(main())
