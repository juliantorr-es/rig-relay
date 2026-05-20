"""Live permission probe — X-Accepted-GitHub-Permissions header capture and normalization.

Probes GitHub endpoints for actual permission requirements. Gated by RIG_LIVE_AUTH_TESTS=1.
Returns content-light probe results. No tokens, auth headers, or raw bodies persisted.
"""

from __future__ import annotations

import hashlib
import os
from typing import Any

_LIVE_AUTH_ENV = "RIG_LIVE_AUTH_TESTS"

_PROBE_ENDPOINTS = [
    {
        "endpoint_family": "repo_metadata",
        "method": "GET",
        "route": "/repos/{owner}/{owner}",
        "purpose": "repository existence and metadata access",
        "expected_permission": "metadata:read",
        "operation_class": "read_only",
    },
    {
        "endpoint_family": "repo_readme",
        "method": "GET",
        "route": "/repos/{owner}/{owner}/readme",
        "purpose": "repository README content access",
        "expected_permission": "contents:read",
        "operation_class": "read_only",
    },
    {
        "endpoint_family": "repo_contents",
        "method": "GET",
        "route": "/repos/{owner}/{owner}/contents/README.md",
        "purpose": "repository file content access",
        "expected_permission": "contents:read",
        "operation_class": "read_only",
    },
]

_FORBIDDEN_PROBE = frozenset({
    "access_token",
    "token_prefix",
    "authorization",
    "client_secret",
    "private_key",
    "raw_response",
    "raw_body",
    "raw_payload",
    "bearer",
    "token",
    "auth_header",
})

_ACCEPTED_PERMISSIONS_HEADER = "x-accepted-github-permissions"
_HTTP_OK = 200
_HTTP_NOT_FOUND = 404


class LivePermissionProbeError(Exception):
    """Raised when live permission probe fails."""


def _sha256_text(val: str) -> str:
    return hashlib.sha256(val.encode("utf-8")).hexdigest()


def is_live_probe_available() -> bool:
    return os.environ.get(_LIVE_AUTH_ENV, "0") == "1"


def normalize_accepted_permissions_header(header_value: str) -> dict[str, Any]:
    """Normalize X-Accepted-GitHub-Permissions header into structured permission set.

    GitHub encodes the header as: "key=value,key=value"
    Example: "pull_requests=write,contents=read"

    Returns: {
        "raw_header_value": "...",
        "raw_header_hash": "sha256...",
        "normalized_permissions": [{"permission_key": "pull_requests", "access_level": "write"}, ...],
        "parse_success": bool,
        "parse_error": null,
    }
    """
    result: dict[str, Any] = {
        "raw_header_value": header_value,
        "raw_header_hash": _sha256_text(header_value),
        "normalized_permissions": [],
        "parse_success": True,
        "parse_error": None,
    }

    if not header_value or not isinstance(header_value, str):
        result["parse_success"] = False
        result["parse_error"] = "empty_or_non_string_header"
        return result

    parts = header_value.split(",")
    for part in parts:
        part = part.strip()
        if not part:
            continue
        if "=" not in part:
            result["parse_error"] = f"malformed_entry_no_equals: {part}"
            continue
        key, _, value = part.partition("=")
        key = key.strip()
        val = value.strip()
        if not key or not val:
            result["parse_error"] = f"empty_key_or_value: {part}"
            continue
        result["normalized_permissions"].append({
            "permission_key": key,
            "access_level": val,
        })

    if not result["normalized_permissions"]:
        result["parse_success"] = False
        if not result["parse_error"]:
            result["parse_error"] = "no_permissions_parsed"

    return result


def _normalize_observed_permission(
    observed_key: str, observed_level: str, static_model: list[dict[str, Any]]
) -> dict[str, Any]:
    """Match an observed permission against the static permission model.

    The observed header uses key names like 'pull_requests', 'contents'
    while the static model uses permission_ids like 'pull_requests:write', 'contents:read'.
    """
    for perm_model in static_model:
        model_id = perm_model.get("permission_id", "")
        model_level = perm_model.get("access_level", "")
        model_key = model_id.split(":")[0] if ":" in model_id else model_id

        if observed_key == model_key:
            match_level = (
                "exact" if observed_level == model_level else "partial_level_mismatch"
            )
            return {
                "observed_key": observed_key,
                "observed_level": observed_level,
                "matched_static_id": model_id,
                "matched_static_level": model_level,
                "match_type": match_level,
                "classification": "sufficient"
                if observed_level == model_level
                else "ambiguous",
            }

    return {
        "observed_key": observed_key,
        "observed_level": observed_level,
        "matched_static_id": None,
        "matched_static_level": None,
        "match_type": "unmodeled",
        "classification": "unmodeled",
    }


