"""Unified Security Queue v1 — governed, content-light, multi-surface.

Normalizes code scanning, Dependabot, secret scanning, security advisories,
and security policy gaps into one schema-governed remediation-planning substrate.
Dry-run/local-only by default. No remediation, no remote mutation.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from rig_relay.core.utils.io import read_safe

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_INTAKE = (
    _REPO_ROOT
    / "docs"
    / "json"
    / "governance"
    / "github_security_intake_result.v1.json"
)
_DEFAULT_WORK_ITEMS = (
    _REPO_ROOT
    / "docs"
    / "json"
    / "governance"
    / "github_security_work_items_v1.v1.json"
)
_DEFAULT_OUTPUT = (
    _REPO_ROOT / "docs" / "json" / "governance" / "github_security_queue_v1.v1.json"
)

_SOURCE_SURFACES = [
    "code_scanning",
    "dependabot",
    "secret_scanning",
    "repository_security_advisory",
    "security_policy_gap",
]

_SEVERITY_ORDER = {
    "critical": 0,
    "high": 1,
    "medium": 2,
    "moderate": 2,
    "low": 3,
    "info": 4,
    "note": 4,
    "unknown": 5,
}

_SURFACE_PERMISSIONS: dict[str, dict[str, list[str]]] = {
    "code_scanning": {
        "read": ["security_events:read", "metadata:read"],
        "remediation": [
            "security_events:write",
            "contents:write",
            "pull_requests:write",
        ],
    },
    "dependabot": {
        "read": ["dependabot_alerts:read", "metadata:read"],
        "remediation": [
            "dependabot_alerts:write",
            "contents:write",
            "pull_requests:write",
        ],
    },
    "secret_scanning": {
        "read": ["security_events:read", "metadata:read"],
        "remediation": ["contents:write", "pull_requests:write"],
    },
    "repository_security_advisory": {
        "read": ["security_events:read", "metadata:read"],
        "remediation": ["security_events:write"],
    },
    "security_policy_gap": {
        "read": ["metadata:read"],
        "remediation": ["contents:write", "pull_requests:write"],
    },
}

_FORBIDDEN_QUEUE = frozenset({
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
    "bearer",
    "secret_value",
    "raw_secret",
    "raw_alert_body",
})


class SecurityQueueError(Exception):
    """Raised when security queue building fails."""


def _sha256_text(val: str) -> str:
    return hashlib.sha256(val.encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _now_iso() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat()


def _load_json(path: Path) -> dict[str, Any] | None:
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


def _calculate_priority(
    severity: str,
    state: str,
    confidence: str = "medium",
    permission_available: bool = True,
    remediation_ready: bool = False,
) -> tuple[int, str]:
    """Deterministic priority: lower number = higher priority."""
    reasons: list[str] = []

    sev_weight = _SEVERITY_ORDER.get(severity, 4)
    reasons.append(f"severity={severity}:w{sev_weight}")

    score = sev_weight

    # Open alerts are higher priority
    if state == "open":
        reasons.append("state=open")
    elif state in {"fixed", "dismissed"}:
        reasons.append("state=resolved")
        score += 3

    # Unknown confidence deprioritizes
    if confidence not in {"high", "medium"}:
        score += 1
        reasons.append(f"confidence={confidence}")

    # Permission gaps block remediation, increase priority to fix
    if not permission_available:
        reasons.append("permission_unavailable")
        score = max(score - 1, 0)  # boost priority to address permission gap

    # Remediation-ready items are actionable now
    if remediation_ready:
        reasons.append("remediation_ready")

    return score, ";".join(reasons)


def _normalize_code_scanning_to_queue_item(
    alert: dict[str, Any], index: int
) -> dict[str, Any]:
    sev = alert.get("rule_severity", alert.get("severity", "unknown"))
    state = alert.get("state", "unknown")
    priority_score, priority_reason = _calculate_priority(sev, state)

    return {
        "queue_item_id": _sha256_text(
            f"cs:{alert.get('alert_number', index)}:{alert.get('rule_id_hash', '')}"
        ),
        "source_surface": "code_scanning",
        "source_kind": "alert",
        "alert_number": alert.get("alert_number"),
        "severity": sev,
        "state": state,
        "security_domain": "code_vulnerability",
        "rule_id_hash": alert.get("rule_id_hash"),
        "file_path_hash": alert.get("file_path_hash"),
        "suggested_group_kind": alert.get(
            "suggested_group_kind", "unknown_triage_needed"
        ),
        "public_or_private_surface": "repository_surface",
        "remediation_lane": alert.get("suggested_group_kind", "unknown_triage_needed"),
        "required_permissions": _SURFACE_PERMISSIONS["code_scanning"]["read"],
        "remediation_permissions": _SURFACE_PERMISSIONS["code_scanning"]["remediation"],
        "mutation_required": False,
        "remote_mutation_status": "disabled",
        "local_mutation_status": "not_attempted",
        "content_light": True,
        "redaction_status": {"clean": True},
        "priority_score": priority_score,
        "priority_reason": priority_reason,
        "blocked_reasons": [],
        "recommended_next_action": "inspect_in_intake_viewer",
    }


def _normalize_dependabot_to_queue_item(
    alert: dict[str, Any], index: int
) -> dict[str, Any]:
    sev = alert.get("severity", "unknown")
    state = alert.get("state", "unknown")
    priority_score, priority_reason = _calculate_priority(sev, state)

    return {
        "queue_item_id": _sha256_text(
            f"db:{alert.get('alert_number', index)}:{alert.get('package_ecosystem', '')}"
        ),
        "source_surface": "dependabot",
        "source_kind": "alert",
        "alert_number": alert.get("alert_number"),
        "severity": sev,
        "state": state,
        "security_domain": "dependency_vulnerability",
        "package_ecosystem": alert.get("package_ecosystem"),
        "package_name_hash": alert.get("package_name_hash"),
        "ghsa_id_hash": alert.get("ghsa_id_hash"),
        "fixed_version_available": alert.get("fixed_version_available", False),
        "public_or_private_surface": "repository_surface",
        "remediation_lane": "dependency_update_needed",
        "required_permissions": _SURFACE_PERMISSIONS["dependabot"]["read"],
        "remediation_permissions": _SURFACE_PERMISSIONS["dependabot"]["remediation"],
        "mutation_required": False,
        "remote_mutation_status": "disabled",
        "local_mutation_status": "not_attempted",
        "content_light": True,
        "redaction_status": {"clean": True},
        "priority_score": priority_score,
        "priority_reason": priority_reason,
        "blocked_reasons": [],
        "recommended_next_action": "review_dependency_update",
    }


def _normalize_secret_scanning_to_queue_item(
    refusal: dict[str, Any], index: int
) -> dict[str, Any]:
    return {
        "queue_item_id": _sha256_text(f"ss:refusal:{index}"),
        "source_surface": "secret_scanning",
        "source_kind": "refusal",
        "severity": "unknown",
        "state": "refused",
        "security_domain": "credential_leak",
        "secret_type": "unknown_refused",
        "public_or_private_surface": "repository_surface",
        "remediation_lane": "permission_required",
        "required_permissions": _SURFACE_PERMISSIONS["secret_scanning"]["read"],
        "remediation_permissions": _SURFACE_PERMISSIONS["secret_scanning"][
            "remediation"
        ],
        "mutation_required": False,
        "remote_mutation_status": "disabled",
        "local_mutation_status": "not_attempted",
        "content_light": True,
        "redaction_status": {"clean": True},
        "priority_score": 3,
        "priority_reason": "severity=unknown:w4;permission_unavailable",
        "blocked_reasons": ["source_surface_refused"],
        "recommended_next_action": "request_secret_scanning_permission",
    }


def _normalize_advisory_to_queue_item(
    advisory: dict[str, Any] | None, index: int
) -> dict[str, Any]:
    if advisory is not None:
        sev = advisory.get("severity", "unknown")
        state = advisory.get("state", "unknown")
        priority_score, priority_reason = _calculate_priority(sev, state)
        return {
            "queue_item_id": _sha256_text(
                f"sa:{advisory.get('ghsa_id', advisory.get('advisory_number', index))}"
            ),
            "source_surface": "repository_security_advisory",
            "source_kind": "advisory",
            "severity": sev,
            "state": state,
            "security_domain": "vulnerability_disclosure",
            "public_or_private_surface": "repository_surface",
            "remediation_lane": "advisory_triage",
            "required_permissions": _SURFACE_PERMISSIONS[
                "repository_security_advisory"
            ]["read"],
            "remediation_permissions": _SURFACE_PERMISSIONS[
                "repository_security_advisory"
            ]["remediation"],
            "mutation_required": False,
            "remote_mutation_status": "disabled",
            "local_mutation_status": "not_attempted",
            "content_light": True,
            "redaction_status": {"clean": True},
            "priority_score": priority_score,
            "priority_reason": priority_reason,
            "blocked_reasons": [],
            "recommended_next_action": "review_advisory",
        }

    return {
        "queue_item_id": _sha256_text(f"sa:missing:{index}"),
        "source_surface": "repository_security_advisory",
        "source_kind": "not_available",
        "severity": "unknown",
        "state": "not_available",
        "security_domain": "vulnerability_disclosure",
        "remediation_lane": "permission_required",
        "required_permissions": _SURFACE_PERMISSIONS["repository_security_advisory"][
            "read"
        ],
        "remediation_permissions": [],
        "mutation_required": False,
        "remote_mutation_status": "disabled",
        "local_mutation_status": "not_attempted",
        "content_light": True,
        "redaction_status": {"clean": True},
        "priority_score": 4,
        "priority_reason": "severity=unknown:w4;source_unavailable",
        "blocked_reasons": ["source_artifact_missing"],
        "recommended_next_action": "enable_advisory_access",
    }


def _normalize_policy_gap_to_queue_item() -> dict[str, Any]:
    return {
        "queue_item_id": _sha256_text("spg:policy_gap"),
        "source_surface": "security_policy_gap",
        "source_kind": "not_available",
        "severity": "medium",
        "state": "not_available",
        "security_domain": "security_policy",
        "remediation_lane": "policy_documentation",
        "required_permissions": _SURFACE_PERMISSIONS["security_policy_gap"]["read"],
        "remediation_permissions": _SURFACE_PERMISSIONS["security_policy_gap"][
            "remediation"
        ],
        "mutation_required": False,
        "remote_mutation_status": "disabled",
        "local_mutation_status": "not_attempted",
        "content_light": True,
        "redaction_status": {"clean": True},
        "priority_score": 2,
        "priority_reason": "severity=medium:w2;permission_unavailable",
        "blocked_reasons": ["source_artifact_missing"],
        "recommended_next_action": "audit_security_policy_gap",
    }


def build_security_queue(
    *,
    intake_path: Path = _DEFAULT_INTAKE,
    work_items_path: Path = _DEFAULT_WORK_ITEMS,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    intake = _load_json(intake_path)
    work_items = _load_json(work_items_path)

    source_artifacts: list[dict[str, Any]] = [
        {
            "path": str(intake_path),
            "present": intake is not None,
            "source_surface": "security_intake",
        },
        {
            "path": str(work_items_path),
            "present": work_items is not None,
            "source_surface": "security_work_items",
        },
    ]

    queue_items: list[dict[str, Any]] = []
    input_surfaces: list[dict[str, Any]] = []

    # Process code scanning alerts
    cs_alerts = intake.get("alerts", {}).get("code_scanning", []) if intake else []
    cs_surface_status = "collected" if cs_alerts else "not_available"
    if intake:
        cs_source = next(
            (
                s
                for s in intake.get("source_surfaces", [])
                if isinstance(s, dict) and s.get("surface") == "code_scanning"
            ),
            {},
        )
        cs_surface_status = (
            cs_source.get("status", "not_available") if cs_source else cs_surface_status
        )

    for i, alert in enumerate(cs_alerts):
        if isinstance(alert, dict):
            queue_items.append(_normalize_code_scanning_to_queue_item(alert, i))

    input_surfaces.append({
        "surface": "code_scanning",
        "status": cs_surface_status,
        "item_count": len([
            qi for qi in queue_items if qi["source_surface"] == "code_scanning"
        ]),
        "live_fetch_status": "not_attempted"
        if cs_surface_status != "collected"
        else "completed",
        "blocked_reason": None
        if cs_surface_status == "collected"
        else "source_artifact_missing_or_dry_run",
    })

    # Process Dependabot alerts
    db_alerts = intake.get("alerts", {}).get("dependabot", []) if intake else []
    db_surface_status = "collected" if db_alerts else "not_available"
    if intake:
        db_source = next(
            (
                s
                for s in intake.get("source_surfaces", [])
                if isinstance(s, dict) and s.get("surface") == "dependabot"
            ),
            {},
        )
        db_surface_status = (
            db_source.get("status", "not_available") if db_source else db_surface_status
        )

    for i, alert in enumerate(db_alerts):
        if isinstance(alert, dict):
            queue_items.append(_normalize_dependabot_to_queue_item(alert, i))

    input_surfaces.append({
        "surface": "dependabot",
        "status": db_surface_status,
        "item_count": len([
            qi for qi in queue_items if qi["source_surface"] == "dependabot"
        ]),
        "live_fetch_status": "not_attempted"
        if db_surface_status != "collected"
        else "completed",
        "blocked_reason": None
        if db_surface_status == "collected"
        else "source_artifact_missing_or_dry_run",
    })

    # Secret scanning — always refused or not available in current state
    ss_refusal: dict[str, Any] = {}
    if intake:
        for refusal in intake.get("refusals", []):
            if (
                isinstance(refusal, dict)
                and refusal.get("surface") == "secret_scanning"
            ):
                ss_refusal = refusal
                break
    queue_items.append(_normalize_secret_scanning_to_queue_item(ss_refusal, 0))
    input_surfaces.append({
        "surface": "secret_scanning",
        "status": "refused",
        "item_count": 1,
        "live_fetch_status": "not_attempted",
        "blocked_reason": "source_surface_refused: missing_permission_or_not_enabled",
    })

    # Security advisories — not yet ingested
    advisory_count = len([
        qi
        for qi in queue_items
        if qi["source_surface"] == "repository_security_advisory"
    ])
    if advisory_count == 0:
        queue_items.append(_normalize_advisory_to_queue_item(None, 0))
    input_surfaces.append({
        "surface": "repository_security_advisory",
        "status": "not_available",
        "item_count": 1,
        "live_fetch_status": "not_attempted",
        "blocked_reason": "source_artifact_missing",
    })

    # Security policy gap
    queue_items.append(_normalize_policy_gap_to_queue_item())
    input_surfaces.append({
        "surface": "security_policy_gap",
        "status": "not_available",
        "item_count": 1,
        "live_fetch_status": "not_attempted",
        "blocked_reason": "source_artifact_missing",
    })

    # Sort by priority score (lower = higher), then by surface order
    surface_order = {s: i for i, s in enumerate(_SOURCE_SURFACES)}
    queue_items.sort(
        key=lambda qi: (
            qi.get("priority_score", 99),
            surface_order.get(qi.get("source_surface", ""), 99),
        )
    )

    # Aggregate summary
    severity_breakdown: dict[str, int] = {}
    surface_breakdown: dict[str, int] = {}
    remediation_lane_breakdown: dict[str, int] = {}
    for qi in queue_items:
        sev = qi.get("severity", "unknown")
        severity_breakdown[sev] = severity_breakdown.get(sev, 0) + 1
        sf = qi.get("source_surface", "unknown")
        surface_breakdown[sf] = surface_breakdown.get(sf, 0) + 1
        lane = qi.get("remediation_lane", "unknown")
        remediation_lane_breakdown[lane] = remediation_lane_breakdown.get(lane, 0) + 1

    # Blocked reasons summary
    blocked_items = [qi for qi in queue_items if qi.get("blocked_reasons")]
    all_blocked_reasons = sorted({
        r for qi in blocked_items for r in qi.get("blocked_reasons", [])
    })

    # Permission gaps
    permission_gaps: list[str] = []
    for surface in _SOURCE_SURFACES:
        perms = _SURFACE_PERMISSIONS.get(surface, {})
        for perm_set in ("read", "remediation"):
            for perm in perms.get(perm_set, []):
                if perm not in permission_gaps:
                    permission_gaps.append(perm)

    report: dict[str, Any] = {
        "schema_version": "rig.github.security_queue.v1",
        "generated_at": generated_at_utc or _now_iso(),
        "content_light": True,
        "remote_mutation": False,
        "source_artifacts": source_artifacts,
        "input_surfaces": input_surfaces,
        "queue_items": queue_items,
        "queue_summary": {
            "total_queue_items": len(queue_items),
            "severity_breakdown": severity_breakdown,
            "surface_breakdown": surface_breakdown,
            "remediation_lane_breakdown": remediation_lane_breakdown,
            "blocked_item_count": len(blocked_items),
            "unblocked_item_count": len(queue_items) - len(blocked_items),
            "blocked_reasons": all_blocked_reasons,
        },
        "permission_summary": {
            "read_permissions": list({
                p
                for s in _SOURCE_SURFACES
                for p in _SURFACE_PERMISSIONS.get(s, {}).get("read", [])
            }),
            "remediation_permissions": list({
                p
                for s in _SOURCE_SURFACES
                for p in _SURFACE_PERMISSIONS.get(s, {}).get("remediation", [])
            }),
            "permission_gaps": sorted(permission_gaps),
        },
        "risk_summary": {
            "highest_severity_present": next(
                (
                    s
                    for s in [
                        "critical",
                        "high",
                        "medium",
                        "moderate",
                        "low",
                        "info",
                        "unknown",
                    ]
                    if severity_breakdown.get(s, 0) > 0
                ),
                "unknown",
            ),
            "open_items": sum(1 for qi in queue_items if qi.get("state") == "open"),
            "resolved_items": sum(
                1 for qi in queue_items if qi.get("state") in {"fixed", "dismissed"}
            ),
            "refused_or_unavailable_items": sum(
                1
                for qi in queue_items
                if qi.get("state") in {"refused", "not_available"}
            ),
        },
        "remediation_readiness_summary": {
            "items_ready_for_remediation": 0,
            "items_blocked_by_permissions": len(blocked_items),
            "items_blocked_by_content_light": 0,
            "remote_mutation_required": False,
            "remediation_possible": False,
        },
        "blocked_reasons": all_blocked_reasons,
        "redaction_summary": {
            "content_light": True,
            "forbidden_fields_present": False,
            "redaction_rules": len(_FORBIDDEN_QUEUE),
            "secret_values_present": False,
            "raw_code_snippets_present": False,
        },
        "content_light_status": "all_items_content_light",
        "intentionally_deferred": [
            "remediation_execution",
            "live_alert_dismissal",
            "secret_value_revocation",
            "PR_creation_for_fixes",
            "cross_surface_deduplication",
            "webhook_ingestion",
        ],
        "recommended_next_slice": "Phase 2 Slice 2 — prioritize top 3 queue items and generate remediation plan",
    }

    _assert_queue_content_light(report)
    return report


def _assert_queue_content_light(data: dict[str, Any]) -> None:
    serialized = json.dumps(data, sort_keys=True)
    for key in _FORBIDDEN_QUEUE:
        if f'"{key}"' in serialized:
            raise ValueError(f"forbidden_key_in_queue: {key}")
    for pattern in (
        "ghp_",
        "gho_",
        "ghu_",
        "ghs_",
        "ghr_",
        "github_pat_",
        "BEGIN PRIVATE KEY",
    ):
        if pattern in serialized:
            raise ValueError(f"forbidden_pattern_in_queue: {pattern}")


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def write_security_queue(
    output_path: Path = _DEFAULT_OUTPUT,
    *,
    intake_path: Path = _DEFAULT_INTAKE,
    work_items_path: Path = _DEFAULT_WORK_ITEMS,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    report = build_security_queue(
        intake_path=intake_path,
        work_items_path=work_items_path,
        generated_at_utc=generated_at_utc,
    )
    _write_json(output_path, report)
    return report


__all__ = [
    "_SURFACE_PERMISSIONS",
    "SecurityQueueError",
    "build_security_queue",
    "write_security_queue",
]
