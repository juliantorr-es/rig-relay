"""Meta provider operating picture - local, deterministic, content-light."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_PERMISSIONS_INVENTORY_JSON = (
    _REPO_ROOT
    / "docs"
    / "json"
    / "governance"
    / "meta_permissions_inventory_v1.v1.json"
)
_DEFAULT_SURFACE_AUDIT_JSON = (
    _REPO_ROOT / "docs" / "json" / "governance" / "meta_surface_audit_v1.v1.json"
)
_DEFAULT_OUTPUT_JSON = (
    _REPO_ROOT / "docs" / "json" / "governance" / "meta_operating_picture_v1.v1.json"
)

_ENV_VARS = (
    "RIG_META_APP_ID",
    "RIG_META_APP_SECRET",
    "RIG_META_ACCESS_TOKEN",
    "RIG_META_PAGE_ID",
    "RIG_META_INSTAGRAM_BUSINESS_ACCOUNT_ID",
    "RIG_META_WHATSAPP_BUSINESS_ACCOUNT_ID",
    "RIG_META_WHATSAPP_PHONE_NUMBER_ID",
    "RIG_META_VERIFY_TOKEN",
)

_FORBIDDEN_FIELDS = frozenset({
    "access_token",
    "app_secret",
    "client_secret",
    "verify_token",
    "authorization",
    "bearer",
    "phone_number",
    "email",
    "raw_response",
    "raw_body",
    "webhook_payload",
    "message_text",
    "comment_text",
    "dm_text",
    "media_url",
    "image_url",
    "video_url",
    "post_caption",
})

_FORBIDDEN_VALUE_PATTERNS = (re.compile(r"EAA[A-Za-z0-9]+"),)


class MetaOperatingPictureError(Exception):
    """Raised when Meta provider artifacts cannot be combined into an operating picture."""


def _now_iso() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat()


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _env_bool(name: str) -> bool:
    return bool(os.getenv(name))


def _load_git_metadata(repo_root: Path) -> tuple[str | None, str | None]:
    try:
        branch = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        return branch or None, head or None
    except (OSError, subprocess.CalledProcessError):
        return None, None


def _check_configured() -> dict[str, bool]:
    return {
        "app_id_configured": _env_bool("RIG_META_APP_ID"),
        "app_secret_configured": _env_bool("RIG_META_APP_SECRET"),
        "access_token_configured": _env_bool("RIG_META_ACCESS_TOKEN"),
        "page_id_configured": _env_bool("RIG_META_PAGE_ID"),
        "instagram_business_account_id_configured": _env_bool(
            "RIG_META_INSTAGRAM_BUSINESS_ACCOUNT_ID"
        ),
        "whatsapp_business_account_id_configured": _env_bool(
            "RIG_META_WHATSAPP_BUSINESS_ACCOUNT_ID"
        ),
        "whatsapp_phone_number_id_configured": _env_bool(
            "RIG_META_WHATSAPP_PHONE_NUMBER_ID"
        ),
        "webhook_verify_token_configured": _env_bool("RIG_META_VERIFY_TOKEN"),
    }


def _infer_surface_statuses(config: dict[str, bool]) -> dict[str, str]:
    has_token = config["access_token_configured"]
    return {
        "facebook_pages": "configured"
        if has_token and config["page_id_configured"]
        else (
            "unconfigured"
            if not config["app_id_configured"] and not has_token
            else "refused"
        ),
        "instagram_graph": "configured"
        if has_token and config["instagram_business_account_id_configured"]
        else (
            "unconfigured"
            if not config["app_id_configured"] and not has_token
            else "refused"
        ),
        "whatsapp_business_cloud": "configured"
        if has_token
        and (
            config["whatsapp_business_account_id_configured"]
            or config["whatsapp_phone_number_id_configured"]
        )
        else (
            "unconfigured"
            if not config["app_id_configured"] and not has_token
            else "refused"
        ),
        "webhooks": "configured"
        if config["webhook_verify_token_configured"]
        else ("unconfigured" if not config["app_id_configured"] else "refused"),
        "publishing": "refused",
        "messaging": "refused",
        "comments_replies": "refused",
    }


def _infer_config_health(config: dict[str, bool]) -> str:
    configured = sum(1 for v in config.values() if v)
    if configured == 0:
        return "unconfigured"
    if configured == len(config):
        return "fully_configured"
    return "partial"


_STRUCTURAL_REFUSED = frozenset({"refused", "not_implemented"})


def _surface_health(surfaces: dict[str, str]) -> str:
    states = set(surfaces.values())
    if states == {"unconfigured"}:
        return "all_unconfigured"
    non_structural = {k: v for k, v in surfaces.items() if v not in _STRUCTURAL_REFUSED}
    non_structural_states = set(non_structural.values())
    if non_structural_states == {"unconfigured"}:
        return "all_unconfigured"
    if "configured" in states:
        return "partial"
    return "all_refused_or_not_implemented"


def _assert_content_light(value: Any) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key in _FORBIDDEN_FIELDS:
                raise ValueError(f"forbidden_key_detected: field '{key}'")
            _assert_content_light(item)
    elif isinstance(value, list):
        for item in value:
            _assert_content_light(item)
    elif isinstance(value, str):
        for pattern in _FORBIDDEN_VALUE_PATTERNS:
            if pattern.search(value):
                raise ValueError(
                    f"forbidden_content_detected: contains '{pattern.pattern}'"
                )


def build_meta_operating_picture(
    *,
    generated_at: str | None = None,
    branch: str | None = None,
    head: str | None = None,
    permissions_inventory_path: Path | str | None = None,
    surface_audit_path: Path | str | None = None,
) -> dict[str, Any]:
    config = _check_configured()
    surfaces = _infer_surface_statuses(config)
    has_any_config = any(config.values())

    evidence: list[str] = []
    if permissions_inventory_path:
        p = Path(permissions_inventory_path)
        if p.exists():
            evidence.append(str(p))
    if surface_audit_path:
        p = Path(surface_audit_path)
        if p.exists():
            evidence.append(str(p))

    report: dict[str, Any] = {
        "schema_version": "rig.meta.operating_picture.v1",
        "generated_at": generated_at or _now_iso(),
        "branch": branch,
        "head": head,
        "content_light": True,
        "remote_mutation": False,
        "live_network": False,
        "configured_summary": config,
        "surface_summary": surfaces,
        "safety_posture": {
            "public_release_ready": False,
            "app_review_required": True,
            "business_verification_required": True,
            "webhook_security_required": True,
            "user_content_ingestion_allowed": False,
            "publishing_allowed": False,
            "messaging_allowed": False,
        },
        "next_recommended_action": [],
        "evidence_paths": evidence,
        "remaining_seams": [
            "Facebook Pages Graph API — read-only metadata profile audit not built; only env presence checked",
            "Instagram Graph API — read-only profile audit not built; business account linkage unverified",
            "WhatsApp Business Cloud — webhook receive and message send refused in v1; phone number and template management not audited",
            "Webhook subscription — refused until app review and business verification completed",
            "Publishing surfaces — all publishing, comment, and reply automation refused in v1",
            "Messaging surfaces — WhatsApp/Instagram messaging refused; requires app review, webhook security, and user consent",
            "App review preflight — packet planned but no review submission built",
            "Business verification — required for public app access; no verification flow built",
        ],
        "redaction_status": {
            "content_light": True,
            "forbidden_strings_present": False,
            "redaction_rule_count": len(_FORBIDDEN_FIELDS),
            "checked_artifact_count": len(evidence),
        },
    }

    actions: list[str] = []
    if has_any_config:
        actions.append("build_permissions_inventory")
    else:
        actions.append("no_action")
    actions.append("build_surface_audit")
    action_set: list[str] = []
    for action in actions:
        if action not in action_set:
            action_set.append(action)
    report["next_recommended_action"] = action_set

    report["summary"] = {
        "config_health": _infer_config_health(config),
        "surface_health": _surface_health(surfaces),
        "safety_health": "refusal_first",
        "next_action": action_set[0],
    }

    _assert_content_light(report)
    return report


def build_meta_operating_picture_from_paths(
    *,
    generated_at: str | None = None,
    repo_root: Path = _REPO_ROOT,
    permissions_inventory_path: Path | str | None = None,
    surface_audit_path: Path | str | None = None,
) -> dict[str, Any]:
    actual_permissions = (
        permissions_inventory_path or _DEFAULT_PERMISSIONS_INVENTORY_JSON
    )
    actual_audit = surface_audit_path or _DEFAULT_SURFACE_AUDIT_JSON
    branch, head = _load_git_metadata(repo_root)
    return build_meta_operating_picture(
        generated_at=generated_at,
        branch=branch,
        head=head,
        permissions_inventory_path=actual_permissions,
        surface_audit_path=actual_audit,
    )


def write_meta_operating_picture(
    path: Path | str = _DEFAULT_OUTPUT_JSON,
    *,
    generated_at: str | None = None,
    repo_root: Path = _REPO_ROOT,
    permissions_inventory_path: Path | str | None = None,
    surface_audit_path: Path | str | None = None,
) -> dict[str, Any]:
    report = build_meta_operating_picture_from_paths(
        generated_at=generated_at,
        repo_root=repo_root,
        permissions_inventory_path=permissions_inventory_path,
        surface_audit_path=surface_audit_path,
    )
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return report


__all__ = [
    "MetaOperatingPictureError",
    "build_meta_operating_picture",
    "build_meta_operating_picture_from_paths",
    "write_meta_operating_picture",
]
