"""Meta surface audit - proposal packet planner, no live API calls, refusal-first."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import subprocess
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_OUTPUT_JSON = (
    _REPO_ROOT / "docs" / "json" / "governance" / "meta_surface_audit_v1.v1.json"
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


class MetaSurfaceAuditError(Exception):
    """Raised when surface audit packets cannot be built."""


def _now_iso() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat()


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _packet_id(seed: str) -> str:
    return "meta-surface-audit:" + _sha256_text(seed)[:12]


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


def _build_audit_packets() -> list[dict[str, Any]]:
    return [
        {
            "packet_id": _packet_id("facebook_page_profile_audit_packet"),
            "surface": "facebook_pages",
            "proposed_future_action": "Build a read-only Facebook Page profile audit that reads public metadata only, no publishing, no content ingestion.",
            "current_status": "blocked_by_app_review",
            "required_config_refs": [
                "RIG_META_APP_ID",
                "RIG_META_ACCESS_TOKEN",
                "RIG_META_PAGE_ID",
            ],
            "required_permission_refs": ["meta.fb_pages.read_metadata"],
            "blocked_by": [
                "app_review_required",
                "business_verification_required",
                "permissions_inventory_must_precede",
            ],
            "user_data_risk": "medium",
            "remote_mutation": False,
            "content_light": True,
            "public_release_relevance": "low",
            "safety_notes": "Read-only profile audit only. Never ingest post content or user comments. Use SHA256 for identifiers. Reject raw page content in evidence.",
        },
        {
            "packet_id": _packet_id("instagram_profile_surface_audit_packet"),
            "surface": "instagram_graph",
            "proposed_future_action": "Build a read-only Instagram business account profile audit. Read business metadata only; no media content ingestion, no publishing.",
            "current_status": "blocked_by_app_review",
            "required_config_refs": [
                "RIG_META_APP_ID",
                "RIG_META_ACCESS_TOKEN",
                "RIG_META_INSTAGRAM_BUSINESS_ACCOUNT_ID",
            ],
            "required_permission_refs": ["meta.instagram.read_business_metadata"],
            "blocked_by": [
                "app_review_required",
                "business_verification_required",
                "instagram_business_account_linkage_unverified",
                "permissions_inventory_must_precede",
            ],
            "user_data_risk": "medium",
            "remote_mutation": False,
            "content_light": True,
            "public_release_relevance": "low",
            "safety_notes": "Read-only business account metadata. Never ingest media URLs, captions, or comments.",
        },
        {
            "packet_id": _packet_id("instagram_content_calendar_packet"),
            "surface": "instagram_graph",
            "proposed_future_action": "Design a content-light content calendar planner that reads media scheduling metadata without ingesting raw media, captions, or comments.",
            "current_status": "deferred",
            "required_config_refs": [
                "RIG_META_APP_ID",
                "RIG_META_ACCESS_TOKEN",
                "RIG_META_INSTAGRAM_BUSINESS_ACCOUNT_ID",
            ],
            "required_permission_refs": ["meta.instagram.read_media_metadata"],
            "blocked_by": [
                "permissions_inventory_must_precede",
                "surface_audit_profile_audit_must_precede",
            ],
            "user_data_risk": "high",
            "remote_mutation": False,
            "content_light": True,
            "public_release_relevance": "low",
            "safety_notes": "Content-light only; never ingest raw media, captions, or engagement data. Use content hashes.",
        },
        {
            "packet_id": _packet_id("whatsapp_business_setup_packet"),
            "surface": "whatsapp_business_cloud",
            "proposed_future_action": "Build a read-only WhatsApp Business account setup audit. Verify business account and phone number configuration without webhook registration or message sending.",
            "current_status": "blocked_by_app_review",
            "required_config_refs": [
                "RIG_META_APP_ID",
                "RIG_META_ACCESS_TOKEN",
                "RIG_META_WHATSAPP_BUSINESS_ACCOUNT_ID",
                "RIG_META_WHATSAPP_PHONE_NUMBER_ID",
            ],
            "required_permission_refs": ["meta.whatsapp.read_business_metadata"],
            "blocked_by": [
                "app_review_required",
                "business_verification_required",
                "permissions_inventory_must_precede",
            ],
            "user_data_risk": "restricted",
            "remote_mutation": False,
            "content_light": True,
            "public_release_relevance": "low",
            "safety_notes": "Read-only account audit. Never register webhooks or send messages. Never store phone numbers raw.",
        },
        {
            "packet_id": _packet_id("webhook_security_packet"),
            "surface": "webhooks",
            "proposed_future_action": "Design a webhook security posture: verify token validation logic, app secret proof signing, replay protection, and raw payload quarantine before any webhook receive.",
            "current_status": "deferred",
            "required_config_refs": ["RIG_META_APP_SECRET", "RIG_META_VERIFY_TOKEN"],
            "required_permission_refs": [
                "meta.webhooks.verify_token",
                "meta.webhooks.signature_validation",
            ],
            "blocked_by": [
                "permissions_inventory_must_precede",
                "app_review_required",
                "business_verification_required",
            ],
            "user_data_risk": "restricted",
            "remote_mutation": False,
            "content_light": True,
            "public_release_relevance": "low",
            "safety_notes": "Security design only. Never register live webhooks. Never process raw webhook payloads in evidence. Quarantine raw payloads.",
        },
        {
            "packet_id": _packet_id("app_review_preflight_packet"),
            "surface": "app_review",
            "proposed_future_action": "Build an app review preflight checklist: audit required permissions, prepare app review submission materials, and verify business verification status.",
            "current_status": "blocked_by_app_review",
            "required_config_refs": ["RIG_META_APP_ID", "RIG_META_APP_SECRET"],
            "required_permission_refs": [],
            "blocked_by": [
                "permissions_inventory_must_precede",
                "business_verification_must_precede",
            ],
            "user_data_risk": "low",
            "remote_mutation": False,
            "content_light": True,
            "public_release_relevance": "low",
            "safety_notes": "Preflight checklist only. Never submit app review automatically. Never submit without explicit user approval.",
        },
        {
            "packet_id": _packet_id("business_verification_packet"),
            "surface": "business_verification",
            "proposed_future_action": "Build a business verification readiness audit: check verification requirements, document needed materials, verify no automated submission.",
            "current_status": "blocked_by_business_verification",
            "required_config_refs": ["RIG_META_APP_ID"],
            "required_permission_refs": [],
            "blocked_by": [
                "business_verification_required",
                "explicit_user_approval_required",
            ],
            "user_data_risk": "low",
            "remote_mutation": False,
            "content_light": True,
            "public_release_relevance": "low",
            "safety_notes": "Readiness audit only. Never submit business verification automatically. Never collect or store identity documents.",
        },
        {
            "packet_id": _packet_id("publishing_refusal_packet"),
            "surface": "publishing_surfaces",
            "proposed_future_action": "Document the permanent v1 refusal of all publishing automation (posts, comments, replies). This refusal is structural, not temporary.",
            "current_status": "refused",
            "required_config_refs": [],
            "required_permission_refs": [
                "meta.publishing.post_to_feed",
                "meta.publishing.comment_reply",
            ],
            "blocked_by": ["publishing_automation_permanently_refused_in_v1"],
            "user_data_risk": "restricted",
            "remote_mutation": False,
            "content_light": True,
            "public_release_relevance": "low",
            "safety_notes": "All publishing automation refused in v1. This refusal is structural. Requires explicit user approval per future action.",
        },
        {
            "packet_id": _packet_id("messaging_refusal_packet"),
            "surface": "messaging_surfaces",
            "proposed_future_action": "Document the permanent v1 refusal of all messaging automation (WhatsApp sends, Instagram DMs). This refusal is structural, not temporary.",
            "current_status": "refused",
            "required_config_refs": [],
            "required_permission_refs": [
                "meta.whatsapp.send_message",
                "meta.publishing.direct_message",
            ],
            "blocked_by": ["messaging_automation_permanently_refused_in_v1"],
            "user_data_risk": "restricted",
            "remote_mutation": False,
            "content_light": True,
            "public_release_relevance": "low",
            "safety_notes": "All messaging automation refused in v1. This refusal is structural. Never automate message sends. Never ingest DMs.",
        },
    ]


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


def _count_by_status(packets: list[dict[str, Any]], status: str) -> int:
    return sum(1 for p in packets if p.get("current_status") == status)


def build_meta_surface_audit(
    *,
    generated_at: str | None = None,
    branch: str | None = None,
    head: str | None = None,
) -> dict[str, Any]:
    packets = _build_audit_packets()
    total = len(packets)
    refused = _count_by_status(packets, "refused")
    deferred = _count_by_status(packets, "deferred")
    blocked = _count_by_status(packets, "blocked_by_app_review") + _count_by_status(
        packets, "blocked_by_business_verification"
    )

    report: dict[str, Any] = {
        "schema_version": "rig.meta.surface_audit.v1",
        "generated_at": generated_at or _now_iso(),
        "branch": branch,
        "head": head,
        "content_light": True,
        "remote_mutation": False,
        "live_network": False,
        "packets": packets,
        "packet_count": total,
        "refused_packet_count": refused,
        "evidence_paths": [],
        "remaining_seams": [
            "all packets are proposal-only; no live implementation built",
            "packet IDs are deterministic from content seeds for reproducibility",
            "publishing_refusal_packet and messaging_refusal_packet are permanent structural refusals",
            "webhook_security_packet requires app review and business verification before activation",
            "app_review_preflight_packet requires explicit user approval before any submission",
            "business_verification_packet requires explicit user approval before any action",
        ],
        "redaction_status": {
            "content_light": True,
            "forbidden_strings_present": False,
            "redaction_rule_count": len(_FORBIDDEN_FIELDS),
        },
        "summary": {
            "total_packets": total,
            "refused_packets": refused,
            "deferred_packets": deferred,
            "blocked_packets": blocked,
        },
    }
    _assert_content_light(report)
    return report


def build_meta_surface_audit_from_paths(
    *, generated_at: str | None = None, repo_root: Path = _REPO_ROOT
) -> dict[str, Any]:
    branch, head = _load_git_metadata(repo_root)
    return build_meta_surface_audit(generated_at=generated_at, branch=branch, head=head)


def write_meta_surface_audit(
    path: Path | str = _DEFAULT_OUTPUT_JSON,
    *,
    generated_at: str | None = None,
    repo_root: Path = _REPO_ROOT,
) -> dict[str, Any]:
    report = build_meta_surface_audit_from_paths(
        generated_at=generated_at, repo_root=repo_root
    )
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return report


__all__ = [
    "MetaSurfaceAuditError",
    "build_meta_surface_audit",
    "build_meta_surface_audit_from_paths",
    "write_meta_surface_audit",
]
