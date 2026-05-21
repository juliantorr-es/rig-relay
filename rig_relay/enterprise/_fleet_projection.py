from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from rig_relay.enterprise._fleet_models import (
    BridgeInstance,
    BridgeInstanceState,
    FleetHealthSummary,
)


def compute_fleet_status(instances: dict[str, BridgeInstance]) -> dict[str, Any]:
    now = datetime.now(UTC)
    tenants: dict[str, Any] = {}
    total = len(instances)
    healthy_count = 0
    degraded_count = 0
    disconnected_count = 0
    failed_count = 0
    for instance in instances.values():
        uptime = ""
        if instance.started_at:
            try:
                started = datetime.fromisoformat(instance.started_at)
                delta = (now - started).total_seconds()
                uptime = f"{int(delta)}s"
            except (ValueError, TypeError):
                uptime = ""
        tenants[instance.tenant_id] = {
            "state": instance.state.value,
            "port": instance.port,
            "uptime_seconds": uptime,
            "active_strands": instance.active_strands,
            "event_count": instance.event_count,
        }
        match instance.state:
            case BridgeInstanceState.HEALTHY:
                healthy_count += 1
            case BridgeInstanceState.DEGRADED:
                degraded_count += 1
            case BridgeInstanceState.DISCONNECTED:
                disconnected_count += 1
            case BridgeInstanceState.FAILED:
                failed_count += 1
    if total == 0:
        health = FleetHealthSummary.NO_INSTANCES
    elif failed_count > 0:
        health = FleetHealthSummary.FAILED_PRESENT
    elif disconnected_count > 0:
        health = FleetHealthSummary.DISCONNECTED_PRESENT
    elif degraded_count > 0:
        health = FleetHealthSummary.DEGRADED_PRESENT
    else:
        health = FleetHealthSummary.ALL_HEALTHY
    return {
        "total_instances": total,
        "healthy": healthy_count,
        "degraded": degraded_count,
        "disconnected": disconnected_count,
        "failed": failed_count,
        "health_summary": health.name,
        "tenants": tenants,
        "generated_at": now.isoformat(),
    }


def instances_all_healthy(instances: dict[str, BridgeInstance]) -> bool:
    if not instances:
        return False
    return all(i.state == BridgeInstanceState.HEALTHY for i in instances.values())


def build_spiderweb_fleet_section(
    instances: dict[str, BridgeInstance],
) -> dict[str, Any]:
    status = compute_fleet_status(instances)
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    for instance in instances.values():
        nodes.append({
            "node_id": instance.instance_id,
            "node_type": "bridge_instance",
            "label": f"tenant={instance.tenant_id} port={instance.port}",
            "strand_state": instance.state.value,
            "event_count": instance.event_count,
            "details": (f"pid={instance.pid} active_strands={instance.active_strands}"),
        })
    instance_ids = list(instances)
    for i in range(len(instance_ids)):
        for j in range(i + 1, len(instance_ids)):
            edges.append({
                "edge_id": f"fleet-{instance_ids[i]}-{instance_ids[j]}",
                "from_node_id": instance_ids[i],
                "to_node_id": instance_ids[j],
                "edge_type": "fleet_peer",
                "confidence": "derived",
                "label": "fleet mesh",
            })
    healthy = instances_all_healthy(instances)
    return {
        "available": True,
        "status": "live" if nodes else "empty",
        "generated_at": status["generated_at"],
        "nodes": nodes,
        "edges": edges,
        "strand_states": {
            "total_nodes": status["total_instances"],
            "healthy_count": status["healthy"],
            "active_count": status["healthy"],
            "idle_count": 0,
            "stale_count": 0,
            "degraded_count": status["degraded"],
            "blocked_count": 0,
            "no_input_count": 0,
        },
        "resource_pressure": {
            "reconnect_pressure": "none",
            "queue_pressure": "none",
            "consumer_errors": "none",
            "consumer_error_count": 0,
            "bridge_health": "healthy" if healthy else "degraded",
        },
        "causal_summary": {
            "observed_links": 0,
            "correlated_only_links": len(edges),
            "total_links": len(edges),
        },
        "degraded_reasons": [
            i.instance_id
            for i in instances.values()
            if i.state == BridgeInstanceState.DEGRADED
        ],
        "source_artifact_hashes": {},
        "renderer_mode": "deterministic_svg",
        "raw_payloads_exposed": False,
        "redaction_status": "content_light",
        "cross_tenant_summary": {
            "total_tenants": len({i.tenant_id for i in instances.values()}),
            "healthy_tenants": status["healthy"],
            "degraded_tenants": status["degraded"],
            "tenant_health_map": {
                i.tenant_id: i.state.value for i in instances.values()
            },
        },
    }


__all__ = [
    "build_spiderweb_fleet_section",
    "compute_fleet_status",
    "instances_all_healthy",
]
