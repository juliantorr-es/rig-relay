"""GitHub App permission posture planning - local, deterministic, content-light."""

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
_DEFAULT_LIVE_AUTH = (
    _REPO_ROOT / "docs" / "json" / "governance" / "live_github_auth_result.v1.json"
)
_DEFAULT_SECURITY_INTAKE = (
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
_DEFAULT_MISSION_CANDIDATES = (
    _REPO_ROOT
    / "docs"
    / "json"
    / "governance"
    / "github_security_mission_candidates_v1.v1.json"
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
    "secret",
})

_ALLOWED_PERMISSION_LEVELS = ("none", "read", "write", "admin", "unknown")
_LEVEL_ORDER = {level: index for index, level in enumerate(_ALLOWED_PERMISSION_LEVELS)}

_PERMISSION_SURFACE_CATALOG = [
    {
        "surface": "code_scanning_alerts",
        "permission_name": "security_events",
        "minimum_level": "read",
        "endpoint_family": "code_scanning",
        "mutation_risk": "read_only",
        "allowed_in_this_slice": True,
        "surface_label": "Code scanning alerts",
    },
    {
        "surface": "secret_scanning_alerts",
        "permission_name": "secret_scanning_alerts",
        "minimum_level": "read",
        "endpoint_family": "secret_scanning",
        "mutation_risk": "sensitive_read",
        "allowed_in_this_slice": True,
        "surface_label": "Secret scanning alerts",
    },
    {
        "surface": "dependabot_alerts",
        "permission_name": "vulnerability_alerts",
        "minimum_level": "read",
        "endpoint_family": "dependabot",
        "mutation_risk": "read_only_security",
        "allowed_in_this_slice": True,
        "surface_label": "Dependabot alerts",
    },
    {
        "surface": "workflow_mutation",
        "permission_name": "workflows",
        "minimum_level": "write",
        "endpoint_family": "actions_workflows",
        "mutation_risk": "mutation_enabled",
        "allowed_in_this_slice": False,
        "surface_label": "Workflows mutation",
    },
]

_MUTATION_PERMISSION_NAMES = frozenset({
    "actions",
    "actions_variables",
    "administration",
    "checks",
    "code_quality",
    "copilot_agent_settings",
    "deployments",
    "issues",
    "packages",
    "pages",
    "pull_requests",
    "repository_hooks",
    "security_events",
    "vulnerability_alerts",
    "workflows",
})


class GitHubPermissionPostureError(Exception):
    """Raised when permission posture planning cannot proceed."""


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


def _normalize_level(value: Any) -> str:
    level = _normalize_lower(value)
    return level if level in _ALLOWED_PERMISSION_LEVELS else "unknown"


