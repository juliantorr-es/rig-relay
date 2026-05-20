"""GitHub security mission packet generation - local, deterministic, content-light."""

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
    / "github_security_mission_candidates_v1.v1.json"
)
_DEFAULT_PACKET_DIR = _REPO_ROOT / ".build" / "rig-relay" / "security-mission-packets"

_READY_ROUTE = "ready_for_investigation"
_ROUTE_ORDER = {
    "ready_for_investigation": 0,
    "advisory_only": 1,
    "permission_required": 2,
    "blocked_insufficient_evidence": 3,
    "blocked_refused_surface": 4,
    "noop": 5,
}

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

_ALLOWED_NEXT_STEPS = [
    "inspect local artifact evidence",
    "inspect repository files manually/read-only",
    "run targeted tests if needed",
    "classify finding",
    "propose remediation plan",
    "produce local investigation receipt",
]

_FORBIDDEN_NEXT_STEPS = [
    "create GitHub issue",
    "create PR",
    "create branch",
    "dismiss alert",
    "request autofix",
    "commit autofix",
    "edit source files",
    "edit workflows",
    "modify dependencies",
    "upload SARIF",
    "perform remote mutation",
    "persist raw credential material or raw alert bodies",
]

_ACCEPTANCE_CRITERIA = [
    "finding classification recorded",
    "evidence references checked",
    "recommended next action selected",
    "no mutation performed",
    "content-light receipt emitted",
    "if remediation is needed, a separate governed mission is proposed rather than performed",
]

_STOP_CONDITIONS = [
    "evidence insufficient",
    "candidate maps to permission-required surface",
    "candidate requires write permission",
    "candidate requires network/live GitHub mutation",
    "candidate would require persisting raw code snippet or credential material",
    "candidate is duplicate/advisory-only",
]


class GitHubSecurityMissionPacketError(Exception):
    """Raised when mission candidates cannot be converted into mission packets."""


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


def _assert_no_forbidden_content(value: Any) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key in _FORBIDDEN_KEYS:
                raise ValueError(
                    "forbidden_key_detected: mission packet artifact contains "
                    f"forbidden field '{key}'"
                )
            _assert_no_forbidden_content(item)
    elif isinstance(value, list):
        for item in value:
            _assert_no_forbidden_content(item)
    elif isinstance(value, str):
        if scan_response_for_secrets(value):
            raise ValueError(
                "forbidden_secret_like_string_detected: mission packet artifact "
                "contains secret-like content"
            )
        for pattern in _FORBIDDEN_VALUE_PATTERNS:
            if pattern.search(value):
                raise ValueError(
                    "forbidden_content_detected: mission packet artifact contains "
                    f"'{pattern.pattern}'"
                )


