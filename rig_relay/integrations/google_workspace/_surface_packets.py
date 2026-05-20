"""Google Workspace surface packets — future work/proposal planning without writes.

Reads operating picture and read intake artifacts to produce deterministic,
content-light work packets for future Google Workspace integration slices.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from rig_relay.core.utils.io import read_safe
from rig_relay.integrations.google_workspace._redaction import (
    _FORBIDDEN_OUTPUT_FIELDS,
    _SECRET_PATTERNS,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_OP_PICTURE_JSON = (
    _REPO_ROOT
    / "docs"
    / "json"
    / "governance"
    / "google_workspace_operating_picture_v1.v1.json"
)
_DEFAULT_READ_INTAKE_JSON = (
    _REPO_ROOT
    / "docs"
    / "json"
    / "governance"
    / "google_workspace_read_intake_v1.v1.json"
)
_DEFAULT_OUTPUT_JSON = (
    _REPO_ROOT
    / "docs"
    / "json"
    / "governance"
    / "google_workspace_surface_packets_v1.v1.json"
)

_PACKET_TEMPLATES: list[dict[str, Any]] = [
    {
        "packet_id": "gw-oauth-setup",
        "packet_type": "oauth_setup_packet",
        "source_surface": "oauth",
        "status": "ready",
        "recommended_local_action": "Configure OAuth consent screen and client credentials",
        "required_scope_refs": [
            "openid",
            "https://www.googleapis.com/auth/userinfo.email",
            "https://www.googleapis.com/auth/userinfo.profile",
        ],
        "blocked_by": [],
        "public_release_relevance": "required",
    },
    {
        "packet_id": "gw-scope-gmail-metadata",
        "packet_type": "scope_request_packet",
        "source_surface": "gmail_metadata",
        "status": "blocked",
        "recommended_local_action": "Request gmail.labels scope for label metadata read",
        "required_scope_refs": ["https://www.googleapis.com/auth/gmail.labels"],
        "blocked_by": ["oauth_unconfigured", "restricted_scope_verification"],
        "public_release_relevance": "optional",
    },
    {
        "packet_id": "gw-scope-calendar-readonly",
        "packet_type": "scope_request_packet",
        "source_surface": "calendar_list",
        "status": "ready",
        "recommended_local_action": "Request calendar.readonly scope for calendar list metadata",
        "required_scope_refs": ["https://www.googleapis.com/auth/calendar.readonly"],
        "blocked_by": ["oauth_unconfigured"],
        "public_release_relevance": "optional",
    },
    {
        "packet_id": "gw-scope-drive-metadata",
        "packet_type": "scope_request_packet",
        "source_surface": "drive_metadata",
        "status": "blocked",
        "recommended_local_action": "Request drive.metadata.readonly scope; restricted scope assessment needed",
        "required_scope_refs": [
            "https://www.googleapis.com/auth/drive.metadata.readonly"
        ],
        "blocked_by": ["oauth_unconfigured", "restricted_scope_verification"],
        "public_release_relevance": "deferred",
    },
    {
        "packet_id": "gw-verification-required",
        "packet_type": "verification_required_packet",
        "source_surface": "oauth_verification",
        "status": "blocked",
        "recommended_local_action": "Complete Google OAuth verification for restricted scopes",
        "required_scope_refs": [],
        "blocked_by": [
            "restricted_scopes_present",
            "security_assessment_required",
            "annual_recertification_required",
        ],
        "public_release_relevance": "required",
    },
    {
        "packet_id": "gw-gmail-metadata-read",
        "packet_type": "gmail_metadata_packet",
        "source_surface": "gmail_metadata",
        "status": "ready",
        "recommended_local_action": "Enable Gmail label metadata reading after scope grant",
        "required_scope_refs": ["https://www.googleapis.com/auth/gmail.labels"],
        "blocked_by": ["scope_not_granted"],
        "public_release_relevance": "optional",
    },
    {
        "packet_id": "gw-calendar-metadata-read",
        "packet_type": "calendar_metadata_packet",
        "source_surface": "calendar_list",
        "status": "ready",
        "recommended_local_action": "Enable Calendar list and event metadata reading after scope grant",
        "required_scope_refs": [
            "https://www.googleapis.com/auth/calendar.readonly",
            "https://www.googleapis.com/auth/calendar.events.readonly",
        ],
        "blocked_by": ["scope_not_granted"],
        "public_release_relevance": "optional",
    },
    {
        "packet_id": "gw-drive-metadata-read",
        "packet_type": "drive_metadata_packet",
        "source_surface": "drive_metadata",
        "status": "blocked",
        "recommended_local_action": "Enable Drive file metadata reading; no file content ingestion in v1",
        "required_scope_refs": [
            "https://www.googleapis.com/auth/drive.metadata.readonly"
        ],
        "blocked_by": [
            "scope_not_granted",
            "restricted_scope_verification",
            "no_file_content_ingestion",
        ],
        "public_release_relevance": "deferred",
    },
    {
        "packet_id": "gw-tasks-metadata-read",
        "packet_type": "tasks_metadata_packet",
        "source_surface": "tasks_readonly",
        "status": "ready",
        "recommended_local_action": "Enable Tasks list reading after scope grant",
        "required_scope_refs": ["https://www.googleapis.com/auth/tasks.readonly"],
        "blocked_by": ["scope_not_granted"],
        "public_release_relevance": "optional",
    },
    {
        "packet_id": "gw-contacts-metadata-read",
        "packet_type": "contacts_metadata_packet",
        "source_surface": "contacts_people_readonly",
        "status": "ready",
        "recommended_local_action": "Enable Contacts/People reading after scope grant; hash all PII",
        "required_scope_refs": ["https://www.googleapis.com/auth/contacts.readonly"],
        "blocked_by": ["scope_not_granted", "pii_redaction_required"],
        "public_release_relevance": "deferred",
    },
    {
        "packet_id": "gw-dwd-deferred",
        "packet_type": "domain_wide_delegation_deferred_packet",
        "source_surface": "admin_directory",
        "status": "deferred",
        "recommended_local_action": "Defer domain-wide delegation to future lane; requires super admin authorization",
        "required_scope_refs": [],
        "blocked_by": [
            "super_admin_authorization_required",
            "domain_wide_delegation_deferred_in_v1",
        ],
        "public_release_relevance": "deferred",
    },
    {
        "packet_id": "gw-scope-profile-split",
        "packet_type": "public_scope_profile_split_packet",
        "source_surface": "oauth_scopes",
        "status": "blocked",
        "recommended_local_action": "Split public scope profiles: internal dev (broad) vs public release (narrow, non-restricted)",
        "required_scope_refs": [],
        "blocked_by": [
            "current_broad_local_dev_posture",
            "restricted_scopes_must_be_removed_for_public",
        ],
        "public_release_relevance": "required",
    },
]


class GoogleWorkspaceSurfacePacketError(Exception):
    """Raised when surface packet projection fails."""


def _now_iso() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat()


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_json_artifact(path: Path) -> dict[str, Any] | None:
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


def _resolve_packet_status(
    packet: dict[str, Any],
    op_picture: dict[str, Any] | None,
    read_intake: dict[str, Any] | None,
) -> dict[str, Any]:
    result = dict(packet)

    if op_picture is None:
        result["status"] = "blocked"
        result["blocked_by"] = list(
            set(result.get("blocked_by", []) + ["operating_picture_missing"])
        )
        return result

    auth_summary = op_picture.get("auth_summary")
    if isinstance(auth_summary, dict):
        if auth_summary.get("oauth_configured") or auth_summary.get(
            "token_hash_present"
        ):
            blocked = result.get("blocked_by", [])
            if "oauth_unconfigured" in blocked:
                new_blocked = [b for b in blocked if b != "oauth_unconfigured"]
                result["blocked_by"] = new_blocked

    if not result.get("blocked_by"):
        result["status"] = "ready"

    return result


def _assert_content_light(value: Any) -> None:
    if isinstance(value, dict):
        for key in value:
            if key in _FORBIDDEN_OUTPUT_FIELDS:
                raise ValueError(
                    f"forbidden_key_detected: surface packets contain forbidden field '{key}'"
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
                    "forbidden_secret_like_string_detected: surface packets contain secret-like content"
                )


def project_google_workspace_surface_packets(
    *,
    operating_picture: dict[str, Any] | None = None,
    read_intake: dict[str, Any] | None = None,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    if operating_picture is None:
        operating_picture = _load_json_artifact(_DEFAULT_OP_PICTURE_JSON)
    if read_intake is None:
        read_intake = _load_json_artifact(_DEFAULT_READ_INTAKE_JSON)

    source_artifacts: list[dict[str, Any]] = []
    if _DEFAULT_OP_PICTURE_JSON.exists():
        source_artifacts.append({
            "artifact_id": "operating_picture",
            "path": str(_DEFAULT_OP_PICTURE_JSON),
            "present": True,
            "artifact_hash": _sha256_file(_DEFAULT_OP_PICTURE_JSON),
        })
    else:
        source_artifacts.append({
            "artifact_id": "operating_picture",
            "path": str(_DEFAULT_OP_PICTURE_JSON),
            "present": False,
            "artifact_hash": None,
        })

    if _DEFAULT_READ_INTAKE_JSON.exists():
        source_artifacts.append({
            "artifact_id": "read_intake",
            "path": str(_DEFAULT_READ_INTAKE_JSON),
            "present": True,
            "artifact_hash": _sha256_file(_DEFAULT_READ_INTAKE_JSON),
        })
    else:
        source_artifacts.append({
            "artifact_id": "read_intake",
            "path": str(_DEFAULT_READ_INTAKE_JSON),
            "present": False,
            "artifact_hash": None,
        })

    packets = [
        _resolve_packet_status(template, operating_picture, read_intake)
        for template in _PACKET_TEMPLATES
    ]

    for packet in packets:
        packet["remote_mutation"] = False
        packet["content_light"] = True
        packet.setdefault("evidence_refs", [])
        if operating_picture is not None:
            packet["evidence_refs"].append(
                "docs/json/governance/google_workspace_operating_picture_v1.v1.json"
            )

    ready_count = sum(1 for p in packets if p.get("status") == "ready")
    blocked_count = sum(1 for p in packets if p.get("status") == "blocked")
    deferred_count = sum(1 for p in packets if p.get("status") == "deferred")

    report: dict[str, Any] = {
        "schema_version": "rig.google_workspace.surface_packets.v1",
        "generated_at": generated_at_utc or _now_iso(),
        "content_light": True,
        "remote_mutation": False,
        "source_artifacts": source_artifacts,
        "packets": packets,
        "packet_count": len(packets),
        "redaction_status": {
            "content_light": True,
            "forbidden_strings_present": False,
            "redaction_rule_count": len(_FORBIDDEN_OUTPUT_FIELDS),
        },
        "summary": {
            "total_packets": len(packets),
            "ready_packets": ready_count,
            "blocked_packets": blocked_count,
            "deferred_packets": deferred_count,
            "next_action": "configure_oauth"
            if ready_count == 0
            else "run_live_read_intake",
        },
    }

    _assert_content_light(report)
    return report


def project_google_workspace_surface_packets_from_paths(
    *,
    operating_picture_path: Path | None = None,
    read_intake_path: Path | None = None,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    op_picture = (
        _load_json_artifact(operating_picture_path) if operating_picture_path else None
    )
    intake = _load_json_artifact(read_intake_path) if read_intake_path else None
    return project_google_workspace_surface_packets(
        operating_picture=op_picture,
        read_intake=intake,
        generated_at_utc=generated_at_utc,
    )


def write_google_workspace_surface_packets(
    path: Path = _DEFAULT_OUTPUT_JSON,
    *,
    operating_picture_path: Path | None = None,
    read_intake_path: Path | None = None,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    report = project_google_workspace_surface_packets_from_paths(
        operating_picture_path=operating_picture_path,
        read_intake_path=read_intake_path,
        generated_at_utc=generated_at_utc,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return report


__all__ = [
    "GoogleWorkspaceSurfacePacketError",
    "project_google_workspace_surface_packets",
    "project_google_workspace_surface_packets_from_paths",
    "write_google_workspace_surface_packets",
]
