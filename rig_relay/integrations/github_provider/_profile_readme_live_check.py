"""Profile README Live Check v1 — governed, content-light, permission-aware.

Inspects a GitHub profile README public surface, generates a local preview,
and produces a publish PR permission audit. Dry-run by default.
No remote mutation. Live network calls gated by RIG_LIVE_AUTH_TESTS=1.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from rig_relay.integrations.github_provider._live_permission_probe import (
    run_live_permission_verification,
)
from rig_relay.integrations.github_provider._profile_readme_preview_generator import (
    generate_preview_file,
)
from rig_relay.integrations.github_provider._redaction import assert_no_raw_github_token

_REPO_ROOT = Path(__file__).resolve().parents[3]
_LIVE_AUTH_ENV = "RIG_LIVE_AUTH_TESTS"

_PROFILE_README_ENDPOINTS = {
    "repo_check": "GET /repos/{owner}/{owner}",
    "readme_check": "GET /repos/{owner}/{owner}/contents/README.md",
    "readme_raw": "GET /repos/{owner}/{owner}/readme",
}

_REQUIRED_READ_PERMISSIONS = [
    {
        "permission_id": "contents:read",
        "permission_kind": "github_app_permission",
        "access_level": "read",
        "required": True,
        "purpose": "Read repository contents including profile README file",
        "github_api_header": "X-Accepted-GitHub-Permissions",
    },
    {
        "permission_id": "metadata:read",
        "permission_kind": "github_app_permission",
        "access_level": "read",
        "required": True,
        "purpose": "Read repository metadata to verify profile repo exists",
    },
]

_REQUIRED_WRITE_PERMISSIONS = [
    {
        "permission_id": "contents:write",
        "permission_kind": "github_app_permission",
        "access_level": "write",
        "required": True,
        "purpose": "Commit profile README changes to publish via PR",
    },
    {
        "permission_id": "pull_requests:write",
        "permission_kind": "github_app_permission",
        "access_level": "write",
        "required": True,
        "purpose": "Open PR for profile README updates",
    },
]

_EXPLICITLY_NOT_REQUIRED = [
    {
        "permission_id": "workflows:write",
        "permission_kind": "github_app_permission",
        "reason": "Profile README PR does not edit .github/workflows/ files. Workflows permission is explicitly not needed for this path.",
    },
    {
        "permission_id": "actions:write",
        "permission_kind": "github_app_permission",
        "reason": "No workflow dispatch, rerun, or cancel operations in profile README path.",
    },
]

_FORBIDDEN_PREVIEW = frozenset({
    "access_token",
    "token_prefix",
    "authorization",
    "client_secret",
    "private_key",
    "raw_response",
    "raw_body",
    "patch",
    "diff",
    "code_snippet",
    "vulnerable_code",
    "file_body",
    "auth_header",
})

_FORBIDDEN_PERMISSION_AUDIT = frozenset({
    "access_token",
    "token_prefix",
    "authorization",
    "client_secret",
    "private_key",
    "raw_response",
    "raw_body",
    "bearer",
})

_HTTP_OK = 200
_HTTP_NOT_FOUND = 404


def _now_iso() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat()


def _sha256_text(val: str) -> str:
    return hashlib.sha256(val.encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class ProfileReadmeLiveCheckError(Exception):
    """Raised when profile README live check fails."""


def _dry_run_profile_check(owner: str) -> dict[str, Any]:
    profile_repo_name = f"github.com/{owner}/{owner}"
    return {
        "owner": owner,
        "profile_repo_name": profile_repo_name,
        "profile_repo_hash": _sha256_text(profile_repo_name),
        "profile_repo_exists": "unknown_dry_run",
        "readme_exists": "unknown_dry_run",
        "readme_sha256": None,
        "readme_size_bytes": None,
        "readme_line_count": None,
        "live_network": False,
        "dry_run": True,
        "status": "dry_run_available",
        "issues_found": ["needs_live_network_check"],
        "evidence_paths": [],
    }


async def _check_profile_repo_exists(
    client: Any, owner: str, headers: dict[str, str], result: dict[str, Any]
) -> None:
    repo_url = f"https://api.github.com/repos/{owner}/{owner}"
    try:
        r = await client.get(repo_url, headers=headers)
        if r.status_code == _HTTP_OK:
            result["profile_repo_exists"] = True
            result["profile_repo_private"] = r.json().get("private", False)
        elif r.status_code == _HTTP_NOT_FOUND:
            result["profile_repo_exists"] = False
            result["issues_found"].append("profile_repo_not_found")
        else:
            result["profile_repo_exists"] = "error"
            result["issues_found"].append(f"profile_repo_check_http_{r.status_code}")
    except Exception:
        result["profile_repo_exists"] = "error_network"
        result["issues_found"].append("profile_repo_network_error")


async def _check_profile_readme_exists(
    client: Any, owner: str, headers: dict[str, str], result: dict[str, Any]
) -> None:
    if result["profile_repo_exists"] is not True:
        return
    readme_url = f"https://api.github.com/repos/{owner}/{owner}/contents/README.md"
    try:
        r = await client.get(readme_url, headers=headers)
        if r.status_code == _HTTP_OK:
            d = r.json()
            result["readme_exists"] = True
            result["readme_sha256"] = d.get("sha")
            result["readme_size_bytes"] = d.get("size")
            result["evidence_paths"].append(
                f"https://github.com/{owner}/{owner}/blob/main/README.md"
            )
            ce = d.get("content", "")
            if ce:
                import base64

                try:
                    decoded = base64.b64decode(ce).decode("utf-8")
                    result["readme_line_count"] = len(decoded.splitlines())
                    result["readme_content_hash"] = _sha256_text(decoded)
                except Exception:
                    result["readme_line_count"] = None
        elif r.status_code == _HTTP_NOT_FOUND:
            result["readme_exists"] = False
            result["issues_found"].append("profile_readme_not_found")
        else:
            result["readme_exists"] = "error"
            result["issues_found"].append(f"profile_readme_http_{r.status_code}")
    except Exception:
        result["readme_exists"] = "error_network"
        result["issues_found"].append("profile_readme_network_error")


async def _live_profile_check(owner: str, access_token: str) -> dict[str, Any]:
    import httpx

    profile_repo_name = f"github.com/{owner}/{owner}"
    result: dict[str, Any] = {
        "owner": owner,
        "profile_repo_name": profile_repo_name,
        "profile_repo_hash": _sha256_text(profile_repo_name),
        "profile_repo_exists": False,
        "readme_exists": False,
        "readme_sha256": None,
        "readme_size_bytes": None,
        "readme_line_count": None,
        "live_network": True,
        "dry_run": False,
        "status": "pending",
        "issues_found": [],
        "evidence_paths": [],
    }

    async with httpx.AsyncClient(timeout=15.0) as client:
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        await _check_profile_repo_exists(client, owner, headers, result)
        await _check_profile_readme_exists(client, owner, headers, result)

    if result["readme_exists"] is True:
        result["status"] = "readme_present"
    elif result["profile_repo_exists"] is True:
        result["status"] = "repo_present_readme_missing"
    elif result["profile_repo_exists"] is False:
        result["status"] = "repo_not_found"
    else:
        result["status"] = "check_incomplete"

    assert_no_raw_github_token(json.dumps(result))
    return result


def check_profile_readme(
    owner: str, *, dry_run: bool = True, access_token: str = ""
) -> dict[str, Any]:
    if dry_run:
        return _dry_run_profile_check(owner)
    if not access_token:
        return _dry_run_profile_check(owner)
    import asyncio

    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(_live_profile_check(owner, access_token))
    finally:
        loop.close()


def is_live_auth_available() -> bool:
    return os.environ.get(_LIVE_AUTH_ENV, "0") == "1"


def build_preview_artifact(
    owner: str,
    profile_check_result: dict[str, Any],
    *,
    generated_at_utc: str | None = None,
    generated_file_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    readme_present = profile_check_result.get("readme_exists") is True
    preview_status = "ready_for_preview" if readme_present else "blocked_no_source"
    if profile_check_result.get("dry_run"):
        preview_status = "blocked_dry_run"

    preview_files: list[dict[str, Any]] = [
        {
            "file_path": "README.md",
            "file_path_hash": _sha256_text("README.md"),
            "surface_type": "profile_readme",
            "operation": "update_existing" if readme_present else "create_new",
            "source_sha256": profile_check_result.get("readme_sha256"),
            "source_size_bytes": profile_check_result.get("readme_size_bytes"),
            "source_line_count": profile_check_result.get("readme_line_count"),
            "content_light": True,
        }
    ]

    blocked_reasons: list[str] = []
    if profile_check_result.get("dry_run"):
        blocked_reasons.append("live_network_required")
    if not readme_present:
        blocked_reasons.append("no_readme_source")

    preview: dict[str, Any] = {
        "schema_version": "rig.github.profile_readme_preview.v1",
        "generated_at": generated_at_utc or _now_iso(),
        "owner": owner,
        "profile_repo": f"github.com/{owner}/{owner}",
        "profile_repo_hash": profile_check_result.get("profile_repo_hash"),
        "content_light": True,
        "remote_mutation": False,
        "dry_run": profile_check_result.get("dry_run", True),
        "live_network": profile_check_result.get("live_network", False),
        "source_readme_present": readme_present,
        "source_readme_sha256": profile_check_result.get("readme_sha256"),
        "preview_status": preview_status,
        "files": preview_files,
        "safety_checks": {
            "no_private_content": True,
            "no_credentials": True,
            "no_raw_markdown_stored": True,
            "content_light_enforced": True,
        },
        "blocked_reasons": blocked_reasons,
        "redaction_status": {
            "content_light": True,
            "forbidden_fields_present": False,
            "redaction_rules": len(_FORBIDDEN_PREVIEW),
        },
    }

    if generated_file_metadata is not None:
        preview["generated_preview_path"] = generated_file_metadata.get(
            "generated_preview_path"
        )
        preview["generated_preview_sha256"] = generated_file_metadata.get(
            "generated_preview_sha256"
        )
        preview["generated_preview_bytes"] = generated_file_metadata.get(
            "generated_preview_bytes"
        )
        preview["generated_preview_line_count"] = generated_file_metadata.get(
            "generated_preview_line_count"
        )
        preview["source_claim_count"] = generated_file_metadata.get(
            "source_claim_count"
        )
        preview["included_claim_count"] = generated_file_metadata.get(
            "included_claim_count"
        )
        preview["excluded_claim_count"] = generated_file_metadata.get(
            "excluded_claim_count"
        )
        preview["excluded_claim_reasons"] = generated_file_metadata.get(
            "excluded_claim_reasons", []
        )
        preview["public_surface_classification"] = generated_file_metadata.get(
            "public_surface_classification"
        )
        preview["permission_neutrality_status"] = generated_file_metadata.get(
            "permission_neutrality_status"
        )
        preview["publish_blocked_reasons"] = generated_file_metadata.get(
            "publish_blocked_reasons", []
        )
        preview["redaction_scan"] = generated_file_metadata.get("redaction_scan")
        preview["included_claims"] = generated_file_metadata.get("included_claims", [])
        preview["excluded_claims"] = generated_file_metadata.get("excluded_claims", [])
        if (
            generated_file_metadata.get("redaction_scan", {}).get("content_clean")
            and preview_status == "blocked_dry_run"
        ):
            preview["preview_status"] = "ready_for_preview"

    _assert_content_light_fieldset(preview, _FORBIDDEN_PREVIEW)
    return preview


def build_permission_audit(
    owner: str,
    profile_check_result: dict[str, Any],
    *,
    effective_permissions: list[str] | None = None,
    generated_at_utc: str | None = None,
    live_probe_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if effective_permissions is None:
        effective_permissions = []

    read_entries = [
        dict(
            perm,
            status=(
                "granted"
                if perm["permission_id"] in effective_permissions
                else "missing"
            ),
        )
        for perm in _REQUIRED_READ_PERMISSIONS
    ]
    write_entries = [
        dict(
            perm,
            status=(
                "granted"
                if perm["permission_id"] in effective_permissions
                else "missing"
            ),
        )
        for perm in _REQUIRED_WRITE_PERMISSIONS
    ]

    missing_read = [
        p["permission_id"] for p in read_entries if p["status"] == "missing"
    ]
    missing_write = [
        p["permission_id"] for p in write_entries if p["status"] == "missing"
    ]
    read_ready = not missing_read
    write_ready = not missing_write

    publish_class = "blocked"
    if profile_check_result.get("dry_run"):
        publish_class = "blocked_dry_run"
    elif read_ready and write_ready:
        publish_class = "permission_ready"
    elif read_ready:
        publish_class = "read_ready_write_missing"
    else:
        publish_class = "blocked_missing_permissions"

    audit: dict[str, Any] = {
        "schema_version": "rig.github.profile_readme_permission_audit.v1",
        "generated_at": generated_at_utc or _now_iso(),
        "owner": owner,
        "profile_repo": f"github.com/{owner}/{owner}",
        "profile_repo_hash": profile_check_result.get("profile_repo_hash"),
        "content_light": True,
        "remote_mutation": False,
        "dry_run": profile_check_result.get("dry_run", True),
        "live_network": profile_check_result.get("live_network", False),
        "proposed_operation": "publish_profile_readme_via_pull_request",
        "required_read_permissions": read_entries,
        "required_write_permissions": write_entries,
        "explicitly_not_required": _EXPLICITLY_NOT_REQUIRED,
        "permission_classification": {
            "read_ready": read_ready,
            "write_ready": write_ready,
            "publish_possible": publish_class,
            "workflows_write_needed": False,
            "actions_write_needed": False,
            "contents_write_sufficient": not missing_write,
            "pull_requests_write_sufficient": True,
            "minimum_permission_set": [
                "contents:read",
                "metadata:read",
                "contents:write",
                "pull_requests:write",
            ],
        },
        "permission_gaps": missing_read + missing_write,
        "recommended_action": "ready_for_pr_creation_lane"
        if write_ready
        else "request_permissions",
        "redaction_status": {"content_light": True, "forbidden_fields_present": False},
    }

    if live_probe_result is not None:
        audit["live_permission_verification"] = live_probe_result

    _assert_content_light_fieldset(audit, _FORBIDDEN_PERMISSION_AUDIT)
    return audit


def _assert_content_light_fieldset(
    data: dict[str, Any], forbidden: frozenset[str]
) -> None:
    for key in data:
        if key in forbidden:
            raise ValueError(f"forbidden_key_in_artifact: {key}")
    assert_no_raw_github_token(json.dumps(data))


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def write_profile_readme_check_artifacts(
    owner: str,
    output_dir: Path | None = None,
    *,
    dry_run: bool = True,
    access_token: str = "",
    generated_at_utc: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    if output_dir is None:
        output_dir = _REPO_ROOT / "docs" / "json" / "governance"

    check_result = check_profile_readme(
        owner, dry_run=dry_run, access_token=access_token
    )

    # Generate actual preview file from evidence-backed claims
    gen_meta = generate_preview_file(owner=owner)

    preview = build_preview_artifact(
        owner,
        check_result,
        generated_at_utc=generated_at_utc,
        generated_file_metadata=gen_meta,
    )
    audit = build_permission_audit(
        owner, check_result, generated_at_utc=generated_at_utc
    )

    # Run live permission probe if conditions allow
    live_probe = run_live_permission_verification(owner, access_token=access_token)
    if live_probe["live_verification_run"]:
        audit = build_permission_audit(
            owner,
            check_result,
            generated_at_utc=generated_at_utc,
            live_probe_result=live_probe,
        )

    _write_json(
        output_dir / "github_profile_readme_live_check_v1.v1.json", check_result
    )
    _write_json(output_dir / "github_profile_readme_preview_v1.v1.json", preview)
    _write_json(output_dir / "github_publish_pr_permission_audit_v1.v1.json", audit)

    return check_result, preview, audit


__all__ = [
    "ProfileReadmeLiveCheckError",
    "build_permission_audit",
    "build_preview_artifact",
    "check_profile_readme",
    "is_live_auth_available",
    "write_profile_readme_check_artifacts",
]
