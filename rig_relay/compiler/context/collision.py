"""COLLISION mode — compile collision warnings for requesting agent.

Checks requested paths against active path reservations in the
coordination store. Returns structured collision report with
severity ratings and recommended actions.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from rig_relay.coordination.models import CoordinationPathReservation, salted_path_hash
from rig_relay.coordination.store import CoordinationStore
from rig_relay.tracing.golden_path import build_golden_path_event
from rig_relay.tracing.store import get_default_trace_store

_STORE_SUBDIR = Path(".build") / "rig-relay" / "coordination"
_HIGH_SEVERITY_THRESHOLD = 2


def _emit_collision_degraded_trace(requesting_paths: list[str]) -> None:
    try:
        store = get_default_trace_store()
        event = build_golden_path_event(
            event_type="context.collision_degraded",
            correlation={"coordination_store_available": False},
            payload={
                "requesting_paths_count": len(requesting_paths),
                "evidence_status": "missing",
            },
        )
        store.write(event)
    except Exception:
        pass


def _resolve_store_path(coordination_store_path: Path | None) -> Path:
    if coordination_store_path is not None:
        return coordination_store_path.resolve()
    return (Path.cwd() / _STORE_SUBDIR).resolve()


def _path_in_reservation(path: str, reservation: CoordinationPathReservation) -> bool:
    for reserved in reservation.paths:
        if path == reserved or path.startswith(reserved.rstrip("/") + "/"):
            return True
        if reserved.startswith(path.rstrip("/") + "/") or reserved == path:
            return True
    return False


def _severity(mode: str, status: str) -> str:
    if mode == "write" and status == "active":
        return "blocked"
    if mode == "write":
        return "high"
    if status == "conflicted":
        return "high"
    return "moderate"


def _recommend_action(
    path: str, reservation: CoordinationPathReservation
) -> dict[str, str | bool]:
    mode = reservation.mode
    status = reservation.status
    expires = reservation.expires_at

    if expires:
        try:
            expires_dt = datetime.fromisoformat(expires.replace("Z", "+00:00"))
            now = datetime.now(UTC)
            if expires_dt <= now:
                return {
                    "wait_for_release": True,
                    "escalate": False,
                    "request_handoff": False,
                    "abandon": False,
                }
        except (ValueError, TypeError):
            pass

    if mode == "write" and status == "active":
        return {
            "wait_for_release": False,
            "escalate": True,
            "request_handoff": True,
            "abandon": False,
        }
    if status == "conflicted":
        return {
            "wait_for_release": False,
            "escalate": True,
            "request_handoff": False,
            "abandon": True,
        }
    return {
        "wait_for_release": True,
        "escalate": False,
        "request_handoff": False,
        "abandon": False,
    }


def _overall_risk(severities: list[str]) -> str:
    if "blocked" in severities:
        return "blocked"
    if severities.count("high") >= _HIGH_SEVERITY_THRESHOLD:
        return "high"
    if "high" in severities:
        return "moderate"
    if "moderate" in severities:
        return "low"
    return "none"


def compile_collision_report(
    requesting_paths: list[str], coordination_store_path: Path | None = None
) -> dict[str, Any]:
    store_root = _resolve_store_path(coordination_store_path)

    if not store_root.is_dir():
        _emit_collision_degraded_trace(requesting_paths)
        return {
            "requested_paths": requesting_paths,
            "conflicting_paths": [],
            "conflict_detail": [],
            "safe_paths": [],
            "recommended_actions": [],
            "overall_risk": "unknown",
            "evidence_status": "missing",
        }

    store = CoordinationStore(store_root)
    projection = store.read_state_projection()

    conflicting_paths: list[str] = []
    conflict_detail: list[dict[str, Any]] = []
    conflict_severities: list[str] = []

    for rp in requesting_paths:
        for _key, reservation in sorted(projection.active_path_reservations.items()):
            if not _path_in_reservation(rp, reservation):
                continue
            sv = _severity(reservation.mode, reservation.status)
            conflicting_paths.append(rp)
            conflict_detail.append({
                "path": salted_path_hash(rp),
                "current_holder": reservation.session_id,
                "lease_expiry": reservation.expires_at,
                "conflict_severity": sv,
            })
            conflict_severities.append(sv)
            break

    safe_paths: list[str] = [p for p in requesting_paths if p not in conflicting_paths]

    recommended_actions: list[dict[str, Any]] = []
    for rp in requesting_paths:
        for _key, reservation in sorted(projection.active_path_reservations.items()):
            if not _path_in_reservation(rp, reservation):
                continue
            recommended_actions.append({
                "path": salted_path_hash(rp),
                **_recommend_action(rp, reservation),
            })
            break

    return {
        "requested_paths": requesting_paths,
        "conflicting_paths": conflicting_paths,
        "conflict_detail": conflict_detail,
        "safe_paths": safe_paths,
        "recommended_actions": recommended_actions,
        "overall_risk": _overall_risk(conflict_severities),
    }
