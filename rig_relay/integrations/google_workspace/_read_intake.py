"""Google Workspace read intake — dry-run and live-gated read-only surface collection.

Content-light: only counts, hashes, scope strings, and refusal booleans.
No raw API bodies, no mutation endpoints.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from rig_relay.core.utils.io import read_safe
from rig_relay.integrations.google_workspace._redaction import (
    _FORBIDDEN_OUTPUT_FIELDS,
    _SECRET_PATTERNS,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]

# Google Workspace read-only surfaces
_SURFACES: list[dict[str, Any]] = [
    {
        "surface": "gmail_profile",
        "product": "gmail",
        "capability_id": "google_workspace.gmail.profile.get",
        "required_scopes": ["https://www.googleapis.com/auth/gmail.readonly"],
        "scope_sensitivity": "restricted",
        "endpoint": "https://gmail.googleapis.com/gmail/v1/users/me/profile",
    },
    {
        "surface": "gmail_labels",
        "product": "gmail",
        "capability_id": "google_workspace.gmail.labels.list",
        "required_scopes": ["https://www.googleapis.com/auth/gmail.labels"],
        "scope_sensitivity": "non_sensitive",
        "endpoint": "https://gmail.googleapis.com/gmail/v1/users/me/labels",
    },
    {
        "surface": "calendar_list",
        "product": "calendar",
        "capability_id": "google_workspace.calendar.calendarList.list",
        "required_scopes": ["https://www.googleapis.com/auth/calendar.readonly"],
        "scope_sensitivity": "sensitive",
        "endpoint": "https://www.googleapis.com/calendar/v3/users/me/calendarList",
    },
    {
        "surface": "calendar_events",
        "product": "calendar",
        "capability_id": "google_workspace.calendar.events.readonly",
        "required_scopes": ["https://www.googleapis.com/auth/calendar.events.readonly"],
        "scope_sensitivity": "sensitive",
        "endpoint": "https://www.googleapis.com/calendar/v3/calendars/primary/events",
    },
    {
        "surface": "drive_files",
        "product": "drive",
        "capability_id": "google_workspace.drive.files.list",
        "required_scopes": ["https://www.googleapis.com/auth/drive.metadata.readonly"],
        "scope_sensitivity": "restricted",
        "endpoint": "https://www.googleapis.com/drive/v3/files",
    },
    {
        "surface": "tasklists",
        "product": "tasks",
        "capability_id": "google_workspace.tasks.tasklists.list",
        "required_scopes": ["https://www.googleapis.com/auth/tasks.readonly"],
        "scope_sensitivity": "non_sensitive",
        "endpoint": "https://www.googleapis.com/tasks/v1/users/@me/lists",
    },
    {
        "surface": "contacts",
        "product": "people",
        "capability_id": "google_workspace.contacts.list",
        "required_scopes": ["https://www.googleapis.com/auth/contacts.readonly"],
        "scope_sensitivity": "non_sensitive",
        "endpoint": "https://people.googleapis.com/v1/people/me/connections",
    },
]

_REDACTION_FORBIDDEN_PATTERNS = [
    "access_token",
    "refresh_token",
    "token_prefix",
    "authorization",
    "client_secret",
    "private_key",
    "raw_response",
    "raw_body",
    "email_body",
    "subject",
    "snippet",
    "calendar_description",
    "drive_file_contents",
    "contact_email",
]


class GoogleWorkspaceReadIntakeError(Exception):
    """Raised when read intake collection fails."""


def _now_iso() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat()


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_scope_manifest(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    raw = read_safe(path, raise_on_error=True)
    try:
        data = json.loads(raw.text)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass
    return None


def _check_scope_granted(scope: str, scope_manifest: dict[str, Any] | None) -> bool:
    if scope_manifest is None:
        return False
    scopes = scope_manifest.get("scopes")
    if not isinstance(scopes, list):
        return False
    for s in scopes:
        if isinstance(s, dict) and s.get("scope_id") == scope:
            return s.get("granted", False) is True
    return any(isinstance(s, dict) and s.get("scope_id") == scope for s in scopes)


def _build_surface_intake(
    surface_def: dict[str, Any], *, scope_manifest: dict[str, Any] | None, dry_run: bool
) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "surface": surface_def["surface"],
        "product": surface_def["product"],
        "status": "dry_run_available" if dry_run else "not_implemented",
        "capability_id": surface_def["capability_id"],
        "required_scopes": list(surface_def["required_scopes"]),
        "metadata_count": None,
        "metadata_hashes": [],
        "identity_hash": None,
        "scope_granted": False,
        "evidence_paths": [],
    }

    for scope in surface_def["required_scopes"]:
        if _check_scope_granted(scope, scope_manifest):
            entry["scope_granted"] = True
            break

    sensitivity = surface_def.get("scope_sensitivity", "non_sensitive")
    if sensitivity == "restricted" and dry_run:
        entry["status"] = "refused"
        entry["evidence_paths"].append(
            "docs/json/integrations/google_workspace_contract_v1.v1.json"
        )

    if entry["scope_granted"] and not dry_run:
        entry["status"] = "present"

    return entry


def _build_refusal(surface_def: dict[str, Any], *, reason: str) -> dict[str, Any]:
    return {
        "surface": surface_def["surface"],
        "required_scope": surface_def["required_scopes"][0]
        if surface_def["required_scopes"]
        else "",
        "granted_scope_present": False,
        "status": "refused",
        "remote_mutation": False,
        "refusal_reason": reason,
    }


def _collect_dry_run(
    scope_manifest: dict[str, Any] | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    surfaces: list[dict[str, Any]] = []
    refusals: list[dict[str, Any]] = []

    for surface_def in _SURFACES:
        entry = _build_surface_intake(
            surface_def, scope_manifest=scope_manifest, dry_run=True
        )
        surfaces.append(entry)

        sensitivity = surface_def.get("scope_sensitivity", "non_sensitive")
        if sensitivity == "restricted":
            refusals.append(
                _build_refusal(surface_def, reason="restricted_scope_unverified")
            )
        elif entry["status"] in {"dry_run_available", "not_implemented"}:
            refusals.append(_build_refusal(surface_def, reason="dry_run_no_network"))

    return surfaces, refusals


def _build_scope_grants(scope_manifest: dict[str, Any] | None) -> list[dict[str, Any]]:
    grants: list[dict[str, Any]] = []
    if scope_manifest is None:
        return grants
    scopes = scope_manifest.get("scopes")
    if not isinstance(scopes, list):
        return grants
    for s in scopes:
        if not isinstance(s, dict):
            continue
        grants.append({
            "scope": s.get("scope_id", ""),
            "granted": False,
            "sensitivity": s.get("sensitivity", "unknown"),
        })
    return grants


def _assert_content_light(value: Any) -> None:
    if isinstance(value, dict):
        for key in value:
            if key in _FORBIDDEN_OUTPUT_FIELDS:
                raise ValueError(
                    f"forbidden_key_detected: intake contains forbidden field '{key}'"
                )
            if key in _REDACTION_FORBIDDEN_PATTERNS:
                raise ValueError(
                    f"forbidden_key_detected: intake contains forbidden field '{key}'"
                )
        for item in value.values():
            _assert_content_light(item)
    elif isinstance(value, list):
        for item in value:
            _assert_content_light(item)
    elif isinstance(value, str):
        for pattern in _SECRET_PATTERNS:
            if pattern.search(value):
                raise ValueError(
                    "forbidden_secret_like_string_detected: intake contains secret-like content"
                )


def build_google_workspace_read_intake(
    *,
    dry_run: bool = True,
    live: bool = False,
    scope_manifest_path: Path | None = None,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    if scope_manifest_path is None:
        scope_manifest_path = (
            _REPO_ROOT
            / "docs"
            / "json"
            / "integrations"
            / "google_workspace_scope_manifest_v1.v1.json"
        )

    scope_manifest = _load_scope_manifest(scope_manifest_path)

    if live and not os.environ.get("RIG_LIVE_AUTH_TESTS") == "1":
        live = False
        dry_run = True

    if live:
        surfaces, refusals = _collect_dry_run(scope_manifest)
    else:
        surfaces, refusals = _collect_dry_run(scope_manifest)

    scope_grants = _build_scope_grants(scope_manifest)

    present_count = sum(1 for s in surfaces if s.get("status") == "present")
    refused_count = sum(1 for s in surfaces if s.get("status") == "refused")
    not_implemented_count = sum(
        1
        for s in surfaces
        if s.get("status") in {"not_implemented", "dry_run_available"}
    )

    next_action = "no_action"
    if present_count == 0 and not_implemented_count > 0:
        next_action = "configure_oauth"
    elif present_count == 0 and refused_count > 0:
        next_action = "request_scope"
    elif present_count > 0:
        next_action = "run_live_read_intake"

    report: dict[str, Any] = {
        "schema_version": "rig.google_workspace.read_intake.v1",
        "generated_at": generated_at_utc or _now_iso(),
        "content_light": True,
        "remote_mutation": False,
        "dry_run": dry_run,
        "live": live,
        "surfaces": surfaces,
        "refusals": refusals,
        "scope_grants": scope_grants,
        "evidence_paths": [
            str(scope_manifest_path) if scope_manifest_path.exists() else ""
        ],
        "redaction_status": {
            "content_light": True,
            "forbidden_strings_present": False,
            "redaction_rule_count": len(_REDACTION_FORBIDDEN_PATTERNS),
        },
        "summary": {
            "total_surfaces": len(surfaces),
            "present_surfaces": present_count,
            "refused_surfaces": refused_count,
            "not_implemented_surfaces": not_implemented_count,
            "next_action": next_action,
        },
    }

    _assert_content_light(report)
    return report


def write_google_workspace_read_intake(
    path: Path,
    *,
    dry_run: bool = True,
    live: bool = False,
    scope_manifest_path: Path | None = None,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    report = build_google_workspace_read_intake(
        dry_run=dry_run,
        live=live,
        scope_manifest_path=scope_manifest_path,
        generated_at_utc=generated_at_utc,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return report


__all__ = [
    "GoogleWorkspaceReadIntakeError",
    "build_google_workspace_read_intake",
    "write_google_workspace_read_intake",
]
