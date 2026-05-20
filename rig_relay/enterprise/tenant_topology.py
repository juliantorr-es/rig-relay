from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any

from rig_relay.enterprise.tenancy import TenantRegistry, TenantScope

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return None


def _count_events(log_path: Path) -> int:
    try:
        with open(log_path, encoding="utf-8") as f:
            return sum(1 for line in f if line.strip())
    except (OSError, FileNotFoundError):
        return 0


def _event_type_counts(log_path: Path) -> dict[str, int]:
    counts: dict[str, int] = {}
    try:
        with open(log_path, encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if not stripped:
                    continue
                event = json.loads(stripped)
                event_type = event.get("event_type", "unknown")
                label = (
                    event_type.rsplit("tenant:", 1)[-1]
                    if "tenant:" in event_type
                    else event_type
                )
                counts[label] = counts.get(label, 0) + 1
    except (OSError, FileNotFoundError):
        pass
    return counts


def _build_tenant_nodes(
    tenant_id: str, scope: str, event_count: int
) -> list[dict[str, Any]]:
    state = "active" if event_count > 0 else "no_input"
    return [
        {
            "node_id": f"{tenant_id}.event_fabric",
            "node_type": "event_fabric",
            "label": f"Event Fabric ({tenant_id})",
            "strand_state": state,
            "event_count": event_count,
            "details": f"{event_count} events"
            if event_count > 0
            else "no events received",
        },
        {
            "node_id": f"{tenant_id}.duckdb_projection",
            "node_type": "duckdb_projection",
            "label": f"DuckDB Projection ({tenant_id})",
            "strand_state": state if scope != "shared_read" else "active",
            "event_count": 0,
            "details": "tenant-scoped projection",
        },
        {
            "node_id": f"{tenant_id}.derived_artifact",
            "node_type": "derived_artifact",
            "label": f"Derived Artifacts ({tenant_id})",
            "strand_state": state if scope != "shared_read" else "active",
            "event_count": 0,
            "details": "tenant-scoped artifacts",
        },
    ]


def _build_tenant_edges(tenant_id: str) -> list[dict[str, Any]]:
    return [
        {
            "edge_id": f"{tenant_id}.edge_001",
            "from_node_id": f"{tenant_id}.event_fabric",
            "to_node_id": f"{tenant_id}.duckdb_projection",
            "edge_type": "consumed_by",
            "confidence": "observed",
            "label": "JSONL read",
        },
        {
            "edge_id": f"{tenant_id}.edge_002",
            "from_node_id": f"{tenant_id}.duckdb_projection",
            "to_node_id": f"{tenant_id}.derived_artifact",
            "edge_type": "produced",
            "confidence": "observed",
            "label": "tenant-scoped projection output",
        },
    ]


@dataclass(slots=True)
class TenantTopologyProjection:
    registry: TenantRegistry

    def build_tenant_topology(self, tenant_id: str) -> dict[str, Any]:
        tenant = self.registry.get(tenant_id)
        if tenant is None:
            return {
                "schema_version": "rig.enterprise.tenant_topology.v1",
                "generated_at": _now_iso(),
                "tenant_id": tenant_id,
                "scope": "unknown",
                "status": "empty",
                "nodes": [],
                "edges": [],
                "strand_states": {},
                "resource_pressure": {},
                "redaction_summary": {
                    "raw_event_payloads_exposed": False,
                    "envelope_level_only": True,
                    "cross_tenant_data_exposed": False,
                },
                "content_light": True,
                "read_side_only": True,
                "mutation_authority": False,
            }

        log_path = tenant.event_log_path / "event_fabric_v1.jsonl"
        event_count = _count_events(log_path)
        nodes = _build_tenant_nodes(tenant_id, tenant.scope, event_count)
        edges = _build_tenant_edges(tenant_id)

        status = "live" if event_count > 0 else "no_input"

        return {
            "schema_version": "rig.enterprise.tenant_topology.v1",
            "generated_at": _now_iso(),
            "tenant_id": tenant_id,
            "scope": tenant.scope,
            "status": status,
            "nodes": nodes,
            "edges": edges,
            "strand_states": {
                "total_nodes": len(nodes),
                "active_count": sum(1 for n in nodes if n["strand_state"] == "active"),
                "no_input_count": sum(
                    1 for n in nodes if n["strand_state"] == "no_input"
                ),
                "degraded_count": 0,
                "unknown_count": 0,
            },
            "resource_pressure": {
                "reconnect_pressure": "none",
                "queue_pressure": "none",
                "consumer_errors": "none",
            },
            "redaction_summary": {
                "raw_event_payloads_exposed": False,
                "envelope_level_only": True,
                "cross_tenant_data_exposed": False,
            },
            "content_light": True,
            "read_side_only": True,
            "mutation_authority": False,
        }

    def build_cross_tenant_summary(self) -> dict[str, Any]:
        active_tenants = self.registry.list_active()
        health_map: dict[str, str] = {}
        healthy = 0
        degraded = 0

        for tenant in active_tenants:
            log_path = tenant.event_log_path / "event_fabric_v1.jsonl"
            event_count = _count_events(log_path)
            if event_count > 0:
                health_map[tenant.tenant_id] = "healthy"
                healthy += 1
            elif tenant.scope == TenantScope.ISOLATED:
                health_map[tenant.tenant_id] = "no_input"
                degraded += 1
            else:
                health_map[tenant.tenant_id] = "healthy"
                healthy += 1

        return {
            "schema_version": "rig.enterprise.tenant_topology.v1",
            "generated_at": _now_iso(),
            "tenant_id": "__cross_tenant__",
            "scope": "cross_tenant_aggregate",
            "status": "live" if degraded == 0 else "degraded",
            "nodes": [],
            "edges": [],
            "strand_states": {
                "total_nodes": 0,
                "active_count": 0,
                "no_input_count": 0,
                "degraded_count": 0,
                "unknown_count": 0,
            },
            "resource_pressure": {
                "reconnect_pressure": "none",
                "queue_pressure": "none",
                "consumer_errors": "none",
            },
            "cross_tenant_summary": {
                "total_tenants": len(active_tenants),
                "healthy_tenants": healthy,
                "degraded_tenants": degraded,
                "tenant_health_map": health_map,
            },
            "redaction_summary": {
                "raw_event_payloads_exposed": False,
                "envelope_level_only": True,
                "cross_tenant_data_exposed": False,
            },
            "content_light": True,
            "read_side_only": True,
            "mutation_authority": False,
        }


__all__ = ["TenantTopologyProjection"]
