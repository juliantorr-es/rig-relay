#!/usr/bin/env python3
"""Rig Relay GitHub Live Auth Check — dry-run config validation and live smoke tests.

Content-light by design: never prints or stores raw tokens, secrets, or private keys.
All identifiers are SHA-256 hashed.

Usage:
    uv run python scripts/rig_github_live_auth_check.py --dry-run
    uv run python scripts/rig_github_live_auth_check.py --live
    uv run python scripts/rig_github_live_auth_check.py --output-json result.json
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import sys
from typing import Any, cast
import uuid

from rig_relay.integrations.github_provider._live_auth import (
    GitHubPermissionMode,
    build_read_only_installation_permissions,
    normalize_permission_mode,
    summarize_permission_posture,
)
from rig_relay.integrations.github_provider._redaction import safe_summary

REPO_ROOT = Path(__file__).resolve().parent.parent
LIVE_ENV_KEY = "RIG_LIVE_AUTH_TESTS"
PERMISSION_MODE_ENV_KEY = "RIG_GITHUB_PERMISSION_MODE"


def _sha256_hex(data: str) -> str:
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def _permission_mode_from_value(value: str | None) -> GitHubPermissionMode:
    return normalize_permission_mode(
        value if value is not None else os.environ.get(PERMISSION_MODE_ENV_KEY)
    )


def _lift_run_live_github(
    config: Any, receipt_id: str, trace_id: str, permission_mode: GitHubPermissionMode
) -> dict[str, Any]:
    """Synchronous wrapper around the live GitHub auth pipeline.

    Lazily imports all live-auth modules and httpx. Content-light output only.
    """
    from rig_relay.integrations.github_provider._live_auth import (
        GitHubLiveAuthError,
        GitHubLiveReadOnlySmoke,
        GitHubLiveTokenExchanger,
    )

    issues: list[dict[str, str]] = []
    results: dict[str, Any] = {}
    requested_permissions = build_read_only_installation_permissions()
    results["permission_mode"] = permission_mode.value
    results.update(
        summarize_permission_posture(
            permission_mode=permission_mode,
            requested_permissions=requested_permissions,
            token_permissions={},
            installation_permission_keys=[],
        )
    )

    if not config._has_private_key():
        issues.append({
            "kind": "missing_private_key",
            "detail": "No private key available from RIG_GITHUB_PRIVATE_KEY_PATH or RIG_GITHUB_PRIVATE_KEY_ENV",
        })
    if config.app_id is None:
        issues.append({
            "kind": "missing_app_id",
            "detail": "RIG_GITHUB_APP_ID is not set",
        })
    if config.installation_id is None:
        issues.append({
            "kind": "missing_installation_id",
            "detail": "RIG_GITHUB_INSTALLATION_ID is not set",
        })

    if issues:
        return {
            "auth_mode": "app_installation",
            "token_exchange": {
                "schema_version": "rig.github.live_auth_refusal.v1",
                "error": "config_incomplete",
                "issues": issues,
            },
        }

    app_id: int = cast(int, config.app_id)
    installation_id: int = cast(int, config.installation_id)

    try:
        private_key = config.load_private_key()
    except GitHubLiveAuthError as e:
        return {
            "auth_mode": "app_installation",
            "token_exchange": {
                "schema_version": "rig.github.live_auth_refusal.v1",
                "error": "private_key_load_failed",
                "error_description": str(e)[:256],
            },
        }

    exchanger = GitHubLiveTokenExchanger()
    try:
        token_result, raw_token = exchanger.exchange_installation_token(
            app_id=app_id,
            installation_id=installation_id,
            private_key_bytes=private_key,
            requested_permissions=requested_permissions,
        )
    except GitHubLiveAuthError as e:
        results["token_exchange"] = {
            "schema_version": "rig.github.live_auth_refusal.v1",
            "error": "token_narrowing_refused",
            "error_description": str(e)[:256],
        }
        results["auth_mode"] = "app_installation"
        return results

    results["token_exchange"] = token_result

    smoke = GitHubLiveReadOnlySmoke()
    try:
        installation_access = smoke.probe_installation_access(
            raw_token,
            installation_id=installation_id,
            repository_selection=token_result.get("repository_selection"),
            permission_keys=sorted(token_result.get("permissions", {}).keys())
            if isinstance(token_result.get("permissions"), dict)
            else None,
        )
    except GitHubLiveAuthError as e:
        results["installation_access"] = {
            "schema_version": "rig.github.live_auth_refusal.v1",
            "auth_mode": "app_installation",
            "error": "installation_access_failed",
            "error_description": str(e)[:256],
        }
        results["auth_mode"] = "app_installation"
        return results

    results["installation_access"] = installation_access
    results["auth_mode"] = "app_installation"
    posture_summary = summarize_permission_posture(
        permission_mode=permission_mode,
        requested_permissions=requested_permissions,
        token_permissions=token_result.get("permissions")
        if isinstance(token_result.get("permissions"), dict)
        else {},
        installation_permission_keys=installation_access.get("permission_keys")
        if isinstance(installation_access.get("permission_keys"), list)
        else [],
    )
    results.update(posture_summary)

    return results


def _dry_run_output(config: Any, issues_report: dict[str, Any]) -> None:
    print("=== Rig Relay GitHub Live Auth Check (dry-run) ===\n")
    summary = config.config_summary()
    print("Configuration:")
    print(f"  App ID configured:         {summary['app_id_configured']}")
    print(f"  Installation ID configured:{summary['installation_id_configured']}")
    print(f"  Private key source:        {summary['private_key_source']}")
    print(f"  Private key present:       {summary['private_key_present']}")
    print(f"  Client ID configured:      {summary['client_id_configured']}")
    print(f"  Client secret configured:  {summary['client_secret_configured']}")
    print(f"  Redirect URI configured:   {summary['redirect_uri_configured']}")
    print(f"  App auth possible:         {summary['app_auth_possible']}")
    print(f"  OAuth auth possible:       {summary['oauth_auth_possible']}")
    print(f"  Any auth configured:       {summary['any_auth_configured']}")
    print()
    print("Issues:")
    if issues_report["issues"]:
        for issue in issues_report["issues"]:
            print(f"  - [{issue['kind']}] {issue['detail']}")
    else:
        print("  (none)")
    print()
    print("Live mode would:")
    print("  1. Load and validate the RSA private key")
    print("  2. Sign a JWT and exchange for an installation access token")
    print("  3. Prove installation access via /installation/repositories")
    print("  4. List accessible repositories from the installation")
    print()
    print(f"Run with --live (and {LIVE_ENV_KEY}=1) to execute live calls.")
    print(f"Receipt ID: {issues_report['receipt_id']}")
    print(f"Trace ID:   {issues_report['trace_id']}")
    config_hash = _sha256_hex(json.dumps(issues_report, sort_keys=True))
    print(f"Auth state hash: {config_hash}")


def _live_output(results: dict[str, Any], issues_report: dict[str, Any]) -> None:
    print("=== Rig Relay GitHub Live Auth Check (live) ===\n")
    print("Configuration:")
    for issue in issues_report["issues"]:
        print(f"  - [{issue['kind']}] {issue['detail']}")
    print(f"  permission_mode: {results.get('permission_mode', 'unknown')}")

    print()
    print("Token exchange:")
    te = results.get("token_exchange", {})
    if te.get("error"):
        print(f"  FAILED: {te.get('error')}")
        print(f"  {te.get('error_description', '')}")
    else:
        print(f"  token_hash:     {te.get('token_hash', 'N/A')}")
        print(f"  token_present:  {te.get('token_present', False)}")
        print(f"  expires_at:     {te.get('expires_at', 'N/A')}")
        print(f"  permissions:    {te.get('permissions', {})}")
        print(f"  repo_selection: {te.get('repository_selection', 'N/A')}")
        print(
            f"  token_narrowing_requested: {results.get('token_narrowing_requested', False)}"
        )
        print(
            f"  token_narrowing_effective:  {results.get('token_narrowing_effective', False)}"
        )

    print()
    print("Installation access:")
    ident = results.get("installation_access", {})
    if ident.get("error"):
        print(f"  FAILED: {ident.get('error')}")
        print(f"  {ident.get('error_description', '')}")
    else:
        print(f"  installation_id_hash:   {ident.get('installation_id_hash', 'N/A')}")
        print(f"  accessible_repo_count:   {ident.get('accessible_repo_count', 0)}")
        print(f"  repository_selection:    {ident.get('repository_selection', 'N/A')}")
        print(f"  permission_keys:         {ident.get('permission_keys', [])}")
        for repo_hash in ident.get("accessible_repo_name_hashes", []):
            print(f"    - repo_name_hash={repo_hash}")

    print()
    print(f"Receipt ID: {issues_report['receipt_id']}")
    print(f"Trace ID:   {issues_report['trace_id']}")
    config_hash = _sha256_hex(json.dumps(safe_summary(results), sort_keys=True))
    print(f"Auth state hash: {config_hash}")


def _build_issues_report(config: Any, receipt_id: str, trace_id: str) -> dict[str, Any]:
    summary = config.config_summary()
    issues: list[dict[str, str]] = []

    if not summary["any_auth_configured"]:
        issues.append({
            "kind": "no_auth_configured",
            "detail": "Neither GitHub App auth nor OAuth auth is configured",
        })

    if summary["app_auth_possible"] and summary["private_key_source"] == "missing":
        issues.append({
            "kind": "private_key_missing",
            "detail": "Private key file pointed to by RIG_GITHUB_PRIVATE_KEY_PATH does not exist",
        })

    if summary["client_id_configured"] and not summary["client_secret_configured"]:
        issues.append({
            "kind": "oauth_incomplete",
            "detail": "RIG_GITHUB_CLIENT_ID is set but RIG_GITHUB_CLIENT_SECRET is not",
        })

    if summary["client_secret_configured"] and not summary["client_id_configured"]:
        issues.append({
            "kind": "oauth_incomplete",
            "detail": "RIG_GITHUB_CLIENT_SECRET is set but RIG_GITHUB_CLIENT_ID is not",
        })

    return {
        "receipt_id": receipt_id,
        "trace_id": trace_id,
        "configured": summary["any_auth_configured"],
        "auth_mode": "app_installation"
        if summary["app_auth_possible"]
        else "oauth"
        if summary["oauth_auth_possible"]
        else "none",
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
        prog="rig-github-live-auth-check",
        description="Dry-run config validation and live smoke tests for GitHub auth.",
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
    parser.add_argument(
        "--permission-mode",
        type=str,
        default=None,
        choices=["development_debug", "preproduction", "public_release"],
        help="Permission posture mode used for token narrowing and reporting.",
    )
    args = parser.parse_args(argv)

    from rig_relay.integrations.github_provider import GitHubLiveAuthConfig

    receipt_id = str(uuid.uuid4())
    trace_id = str(uuid.uuid4())
    permission_mode = _permission_mode_from_value(args.permission_mode)

    config = GitHubLiveAuthConfig.from_environment()
    issues_report = _build_issues_report(config, receipt_id, trace_id)

    if args.live:
        if os.environ.get(LIVE_ENV_KEY) != "1":
            print(
                f"ERROR: {LIVE_ENV_KEY}=1 is required for --live mode.", file=sys.stderr
            )
            return 1

        results = _lift_run_live_github(config, receipt_id, trace_id, permission_mode)
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
                    "permission_mode": permission_mode.value,
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
                "permission_mode": permission_mode.value,
                "config_summary": config.config_summary(),
                "issues": issues_report["issues"],
                "timestamp_utc": datetime.now(UTC).isoformat(),
            },
        )

    return 0 if not issues_report["issues"] else 1


__all__: list[str] = []

if __name__ == "__main__":
    raise SystemExit(main())
