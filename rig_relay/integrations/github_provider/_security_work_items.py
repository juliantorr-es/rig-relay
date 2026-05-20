"""GitHub security work-item projection — local, deterministic, content-light."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from rig_relay.core.utils.io import read_safe
from rig_relay.integrations.github_provider._redaction import (
    hash_identifier,
    safe_summary,
    scan_response_for_secrets,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_SOURCE_ARTIFACT = (
    _REPO_ROOT
    / "docs"
    / "json"
    / "governance"
    / "github_security_intake_result.v1.json"
)

_FORBIDDEN_KEYS = frozenset({
    "access_token",
    "token_prefix",
    "authorization",
    "client_secret",
    "private_key",
    "raw_response",
    "raw_body",
    "patch",
    "diff",
    "contents",
    "code_snippet",
})

_GROUP_KIND_ORDER = {"code_scanning": 0, "dependabot": 1, "refusal": 2, "unknown": 3}


class GitHubSecurityWorkItemProjectionError(Exception):
    """Raised when security intake cannot be projected into work items."""


def _now_iso() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat()


def _stable_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _hash_or_unknown(value: Any, default: str = "unknown") -> str:
    if isinstance(value, str) and value:
        return hash_identifier(value)
    if value is None:
        return default
    text = str(value)
    return hash_identifier(text) if text else default


def _normalize_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(_REPO_ROOT))
    except ValueError:
        return resolved.as_posix()


def _count_refused_surfaces(source_surfaces: list[dict[str, Any]]) -> int:
    return sum(
        1 for item in source_surfaces if str(item.get("status", "")) == "refused"
    )


def _assert_no_forbidden_keys(value: Any) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key in _FORBIDDEN_KEYS:
                raise ValueError(
                    f"forbidden_key_detected: work item artifact contains forbidden field '{key}'"
                )
            _assert_no_forbidden_keys(item)
    elif isinstance(value, list):
        for item in value:
            _assert_no_forbidden_keys(item)
    elif isinstance(value, str):
        findings = scan_response_for_secrets(value)
        if findings:
            raise ValueError(
                f"forbidden_secret_like_string_detected: {', '.join(findings)}"
            )


def _severity_bucket(value: Any) -> str:
    severity = str(value or "").strip().lower()
    match severity:
        case "critical" | "high" | "medium" | "moderate" | "low" | "warning" | "note":
            return severity
        case "":
            return "unknown"
        case _:
            return "unknown"


def _recommended_lane_for_code_scanning(alert: dict[str, Any]) -> str:
    state = str(alert.get("state", "")).lower()
    if state in {"fixed", "dismissed"}:
        return "advisory_only"
    suggested = str(alert.get("suggested_group_kind", "")).strip()
    if suggested == "codeql_security_fix_needed":
        return "security_patch"
    return "investigation"


def _recommended_lane_for_dependabot(alert: dict[str, Any]) -> str:
    state = str(alert.get("state", "")).lower()
    if state in {"fixed", "dismissed"}:
        return "advisory_only"
    return "dependency_update"


def _recommended_action_for_lane(lane: str) -> str:
    return {
        "security_patch": "inspect_code_scanning_alert",
        "dependency_update": "update_dependency",
        "investigation": "inspect_code_scanning_alert",
        "permission_required": "request_permission",
        "advisory_only": "ignore_noop",
        "refused_surface": "document_refusal",
    }.get(lane, "document_refusal")


def _build_code_scanning_candidate(alert: dict[str, Any]) -> tuple[dict[str, Any], str]:
    finding_key = f"code_scanning#{alert.get('alert_number', 0)}"
    lane = _recommended_lane_for_code_scanning(alert)
    severity = _severity_bucket(
        alert.get("rule_security_severity_level") or alert.get("rule_severity")
    )
    group_key = "|".join([
        "code_scanning",
        str(alert.get("suggested_group_kind", "unknown_triage_needed")),
        str(alert.get("state", "unknown")).lower(),
        severity,
        str(alert.get("rule_id_hash", "")),
    ])
    source_hashes = {
        "rule_id_hash": str(alert.get("rule_id_hash", "")),
        "file_path_hash": str(alert.get("file_path_hash", "")),
        "most_recent_instance_ref_hash": str(
            alert.get("most_recent_instance_ref_hash", "")
        ),
        "html_url_hash": str(alert.get("html_url_hash", "")),
    }
    candidate_id = _sha256_text(_stable_json([finding_key, group_key, source_hashes]))
    return {
        "candidate_id": candidate_id,
        "source_surface": "code_scanning",
        "source_finding_key": finding_key,
        "normalized_severity": severity,
        "state": str(alert.get("state", "unknown")).lower() or "unknown",
        "confidence": "medium",
        "recommended_lane": lane,
        "recommended_action": _recommended_action_for_lane(lane),
        "mutation_allowed": False,
        "remote_mutation_required": False,
        "rationale": (
            f"Code scanning alert {finding_key} is {alert.get('state', 'unknown')}"
        ),
        "source_hashes": source_hashes,
    }, group_key


def _build_dependabot_candidate(alert: dict[str, Any]) -> tuple[dict[str, Any], str]:
    finding_key = f"dependabot#{alert.get('alert_number', 0)}"
    lane = _recommended_lane_for_dependabot(alert)
    severity = _severity_bucket(alert.get("severity"))
    group_key = "|".join([
        "dependabot",
        str(alert.get("package_ecosystem", "unknown")),
        str(alert.get("package_name_hash", "unknown")),
        str(alert.get("state", "unknown")).lower(),
        severity,
    ])
    source_hashes = {
        "package_coordinate_hash": str(alert.get("package_coordinate_hash", "")),
        "package_name_hash": str(alert.get("package_name_hash", "")),
        "manifest_path_hash": str(alert.get("manifest_path_hash", "")),
        "ghsa_id_hash": str(alert.get("ghsa_id_hash", "")),
        "html_url_hash": str(alert.get("html_url_hash", "")),
    }
    candidate_id = _sha256_text(_stable_json([finding_key, group_key, source_hashes]))
    return {
        "candidate_id": candidate_id,
        "source_surface": "dependabot",
        "source_finding_key": finding_key,
        "normalized_severity": severity,
        "state": str(alert.get("state", "unknown")).lower() or "unknown",
        "confidence": "medium",
        "recommended_lane": lane,
        "recommended_action": _recommended_action_for_lane(lane),
        "mutation_allowed": False,
        "remote_mutation_required": False,
        "rationale": f"Dependabot alert {finding_key} is {alert.get('state', 'unknown')}",
        "source_hashes": source_hashes,
    }, group_key


def _build_refusal_candidate(refusal: dict[str, Any]) -> tuple[dict[str, Any], str]:
    surface = str(refusal.get("surface", "refusal"))
    reason = str(refusal.get("reason", "unknown"))
    permission = str(refusal.get("required_permission", ""))
    finding_key = f"{surface}:{reason}"
    group_key = "|".join([surface, reason, permission])
    source_hashes = {
        "surface_hash": hash_identifier(surface),
        "reason_hash": hash_identifier(reason),
        "required_permission_hash": hash_identifier(permission) if permission else "",
    }
    candidate_id = _sha256_text(_stable_json([finding_key, group_key, source_hashes]))
    return {
        "candidate_id": candidate_id,
        "source_surface": "refusal",
        "source_finding_key": finding_key,
        "normalized_severity": "unknown",
        "state": "refused",
        "confidence": "high",
        "recommended_lane": "permission_required",
        "recommended_action": "request_permission",
        "mutation_allowed": False,
        "remote_mutation_required": False,
        "rationale": f"{surface} ingestion was refused because {reason}.",
        "source_hashes": source_hashes,
        "required_permission": permission,
        "refusal_reason": reason,
    }, group_key


def _build_group(
    group_kind: str, group_key: str, candidates: list[dict[str, Any]]
) -> dict[str, Any]:
    candidate_ids = [candidate["candidate_id"] for candidate in candidates]
    severity_summary: dict[str, int] = {}
    for candidate in candidates:
        severity = str(candidate.get("normalized_severity", "unknown"))
        severity_summary[severity] = severity_summary.get(severity, 0) + 1
    recommended_lane = (
        candidates[0]["recommended_lane"] if candidates else "investigation"
    )
    recommended_action = (
        candidates[0]["recommended_action"] if candidates else "document_refusal"
    )
    source_hashes = {
        "group_key_hash": hash_identifier(group_key),
        "candidate_id_hashes": candidate_ids,
    }
    return {
        "group_id": _sha256_text(_stable_json([group_kind, group_key, candidate_ids])),
        "group_kind": group_kind,
        "group_key": group_key,
        "source_surface": group_kind,
        "candidate_count": len(candidates),
        "recommended_lane": recommended_lane,
        "recommended_action": recommended_action,
        "mutation_allowed": False,
        "remote_mutation_required": False,
        "severity_summary": severity_summary,
        "candidates": candidates,
        "source_hashes": source_hashes,
        "rationale": candidates[0]["rationale"] if candidates else "",
    }


def _sorted_group_key(item: dict[str, Any]) -> tuple[int, str]:
    return (
        _GROUP_KIND_ORDER.get(str(item.get("group_kind", "unknown")), 3),
        str(item.get("group_key", "")),
    )


def _build_summary(report: dict[str, Any]) -> dict[str, Any]:
    by_surface: dict[str, int] = {}
    by_lane: dict[str, int] = {}
    by_action: dict[str, int] = {}
    for group in report["candidate_groups"]:
        for candidate in group["candidates"]:
            surface = str(candidate.get("source_surface", "unknown"))
            lane = str(candidate.get("recommended_lane", "investigation"))
            action = str(candidate.get("recommended_action", "document_refusal"))
            by_surface[surface] = by_surface.get(surface, 0) + 1
            by_lane[lane] = by_lane.get(lane, 0) + 1
            by_action[action] = by_action.get(action, 0) + 1
    return {
        "work_item_count": report["work_item_count"],
        "source_alert_count": report["source_alert_count"],
        "candidate_group_count": report["candidate_group_count"],
        "refused_surface_count": report["refused_surface_count"],
        "by_surface": dict(sorted(by_surface.items())),
        "by_lane": dict(sorted(by_lane.items())),
        "by_action": dict(sorted(by_action.items())),
    }


def project_github_security_work_items(
    intake: dict[str, Any],
    *,
    source_artifact_path: str,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    if str(intake.get("schema_version", "")) != "rig.github.security_intake.v1":
        raise GitHubSecurityWorkItemProjectionError(
            "expected rig.github.security_intake.v1 intake artifact"
        )

    generated_at = generated_at_utc or _now_iso()
    source_hash = _sha256_text(_stable_json(intake))

    code_scanning_groups: dict[str, list[dict[str, Any]]] = {}
    dependabot_groups: dict[str, list[dict[str, Any]]] = {}
    refusal_groups: dict[str, list[dict[str, Any]]] = {}
    source_alert_count = 0

    alerts = intake.get("alerts", {})
    if not isinstance(alerts, dict):
        alerts = {}
    for alert in alerts.get("code_scanning", []):
        if not isinstance(alert, dict):
            continue
        source_alert_count += 1
        candidate, group_key = _build_code_scanning_candidate(alert)
        code_scanning_groups.setdefault(group_key, []).append(candidate)

    for alert in alerts.get("dependabot", []):
        if not isinstance(alert, dict):
            continue
        source_alert_count += 1
        candidate, group_key = _build_dependabot_candidate(alert)
        dependabot_groups.setdefault(group_key, []).append(candidate)

    refusals = intake.get("refusals", [])
    if not isinstance(refusals, list):
        refusals = []
    for refusal in refusals:
        if not isinstance(refusal, dict):
            continue
        candidate, group_key = _build_refusal_candidate(refusal)
        refusal_groups.setdefault(group_key, []).append(candidate)

    candidate_groups = []
    for group_key in sorted(code_scanning_groups):
        candidate_groups.append(
            _build_group(
                "code_scanning",
                group_key,
                sorted(
                    code_scanning_groups[group_key],
                    key=lambda item: item["candidate_id"],
                ),
            )
        )
    for group_key in sorted(dependabot_groups):
        candidate_groups.append(
            _build_group(
                "dependabot",
                group_key,
                sorted(
                    dependabot_groups[group_key], key=lambda item: item["candidate_id"]
                ),
            )
        )
    for group_key in sorted(refusal_groups):
        candidate_groups.append(
            _build_group(
                "refusal",
                group_key,
                sorted(
                    refusal_groups[group_key], key=lambda item: item["candidate_id"]
                ),
            )
        )

    candidate_groups.sort(key=_sorted_group_key)
    work_item_count = sum(group["candidate_count"] for group in candidate_groups)
    refused_surface_count = _count_refused_surfaces(intake.get("source_surfaces", []))
    projected_refusals = []
    for refusal in refusals:
        if not isinstance(refusal, dict):
            continue
        projected_refusals.append({
            "surface": str(refusal.get("surface", "unknown")),
            "status": str(refusal.get("status", "refused")),
            "reason": str(refusal.get("reason", "unknown")),
            "required_permission": str(refusal.get("required_permission", "")),
            "remote_mutation": False,
            "recommended_lane": "permission_required",
            "recommended_action": "request_permission",
            "candidate_id": _sha256_text(
                _stable_json([
                    str(refusal.get("surface", "unknown")),
                    str(refusal.get("reason", "unknown")),
                    str(refusal.get("required_permission", "")),
                ])
            ),
        })
    projected_refusals.sort(key=lambda item: item["candidate_id"])
    report = {
        "schema_version": "rig.github.security_work_items.v1",
        "generated_at_utc": generated_at,
        "source_artifact_path": source_artifact_path,
        "source_artifact_hash": source_hash,
        "remote_mutation": False,
        "content_light": True,
        "source_alert_count": source_alert_count,
        "work_item_count": work_item_count,
        "refused_surface_count": refused_surface_count,
        "candidate_group_count": len(candidate_groups),
        "candidate_groups": candidate_groups,
        "refusals": projected_refusals,
    }
    report["summary"] = _build_summary(report)
    _assert_no_forbidden_keys(report)
    return safe_summary(report)


def project_github_security_work_items_from_path(
    input_path: Path | str = _DEFAULT_SOURCE_ARTIFACT,
    *,
    source_artifact_path: str | None = None,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    path = Path(input_path)
    raw = read_safe(path, raise_on_error=True)
    intake = json.loads(raw.text)
    display_path = source_artifact_path or _normalize_path(path)
    return project_github_security_work_items(
        intake, source_artifact_path=display_path, generated_at_utc=generated_at_utc
    )


__all__ = [
    "GitHubSecurityWorkItemProjectionError",
    "project_github_security_work_items",
    "project_github_security_work_items_from_path",
]
