"""HANDOFF mode — cross-agent handoff packet compiler.

Reads coordination store (sessions, leases, conflicts, artifacts) and
builds a content-light handoff packet. No raw file contents or secrets.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from rig_relay.coordination.models import CoordinationStateProjection, salted_path_hash
from rig_relay.coordination.store import CoordinationStore

_STORE_SUBDIR = Path(".build") / "rig-relay" / "coordination"


def _resolve_store_path(coordination_store_path: Path | None) -> Path:
    if coordination_store_path is not None:
        return coordination_store_path.resolve()
    return (Path.cwd() / _STORE_SUBDIR).resolve()


def _read_handoff_events(store_root: Path) -> list[dict[str, Any]]:
    events_path = store_root / "events.jsonl"
    if not events_path.is_file():
        return []

    handoff_kinds = frozenset({
        "coord.handoff.requested",
        "coord.handoff.accepted",
        "coord.handoff.rejected",
    })
    results: list[dict[str, Any]] = []
    try:
        with events_path.open("r", encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    event = json.loads(stripped)
                except json.JSONDecodeError:
                    continue
                if event.get("event_name") in handoff_kinds:
                    payload = event.get("payload", {})
                    results.append({
                        "from_agent": payload.get("handoff_from_session_id", ""),
                        "to_agent": payload.get("handoff_to_session_id", ""),
                        "reason": payload.get("event_kind", ""),
                        "status": payload.get("status", "unknown"),
                    })
    except OSError:
        pass

    return results


def _build_active_agents(
    projection: CoordinationStateProjection,
) -> list[dict[str, Any]]:
    agents: list[dict[str, Any]] = []
    for session_id, session in sorted(projection.active_sessions.items()):
        claimed_paths = sorted(session.reserved_paths) if session.reserved_paths else []
        agents.append({
            "agent_id": session_id,
            "status": session.status,
            "claimed_paths": claimed_paths,
            "last_heartbeat": session.updated_at,
        })
    return agents


def _build_file_leases(projection: CoordinationStateProjection) -> list[dict[str, Any]]:
    leases: list[dict[str, Any]] = []
    for _key, reservation in sorted(projection.active_path_reservations.items()):
        for path in reservation.paths:
            leases.append({
                "path": salted_path_hash(path),
                "lease_holder": reservation.session_id,
                "expires_at": reservation.expires_at,
                "conflict_status": reservation.status,
            })
    return leases


def _build_collision_warnings(
    projection: CoordinationStateProjection,
) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    for conflict in projection.conflicts:
        warnings.append({
            "path": (salted_path_hash(conflict.paths[0]) if conflict.paths else ""),
            "agent_a": conflict.session_id,
            "agent_b": conflict.other_session_id or "",
            "collision_type": conflict.kind,
        })
    return warnings


def _build_published_artifacts(
    projection: CoordinationStateProjection,
) -> list[dict[str, Any]]:
    return [
        {
            "artifact_id": a.artifact_sha256,
            "path": a.artifact_uri,
            "sha256": a.artifact_sha256,
        }
        for a in projection.recent_artifacts
    ]


def _build_do_not_touch_paths(projection: CoordinationStateProjection) -> list[str]:
    paths: list[str] = []
    for _key, reservation in sorted(projection.active_path_reservations.items()):
        if reservation.mode == "write":
            paths.extend(salted_path_hash(p) for p in reservation.paths)
    return sorted(set(paths))


def _recommend_free_paths(workspace_root: Path, claimed_paths: set[str]) -> list[str]:
    candidates: list[str] = []
    for subdir_name in ("rig_relay", "tests", "docs", "scripts"):
        subdir = workspace_root / subdir_name
        if not subdir.is_dir():
            continue
        for f in sorted(subdir.rglob("*"))[:200]:
            if f.is_file():
                rel = str(f.relative_to(workspace_root))
                if rel not in claimed_paths:
                    candidates.append(salted_path_hash(rel))
    return list(dict.fromkeys(candidates))[:20]


def compile_handoff_packet(
    session_id: str, coordination_store_path: Path | None = None
) -> dict[str, Any]:
    store_root = _resolve_store_path(coordination_store_path)

    if not store_root.is_dir():
        return {
            "active_agents": [],
            "file_leases": [],
            "collision_warnings": [],
            "published_artifacts": [],
            "pending_handoffs": [],
            "do_not_touch_paths": [],
            "recommended_next_paths": [],
        }

    store = CoordinationStore(store_root)
    projection = store.read_state_projection()

    workspace_root = Path.cwd().resolve()
    claimed_paths: set[str] = set()
    for _key, reservation in sorted(projection.active_path_reservations.items()):
        claimed_paths.update(reservation.paths)

    return {
        "session_id": session_id,
        "active_agents": _build_active_agents(projection),
        "file_leases": _build_file_leases(projection),
        "collision_warnings": _build_collision_warnings(projection),
        "published_artifacts": _build_published_artifacts(projection),
        "pending_handoffs": _read_handoff_events(store_root),
        "do_not_touch_paths": _build_do_not_touch_paths(projection),
        "recommended_next_paths": _recommend_free_paths(workspace_root, claimed_paths),
    }