def _permission_entries_from_permissions(
    permissions: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    if not isinstance(permissions, dict):
        return []
    entries = [
        {
            "permission_name": _normalize_text(permission_name),
            "level": _normalize_level(raw_level),
        }
        for permission_name, raw_level in permissions.items()
        if isinstance(permission_name, str)
    ]
    entries.sort(key=lambda item: item["permission_name"])
    return entries


def _permission_names_from_entries(entries: list[dict[str, Any]]) -> list[str]:
    names = {
        _normalize_text(entry.get("permission_name"), default="")
        for entry in entries
        if isinstance(entry, dict)
    }
    return sorted(name for name in names if name)


def _permission_mode_name(live_auth: dict[str, Any] | None) -> str:
    if not isinstance(live_auth, dict):
        return "unknown"
    mode = _normalize_lower(live_auth.get("permission_mode"), default="unknown")
    return (
        mode
        if mode in {"development_debug", "preproduction", "public_release"}
        else "unknown"
    )


def _live_auth_posture_inputs(live_auth: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(live_auth, dict):
        return {
            "permission_mode": "unknown",
            "requested_permissions": [],
            "effective_permissions": [],
            "app_granted_permissions": [],
        }
    requested_permissions = live_auth.get("requested_token_permissions", [])
    if not isinstance(requested_permissions, list):
        requested_permissions = []
    effective_permissions = live_auth.get("effective_token_permissions", [])
    if not isinstance(effective_permissions, list):
        effective_permissions = []
    app_granted_permissions = _string_list(
        live_auth.get("app_granted_permissions")
        or live_auth.get("broad_app_permissions_observed")
        or []
    )
    return {
        "permission_mode": _permission_mode_name(live_auth),
        "requested_permissions": requested_permissions,
        "effective_permissions": effective_permissions,
        "app_granted_permissions": app_granted_permissions,
    }


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    result = [str(item) for item in value if isinstance(item, str)]
    result.sort()
    return result


def _normalize_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(_REPO_ROOT))
    except ValueError:
        return resolved.as_posix()


def _assert_no_forbidden_content(value: Any, path: tuple[str, ...] = ()) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key in _FORBIDDEN_KEYS and (not path or path[-1] != "permissions"):
                raise ValueError(
                    "forbidden_key_detected: permission posture artifact contains "
                    f"forbidden field '{key}'"
                )
            _assert_no_forbidden_content(item, path + (key,))
    elif isinstance(value, list):
        for item in value:
            _assert_no_forbidden_content(item, path)
    elif isinstance(value, str):
        if scan_response_for_secrets(value):
            raise ValueError(
                "forbidden_secret_like_string_detected: permission posture artifact "
                "contains secret-like content"
            )


def _artifact_status(path: Path) -> dict[str, Any]:
    record = {
        "path": _normalize_path(path),
        "present": False,
        "status": "input_unavailable",
        "artifact_hash": None,
        "schema_version": None,
        "reason": "missing_file",
    }
    if not path.exists():
        return record
    try:
        raw = read_safe(path, raise_on_error=True)
        payload = json.loads(raw.text)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        record["reason"] = "parse_error"
        record["error"] = exc.__class__.__name__
        return record

    schema_version = None
    if isinstance(payload, dict):
        schema_version = _infer_schema_version(path, payload)
        record["artifact_hash"] = _sha256_text(_stable_json(payload))
    else:
        record["artifact_hash"] = _sha256_text(_stable_json(payload))

    record.update({
        "present": True,
        "status": "available",
        "schema_version": schema_version,
        "reason": None,
    })
    return record


def _infer_schema_version(path: Path, payload: dict[str, Any]) -> str | None:
    schema_version = payload.get("schema_version")
    if isinstance(schema_version, str) and schema_version:
        return schema_version
    if path.name == "live_github_auth_result.v1.json":
        return "rig.github.live_auth_result.v1"
    return None


def _load_json_artifact(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    raw = read_safe(path, raise_on_error=True)
    payload = json.loads(raw.text)
    return payload if isinstance(payload, dict) else None


def _observed_permissions_from_live_auth(
    live_auth: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    if not isinstance(live_auth, dict):
        return []
    effective_permissions = live_auth.get("effective_token_permissions", [])
    if isinstance(effective_permissions, list) and effective_permissions:
        observed = [
            {
                "permission_name": _normalize_text(
                    item.get("permission_name"), default="unknown"
                ),
                "level": _normalize_level(item.get("level")),
                "source_artifact": "live_auth",
                "observed_from": "effective_token_permissions",
                "permission_name_hash": hash_identifier(
                    _normalize_text(item.get("permission_name"), default="unknown")
                ),
                "level_hash": hash_identifier(_normalize_level(item.get("level"))),
            }
            for item in effective_permissions
            if isinstance(item, dict)
        ]
        observed.sort(key=lambda item: item["permission_name"])
        return observed
    token_exchange = live_auth.get("live_results", {}).get("token_exchange", {})
    permissions = token_exchange.get("permissions", {})
    if not isinstance(permissions, dict):
        return []

    observed: list[dict[str, Any]] = []
    for permission_name, raw_level in permissions.items():
        name = _normalize_text(permission_name)
        level = _normalize_level(raw_level)
        observed.append({
            "permission_name": name,
            "level": level,
            "source_artifact": "live_auth",
            "observed_from": "live_results.token_exchange.permissions",
            "permission_name_hash": hash_identifier(name),
            "level_hash": hash_identifier(level),
        })
    observed.sort(key=lambda item: item["permission_name"])
    return observed


def _level_satisfies(observed_level: str, minimum_level: str) -> bool:
    return _LEVEL_ORDER.get(observed_level, 99) >= _LEVEL_ORDER.get(minimum_level, 99)


def _permission_catalog_status(observed_levels: dict[str, str]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for item in _PERMISSION_SURFACE_CATALOG:
        permission_name = item["permission_name"]
        observed_level = observed_levels.get(permission_name, "none")
        if item["allowed_in_this_slice"] is False:
            status = "non_goal"
        elif _level_satisfies(observed_level, item["minimum_level"]):
            status = "observed"
        else:
            status = "missing"
        results.append({
            **item,
            "observed_level": observed_level,
            "status": status,
            "permission_name_hash": hash_identifier(permission_name),
            "surface_hash": hash_identifier(item["surface"]),
        })
    results.sort(key=lambda item: item["permission_name"])
    return results


def _permission_name_from_required_text(required_permission: str) -> str | None:
    text = required_permission.lower()
    if "code scanning" in text:
        return "security_events"
    if "secret scanning" in text:
        return "secret_scanning_alerts"
    if "dependabot" in text:
        return "vulnerability_alerts"
    if "workflow" in text:
        return "workflows"
    return None


def _minimum_level_from_required_text(required_permission: str) -> str:
    text = required_permission.lower()
    if "write" in text:
        return "write"
    if "admin" in text:
        return "admin"
    if "read" in text:
        return "read"
    return "unknown"


def _build_candidate_index(
    work_items: dict[str, Any] | None,
) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    if not isinstance(work_items, dict):
        return index
    groups = work_items.get("candidate_groups", [])
    if not isinstance(groups, list):
        return index
    for group in groups:
        if not isinstance(group, dict):
            continue
        candidates = group.get("candidates", [])
        if not isinstance(candidates, list):
            continue
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            candidate_id = _normalize_text(candidate.get("candidate_id"), default="")
            if not candidate_id:
                continue
            index[candidate_id] = {
                "candidate_id": candidate_id,
                "source_surface": _normalize_text(candidate.get("source_surface")),
                "required_permission": _normalize_text(
                    candidate.get("required_permission"), default=""
                ),
                "refusal_reason": _normalize_text(
                    candidate.get("refusal_reason"), default=""
                ),
                "recommended_lane": _normalize_text(
                    candidate.get("recommended_lane"), default=""
                ),
                "source_hashes": candidate.get("source_hashes")
                if isinstance(candidate.get("source_hashes"), dict)
                else {},
            }
    return index


def _build_mission_candidate_lookup(
    mission_candidates: dict[str, Any] | None,
) -> dict[str, dict[str, Any]]:
    lookup: dict[str, dict[str, Any]] = {}
    if not isinstance(mission_candidates, dict):
        return lookup
    candidates = mission_candidates.get("mission_candidates", [])
    if not isinstance(candidates, list):
        return lookup
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        source_candidate_id = _normalize_text(
            candidate.get("source_candidate_id"), default=""
        )
        if not source_candidate_id:
            continue
        lookup[source_candidate_id] = {
            "mission_candidate_id": _normalize_text(
                candidate.get("mission_candidate_id")
            ),
            "route": _normalize_text(candidate.get("route")),
            "mission_type": _normalize_text(candidate.get("mission_type")),
            "priority": _normalize_text(candidate.get("priority")),
            "recommended_lane": _normalize_text(candidate.get("recommended_lane")),
        }
    return lookup


def _build_permission_request_plan(
    candidate_index: dict[str, dict[str, Any]],
    mission_lookup: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    blocked_links: list[dict[str, Any]] = []
    unknown_links: list[dict[str, Any]] = []

    for source_candidate_id, mission_candidate in mission_lookup.items():
        if mission_candidate.get("route") != "permission_required":
            continue
        work_item = candidate_index.get(source_candidate_id)
        if not work_item:
            unknown_links.append({
                "mission_candidate_id": mission_candidate["mission_candidate_id"],
                "source_candidate_id": source_candidate_id,
                "route": "blocked_unknown_permission_surface",
                "mission_type": mission_candidate["mission_type"],
                "blocked_reason": "unknown_permission_surface",
                "remote_mutation": False,
                "rationale": "permission_required mission candidate could not be mapped to a permission request.",
            })
            continue

        required_permission = work_item.get("required_permission", "")
        permission_name = _permission_name_from_required_text(required_permission)
        minimum_level = _minimum_level_from_required_text(required_permission)
        if not permission_name or minimum_level == "unknown":
            unknown_links.append({
                "mission_candidate_id": mission_candidate["mission_candidate_id"],
                "source_candidate_id": source_candidate_id,
                "route": "blocked_unknown_permission_surface",
                "mission_type": mission_candidate["mission_type"],
                "blocked_reason": "unknown_permission_surface",
                "remote_mutation": False,
                "rationale": "permission_required mission candidate could not be mapped to a permission request.",
            })
            continue

        key = (permission_name, minimum_level, work_item["source_surface"])
        grouped.setdefault(key, []).append({
            "mission_candidate_id": mission_candidate["mission_candidate_id"],
            "source_candidate_id": source_candidate_id,
            "required_permission": required_permission,
            "work_item_surface": work_item["source_surface"],
        })

    permission_request_plan: list[dict[str, Any]] = []
    missing_permissions: list[dict[str, Any]] = []

    for (
        permission_name,
        minimum_level,
        surface_unblocked,
    ), candidates in grouped.items():
        candidate_ids = sorted({item["mission_candidate_id"] for item in candidates})
        source_candidate_ids = sorted({
            item["source_candidate_id"] for item in candidates
        })
        request_id = _sha256_text(
            _stable_json([
                permission_name,
                minimum_level,
                surface_unblocked,
                candidate_ids,
            ])
        )
        risk_classification = {
            "security_events": "read_only",
            "vulnerability_alerts": "read_only",
            "secret_scanning_alerts": "sensitive_read",
        }.get(permission_name, "read_only")
        plan_entry = {
            "request_id": request_id,
            "permission_name": permission_name,
            "requested_level": minimum_level,
            "surface_unblocked": surface_unblocked,
            "candidate_ids_unblocked": candidate_ids,
            "rationale": (
                f"Request {permission_name} {minimum_level} to unblock {surface_unblocked} security intake."
            ),
            "risk_classification": risk_classification,
            "requires_owner_action": True,
            "remote_mutation": False,
            "recommended_operator_action": "update_github_app_permission_manually",
        }
        permission_request_plan.append(plan_entry)
        missing_permissions.append({
            "permission_name": permission_name,
            "minimum_level": minimum_level,
            "observed_level": "none",
            "surface_unblocked": surface_unblocked,
            "candidate_ids_unblocked": candidate_ids,
            "request_id": request_id,
            "rationale": plan_entry["rationale"],
            "risk_classification": risk_classification,
            "requires_owner_action": True,
            "remote_mutation": False,
            "recommended_operator_action": "update_github_app_permission_manually",
            "blocked_candidate_count": len(candidate_ids),
            "source_candidate_ids": source_candidate_ids,
        })

        for item in candidates:
            blocked_links.append({
                "mission_candidate_id": item["mission_candidate_id"],
                "source_candidate_id": item["source_candidate_id"],
                "permission_request_id": request_id,
                "permission_name": permission_name,
                "surface_unblocked": surface_unblocked,
                "blocked_reason": "permission_required",
                "remote_mutation": False,
                "rationale": (
                    f"permission_required mission candidate maps to {permission_name} {minimum_level} request."
                ),
            })

    blocked_links.extend(unknown_links)
    permission_request_plan.sort(
        key=lambda item: (item["permission_name"], item["surface_unblocked"])
    )
    missing_permissions.sort(
        key=lambda item: (item["permission_name"], item["surface_unblocked"])
    )
    blocked_links.sort(
        key=lambda item: (item["blocked_reason"], item["mission_candidate_id"])
    )
    return permission_request_plan, missing_permissions, blocked_links


def _required_permissions(observed_levels: dict[str, str]) -> list[dict[str, Any]]:
    required: list[dict[str, Any]] = []
    for item in _PERMISSION_SURFACE_CATALOG:
        permission_name = item["permission_name"]
        observed_level = observed_levels.get(permission_name, "none")
        if item["allowed_in_this_slice"] is False:
            status = "non_goal"
        elif _level_satisfies(observed_level, item["minimum_level"]):
            status = "observed"
        else:
            status = "missing"
        required.append({
            **item,
            "observed_level": observed_level,
            "status": status,
            "permission_name_hash": hash_identifier(permission_name),
            "surface_hash": hash_identifier(item["surface"]),
        })
    required.sort(key=lambda item: item["permission_name"])
    return required


def _build_risk_summary(
    observed_permissions: list[dict[str, Any]],
    permission_request_plan: list[dict[str, Any]],
) -> dict[str, Any]:
    requested_read_permissions_count = sum(
        1 for item in permission_request_plan if item["requested_level"] == "read"
    )
    requested_sensitive_read_permissions_count = sum(
        1
        for item in permission_request_plan
        if item["risk_classification"] == "sensitive_read"
    )
    requested_write_permissions_count = sum(
        1 for item in permission_request_plan if item["requested_level"] == "write"
    )
    requested_admin_permissions_count = sum(
        1 for item in permission_request_plan if item["requested_level"] == "admin"
    )
    return {
        "requested_read_permissions_count": requested_read_permissions_count,
        "requested_sensitive_read_permissions_count": requested_sensitive_read_permissions_count,
        "requested_write_permissions_count": requested_write_permissions_count,
        "requested_admin_permissions_count": requested_admin_permissions_count,
        "mutation_permissions_requested": bool(
            requested_write_permissions_count or requested_admin_permissions_count
        ),
        "secret_material_persisted": False,
        "remote_mutation": False,
        "observed_permission_count": len(observed_permissions),
        "missing_permission_count": len(permission_request_plan),
        "permission_request_count": len(permission_request_plan),
    }


def _build_posture_summary(
    *,
    permission_mode: str,
    requested_permissions: list[dict[str, Any]],
    effective_permissions: list[dict[str, Any]],
    app_granted_permissions: list[str],
) -> dict[str, Any]:
    requested_names = _permission_names_from_entries(requested_permissions)
    effective_names = _permission_names_from_entries(effective_permissions)
    broad_app_permissions_observed = [
        name for name in app_granted_permissions if name not in requested_names
    ]
    mutation_permissions_observed = [
        name for name in app_granted_permissions if name in _MUTATION_PERMISSION_NAMES
    ]
    token_narrowing_requested = bool(requested_names)
    token_narrowing_effective = token_narrowing_requested and (
        requested_names == effective_names
    )
    broad_app_permission_risk_mitigated_by_token_scope = bool(
        token_narrowing_requested
        and token_narrowing_effective
        and broad_app_permissions_observed
    )
    over_permission_count = len(broad_app_permissions_observed)
    mutation_permission_count = len(mutation_permissions_observed)

    if permission_mode == "public_release":
        if mutation_permission_count:
            permission_posture_status = "mutation_enabled"
        elif over_permission_count:
            permission_posture_status = "over_permissioned"
        elif token_narrowing_effective:
            permission_posture_status = "least_privilege"
        else:
            permission_posture_status = "unknown"
    elif permission_mode == "preproduction":
        if mutation_permission_count or over_permission_count:
            permission_posture_status = "over_permissioned"
        elif token_narrowing_effective:
            permission_posture_status = "read_only_sufficient"
        else:
            permission_posture_status = "unknown"
    elif mutation_permission_count or over_permission_count:
        permission_posture_status = "development_debug_overpermissioned"
    elif token_narrowing_effective:
        permission_posture_status = "read_only_sufficient"
    else:
        permission_posture_status = "unknown"

    public_release_ready = (
        permission_mode == "public_release"
        and not over_permission_count
        and not mutation_permission_count
        and token_narrowing_effective
    )
    recommended_permission_reductions = [
        {
            "permission_name": name,
            "recommended_level": "none" if name == "workflows" else "read",
            "rationale": "reduce broad setup/debug permissions for release posture",
        }
        for name in mutation_permissions_observed
    ]
    recommended_permission_reductions.sort(key=lambda item: item["permission_name"])
    return {
        "permission_mode": permission_mode,
        "app_granted_permissions": app_granted_permissions,
        "requested_token_permissions": requested_permissions,
        "effective_token_permissions": effective_permissions,
        "token_narrowing_requested": token_narrowing_requested,
        "token_narrowing_effective": token_narrowing_effective,
        "broad_app_permissions_observed": broad_app_permissions_observed,
        "mutation_permissions_observed": mutation_permissions_observed,
        "unsafe_broad_token_used": False,
        "public_release_ready": public_release_ready,
        "permission_posture_status": permission_posture_status,
        "over_permissioned": bool(over_permission_count or mutation_permission_count),
        "over_permission_count": over_permission_count,
        "mutation_permission_count": mutation_permission_count,
        "broad_app_permission_risk_mitigated_by_token_scope": broad_app_permission_risk_mitigated_by_token_scope,
        "read_only_token_enforced": token_narrowing_effective,
        "recommended_permission_reductions": recommended_permission_reductions,
    }


def _build_refusals() -> list[dict[str, Any]]:
    return [
        {
            "surface": "workflow_mutation",
            "status": "refused",
            "reason": "non_goal_surface",
            "required_permission": "workflows write",
            "remote_mutation": False,
        }
    ]


def build_github_permission_posture_report(
    *,
    live_auth: dict[str, Any] | None,
    security_intake: dict[str, Any] | None,
    work_items: dict[str, Any] | None,
    mission_candidates: dict[str, Any] | None,
    source_artifacts: list[dict[str, Any]],
    permission_mode: str | None = None,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    generated_at = generated_at_utc or _now_iso()
    for artifact in (live_auth, security_intake, work_items, mission_candidates):
        if isinstance(artifact, dict):
            _assert_no_forbidden_content(artifact)
    observed_permissions = _observed_permissions_from_live_auth(live_auth)
    posture_inputs = _live_auth_posture_inputs(live_auth)
    effective_permissions = posture_inputs["effective_permissions"]
    if not effective_permissions:
        effective_permissions = [
            {"permission_name": item["permission_name"], "level": item["level"]}
            for item in observed_permissions
        ]
    posture_summary = _build_posture_summary(
        permission_mode=permission_mode
        or str(posture_inputs["permission_mode"])
        or "unknown",
        requested_permissions=posture_inputs["requested_permissions"],
        effective_permissions=effective_permissions,
        app_granted_permissions=posture_inputs["app_granted_permissions"],
    )
    required_permissions = _required_permissions({
        item["permission_name"]: item["level"] for item in observed_permissions
    })
    candidate_index = _build_candidate_index(work_items)
    mission_lookup = _build_mission_candidate_lookup(mission_candidates)
    permission_request_plan, missing_permissions, blocked_candidate_links = (
        _build_permission_request_plan(candidate_index, mission_lookup)
    )

    if not any(artifact.get("present") is True for artifact in source_artifacts):
        raise GitHubPermissionPostureError("no meaningful input artifacts available")

    refusal_records = _build_refusals()
    input_unavailable_count = sum(
        1
        for artifact in source_artifacts
        if artifact.get("status") == "input_unavailable"
    )

    report = {
        "schema_version": "rig.github_app_permission_posture.v1",
        "generated_at_utc": generated_at,
        "content_light": True,
        "remote_mutation": False,
        **posture_summary,
        "source_artifacts": source_artifacts,
        "observed_permissions": observed_permissions,
        "required_permissions": required_permissions,
        "missing_permissions": missing_permissions,
        "permission_request_plan": permission_request_plan,
        "blocked_candidate_links": blocked_candidate_links,
        "risk_summary": _build_risk_summary(
            observed_permissions, permission_request_plan
        ),
        "refusals": refusal_records,
        "summary": {
            "observed_permission_count": len(observed_permissions),
            "required_permission_count": len(required_permissions),
            "missing_permission_count": len(missing_permissions),
            "permission_request_count": len(permission_request_plan),
            "blocked_candidate_count": len(blocked_candidate_links),
            "input_unavailable_count": input_unavailable_count,
            "mutation_permissions_requested": False,
            "remote_mutation": False,
            "permission_mode": posture_summary["permission_mode"],
            "permission_posture_status": posture_summary["permission_posture_status"],
            "public_release_ready": posture_summary["public_release_ready"],
            "over_permission_count": posture_summary["over_permission_count"],
            "mutation_permission_count": posture_summary["mutation_permission_count"],
            "unsafe_broad_token_used": posture_summary["unsafe_broad_token_used"],
            "broad_app_permission_risk_mitigated_by_token_scope": posture_summary[
                "broad_app_permission_risk_mitigated_by_token_scope"
            ],
            "by_permission_name": [
                {"permission_name": item["permission_name"], "level": item["level"]}
                for item in observed_permissions
            ],
            "by_requested_permission": [
                {
                    "permission_name": item["permission_name"],
                    "requested_level": item["requested_level"],
                }
                for item in permission_request_plan
            ],
            "recommended_permission_reductions": posture_summary[
                "recommended_permission_reductions"
            ],
        },
    }
    _assert_no_forbidden_content(report)
    return safe_summary(report)


def build_github_permission_posture_report_from_paths(
    *,
    live_auth_json: Path | str = _DEFAULT_LIVE_AUTH,
    security_intake_json: Path | str = _DEFAULT_SECURITY_INTAKE,
    work_items_json: Path | str = _DEFAULT_WORK_ITEMS,
    mission_candidates_json: Path | str = _DEFAULT_MISSION_CANDIDATES,
    permission_mode: str | None = None,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    live_auth_path = Path(live_auth_json)
    security_intake_path = Path(security_intake_json)
    work_items_path = Path(work_items_json)
    mission_candidates_path = Path(mission_candidates_json)

    source_artifacts = [
        _artifact_status(live_auth_path),
        _artifact_status(security_intake_path),
        _artifact_status(work_items_path),
        _artifact_status(mission_candidates_path),
    ]
    live_auth = _load_json_artifact(live_auth_path)
    security_intake = _load_json_artifact(security_intake_path)
    work_items = _load_json_artifact(work_items_path)
    mission_candidates = _load_json_artifact(mission_candidates_path)

    if not any(artifact["present"] for artifact in source_artifacts):
        raise GitHubPermissionPostureError("no meaningful input artifacts available")

    return build_github_permission_posture_report(
        live_auth=live_auth,
        security_intake=security_intake,
        work_items=work_items,
        mission_candidates=mission_candidates,
        source_artifacts=source_artifacts,
        permission_mode=permission_mode,
        generated_at_utc=generated_at_utc,
    )


__all__ = [
    "GitHubPermissionPostureError",
    "build_github_permission_posture_report",
    "build_github_permission_posture_report_from_paths",
]
