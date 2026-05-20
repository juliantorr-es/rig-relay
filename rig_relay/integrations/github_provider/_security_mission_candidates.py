"""GitHub security mission candidate routing - local, deterministic, content-light."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
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
    / "github_security_work_items_v1.v1.json"
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

_ROUTE_ORDER = {
    "ready_for_dependency_update": 0,
    "ready_for_investigation": 1,
    "permission_required": 2,
    "advisory_only": 3,
    "blocked_insufficient_evidence": 4,
    "blocked_refused_surface": 5,
    "noop": 6,
}

_MISSION_TYPE_ORDER = {
    "dependency_update_plan": 0,
    "investigate_security_alert": 1,
    "permission_enablement_plan": 2,
    "advisory_record": 3,
    "refusal_record": 4,
    "unknown_security_work": 5,
}

_PRIORITY_ORDER = {"p0": 0, "p1": 1, "p2": 2, "p3": 3, "p4": 4}

_FORBIDDEN_TEXT_PATTERNS = (
    re.compile(r"ghp_[A-Za-z0-9]{20,}"),
    re.compile(r"gho_[A-Za-z0-9]{20,}"),
    re.compile(r"ghu_[A-Za-z0-9]{20,}"),
    re.compile(r"ghs_[A-Za-z0-9]{20,}"),
    re.compile(r"ghr_[A-Za-z0-9]{20,}"),
    re.compile(r"github_pat_[A-Za-z0-9]{20,}"),
    re.compile(r"-----BEGIN (?:RSA |EC |DSA )?PRIVATE KEY-----"),
    re.compile(r"\baccess_token\b"),
    re.compile(r"\btoken_prefix\b"),
    re.compile(r"\bauthorization\b"),
    re.compile(r"\bclient_secret\b"),
    re.compile(r"\bprivate_key\b"),
    re.compile(r"\braw_response\b"),
    re.compile(r"\braw_body\b"),
    re.compile(r"\bpatch\b"),
    re.compile(r"\bdiff\b"),
    re.compile(r"\bcontents\b"),
    re.compile(r"\bcode_snippet\b"),
    re.compile(r"\bsecret\b"),
)


class GitHubSecurityMissionCandidateRoutingError(Exception):
    """Raised when security work items cannot be routed into mission candidates."""


def _now_iso() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat()


def _stable_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _normalize_text(value: Any, default: str = "unknown") -> str:
    if isinstance(value, str):
        text = value.strip()
        return text if text else default
    if value is None:
        return default
    text = str(value).strip()
    return text if text else default


def _normalize_lower(value: Any, default: str = "unknown") -> str:
    return _normalize_text(value, default=default).lower()


def _normalize_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(_REPO_ROOT))
    except ValueError:
        return resolved.as_posix()


def _normalize_mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _normalize_severity(value: Any) -> str:
    severity = _normalize_lower(value)
    match severity:
        case "critical" | "high" | "medium" | "moderate" | "low" | "info" | "note":
            return severity
        case _:
            return "unknown"


def _priority_from_severity(severity: str, *, permission_required: bool) -> str:
    match severity:
        case "critical":
            return "p0"
        case "high":
            return "p1"
        case "medium" | "moderate":
            return "p2"
        case "low":
            return "p3"
        case "info" | "note":
            return "p4"
        case _:
            return "p3" if permission_required else "p4"


def _assert_no_forbidden_content(value: Any) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key in _FORBIDDEN_KEYS:
                raise ValueError(
                    "forbidden_key_detected: mission candidate artifact contains "
                    f"forbidden field '{key}'"
                )
            _assert_no_forbidden_content(item)
    elif isinstance(value, list):
        for item in value:
            _assert_no_forbidden_content(item)
    elif isinstance(value, str):
        if scan_response_for_secrets(value):
            raise ValueError(
                "forbidden_secret_like_string_detected: mission candidate artifact "
                "contains secret-like content"
            )
        for pattern in _FORBIDDEN_TEXT_PATTERNS:
            if pattern.search(value):
                raise ValueError(
                    "forbidden_content_detected: mission candidate artifact contains "
                    f"'{pattern.pattern}'"
                )


def _route_bucket(route: str) -> str:
    if route.startswith("ready_"):
        return "ready"
    if route in {"advisory_only", "noop"}:
        return "advisory"
    return "blocked"


def _has_evidence(candidate: dict[str, Any]) -> bool:
    candidate_id = _normalize_text(
        candidate.get("source_candidate_id") or candidate.get("candidate_id"),
        default="",
    )
    if not candidate_id or candidate_id == "unknown":
        return False
    hashes = _normalize_mapping(candidate.get("source_hashes"))
    return any(bool(_normalize_text(value, default="")) for value in hashes.values())


def _route_from_candidate(candidate: dict[str, Any]) -> tuple[str, str, str, bool]:
    surface = _normalize_lower(candidate.get("source_surface"))
    lane = _normalize_lower(candidate.get("recommended_lane"))
    severity = _normalize_severity(candidate.get("normalized_severity"))
    permission_required = lane == "permission_required"
    has_evidence = _has_evidence(candidate)

    if surface == "dependabot":
        if lane == "dependency_update" and has_evidence:
            route = "ready_for_dependency_update"
            mission_type = "dependency_update_plan"
        elif lane == "advisory_only":
            route = "advisory_only"
            mission_type = "advisory_record"
        else:
            route = "blocked_insufficient_evidence"
            mission_type = "unknown_security_work"
    elif surface == "code_scanning":
        if lane in {"security_patch", "investigation"} and has_evidence:
            route = "ready_for_investigation"
            mission_type = "investigate_security_alert"
        elif lane == "advisory_only":
            route = "advisory_only"
            mission_type = "advisory_record"
        else:
            route = "blocked_insufficient_evidence"
            mission_type = "unknown_security_work"
    elif surface == "refusal":
        if lane == "permission_required":
            route = "permission_required"
            mission_type = "permission_enablement_plan"
        elif lane == "advisory_only":
            route = "advisory_only"
            mission_type = "advisory_record"
        else:
            route = "blocked_refused_surface"
            mission_type = "refusal_record"
    else:
        route = "blocked_insufficient_evidence"
        mission_type = "unknown_security_work"

    priority = _priority_from_severity(
        severity, permission_required=permission_required
    )
    return route, mission_type, priority, permission_required


def _proposed_next_action(route: str) -> str:
    return {
        "ready_for_dependency_update": "update_dependency",
        "ready_for_investigation": "inspect_code_scanning_alert",
        "permission_required": "request_permission",
        "advisory_only": "ignore_noop",
        "blocked_insufficient_evidence": "gather_missing_evidence",
        "blocked_refused_surface": "document_refusal",
        "noop": "ignore_noop",
    }.get(route, "document_refusal")


def _requires_human_review(route: str) -> bool:
    return route not in {"advisory_only", "noop"}


def _build_mission_candidate(
    candidate: dict[str, Any], *, group_id: str, group_key: str
) -> dict[str, Any]:
    route, mission_type, priority, permission_required = _route_from_candidate(
        candidate
    )
    source_candidate_id = _normalize_text(candidate.get("candidate_id"))
    source_surface = _normalize_lower(candidate.get("source_surface"))
    recommended_lane = _normalize_lower(candidate.get("recommended_lane"))
    severity = _normalize_severity(candidate.get("normalized_severity"))
    state = _normalize_lower(candidate.get("state"))
    confidence = _normalize_lower(candidate.get("confidence"), default="unknown")
    source_hashes = _normalize_mapping(candidate.get("source_hashes"))

    normalized_source = [
        source_candidate_id,
        source_surface,
        recommended_lane,
        severity,
        state,
        confidence,
        route,
        mission_type,
        priority,
        group_id,
        group_key,
        source_hashes,
    ]
    mission_candidate_id = _sha256_text(_stable_json(normalized_source))
    rationale = {
        "ready_for_dependency_update": "Dependabot work item is actionable for a local dependency update plan.",
        "ready_for_investigation": "Code scanning work item is actionable for a local security investigation.",
        "permission_required": "Work item is blocked until the required GitHub App permission is enabled.",
        "advisory_only": "Work item is advisory and does not require follow-up.",
        "blocked_insufficient_evidence": "Work item does not contain enough evidence for a governed mission.",
        "blocked_refused_surface": "Work item was refused upstream and cannot be turned into an actionable mission.",
        "noop": "Work item requires no follow-up.",
    }[route]
    severity_basis = {
        "critical": "normalized severity critical -> p0",
        "high": "normalized severity high -> p1",
        "medium": "normalized severity medium -> p2",
        "moderate": "normalized severity moderate -> p2",
        "low": "normalized severity low -> p3",
        "info": "normalized severity info -> p4",
        "note": "normalized severity note -> p4",
        "unknown": (
            "permission_required lane with unknown severity -> p3"
            if permission_required
            else "unknown severity -> p4"
        ),
    }[severity]
    if (
        route in {"blocked_insufficient_evidence", "blocked_refused_surface"}
        and priority == "p4"
    ):
        severity_basis = "blocked route with unknown or insufficient evidence -> p4"
    return {
        "mission_candidate_id": mission_candidate_id,
        "source_candidate_id": source_candidate_id,
        "source_surface": source_surface,
        "recommended_lane": recommended_lane,
        "route": route,
        "mission_type": mission_type,
        "priority": priority,
        "severity_basis": severity_basis,
        "mutation_allowed": False,
        "remote_mutation_required": False,
        "requires_human_review": _requires_human_review(route),
        "requires_permission_change": route == "permission_required",
        "proposed_next_action": _proposed_next_action(route),
        "state": state,
        "confidence": confidence,
        "rationale": rationale,
        "source_hashes": {
            "candidate_id_hash": hash_identifier(source_candidate_id),
            "group_id_hash": hash_identifier(group_id),
            "group_key_hash": hash_identifier(group_key),
            "source_surface_hash": hash_identifier(source_surface),
            "recommended_lane_hash": hash_identifier(recommended_lane),
            "route_hash": hash_identifier(route),
            "mission_type_hash": hash_identifier(mission_type),
            "priority_hash": hash_identifier(priority),
            "severity_hash": hash_identifier(severity),
            "state_hash": hash_identifier(state),
            "confidence_hash": hash_identifier(confidence),
        },
    }


def _build_route_group(
    route: str, mission_type: str, priority: str, candidates: list[dict[str, Any]]
) -> dict[str, Any]:
    candidate_ids = [candidate["mission_candidate_id"] for candidate in candidates]
    source_candidate_ids = [
        candidate["source_candidate_id"] for candidate in candidates
    ]
    source_surfaces: dict[str, int] = {}
    severity_summary: dict[str, int] = {}
    for candidate in candidates:
        source_surface = candidate["source_surface"]
        source_surfaces[source_surface] = source_surfaces.get(source_surface, 0) + 1
        severity = candidate["priority"]
        severity_summary[severity] = severity_summary.get(severity, 0) + 1

    return {
        "route_group_id": _sha256_text(
            _stable_json([route, mission_type, priority, candidate_ids])
        ),
        "route": route,
        "mission_type": mission_type,
        "priority": priority,
        "candidate_count": len(candidates),
        "candidate_ids": candidate_ids,
        "source_candidate_ids": source_candidate_ids,
        "source_surfaces": dict(sorted(source_surfaces.items())),
        "severity_summary": dict(sorted(severity_summary.items())),
        "mutation_allowed": False,
        "remote_mutation_required": False,
        "requires_human_review": any(
            candidate["requires_human_review"] for candidate in candidates
        ),
        "requires_permission_change": any(
            candidate["requires_permission_change"] for candidate in candidates
        ),
        "proposed_next_action": candidates[0]["proposed_next_action"]
        if candidates
        else "ignore_noop",
        "rationale": candidates[0]["rationale"] if candidates else "",
        "source_hashes": {
            "route_hash": hash_identifier(route),
            "mission_type_hash": hash_identifier(mission_type),
            "priority_hash": hash_identifier(priority),
            "candidate_id_hashes": candidate_ids,
            "source_candidate_id_hashes": [
                hash_identifier(candidate_id) for candidate_id in source_candidate_ids
            ],
        },
    }


def _sorted_route_group_key(item: dict[str, Any]) -> tuple[int, int, int, str]:
    return (
        _ROUTE_ORDER.get(str(item.get("route", "blocked_insufficient_evidence")), 99),
        _MISSION_TYPE_ORDER.get(
            str(item.get("mission_type", "unknown_security_work")), 99
        ),
        _PRIORITY_ORDER.get(str(item.get("priority", "p4")), 99),
        str(item.get("route_group_id", "")),
    )


def _build_blocked_reason(candidate: dict[str, Any]) -> dict[str, Any]:
    route = candidate["route"]
    blocked_reason = (
        "missing_permission_or_not_enabled"
        if route == "permission_required"
        else "insufficient_evidence"
        if route == "blocked_insufficient_evidence"
        else "refused_upstream"
    )
    result = {
        "mission_candidate_id": candidate["mission_candidate_id"],
        "source_candidate_id": candidate["source_candidate_id"],
        "route": route,
        "mission_type": candidate["mission_type"],
        "reason": blocked_reason,
        "remote_mutation": False,
        "proposed_next_action": candidate["proposed_next_action"],
        "rationale": candidate["rationale"],
    }
    if candidate["requires_permission_change"]:
        permission_hash = candidate["source_hashes"].get("required_permission_hash")
        if isinstance(permission_hash, str) and permission_hash:
            result["required_permission_hash"] = permission_hash
    return result


def _flatten_candidates(
    work_items: dict[str, Any],
) -> list[tuple[dict[str, Any], str, str]]:
    groups = work_items.get("candidate_groups", [])
    if not isinstance(groups, list):
        raise GitHubSecurityMissionCandidateRoutingError(
            "expected candidate_groups to be a list"
        )

    flattened: list[tuple[dict[str, Any], str, str]] = []
    for group in groups:
        if not isinstance(group, dict):
            continue
        group_id = _normalize_text(group.get("group_id"))
        group_key = _normalize_text(group.get("group_key"))
        candidates = group.get("candidates", [])
        if not isinstance(candidates, list):
            continue
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            flattened.append((candidate, group_id, group_key))
    return flattened


def route_github_security_work_items(
    work_items: dict[str, Any],
    *,
    source_artifact_path: str,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    if (
        _normalize_text(work_items.get("schema_version"))
        != "rig.github.security_work_items.v1"
    ):
        raise GitHubSecurityMissionCandidateRoutingError(
            "expected rig.github.security_work_items.v1 work-item artifact"
        )
    for required_key in ("candidate_groups", "refusals", "summary"):
        if required_key not in work_items:
            raise GitHubSecurityMissionCandidateRoutingError(
                f"missing required work-item field '{required_key}'"
            )
    if not isinstance(work_items.get("candidate_groups"), list):
        raise GitHubSecurityMissionCandidateRoutingError(
            "expected candidate_groups to be a list"
        )
    if not isinstance(work_items.get("refusals"), list):
        raise GitHubSecurityMissionCandidateRoutingError(
            "expected refusals to be a list"
        )
    if not isinstance(work_items.get("summary"), dict):
        raise GitHubSecurityMissionCandidateRoutingError(
            "expected summary to be a mapping"
        )

    generated_at = generated_at_utc or _now_iso()
    source_hash = _sha256_text(_stable_json(work_items))

    flattened = _flatten_candidates(work_items)
    mission_candidates: list[dict[str, Any]] = []
    for candidate, group_id, group_key in flattened:
        mission_candidates.append(
            _build_mission_candidate(candidate, group_id=group_id, group_key=group_key)
        )

    mission_candidates.sort(
        key=lambda item: (
            _ROUTE_ORDER.get(item["route"], 99),
            _MISSION_TYPE_ORDER.get(item["mission_type"], 99),
            _PRIORITY_ORDER.get(item["priority"], 99),
            item["mission_candidate_id"],
        )
    )

    route_groups_by_key: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for candidate in mission_candidates:
        route_groups_by_key.setdefault(
            (candidate["route"], candidate["mission_type"], candidate["priority"]), []
        ).append(candidate)

    route_groups = [
        _build_route_group(route, mission_type, priority, candidates)
        for (route, mission_type, priority), candidates in route_groups_by_key.items()
    ]
    route_groups.sort(key=_sorted_route_group_key)

    blocked_reasons = [
        _build_blocked_reason(candidate)
        for candidate in mission_candidates
        if _route_bucket(candidate["route"]) == "blocked"
    ]
    blocked_reasons.sort(key=lambda item: item["mission_candidate_id"])

    ready_candidate_count = sum(
        1 for candidate in mission_candidates if candidate["route"].startswith("ready_")
    )
    advisory_candidate_count = sum(
        1
        for candidate in mission_candidates
        if _route_bucket(candidate["route"]) == "advisory"
    )
    blocked_candidate_count = sum(
        1
        for candidate in mission_candidates
        if _route_bucket(candidate["route"]) == "blocked"
    )

    report = {
        "schema_version": "rig.github.security_mission_candidates.v1",
        "generated_at_utc": generated_at,
        "source_artifact_path": source_artifact_path,
        "source_artifact_hash": source_hash,
        "content_light": True,
        "remote_mutation": False,
        "mission_candidate_count": len(mission_candidates),
        "blocked_candidate_count": blocked_candidate_count,
        "advisory_candidate_count": advisory_candidate_count,
        "ready_candidate_count": ready_candidate_count,
        "route_group_count": len(route_groups),
        "route_groups": route_groups,
        "mission_candidates": mission_candidates,
        "blocked_reasons": blocked_reasons,
    }
    report["summary"] = {
        "mission_candidate_count": report["mission_candidate_count"],
        "blocked_candidate_count": report["blocked_candidate_count"],
        "advisory_candidate_count": report["advisory_candidate_count"],
        "ready_candidate_count": report["ready_candidate_count"],
        "route_group_count": report["route_group_count"],
        "by_route": dict(
            sorted(
                {
                    route: sum(
                        1
                        for candidate in mission_candidates
                        if candidate["route"] == route
                    )
                    for route in {
                        candidate["route"] for candidate in mission_candidates
                    }
                }.items()
            )
        ),
        "by_mission_type": dict(
            sorted(
                {
                    mission_type: sum(
                        1
                        for candidate in mission_candidates
                        if candidate["mission_type"] == mission_type
                    )
                    for mission_type in {
                        candidate["mission_type"] for candidate in mission_candidates
                    }
                }.items()
            )
        ),
        "by_priority": dict(
            sorted(
                {
                    priority: sum(
                        1
                        for candidate in mission_candidates
                        if candidate["priority"] == priority
                    )
                    for priority in {
                        candidate["priority"] for candidate in mission_candidates
                    }
                }.items()
            )
        ),
    }
    _assert_no_forbidden_content(report)
    return safe_summary(report)


def route_github_security_work_items_from_path(
    input_path: Path | str = _DEFAULT_SOURCE_ARTIFACT,
    *,
    source_artifact_path: str | None = None,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    path = Path(input_path)
    raw = read_safe(path, raise_on_error=True)
    work_items = json.loads(raw.text)
    display_path = source_artifact_path or _normalize_path(path)
    return route_github_security_work_items(
        work_items, source_artifact_path=display_path, generated_at_utc=generated_at_utc
    )


__all__ = [
    "GitHubSecurityMissionCandidateRoutingError",
    "route_github_security_work_items",
    "route_github_security_work_items_from_path",
]