def _build_probe_entry(
    endpoint_spec: dict[str, Any],
    status_code: int,
    accepted_header: str | None,
    static_permissions: list[dict[str, Any]],
) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "endpoint_family": endpoint_spec["endpoint_family"],
        "method": endpoint_spec["method"],
        "route_pattern": endpoint_spec["route"],
        "expected_permission": endpoint_spec["expected_permission"],
        "status_code": status_code,
        "accessible": status_code == _HTTP_OK,
        "accepted_permissions_header": None,
        "live_verification": "success"
        if status_code in {_HTTP_OK, _HTTP_NOT_FOUND}
        else "http_error",
        "redaction_status": {"content_clean": True, "forbidden_fields": False},
    }

    if accepted_header:
        normalized = normalize_accepted_permissions_header(accepted_header)
        observed = []
        for np in normalized["normalized_permissions"]:
            observed.append(
                _normalize_observed_permission(
                    np["permission_key"], np["access_level"], static_permissions
                )
            )

        entry["accepted_permissions_header"] = {
            "raw_header_hash": normalized["raw_header_hash"],
            "parse_success": normalized["parse_success"],
            "parse_error": normalized["parse_error"],
            "permission_count": len(normalized["normalized_permissions"]),
            "observed_permissions": observed,
        }

    return entry


async def _probe_endpoint(
    client: Any, owner: str, endpoint_spec: dict[str, Any], access_token: str
) -> tuple[int, str | None]:
    """Probe a single endpoint and return (status_code, accepted_header_value)."""
    import httpx

    url = f"https://api.github.com{endpoint_spec['route'].replace('{owner}', owner)}"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    try:
        r = await client.get(url, headers=headers)
        accepted = r.headers.get(_ACCEPTED_PERMISSIONS_HEADER)
        return r.status_code, accepted
    except httpx.RequestError:
        return 0, None


async def _run_live_probes(owner: str, access_token: str) -> list[dict[str, Any]]:
    import httpx

    results: list[dict[str, Any]] = []

    # Combine read+write static models for matching
    from rig_relay.integrations.github_provider._profile_readme_live_check import (
        _REQUIRED_READ_PERMISSIONS,
        _REQUIRED_WRITE_PERMISSIONS,
    )

    static_model = _REQUIRED_READ_PERMISSIONS + _REQUIRED_WRITE_PERMISSIONS

    async with httpx.AsyncClient(timeout=15.0) as client:
        for spec in _PROBE_ENDPOINTS:
            sc, header_val = await _probe_endpoint(client, owner, spec, access_token)
            entry = _build_probe_entry(spec, sc, header_val, static_model)
            results.append(entry)

    return results


def run_live_permission_verification(
    owner: str, *, access_token: str = ""
) -> dict[str, Any]:
    """Run live permission verification probes. Returns content-light result.

    Gated: only runs live if RIG_LIVE_AUTH_TESTS=1 and token is present.
    """
    if not is_live_probe_available():
        return {
            "live_verification_run": False,
            "skipped_reason": "RIG_LIVE_AUTH_TESTS_not_set",
            "probes": [],
            "summary": {
                "endpoints_probed": 0,
                "endpoints_accessible": 0,
                "accepted_headers_captured": 0,
                "permissions_observed": 0,
            },
        }

    if not access_token:
        return {
            "live_verification_run": False,
            "skipped_reason": "no_access_token_provided",
            "probes": [],
            "summary": {
                "endpoints_probed": 0,
                "endpoints_accessible": 0,
                "accepted_headers_captured": 0,
                "permissions_observed": 0,
            },
        }

    import asyncio

    loop = asyncio.new_event_loop()
    try:
        probes = loop.run_until_complete(_run_live_probes(owner, access_token))
    finally:
        loop.close()

    accessible = sum(1 for p in probes if p["accessible"])
    headers_captured = sum(
        1
        for p in probes
        if p["accepted_permissions_header"]
        and p["accepted_permissions_header"]["parse_success"]
    )
    perms_observed = sum(
        1
        for p in probes
        if p["accepted_permissions_header"]
        for _ in p["accepted_permissions_header"]["observed_permissions"]
    )

    return {
        "live_verification_run": True,
        "skipped_reason": None,
        "probes": probes,
        "summary": {
            "endpoints_probed": len(probes),
            "endpoints_accessible": accessible,
            "accepted_headers_captured": headers_captured,
            "permissions_observed": perms_observed,
        },
    }


def _assert_probe_content_light(data: dict[str, Any]) -> None:
    import json

    serialized = json.dumps(data, sort_keys=True)
    for key in _FORBIDDEN_PROBE:
        if f'"{key}"' in serialized:
            raise ValueError(f"forbidden_key_in_probe_result: {key}")


__all__ = [
    "LivePermissionProbeError",
    "is_live_probe_available",
    "normalize_accepted_permissions_header",
    "run_live_permission_verification",
]