def _candidate_group_map(
    route_groups: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    mapping: dict[str, dict[str, Any]] = {}
    for group in route_groups:
        if not isinstance(group, dict):
            continue
        for candidate_id in group.get("candidate_ids", []):
            if isinstance(candidate_id, str) and candidate_id:
                mapping[candidate_id] = group
    return mapping


def _route_counts(mission_candidates: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for candidate in mission_candidates:
        route = _normalize_lower(candidate.get("route"))
        counts[route] = counts.get(route, 0) + 1
    return counts


def _build_packet(
    candidate: dict[str, Any],
    route_group: dict[str, Any],
    *,
    packet_dir: Path,
    source_artifact_hash: str,
    selected_route: str = _READY_ROUTE,
) -> dict[str, Any]:
    mission_candidate_id = _normalize_text(candidate.get("mission_candidate_id"))
    source_candidate_id = _normalize_text(candidate.get("source_candidate_id"))
    source_surface = _normalize_lower(candidate.get("source_surface"))
    mission_type = _normalize_lower(candidate.get("mission_type"))
    route = _normalize_lower(candidate.get("route"))
    priority = _normalize_lower(candidate.get("priority"), default="p4")
    normalized_severity = _normalize_lower(
        candidate.get("normalized_severity"), default="unknown"
    )
    recommended_action = _normalize_text(candidate.get("recommended_action"))
    proposed_next_action = _normalize_text(candidate.get("proposed_next_action"))
    source_alert_count = int(route_group.get("candidate_count") or 0)
    investigation_goal = _packet_investigation_goal(source_candidate_id)
    investigation_constraints = _packet_investigation_constraints()
    evidence_refs = _packet_evidence_refs(
        mission_candidate_id=mission_candidate_id,
        source_candidate_id=source_candidate_id,
        route_group_id=_normalize_text(route_group.get("route_group_id")),
        source_artifact_hash=source_artifact_hash,
    )
    evidence_hashes = _packet_evidence_hashes(
        mission_candidate_id=mission_candidate_id,
        source_candidate_id=source_candidate_id,
        route_group_id=_normalize_text(route_group.get("route_group_id")),
        route_group_key=_normalize_text(route_group.get("group_key")),
        source_surface=source_surface,
        mission_type=mission_type,
        route=route,
        priority=priority,
        normalized_severity=normalized_severity,
        source_alert_count=source_alert_count,
    )
    packet_id = _sha256_text(
        _stable_json([
            mission_candidate_id,
            source_candidate_id,
            source_surface,
            mission_type,
            route,
            priority,
            normalized_severity,
            source_alert_count,
            evidence_hashes,
        ])
    )
    return {
        "packet_id": packet_id,
        "packet_path": _packet_path(packet_dir, source_candidate_id),
        "mission_candidate_id": mission_candidate_id,
        "source_candidate_id": source_candidate_id,
        "source_surface": source_surface,
        "mission_type": mission_type,
        "route": route,
        "priority": priority,
        "normalized_severity": normalized_severity,
        "recommended_action": recommended_action,
        "proposed_next_action": proposed_next_action,
        "investigation_goal": investigation_goal,
        "investigation_constraints": investigation_constraints,
        "evidence_refs": evidence_refs,
        "evidence_hashes": evidence_hashes,
        "source_alert_count": source_alert_count,
        "content_light": True,
        "remote_mutation": False,
        "mutation_allowed": False,
        "requires_human_review": True,
        "allowed_next_steps": list(_ALLOWED_NEXT_STEPS),
        "forbidden_next_steps": list(_FORBIDDEN_NEXT_STEPS),
        "acceptance_criteria": list(_ACCEPTANCE_CRITERIA),
        "stop_conditions": list(_STOP_CONDITIONS),
        "source_hashes": {
            "source_artifact_hash": source_artifact_hash,
            "route_group_id_hash": hash_identifier(
                _normalize_text(route_group.get("route_group_id"))
            ),
            "route_group_key_hash": hash_identifier(
                _normalize_text(route_group.get("group_key"))
            ),
        },
    }


def _packet_path(packet_dir: Path, source_candidate_id: str) -> str:
    return _normalize_path(packet_dir / f"{source_candidate_id}.v1.json")


def _packet_investigation_goal(source_candidate_id: str) -> str:
    return (
        "Investigate grouped code-scanning alerts for candidate "
        f"{source_candidate_id}. Determine whether it is true positive, "
        "false positive, duplicate, or advisory-only."
    )


def _packet_investigation_constraints() -> list[str]:
    return [
        "content_light only",
        "read-only local investigation",
        "no remote mutation",
        "no raw alert bodies or source snippets",
        "no GitHub issue, PR, or branch creation",
    ]


def _packet_evidence_refs(
    *,
    mission_candidate_id: str,
    source_candidate_id: str,
    route_group_id: str,
    source_artifact_hash: str,
) -> list[str]:
    return [
        f"mission_candidate_id:{mission_candidate_id}",
        f"source_candidate_id:{source_candidate_id}",
        f"route_group_id:{route_group_id}",
        f"source_artifact_hash:{source_artifact_hash}",
    ]


def _packet_evidence_hashes(
    *,
    mission_candidate_id: str,
    source_candidate_id: str,
    route_group_id: str,
    route_group_key: str,
    source_surface: str,
    mission_type: str,
    route: str,
    priority: str,
    normalized_severity: str,
    source_alert_count: int,
) -> dict[str, str]:
    return {
        "mission_candidate_id_hash": hash_identifier(mission_candidate_id),
        "source_candidate_id_hash": hash_identifier(source_candidate_id),
        "route_group_id_hash": hash_identifier(route_group_id),
        "route_group_key_hash": hash_identifier(route_group_key),
        "source_surface_hash": hash_identifier(source_surface),
        "mission_type_hash": hash_identifier(mission_type),
        "route_hash": hash_identifier(route),
        "priority_hash": hash_identifier(priority),
        "normalized_severity_hash": hash_identifier(normalized_severity),
        "source_alert_count_hash": hash_identifier(str(source_alert_count)),
    }


def _sorted_packet_key(packet: dict[str, Any]) -> tuple[int, str]:
    return (
        _ROUTE_ORDER.get(str(packet.get("route", "ready_for_investigation")), 99),
        str(packet.get("packet_id", "")),
    )


def _build_route_summary(
    mission_candidates: list[dict[str, Any]], packets: list[dict[str, Any]]
) -> dict[str, Any]:
    input_by_route = dict(sorted(_route_counts(mission_candidates).items()))
    selected_by_route: dict[str, int] = {}
    for packet in packets:
        route = _normalize_lower(packet.get("route"))
        selected_by_route[route] = selected_by_route.get(route, 0) + 1
    return {
        "selection_mode": "ready_only",
        "input_by_route": input_by_route,
        "selected_by_route": dict(sorted(selected_by_route.items())),
        "selected_route": _READY_ROUTE,
    }


def _build_risk_summary(report: dict[str, Any]) -> dict[str, Any]:
    mission_summary = report.get("summary", {})
    if not isinstance(mission_summary, dict):
        mission_summary = {}
    return {
        "content_light": True,
        "remote_mutation": False,
        "mutation_allowed": False,
        "requires_human_review": True,
        "ready_candidate_count": int(mission_summary.get("ready_candidate_count") or 0),
        "advisory_candidate_count": int(
            mission_summary.get("advisory_candidate_count") or 0
        ),
        "permission_required_candidate_count": int(
            mission_summary.get("blocked_candidate_count") or 0
        ),
    }


def _build_summary(
    *, packet_count: int, excluded_by_route: dict[str, int], source_artifact_hash: str
) -> dict[str, Any]:
    return {
        "packet_count": packet_count,
        "excluded_candidate_count": sum(excluded_by_route.values()),
        "excluded_by_route": dict(sorted(excluded_by_route.items())),
        "source_artifact_hash": source_artifact_hash,
        "remote_mutation": False,
    }


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def project_github_security_mission_packets(
    mission_candidates: dict[str, Any],
    *,
    source_artifact_path: str,
    packet_dir: Path | str = _DEFAULT_PACKET_DIR,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    if (
        _normalize_text(mission_candidates.get("schema_version"))
        != "rig.github.security_mission_candidates.v1"
    ):
        raise GitHubSecurityMissionPacketError(
            "expected rig.github.security_mission_candidates.v1 mission-candidate artifact"
        )
    for required_key in ("mission_candidates", "route_groups", "summary"):
        if required_key not in mission_candidates:
            raise GitHubSecurityMissionPacketError(
                f"missing required mission-candidate field '{required_key}'"
            )

    packets_dir = Path(packet_dir)
    generated_at = generated_at_utc or _now_iso()
    source_hash = _sha256_text(_stable_json(mission_candidates))

    candidates = mission_candidates.get("mission_candidates", [])
    route_groups = mission_candidates.get("route_groups", [])
    if not isinstance(candidates, list):
        raise GitHubSecurityMissionPacketError(
            "expected mission_candidates to be a list"
        )
    if not isinstance(route_groups, list):
        raise GitHubSecurityMissionPacketError("expected route_groups to be a list")

    route_group_by_candidate_id = _candidate_group_map([
        group for group in route_groups if isinstance(group, dict)
    ])

    selected_packets: list[dict[str, Any]] = []
    excluded_by_route: dict[str, int] = {}
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        route = _normalize_lower(candidate.get("route"))
        if route == _READY_ROUTE:
            group = route_group_by_candidate_id.get(
                _normalize_text(candidate.get("mission_candidate_id"))
            )
            if group is None:
                raise GitHubSecurityMissionPacketError(
                    "ready mission candidate is missing a matching route group"
                )
            packet = _build_packet(
                candidate,
                group,
                packet_dir=packets_dir,
                source_artifact_hash=source_hash,
            )
            selected_packets.append(packet)
        else:
            excluded_by_route[route] = excluded_by_route.get(route, 0) + 1

    selected_packets.sort(key=_sorted_packet_key)

    for packet in selected_packets:
        packet_file = Path(packet["packet_path"])
        _write_json(packet_file, safe_summary(packet))

    report = {
        "schema_version": "rig.github.security_mission_packets.v1",
        "generated_at_utc": generated_at,
        "source_artifact_path": source_artifact_path,
        "source_artifact_hash": source_hash,
        "packet_dir": _normalize_path(packets_dir),
        "content_light": True,
        "remote_mutation": False,
        "packet_count": len(selected_packets),
        "excluded_candidate_count": sum(excluded_by_route.values()),
        "excluded_by_route": dict(sorted(excluded_by_route.items())),
        "packets": selected_packets,
        "route_summary": _build_route_summary(candidates, selected_packets),
        "risk_summary": _build_risk_summary(mission_candidates),
    }
    report["summary"] = _build_summary(
        packet_count=report["packet_count"],
        excluded_by_route=excluded_by_route,
        source_artifact_hash=source_hash,
    )
    _assert_no_forbidden_content(report)
    return safe_summary(report)


def project_github_security_mission_packets_from_path(
    input_path: Path | str = _DEFAULT_SOURCE_ARTIFACT,
    *,
    source_artifact_path: str | None = None,
    packet_dir: Path | str = _DEFAULT_PACKET_DIR,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    path = Path(input_path)
    raw = read_safe(path, raise_on_error=True)
    mission_candidates = json.loads(raw.text)
    display_path = source_artifact_path or _normalize_path(path)
    return project_github_security_mission_packets(
        mission_candidates,
        source_artifact_path=display_path,
        packet_dir=packet_dir,
        generated_at_utc=generated_at_utc,
    )


__all__ = [
    "GitHubSecurityMissionPacketError",
    "project_github_security_mission_packets",
    "project_github_security_mission_packets_from_path",
]
