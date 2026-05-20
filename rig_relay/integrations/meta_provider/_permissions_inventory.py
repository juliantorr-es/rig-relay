"""Meta permissions inventory - static, no live network calls, refusal-first posture."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import subprocess
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_OUTPUT_JSON = (
    _REPO_ROOT
    / "docs"
    / "json"
    / "governance"
    / "meta_permissions_inventory_v1.v1.json"
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


class MetaPermissionsInventoryError(Exception):
    """Raised when the static permission inventory cannot be built."""


def _now_iso() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat()


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


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


def _build_facebook_pages_permissions() -> list[dict[str, Any]]:
    return [
        {
            "capability_id": "meta.fb_pages.read_metadata",
            "surface": "facebook_pages",
            "operation_kind": "read",
            "required_permission_names": [
                "pages_read_engagement",
                "pages_read_user_content",
            ],
            "app_review_likely_required": True,
            "business_verification_likely_required": True,
            "user_data_risk": "medium",
            "content_light_allowed": True,
            "v1_status": "supported_readonly",
            "refusal_reason": "",
            "requires_doc_verification": True,
            "confidence": "medium",
            "notes": "verify against current Meta developer docs before implementation",
            "future_public_app_posture": "read_only_profile_audit",
        },
        {
            "capability_id": "meta.fb_pages.manage_content",
            "surface": "facebook_pages",
            "operation_kind": "manage",
            "required_permission_names": [
                "pages_manage_posts",
                "pages_manage_metadata",
            ],
            "app_review_likely_required": True,
            "business_verification_likely_required": True,
            "user_data_risk": "high",
            "content_light_allowed": False,
            "v1_status": "refused",
            "refusal_reason": "publishing_and_content_management_refused_in_v1",
            "requires_doc_verification": True,
            "confidence": "medium",
            "notes": "verify against current Meta developer docs before implementation",
            "future_public_app_posture": "requires_app_review_and_business_verification",
        },
        {
            "capability_id": "meta.fb_pages.read_insights",
            "surface": "facebook_pages",
            "operation_kind": "read",
            "required_permission_names": ["pages_read_engagement"],
            "app_review_likely_required": True,
            "business_verification_likely_required": True,
            "user_data_risk": "medium",
            "content_light_allowed": True,
            "v1_status": "deferred",
            "refusal_reason": "deferred_to_future_slice; read_metadata_audit_must_precede",
            "requires_doc_verification": True,
            "confidence": "medium",
            "notes": "verify against current Meta developer docs before implementation",
            "future_public_app_posture": "read_only_insights_audit",
        },
        {
            "capability_id": "meta.fb_pages.publish_post",
            "surface": "facebook_pages",
            "operation_kind": "publish",
            "required_permission_names": [
                "pages_manage_posts",
                "pages_read_user_content",
            ],
            "app_review_likely_required": True,
            "business_verification_likely_required": True,
            "user_data_risk": "high",
            "content_light_allowed": False,
            "v1_status": "refused",
            "refusal_reason": "all_publishing_refused_in_v1",
            "requires_doc_verification": True,
            "confidence": "high",
            "notes": "verify against current Meta developer docs before implementation",
            "future_public_app_posture": "requires_explicit_user_approval_per_action",
        },
    ]


def _build_instagram_graph_permissions() -> list[dict[str, Any]]:
    return [
        {
            "capability_id": "meta.instagram.read_business_metadata",
            "surface": "instagram_graph",
            "operation_kind": "read",
            "required_permission_names": [
                "instagram_basic",
                "instagram_manage_insights",
            ],
            "app_review_likely_required": True,
            "business_verification_likely_required": True,
            "user_data_risk": "medium",
            "content_light_allowed": True,
            "v1_status": "supported_readonly",
            "refusal_reason": "",
            "requires_doc_verification": True,
            "confidence": "medium",
            "notes": "verify against current Meta developer docs before implementation",
            "future_public_app_posture": "read_only_profile_audit",
        },
        {
            "capability_id": "meta.instagram.read_media_metadata",
            "surface": "instagram_graph",
            "operation_kind": "read",
            "required_permission_names": [
                "instagram_basic",
                "instagram_content_publish",
            ],
            "app_review_likely_required": True,
            "business_verification_likely_required": True,
            "user_data_risk": "high",
            "content_light_allowed": True,
            "v1_status": "deferred",
            "refusal_reason": "deferred_to_future_slice; media_content_has_privacy_risk",
            "requires_doc_verification": True,
            "confidence": "medium",
            "notes": "verify against current Meta developer docs before implementation",
            "future_public_app_posture": "read_only_audit_with_redaction",
        },
        {
            "capability_id": "meta.instagram.publish_media",
            "surface": "instagram_graph",
            "operation_kind": "publish",
            "required_permission_names": [
                "instagram_content_publish",
                "instagram_manage_comments",
            ],
            "app_review_likely_required": True,
            "business_verification_likely_required": True,
            "user_data_risk": "high",
            "content_light_allowed": False,
            "v1_status": "refused",
            "refusal_reason": "all_publishing_refused_in_v1",
            "requires_doc_verification": True,
            "confidence": "high",
            "notes": "verify against current Meta developer docs before implementation",
            "future_public_app_posture": "requires_explicit_user_approval_per_action",
        },
        {
            "capability_id": "meta.instagram.comment_moderation",
            "surface": "instagram_graph",
            "operation_kind": "manage",
            "required_permission_names": ["instagram_manage_comments"],
            "app_review_likely_required": True,
            "business_verification_likely_required": True,
            "user_data_risk": "high",
            "content_light_allowed": False,
            "v1_status": "refused",
            "refusal_reason": "comment_reply_automation_refused_in_v1",
            "requires_doc_verification": True,
            "confidence": "medium",
            "notes": "verify against current Meta developer docs before implementation",
            "future_public_app_posture": "requires_explicit_user_approval_per_action",
        },
    ]


def _build_whatsapp_business_permissions() -> list[dict[str, Any]]:
    return [
        {
            "capability_id": "meta.whatsapp.read_business_metadata",
            "surface": "whatsapp_business_cloud",
            "operation_kind": "read",
            "required_permission_names": ["whatsapp_business_management"],
            "app_review_likely_required": True,
            "business_verification_likely_required": True,
            "user_data_risk": "medium",
            "content_light_allowed": True,
            "v1_status": "supported_readonly",
            "refusal_reason": "",
            "requires_doc_verification": True,
            "confidence": "medium",
            "notes": "verify against current Meta developer docs before implementation",
            "future_public_app_posture": "read_only_account_audit",
        },
        {
            "capability_id": "meta.whatsapp.webhook_receive",
            "surface": "whatsapp_business_cloud",
            "operation_kind": "webhook_receive",
            "required_permission_names": ["whatsapp_business_messaging"],
            "app_review_likely_required": True,
            "business_verification_likely_required": True,
            "user_data_risk": "restricted",
            "content_light_allowed": False,
            "v1_status": "refused",
            "refusal_reason": "webhook_receive_refused_in_v1; requires_app_review_and_security_audit",
            "requires_doc_verification": True,
            "confidence": "high",
            "notes": "verify against current Meta developer docs before implementation",
            "future_public_app_posture": "requires_app_review_business_verification_and_webhook_security",
        },
        {
            "capability_id": "meta.whatsapp.send_message",
            "surface": "whatsapp_business_cloud",
            "operation_kind": "message_send",
            "required_permission_names": ["whatsapp_business_messaging"],
            "app_review_likely_required": True,
            "business_verification_likely_required": True,
            "user_data_risk": "restricted",
            "content_light_allowed": False,
            "v1_status": "refused",
            "refusal_reason": "all_messaging_refused_in_v1; never_automate_message_sends",
            "requires_doc_verification": True,
            "confidence": "high",
            "notes": "verify against current Meta developer docs before implementation",
            "future_public_app_posture": "never_automated_without_explicit_user_approval",
        },
        {
            "capability_id": "meta.whatsapp.manage_templates",
            "surface": "whatsapp_business_cloud",
            "operation_kind": "manage",
            "required_permission_names": ["whatsapp_business_management"],
            "app_review_likely_required": True,
            "business_verification_likely_required": True,
            "user_data_risk": "restricted",
            "content_light_allowed": False,
            "v1_status": "refused",
            "refusal_reason": "template_management_refused_in_v1",
            "requires_doc_verification": True,
            "confidence": "high",
            "notes": "verify against current Meta developer docs before implementation",
            "future_public_app_posture": "requires_app_review_and_explicit_user_approval",
        },
    ]


def _build_webhook_permissions() -> list[dict[str, Any]]:
    return [
        {
            "capability_id": "meta.webhooks.verify_token",
            "surface": "webhooks",
            "operation_kind": "admin",
            "required_permission_names": [],
            "app_review_likely_required": False,
            "business_verification_likely_required": False,
            "user_data_risk": "low",
            "content_light_allowed": True,
            "v1_status": "supported_readonly",
            "refusal_reason": "",
            "requires_doc_verification": True,
            "confidence": "high",
            "notes": "verify against current Meta developer docs before implementation",
            "future_public_app_posture": "config_audit_only",
        },
        {
            "capability_id": "meta.webhooks.signature_validation",
            "surface": "webhooks",
            "operation_kind": "admin",
            "required_permission_names": [],
            "app_review_likely_required": False,
            "business_verification_likely_required": False,
            "user_data_risk": "low",
            "content_light_allowed": True,
            "v1_status": "supported_readonly",
            "refusal_reason": "",
            "requires_doc_verification": True,
            "confidence": "high",
            "notes": "verify against current Meta developer docs before implementation",
            "future_public_app_posture": "security_packet_only",
        },
        {
            "capability_id": "meta.webhooks.replay_protection",
            "surface": "webhooks",
            "operation_kind": "admin",
            "required_permission_names": [],
            "app_review_likely_required": False,
            "business_verification_likely_required": False,
            "user_data_risk": "low",
            "content_light_allowed": True,
            "v1_status": "deferred",
            "refusal_reason": "deferred_to_future_slice",
            "requires_doc_verification": True,
            "confidence": "high",
            "notes": "verify against current Meta developer docs before implementation",
            "future_public_app_posture": "security_packet_only",
        },
        {
            "capability_id": "meta.webhooks.raw_payload_quarantine",
            "surface": "webhooks",
            "operation_kind": "webhook_receive",
            "required_permission_names": [],
            "app_review_likely_required": True,
            "business_verification_likely_required": True,
            "user_data_risk": "restricted",
            "content_light_allowed": False,
            "v1_status": "refused",
            "refusal_reason": "raw_webhook_payload_ingestion_refused_in_v1",
            "requires_doc_verification": True,
            "confidence": "high",
            "notes": "verify against current Meta developer docs before implementation",
            "future_public_app_posture": "requires_app_review_and_payload_quarantine_design",
        },
    ]


def _build_publishing_surface_permissions() -> list[dict[str, Any]]:
    return [
        {
            "capability_id": "meta.publishing.post_to_feed",
            "surface": "publishing_surfaces",
            "operation_kind": "publish",
            "required_permission_names": [
                "pages_manage_posts",
                "instagram_content_publish",
            ],
            "app_review_likely_required": True,
            "business_verification_likely_required": True,
            "user_data_risk": "high",
            "content_light_allowed": False,
            "v1_status": "refused",
            "refusal_reason": "all_publishing_refused_in_v1",
            "requires_doc_verification": True,
            "confidence": "high",
            "notes": "verify against current Meta developer docs before implementation",
            "future_public_app_posture": "requires_explicit_user_approval_per_action",
        },
        {
            "capability_id": "meta.publishing.comment_reply",
            "surface": "publishing_surfaces",
            "operation_kind": "publish",
            "required_permission_names": [
                "pages_manage_posts",
                "instagram_manage_comments",
            ],
            "app_review_likely_required": True,
            "business_verification_likely_required": True,
            "user_data_risk": "restricted",
            "content_light_allowed": False,
            "v1_status": "refused",
            "refusal_reason": "comment_reply_automation_refused_in_v1",
            "requires_doc_verification": True,
            "confidence": "high",
            "notes": "verify against current Meta developer docs before implementation",
            "future_public_app_posture": "requires_explicit_user_approval_per_action",
        },
        {
            "capability_id": "meta.publishing.direct_message",
            "surface": "publishing_surfaces",
            "operation_kind": "message_send",
            "required_permission_names": [
                "pages_messaging",
                "instagram_manage_messages",
            ],
            "app_review_likely_required": True,
            "business_verification_likely_required": True,
            "user_data_risk": "restricted",
            "content_light_allowed": False,
            "v1_status": "refused",
            "refusal_reason": "all_messaging_refused_in_v1",
            "requires_doc_verification": True,
            "confidence": "high",
            "notes": "verify against current Meta developer docs before implementation",
            "future_public_app_posture": "never_automated_without_explicit_user_approval",
        },
    ]


def _ast_surfaces() -> list[dict[str, Any]]:
    return [
        {
            "surface_name": "Facebook Pages Graph",
            "capabilities": _build_facebook_pages_permissions(),
        },
        {
            "surface_name": "Instagram Graph",
            "capabilities": _build_instagram_graph_permissions(),
        },
        {
            "surface_name": "WhatsApp Business Cloud",
            "capabilities": _build_whatsapp_business_permissions(),
        },
        {"surface_name": "Webhooks", "capabilities": _build_webhook_permissions()},
        {
            "surface_name": "Publishing Surfaces",
            "capabilities": _build_publishing_surface_permissions(),
        },
    ]


def _count_by_status(capabilities: list[dict[str, Any]], status: str) -> int:
    return sum(1 for c in capabilities if c.get("v1_status") == status)


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


def build_meta_permissions_inventory(
    *,
    generated_at: str | None = None,
    branch: str | None = None,
    head: str | None = None,
) -> dict[str, Any]:
    surfaces = _ast_surfaces()
    all_capabilities: list[dict[str, Any]] = []
    for surface in surfaces:
        all_capabilities.extend(surface["capabilities"])

    total = len(all_capabilities)
    refused = _count_by_status(all_capabilities, "refused")
    deferred = _count_by_status(all_capabilities, "deferred")
    supported_readonly = _count_by_status(all_capabilities, "supported_readonly")
    high_risk = sum(
        1 for c in all_capabilities if c.get("user_data_risk") in {"high", "restricted"}
    )
    app_review = sum(1 for c in all_capabilities if c.get("app_review_likely_required"))
    biz_verify = sum(
        1 for c in all_capabilities if c.get("business_verification_likely_required")
    )

    report: dict[str, Any] = {
        "schema_version": "rig.meta.permissions_inventory.v1",
        "generated_at": generated_at or _now_iso(),
        "branch": branch,
        "head": head,
        "content_light": True,
        "remote_mutation": False,
        "live_network": False,
        "surfaces": surfaces,
        "capability_count": total,
        "refused_count": refused,
        "deferred_count": deferred,
        "evidence_paths": [],
        "remaining_seams": [
            "all permission names require verification against current Meta developer docs",
            "exact app review requirements per capability need Meta App Dashboard confirmation",
            "WhatsApp Business Cloud webhook receive and message send permanently refused in v1",
            "publishing and messaging automation permanently refused in v1",
        ],
        "redaction_status": {
            "content_light": True,
            "forbidden_strings_present": False,
            "redaction_rule_count": len(_FORBIDDEN_FIELDS),
        },
        "summary": {
            "total_capabilities": total,
            "supported_readonly_count": supported_readonly,
            "refused_count": refused,
            "deferred_count": deferred,
            "high_risk_count": high_risk,
            "app_review_likely_count": app_review,
            "business_verification_likely_count": biz_verify,
        },
    }
    _assert_content_light(report)
    return report


def build_meta_permissions_inventory_from_paths(
    *, generated_at: str | None = None, repo_root: Path = _REPO_ROOT
) -> dict[str, Any]:
    branch, head = _load_git_metadata(repo_root)
    return build_meta_permissions_inventory(
        generated_at=generated_at, branch=branch, head=head
    )


def write_meta_permissions_inventory(
    path: Path | str = _DEFAULT_OUTPUT_JSON,
    *,
    generated_at: str | None = None,
    repo_root: Path = _REPO_ROOT,
) -> dict[str, Any]:
    report = build_meta_permissions_inventory_from_paths(
        generated_at=generated_at, repo_root=repo_root
    )
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return report


__all__ = [
    "MetaPermissionsInventoryError",
    "build_meta_permissions_inventory",
    "build_meta_permissions_inventory_from_paths",
    "write_meta_permissions_inventory",
]
