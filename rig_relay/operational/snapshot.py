"""Operational Snapshot v1 — content-light, read-only, sensor-fusion boundary.

Composes durable canonical evidence from Lane B-owned sources into a single
typed operational snapshot suitable for desktop projections and future
data-plane ingestion.

Read-only. Never mutates evidence, rewrites ledgers, or calls external APIs.

Source inventory (admitted in v1):
    - storage_lifecycle  → compute_storage_summary()
    - github_truth       → GitHubTruthStore
    - coordination       → CoordinationStore.read_state_projection()
    - fleet_queue        → FleetQueue.list_items()

Deferred sources:
    - a2a_tasks          → Lane C territory (durable but cross-lane read contract pending)
    - receipt_governance → Requires DuckDB (deferred to analytics layer)
    - trace_handshake    → Ephemeral observation (not canonical evidence)
"""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_BUILD_ROOT = REPO_ROOT / ".build" / "rig-relay"

FORBIDDEN_FIELDS = frozenset({
    "access_token",
    "Authorization",
    "api_key",
    "Bearer",
    "credential",
    "password",
    "private_key",
    "raw_prompt",
    "raw_source",
    "secret",
    "token",
})


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _sha256(data: str) -> str:
    return f"sha256:{hashlib.sha256(data.encode('utf-8')).hexdigest()}"


def _content_light_assert(record: dict[str, Any], label: str = "") -> None:
    serialized = json.dumps(record, sort_keys=True).lower()
    found = [f for f in FORBIDDEN_FIELDS if f.lower() in serialized]
    if found:
        raise ValueError(
            f"Operational snapshot record contains forbidden fields: {found}"
            + (f" (source: {label})" if label else "")
        )


def build_operational_snapshot(build_root: Path | None = None) -> dict[str, Any]:
    """Build a content-light operational snapshot from canonical Lane B sources.

    Each source degrades independently — one bad sensor does not black out
    the entire cockpit.

    Args:
        build_root: Path to .build/rig-relay directory.

    Returns:
        Typed snapshot dict with sources, source_inventory, and summary.
    """
    root = build_root or DEFAULT_BUILD_ROOT

    snapshot: dict[str, Any] = {
        "schema_version": "rig.relay.operational_snapshot.v1",
        "generated_at": _now_iso(),
        "content_light": True,
        "read_only": True,
        "sources": {},
        "source_inventory": [],
        "warnings": [],
    }

    # ── Storage lifecycle ──────────────────────────────────────────────
    snapshot["sources"]["storage_lifecycle"] = _read_storage_lifecycle()
    snapshot["source_inventory"].append(
        _inventory_entry(
            source_id="storage_lifecycle",
            authority="rebuildable_projection",
            persistence_form="package_owned_computed_read_model",
            available="storage_lifecycle" in snapshot["sources"],
        )
    )

    # ── GitHub truth ───────────────────────────────────────────────────
    snapshot["sources"]["github_truth"] = _read_github_truth()
    snapshot["source_inventory"].append(
        _inventory_entry(
            source_id="github_truth",
            authority="canonical",
            persistence_form="jsonl",
            available="github_truth" in snapshot["sources"],
        )
    )

    # ── Coordination ───────────────────────────────────────────────────
    snapshot["sources"]["coordination"] = _read_coordination(root)
    snapshot["source_inventory"].append(
        _inventory_entry(
            source_id="coordination",
            authority="canonical",
            persistence_form="jsonl",
            available="coordination" in snapshot["sources"],
        )
    )

    # ── Fleet queue ────────────────────────────────────────────────────
    snapshot["sources"]["fleet_queue"] = _read_fleet_queue(root)
    snapshot["source_inventory"].append(
        _inventory_entry(
            source_id="fleet_queue",
            authority="canonical",
            persistence_form="jsonl",
            available="fleet_queue" in snapshot["sources"],
        )
    )

    # ── Deferred sources ───────────────────────────────────────────────
    snapshot["source_inventory"].append(
        _inventory_entry(
            source_id="a2a_tasks",
            authority="canonical",
            persistence_form="jsonl",
            available=False,
            degradation_reason="Lane C territory — cross-lane read contract pending",
        )
    )
    snapshot["source_inventory"].append(
        _inventory_entry(
            source_id="receipt_governance",
            authority="canonical",
            persistence_form="sharded_json",
            available=False,
            degradation_reason="Requires DuckDB — deferred to analytics layer",
        )
    )
    snapshot["source_inventory"].append(
        _inventory_entry(
            source_id="trace_handshake",
            authority="ephemeral_observation",
            persistence_form="package_owned_computed_read_model",
            available=False,
            degradation_reason="Ephemeral observation — not canonical evidence for operational snapshot",
        )
    )

    # ── Warnings for unavailable sources ───────────────────────────────
    for entry in snapshot["source_inventory"]:
        if not entry.get("available"):
            reason = entry.get("degradation_reason", "unavailable")
            snapshot["warnings"].append(
                f"Source '{entry['source_id']}' unavailable: {reason}"
            )

    # ── Content-light enforcement ──────────────────────────────────────
    _content_light_assert(snapshot, label="operational_snapshot")

    return snapshot


