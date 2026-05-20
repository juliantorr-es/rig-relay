"""GitHub provider operating picture - local, deterministic, content-light."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import subprocess
from typing import Any

from rig_relay.core.utils.io import read_safe
from rig_relay.integrations.github_provider._redaction import (
    safe_summary,
    scan_response_for_secrets,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_LIVE_AUTH_JSON = (
    _REPO_ROOT / "docs" / "json" / "governance" / "live_github_auth_result.v1.json"
)
_DEFAULT_SECURITY_INTAKE_JSON = (
    _REPO_ROOT
    / "docs"
    / "json"
    / "governance"
    / "github_security_intake_result.v1.json"
)
_DEFAULT_MISSION_CANDIDATES_JSON = (
    _REPO_ROOT
    / "docs"
    / "json"
    / "governance"
    / "github_security_mission_candidates_v1.v1.json"
)
_DEFAULT_MISSION_PACKETS_JSON = (
    _REPO_ROOT
    / "docs"
    / "json"
    / "governance"
    / "github_security_mission_packets_v1.v1.json"
)
_DEFAULT_CI_CD_RELIABILITY_JSON = (
    _REPO_ROOT / "docs" / "json" / "governance" / "github_ci_cd_reliability_v1.v1.json"
)
_DEFAULT_SWIFT_CODEQL_ADVISORY_PARKING_JSON = (
    _REPO_ROOT
    / "docs"
    / "json"
    / "governance"
    / "swift_codeql_advisory_parking_v1.v1.json"
)
_DEFAULT_OUTPUT_JSON = (
    _REPO_ROOT / "docs" / "json" / "governance" / "github_operating_picture_v1.v1.json"
)

_SOURCE_PATH_KEYS = (
    "live_auth_json",
    "security_intake_json",
    "mission_candidates_json",
    "mission_packets_json",
    "ci_cd_reliability_json",
    "swift_codeql_advisory_parking_json",
)

_FORBIDDEN_FIELDS = frozenset({
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

_FORBIDDEN_VALUE_PATTERNS = (
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

_REQUIRED_READ_SURFACES = [
    "code_scanning_alerts",
    "dependabot_alerts",
    "checks",
    "actions",
    "metadata",
]


class GitHubOperatingPictureError(Exception):
    """Raised when provider artifacts cannot be combined into an operating picture."""


def _now_iso() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat()


def _stable_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _normalize_text(value: Any, default: str | None = None) -> str | None:
    if value is None:
        return default
    if isinstance(value, str):
        text = value.strip()
        return text if text else default
    text = str(value).strip()
    return text if text else default


def _live_auth_summary(data: dict[str, Any]) -> dict[str, Any]:
    live_results = data.get("live_results")
    if not isinstance(live_results, dict):
        live_results = {}
    token_exchange = live_results.get("token_exchange")
    if not isinstance(token_exchange, dict):
        token_exchange = {}
    installation_access = live_results.get("installation_access")
    if not isinstance(installation_access, dict):
        installation_access = {}
    config_summary = data.get("config_summary")
    if not isinstance(config_summary, dict):
        config_summary = {}
    return safe_summary({
        "permission_mode": data.get("permission_mode"),
        "app_installation_configured": config_summary.get("app_auth_possible"),
        "installation_access_proven": installation_access.get("installation_access")
        == "success",
        "token_present": token_exchange.get("token_present"),
        "token_hash_present": bool(token_exchange.get("token_hash")),
        "token_narrowing_requested": live_results.get("token_narrowing_requested"),
        "token_narrowing_effective": live_results.get("token_narrowing_effective"),
        "unsafe_broad_token_used": live_results.get("unsafe_broad_token_used"),
        "public_release_ready": live_results.get("public_release_ready"),
        "installation_id_hash": installation_access.get("installation_id_hash"),
        "accessible_repo_count": installation_access.get("accessible_repo_count"),
        "repository_selection": installation_access.get("repository_selection"),
    })


def _security_intake_summary(data: dict[str, Any]) -> dict[str, Any]:
    counts = data.get("counts")
    summary = data.get("summary")
    if not isinstance(counts, dict):
        counts = {}
    if not isinstance(summary, dict):
        summary = {}
    source_surfaces = data.get("source_surfaces")
    refused_count = summary.get("refused_surface_count")
    if refused_count is None:
        refused_count = counts.get("refused_surfaces")
    return safe_summary({
        "permission_mode": data.get("permission_mode"),
        "code_scanning_total": counts.get("code_scanning_total"),
        "code_scanning_open": counts.get("code_scanning_open"),
        "dependabot_total": counts.get("dependabot_total"),
        "refused_surface_count": refused_count,
        "token_narrowing_requested": data.get("token_narrowing_requested"),
        "token_narrowing_effective": data.get("token_narrowing_effective"),
        "public_release_ready": data.get("public_release_ready"),
        "source_surface_statuses": [
            {"surface": item.get("surface"), "status": item.get("status")}
            for item in source_surfaces
            if isinstance(item, dict)
        ]
        if isinstance(source_surfaces, list)
        else [],
    })


def _mission_candidates_summary(data: dict[str, Any]) -> dict[str, Any]:
    summary = data.get("summary")
    if not isinstance(summary, dict):
        summary = {}
    return safe_summary({
        "mission_candidate_count": data.get("mission_candidate_count"),
        "ready_candidate_count": data.get("ready_candidate_count"),
        "advisory_candidate_count": data.get("advisory_candidate_count"),
        "blocked_candidate_count": data.get("blocked_candidate_count"),
        "by_route": summary.get("by_route"),
        "by_mission_type": summary.get("by_mission_type"),
        "by_priority": summary.get("by_priority"),
    })


def _mission_packets_summary(data: dict[str, Any]) -> dict[str, Any]:
    summary = data.get("summary")
    route_summary = data.get("route_summary")
    if not isinstance(summary, dict):
        summary = {}
    if not isinstance(route_summary, dict):
        route_summary = {}
    return safe_summary({
        "packet_count": data.get("packet_count"),
        "excluded_candidate_count": data.get("excluded_candidate_count"),
        "excluded_by_route": data.get("excluded_by_route"),
        "packet_index_stale": None,
        "selected_route": route_summary.get("selected_route"),
        "selected_by_route": route_summary.get("selected_by_route"),
        "source_artifact_hash": summary.get("source_artifact_hash"),
    })


def _ci_cd_reliability_summary(data: dict[str, Any]) -> dict[str, Any]:
    return safe_summary({
        "workflow_name": data.get("workflow_name"),
        "workflow_path": data.get("workflow_path"),
        "required_checks_count": len(data.get("required_checks", []))
        if isinstance(data.get("required_checks"), list)
        else 0,
        "advisory_checks_count": len(data.get("advisory_checks", []))
        if isinstance(data.get("advisory_checks"), list)
        else 0,
        "github_default_setup_suspected": data.get("github_default_setup_suspected"),
    })


def _swift_codeql_advisory_parking_summary(data: dict[str, Any]) -> dict[str, Any]:
    return safe_summary({
        "parked_surface": data.get("parked_surface"),
        "recommendation": data.get("recommendation"),
        "required_ci_preserved": data.get("required_ci_preserved"),
        "default_ci_required": data.get("default_ci_required"),
        "codeql_languages_required": data.get("codeql_languages_required"),
        "codeql_languages_advisory": data.get("codeql_languages_advisory"),
    })


def _artifact_summary(artifact_id: str, data: dict[str, Any]) -> dict[str, Any]:
    summarizers = {
        "live_auth": _live_auth_summary,
        "security_intake": _security_intake_summary,
        "security_mission_candidates": _mission_candidates_summary,
        "security_mission_packets": _mission_packets_summary,
        "github_ci_cd_reliability": _ci_cd_reliability_summary,
        "swift_codeql_advisory_parking": _swift_codeql_advisory_parking_summary,
    }
    summarizer = summarizers.get(artifact_id)
    if summarizer is None:
        return safe_summary(data)
    return summarizer(data)


def _load_artifact(
    artifact_id: str, path: Path, *, expected_schema_version: str | None = None
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    descriptor: dict[str, Any] = {
        "artifact_id": artifact_id,
        "path": str(path),
        "present": False,
        "status": "missing",
        "artifact_hash": None,
        "schema_version": None,
        "summary": None,
    }
    if not path.exists():
        return descriptor, None

    raw = read_safe(path, raise_on_error=True)
    artifact_hash = _sha256_file(path)
    descriptor["present"] = True
    descriptor["artifact_hash"] = artifact_hash

    try:
        data = json.loads(raw.text)
    except json.JSONDecodeError as exc:
        descriptor["status"] = "invalid"
        descriptor["error_kind"] = "json_decode_error"
        descriptor["error"] = str(exc)
        return descriptor, None

    if not isinstance(data, dict):
        descriptor["status"] = "invalid"
        descriptor["error_kind"] = "invalid_root_type"
        return descriptor, None

    descriptor["content_hash"] = _sha256_text(_stable_json(data))
    schema_version = _normalize_text(data.get("schema_version"))
    descriptor["schema_version"] = schema_version
    if expected_schema_version and schema_version != expected_schema_version:
        descriptor["status"] = "invalid"
        descriptor["error_kind"] = "schema_version_mismatch"
        descriptor["summary"] = _artifact_summary(artifact_id, data)
        return descriptor, data

    descriptor["status"] = "present"
    descriptor["summary"] = _artifact_summary(artifact_id, data)
    return descriptor, data


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


def _route_counts(mission_candidates: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for candidate in mission_candidates:
        if not isinstance(candidate, dict):
            continue
        route = _normalize_text(candidate.get("route"), "unknown") or "unknown"
        counts[route] = counts.get(route, 0) + 1
    return dict(sorted(counts.items()))


def _lane_counts(mission_candidates: list[dict[str, Any]]) -> dict[str, int]:
    lanes = {
        "dependency_update_needed": 0,
        "codeql_security_fix_needed": 0,
        "code_quality_fix_needed": 0,
        "workflow_or_ci_fix_needed": 0,
        "permission_blocked": 0,
        "unknown_triage_needed": 0,
    }
    for candidate in mission_candidates:
        if not isinstance(candidate, dict):
            continue
        route = _normalize_text(candidate.get("route"), "unknown")
        source_surface = _normalize_text(candidate.get("source_surface"), "unknown")
        mission_type = _normalize_text(candidate.get("mission_type"), "unknown")
        if route == "ready_for_dependency_update":
            lanes["dependency_update_needed"] += 1
        elif route == "ready_for_investigation" and source_surface == "code_scanning":
            lanes["codeql_security_fix_needed"] += 1
        elif route == "advisory_only" and source_surface == "code_scanning":
            lanes["code_quality_fix_needed"] += 1
        elif (
            route == "permission_required"
            or mission_type == "permission_enablement_plan"
        ):
            lanes["permission_blocked"] += 1
        elif route in {"blocked_insufficient_evidence", "blocked_refused_surface"}:
            lanes["unknown_triage_needed"] += 1
    return lanes


def _artifact_descriptor_map(
    descriptors: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    return {
        str(descriptor.get("artifact_id")): descriptor
        for descriptor in descriptors
        if isinstance(descriptor, dict) and descriptor.get("artifact_id")
    }


def _operating_picture_sections(
    source_artifacts: list[dict[str, Any]], artifacts: dict[str, dict[str, Any] | None]
) -> dict[str, Any]:
    artifact_map = _artifact_descriptor_map(source_artifacts)
    required_surface_statuses = _required_surface_statuses(
        artifacts.get("live_auth"),
        artifacts.get("security_intake"),
        artifacts.get("github_ci_cd_reliability"),
    )
    packet_summary = _build_packet_summary(
        artifacts.get("security_mission_packets"),
        artifact_map.get("security_mission_packets"),
        artifact_map.get("security_mission_candidates"),
    )
    local_patch_lane_summary = _build_local_patch_lane_summary(
        artifacts.get("security_mission_candidates"),
        artifacts.get("github_ci_cd_reliability"),
    )
    return {
        "auth_summary": _build_auth_summary(artifacts.get("live_auth")),
        "permission_summary": {
            "required_read_surfaces": list(_REQUIRED_READ_SURFACES),
            "known_available_surfaces": required_surface_statuses[0],
            "refused_surfaces": required_surface_statuses[1],
        },
        "intake_summary": _build_intake_summary(
            artifacts.get("security_intake"), artifacts.get("github_ci_cd_reliability")
        ),
        "candidate_summary": _build_candidate_summary(
            artifacts.get("security_mission_candidates"),
            artifact_map.get("security_mission_candidates"),
        ),
        "packet_summary": packet_summary,
        "local_patch_lane_summary": local_patch_lane_summary,
        "next_recommended_actions": _next_actions(
            auth_summary=_build_auth_summary(artifacts.get("live_auth")),
            intake_present=artifacts.get("security_intake") is not None,
            candidate_present=artifacts.get("security_mission_candidates") is not None,
            packet_present=artifacts.get("security_mission_packets") is not None,
            packet_index_stale=bool(packet_summary.get("packet_index_stale")),
            permission_blocked_count=int(
                local_patch_lane_summary["permission_blocked"]
            ),
        ),
    }


def _required_surface_statuses(
    live_auth: dict[str, Any] | None,
    intake: dict[str, Any] | None,
    ci_cd: dict[str, Any] | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    known_available: list[dict[str, Any]] = []
    refused: list[dict[str, Any]] = []

    intake_surfaces = {}
    if isinstance(intake, dict):
        for item in intake.get("source_surfaces", []):
            if isinstance(item, dict) and item.get("surface"):
                intake_surfaces[str(item["surface"])] = item

    live_paths = []
    if isinstance(live_auth, dict):
        live_paths.append("docs/json/governance/live_github_auth_result.v1.json")
    intake_paths = []
    if isinstance(intake, dict):
        intake_paths.append(
            "docs/json/governance/github_security_intake_result.v1.json"
        )
    ci_paths = []
    if isinstance(ci_cd, dict):
        ci_paths.append("docs/json/governance/github_ci_cd_reliability_v1.v1.json")

    known_available.append({
        "surface": "code_scanning_alerts",
        "status": "present" if intake_surfaces.get("code_scanning") else "missing",
        "evidence_paths": intake_paths if intake_surfaces.get("code_scanning") else [],
    })
    known_available.append({
        "surface": "dependabot_alerts",
        "status": "refused" if intake_surfaces.get("dependabot") else "missing",
        "evidence_paths": intake_paths if intake_surfaces.get("dependabot") else [],
    })
    known_available.append({
        "surface": "checks",
        "status": "present" if ci_cd else "missing",
        "evidence_paths": ci_paths if ci_cd else [],
    })
    known_available.append({
        "surface": "actions",
        "status": "present" if ci_cd else "missing",
        "evidence_paths": ci_paths if ci_cd else [],
    })
    known_available.append({
        "surface": "metadata",
        "status": "present" if live_auth else "missing",
        "evidence_paths": live_paths if live_auth else [],
    })

    refused.append({
        "surface": "dependabot_alerts",
        "status": "refused",
        "reason": "missing_permission_or_not_enabled",
        "required_permission_name": "dependabot_alerts",
        "evidence_paths": intake_paths,
    })
    refused.append({
        "surface": "secret_scanning_alerts",
        "status": "refused",
        "reason": "missing_permission_or_not_enabled",
        "required_permission_name": "secret_scanning_alerts",
        "evidence_paths": intake_paths,
    })
    refused.append({
        "surface": "repository_security_advisories",
        "status": "refused",
        "reason": "missing_permission_or_not_enabled",
        "required_permission_name": "repository_security_advisories",
        "evidence_paths": [],
    })
    return known_available, refused


def _next_actions(
    *,
    auth_summary: dict[str, Any],
    intake_present: bool,
    candidate_present: bool,
    packet_present: bool,
    packet_index_stale: bool,
    permission_blocked_count: int,
) -> list[str]:
    actions: list[str] = []
    if not auth_summary.get("installation_access_proven"):
        actions.append("fix_auth")
    elif not intake_present and not candidate_present:
        actions.append("run_live_intake_dry_run")
    elif intake_present and not candidate_present:
        actions.append("regenerate_candidates")
    elif candidate_present and not packet_present:
        actions.append("regenerate_packets")
    elif packet_index_stale:
        actions.append("regenerate_packets")
    else:
        actions.append("run_packet_lane")
    if permission_blocked_count > 0:
        actions.append("request_permission")
    if not actions:
        actions.append("no_action")
    result: list[str] = []
    for action in actions:
        if action not in result:
            result.append(action)
    return result


def _packet_index_stale(
    *,
    candidate_artifact: dict[str, Any] | None,
    candidate_descriptor: dict[str, Any] | None,
    packet_artifact: dict[str, Any] | None,
    packet_descriptor: dict[str, Any] | None,
) -> bool:
    if candidate_artifact is None:
        return False
    if (
        packet_artifact is None
        or packet_descriptor is None
        or candidate_descriptor is None
    ):
        return True
    packet_source_hash = _normalize_text(
        packet_artifact.get("source_artifact_hash"), default=None
    )
    candidate_file_hash = _normalize_text(
        candidate_descriptor.get("artifact_hash"), default=None
    )
    if packet_source_hash is None or candidate_file_hash is None:
        return True
    return packet_source_hash != candidate_file_hash


def _assert_content_light(value: Any) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key in _FORBIDDEN_FIELDS:
                raise ValueError(
                    "forbidden_key_detected: operating picture contains forbidden "
                    f"field '{key}'"
                )
            _assert_content_light(item)
    elif isinstance(value, list):
        for item in value:
            _assert_content_light(item)
    elif isinstance(value, str):
        if scan_response_for_secrets(value):
            raise ValueError(
                "forbidden_secret_like_string_detected: operating picture contains "
                "secret-like content"
            )
        for pattern in _FORBIDDEN_VALUE_PATTERNS:
            if pattern.search(value):
                raise ValueError(
                    "forbidden_content_detected: operating picture contains "
                    f"'{pattern.pattern}'"
                )


def build_github_operating_picture(
    *,
    context: dict[str, Any],
    source_artifacts: list[dict[str, Any]],
    artifacts: dict[str, dict[str, Any] | None],
) -> dict[str, Any]:
    owner = context.get("owner")
    repo = context.get("repo")
    generated_at_utc = context.get("generated_at_utc")
    branch = context.get("branch")
    head = context.get("head")
    sections = _operating_picture_sections(source_artifacts, artifacts)
    evidence_paths = [
        descriptor["path"]
        for descriptor in sorted(
            source_artifacts, key=lambda item: str(item["artifact_id"])
        )
        if descriptor.get("present")
        and isinstance(descriptor.get("path"), str)
        and descriptor["path"]
    ]
    report = {
        "schema_version": "rig.github.operating_picture.v1",
        "generated_at_utc": generated_at_utc or _now_iso(),
        "branch": branch,
        "head": head,
        "owner": owner,
        "repo": repo,
        "content_light": True,
        "remote_mutation": False,
        "source_artifacts": sorted(
            source_artifacts, key=lambda item: str(item["artifact_id"])
        ),
        "auth_summary": sections["auth_summary"],
        "permission_summary": sections["permission_summary"],
        "intake_summary": sections["intake_summary"],
        "candidate_summary": sections["candidate_summary"],
        "packet_summary": sections["packet_summary"],
        "local_patch_lane_summary": sections["local_patch_lane_summary"],
        "next_recommended_actions": sections["next_recommended_actions"],
        "evidence_paths": evidence_paths,
        "redaction_status": {
            "content_light": True,
            "forbidden_strings_present": False,
            "redaction_rule_count": len(_FORBIDDEN_FIELDS),
            "checked_artifact_count": len(source_artifacts),
        },
        "remaining_seams": [
            "dependabot intake remains refusal-safe until endpoint or permission coverage changes",
            "secret_scanning_alerts and repository_security_advisories remain permission-gated surfaces",
            "workflow-run and check-run live reads are still represented through local CI/CD evidence",
        ],
    }
    report["summary"] = {
        "auth_health": "installation_access_proven"
        if sections["auth_summary"].get("installation_access_proven")
        else "auth_unproven",
        "intake_health": "partial_refusal"
        if sections["intake_summary"]["dependabot"]["status"] == "refused"
        else "present",
        "packet_health": "fresh"
        if not sections["packet_summary"].get("packet_index_stale")
        else "stale",
        "packet_index_stale": sections["packet_summary"].get(
            "packet_index_stale", False
        ),
        "next_recommended_action": (
            sections["next_recommended_actions"][0]
            if sections["next_recommended_actions"]
            else "no_action"
        ),
    }
    _assert_content_light(report)
    return safe_summary(report)


def _build_auth_summary(live_auth_artifact: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(live_auth_artifact, dict):
        return {
            "app_installation_configured": False,
            "installation_access_proven": False,
            "token_present": False,
            "token_hash_present": False,
            "token_narrowing_requested": False,
            "token_narrowing_effective": False,
            "unsafe_broad_token_used": False,
            "public_release_ready": False,
            "installation_id_hash": None,
            "accessible_repo_count": 0,
            "repository_selection": None,
            "permission_mode": None,
        }
    config_summary = live_auth_artifact.get("config_summary")
    if not isinstance(config_summary, dict):
        config_summary = {}
    live_results = live_auth_artifact.get("live_results")
    if not isinstance(live_results, dict):
        live_results = {}
    installation_access = live_results.get("installation_access")
    if not isinstance(installation_access, dict):
        installation_access = {}
    token_exchange = live_results.get("token_exchange")
    if not isinstance(token_exchange, dict):
        token_exchange = {}
    return {
        "app_installation_configured": bool(config_summary.get("app_auth_possible")),
        "installation_access_proven": installation_access.get("installation_access")
        == "success",
        "token_present": bool(token_exchange.get("token_present")),
        "token_hash_present": bool(token_exchange.get("token_hash")),
        "token_narrowing_requested": bool(
            live_results.get("token_narrowing_requested")
        ),
        "token_narrowing_effective": bool(
            live_results.get("token_narrowing_effective")
        ),
        "unsafe_broad_token_used": bool(live_results.get("unsafe_broad_token_used")),
        "public_release_ready": bool(live_results.get("public_release_ready")),
        "installation_id_hash": installation_access.get("installation_id_hash"),
        "accessible_repo_count": int(
            installation_access.get("accessible_repo_count") or 0
        ),
        "repository_selection": installation_access.get("repository_selection"),
        "permission_mode": live_results.get("permission_mode"),
    }


def _build_intake_summary(
    security_intake_artifact: dict[str, Any] | None,
    ci_cd_reliability_artifact: dict[str, Any] | None,
) -> dict[str, Any]:
    if not isinstance(security_intake_artifact, dict):
        security_intake_artifact = {}
    counts = security_intake_artifact.get("counts")
    if not isinstance(counts, dict):
        counts = {}
    source_surfaces = security_intake_artifact.get("source_surfaces")
    source_surface_map: dict[str, dict[str, Any]] = {}
    if isinstance(source_surfaces, list):
        for item in source_surfaces:
            if isinstance(item, dict) and item.get("surface"):
                source_surface_map[str(item["surface"])] = item
    ci_present = isinstance(ci_cd_reliability_artifact, dict)
    ci_paths = (
        ["docs/json/governance/github_ci_cd_reliability_v1.v1.json"]
        if ci_present
        else []
    )
    intake_paths = ["docs/json/governance/github_security_intake_result.v1.json"]
    return {
        "code_scanning": {
            "status": "present"
            if source_surface_map.get("code_scanning")
            else "missing",
            "total": counts.get("code_scanning_total", 0),
            "open": counts.get("code_scanning_open", 0),
            "evidence_paths": intake_paths
            if source_surface_map.get("code_scanning")
            else [],
        },
        "dependabot": {
            "status": "refused" if source_surface_map.get("dependabot") else "missing",
            "total": counts.get("dependabot_total", 0),
            "open": counts.get("dependabot_open", 0),
            "refusal_reason": "missing_permission_or_not_enabled"
            if source_surface_map.get("dependabot")
            else None,
            "evidence_paths": intake_paths
            if source_surface_map.get("dependabot")
            else [],
        },
        "checks": {
            "status": "present" if ci_present else "missing",
            "evidence_paths": ci_paths,
        },
        "workflow_runs": {
            "status": "present" if ci_present else "missing",
            "evidence_paths": ci_paths,
        },
    }


def _build_candidate_summary(
    mission_candidates_artifact: dict[str, Any] | None,
    descriptor: dict[str, Any] | None,
) -> dict[str, Any]:
    if not isinstance(mission_candidates_artifact, dict):
        return {
            "source_artifact_path": descriptor.get("path") if descriptor else None,
            "artifact_hash": descriptor.get("artifact_hash") if descriptor else None,
            "source_artifact_hash": None,
            "candidate_count": 0,
            "ready_for_investigation_count": 0,
            "advisory_only_count": 0,
            "permission_required_count": 0,
        }
    summary = mission_candidates_artifact.get("summary")
    if not isinstance(summary, dict):
        summary = {}
    counts = {
        "ready_for_investigation_count": int(
            summary.get("ready_candidate_count")
            or mission_candidates_artifact.get("ready_candidate_count")
            or 0
        ),
        "advisory_only_count": int(
            summary.get("advisory_candidate_count")
            or mission_candidates_artifact.get("advisory_candidate_count")
            or 0
        ),
        "permission_required_count": int(
            summary.get("blocked_candidate_count")
            or mission_candidates_artifact.get("blocked_candidate_count")
            or 0
        ),
    }
    return {
        "source_artifact_path": mission_candidates_artifact.get("source_artifact_path"),
        "artifact_hash": descriptor.get("artifact_hash") if descriptor else None,
        "source_artifact_hash": mission_candidates_artifact.get("source_artifact_hash"),
        "candidate_count": int(
            mission_candidates_artifact.get("mission_candidate_count") or 0
        ),
        **counts,
    }


def _build_packet_summary(
    mission_packets_artifact: dict[str, Any] | None,
    packet_descriptor: dict[str, Any] | None,
    candidate_descriptor: dict[str, Any] | None,
) -> dict[str, Any]:
    candidate_file_hash = None
    if candidate_descriptor:
        candidate_file_hash = candidate_descriptor.get("content_hash")
        if candidate_file_hash is None:
            candidate_file_hash = candidate_descriptor.get("artifact_hash")
    if not isinstance(mission_packets_artifact, dict):
        return {
            "packet_index_path": packet_descriptor.get("path")
            if packet_descriptor
            else None,
            "artifact_hash": packet_descriptor.get("artifact_hash")
            if packet_descriptor
            else None,
            "source_artifact_path": mission_packets_artifact.get("source_artifact_path")
            if isinstance(mission_packets_artifact, dict)
            else None,
            "source_artifact_hash": None,
            "packet_count": 0,
            "excluded_candidate_count": 0,
            "excluded_by_route": {},
            "packet_index_stale": bool(candidate_descriptor),
        }
    summary = mission_packets_artifact.get("summary")
    if not isinstance(summary, dict):
        summary = {}
    packet_source_hash = summary.get(
        "source_artifact_hash"
    ) or mission_packets_artifact.get("source_artifact_hash")
    packet_count = int(mission_packets_artifact.get("packet_count") or 0)
    excluded_candidate_count = int(
        mission_packets_artifact.get("excluded_candidate_count") or 0
    )
    excluded_by_route = mission_packets_artifact.get("excluded_by_route")
    if not isinstance(excluded_by_route, dict):
        excluded_by_route = {}
    return {
        "packet_index_path": mission_packets_artifact.get("source_artifact_path"),
        "artifact_hash": packet_descriptor.get("artifact_hash")
        if packet_descriptor
        else None,
        "source_artifact_path": mission_packets_artifact.get("source_artifact_path"),
        "source_artifact_hash": packet_source_hash,
        "packet_count": packet_count,
        "excluded_candidate_count": excluded_candidate_count,
        "excluded_by_route": dict(sorted(excluded_by_route.items())),
        "packet_index_stale": bool(
            candidate_file_hash is not None
            and packet_source_hash != candidate_file_hash
        ),
    }


def _build_local_patch_lane_summary(
    mission_candidates_artifact: dict[str, Any] | None,
    ci_cd_reliability_artifact: dict[str, Any] | None,
) -> dict[str, int]:
    if not isinstance(mission_candidates_artifact, dict):
        mission_candidates = []
    else:
        mission_candidates = mission_candidates_artifact.get("mission_candidates", [])
        if not isinstance(mission_candidates, list):
            mission_candidates = []
    lanes = _lane_counts([
        candidate for candidate in mission_candidates if isinstance(candidate, dict)
    ])
    lanes["workflow_or_ci_fix_needed"] = 0
    if isinstance(ci_cd_reliability_artifact, dict):
        lanes["workflow_or_ci_fix_needed"] = 0
    return lanes


def _source_paths_from_mapping(
    source_paths: dict[str, Path | str] | None,
) -> dict[str, Path | str]:
    if source_paths is None:
        return {}
    return {
        key: value
        for key, value in source_paths.items()
        if key in _SOURCE_PATH_KEYS and value is not None
    }


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def build_github_operating_picture_from_paths(
    *,
    owner: str | None = None,
    repo: str | None = None,
    source_paths: dict[str, Path | str] | None = None,
    generated_at_utc: str | None = None,
    repo_root: Path = _REPO_ROOT,
) -> dict[str, Any]:
    source_paths = _source_paths_from_mapping(source_paths)
    source_specs = [
        (
            "live_auth",
            Path(source_paths.get("live_auth_json", _DEFAULT_LIVE_AUTH_JSON)),
            "rig.github.live_auth_result.v1",
        ),
        (
            "security_intake",
            Path(
                source_paths.get("security_intake_json", _DEFAULT_SECURITY_INTAKE_JSON)
            ),
            "rig.github.security_intake.v1",
        ),
        (
            "security_mission_candidates",
            Path(
                source_paths.get(
                    "mission_candidates_json", _DEFAULT_MISSION_CANDIDATES_JSON
                )
            ),
            "rig.github.security_mission_candidates.v1",
        ),
        (
            "security_mission_packets",
            Path(
                source_paths.get("mission_packets_json", _DEFAULT_MISSION_PACKETS_JSON)
            ),
            "rig.github.security_mission_packets.v1",
        ),
        (
            "github_ci_cd_reliability",
            Path(
                source_paths.get(
                    "ci_cd_reliability_json", _DEFAULT_CI_CD_RELIABILITY_JSON
                )
            ),
            "rig.github_ci_cd_reliability.v1",
        ),
        (
            "swift_codeql_advisory_parking",
            Path(
                source_paths.get(
                    "swift_codeql_advisory_parking_json",
                    _DEFAULT_SWIFT_CODEQL_ADVISORY_PARKING_JSON,
                )
            ),
            "rig.swift_codeql_advisory_parking.v1",
        ),
    ]
    descriptors: list[dict[str, Any]] = []
    live_auth = None
    security_intake = None
    mission_candidates = None
    mission_packets = None
    ci_cd_reliability = None
    swift_codeql_advisory_parking = None
    for artifact_id, path, schema_version in source_specs:
        descriptor, data = _load_artifact(
            artifact_id, path, expected_schema_version=schema_version
        )
        descriptors.append(descriptor)
        match artifact_id:
            case "live_auth":
                live_auth = data
            case "security_intake":
                security_intake = data
            case "security_mission_candidates":
                mission_candidates = data
            case "security_mission_packets":
                mission_packets = data
            case "github_ci_cd_reliability":
                ci_cd_reliability = data
            case "swift_codeql_advisory_parking":
                swift_codeql_advisory_parking = data

    branch, head = _load_git_metadata(repo_root)
    report = build_github_operating_picture(
        context={
            "owner": owner,
            "repo": repo,
            "generated_at_utc": generated_at_utc,
            "branch": branch,
            "head": head,
        },
        source_artifacts=descriptors,
        artifacts={
            "live_auth": live_auth,
            "security_intake": security_intake,
            "security_mission_candidates": mission_candidates,
            "security_mission_packets": mission_packets,
            "github_ci_cd_reliability": ci_cd_reliability,
            "swift_codeql_advisory_parking": swift_codeql_advisory_parking,
        },
    )
    return report


def write_github_operating_picture(
    path: Path | str = _DEFAULT_OUTPUT_JSON,
    *,
    owner: str | None = None,
    repo: str | None = None,
    source_paths: dict[str, Path | str] | None = None,
    generated_at_utc: str | None = None,
    repo_root: Path = _REPO_ROOT,
) -> dict[str, Any]:
    report = build_github_operating_picture_from_paths(
        owner=owner,
        repo=repo,
        source_paths=source_paths,
        generated_at_utc=generated_at_utc,
        repo_root=repo_root,
    )
    output_path = Path(path)
    _write_json(output_path, report)
    return report


__all__ = [
    "GitHubOperatingPictureError",
    "build_github_operating_picture",
    "build_github_operating_picture_from_paths",
    "write_github_operating_picture",
]