def _inventory_entry(
    source_id: str,
    authority: str,
    persistence_form: str,
    available: bool,
    degradation_reason: str = "",
) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "source_id": source_id,
        "authority_classification": authority,
        "persistence_form": persistence_form,
        "available": available,
        "content_light": True,
    }
    if degradation_reason:
        entry["degradation_reason"] = degradation_reason
    return entry


# ── Source readers ────────────────────────────────────────────────────────


def _read_storage_lifecycle() -> dict[str, Any] | None:
    try:
        from rig_relay.evidence.storage_lifecycle import compute_storage_summary

        summary = compute_storage_summary()
        result = {
            "budget_status": summary.get("budget_status"),
            "total_size_mb": summary.get("total_size_mb"),
            "category_count": summary.get("category_count"),
            "stale_lease_count": summary.get("stale_lease_count"),
            "rollup_candidate_count": summary.get("rollup_candidate_count"),
            "prune_candidate_count": summary.get("prune_candidate_count"),
            "recommendations_count": len(summary.get("recommendations", [])),
            "warning_count": len(summary.get("warnings", [])),
            "largest_category": summary.get("largest_category"),
        }
        _content_light_assert(result, label="storage_lifecycle")
        return result
    except Exception:
        return None


def _read_github_truth() -> dict[str, Any] | None:
    try:
        from rig_relay.evidence.github_truth_store import GitHubTruthStore

        store = GitHubTruthStore()
        all_obs = store.list_observations()

        if not all_obs:
            return {"available": True, "observation_count": 0, "operations": {}}

        operations: dict[str, dict[str, Any]] = {}
        for obs in all_obs:
            opkind = obs.get("operation_kind", "unknown")
            if opkind not in operations:
                operations[opkind] = {
                    "count": 0,
                    "latest_observed_at": obs.get("observed_at"),
                    "latest_status": obs.get("status"),
                    "latest_verification_status": obs.get("verification_status"),
                    "latest_ci_state": obs.get("ci_state"),
                    "latest_overall_state": obs.get("overall_state"),
                }
            operations[opkind]["count"] += 1

        op_kinds_seen: set[str] = set()

        for obs in all_obs:
            repo_hash = obs.get("repository_hash", "")
            key = f"{obs.get('operation_kind', 'unknown')}:{repo_hash}"
            if key not in op_kinds_seen:
                op_kinds_seen.add(key)
                op_kind = obs.get("operation_kind", "unknown")
                if op_kind in operations:
                    operations[op_kind]["latest_repository_hash"] = repo_hash

        latest_obs = all_obs[0] if all_obs else {}
        result: dict[str, Any] = {
            "available": True,
            "observation_count": len(all_obs),
            "operation_kinds_count": len(operations),
            "latest_observed_at": latest_obs.get("observed_at"),
            "operations": operations,
        }
        _content_light_assert(result, label="github_truth")
        return result
    except Exception:
        return None


def _read_coordination(build_root: Path) -> dict[str, Any] | None:
    try:
        from rig_relay.coordination.store import CoordinationStore

        store = CoordinationStore(root=build_root / "coordination")
        proj = store.read_state_projection()

        sessions = proj.sessions if hasattr(proj, "sessions") else {}
        tasks = proj.tasks if hasattr(proj, "tasks") else {}
        leases = proj.leases if hasattr(proj, "leases") else {}
        artifacts = proj.artifacts if hasattr(proj, "artifacts") else []
        conflicts = proj.conflicts if hasattr(proj, "conflicts") else []

        sessions_active = sum(
            1 for s in sessions.values() if getattr(s, "status", "") == "active"
        )

        leases_active = len(leases)
        write_leases = sum(
            1 for l in leases.values() if getattr(l, "mode", "") == "write"
        )
        read_leases = leases_active - write_leases

        result: dict[str, Any] = {
            "available": True,
            "session_count": len(sessions),
            "sessions_active": sessions_active,
            "task_count": len(tasks),
            "active_leases_count": leases_active,
            "write_leases_count": write_leases,
            "read_leases_count": read_leases,
            "artifact_count": len(artifacts),
            "conflict_count": len(conflicts),
            "has_coordination_store": True,
        }
        _content_light_assert(result, label="coordination")
        return result
    except Exception:
        return None


def _read_fleet_queue(build_root: Path) -> dict[str, Any] | None:
    try:
        from rig_relay.coordination.fleet_queue import FleetQueue

        events_path = build_root / "coordination" / "queue" / "events.jsonl"
        if not events_path.is_file():
            return {"available": True, "item_count": 0, "status_counts": {}}

        queue = FleetQueue(events_path)
        snapshot = queue.list_items()

        result: dict[str, Any] = {
            "available": True,
            "item_count": snapshot.total_count,
            "status_counts": snapshot.status_counts,
        }
        _content_light_assert(result, label="fleet_queue")
        return result
    except Exception:
        return None


__all__ = ["build_operational_snapshot"]
