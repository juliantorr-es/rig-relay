from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import IntEnum, StrEnum, auto
import os
import signal
import subprocess
import time
from typing import Any


class BridgeInstanceState(StrEnum):
    STARTING = auto()
    HEALTHY = auto()
    DEGRADED = auto()
    DISCONNECTED = auto()
    FAILED = auto()
    STOPPED = auto()


class FleetHealthSummary(IntEnum):
    ALL_HEALTHY = 0
    DEGRADED_PRESENT = 1
    DISCONNECTED_PRESENT = 2
    FAILED_PRESENT = 3
    NO_INSTANCES = 4


@dataclass(slots=True)
class BridgeInstance:
    instance_id: str
    tenant_id: str
    state: BridgeInstanceState = BridgeInstanceState.STOPPED
    port: int = 0
    health_port: int = 0
    pid: int | None = None
    process: subprocess.Popen[bytes] | None = field(default=None, repr=False)
    started_at: str = ""
    last_heartbeat: str = ""
    active_strands: int = 0
    event_count: int = 0
    health_metrics: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class FleetController:
    instances: dict[str, BridgeInstance] = field(default_factory=dict)
    max_instances: int = 10
    base_port: int = 9100
    _rig_relay_path: str = field(default="rig-relay")

    def start_instance(self, tenant_id: str) -> BridgeInstance:
        if len(self.instances) >= self.max_instances:
            raise RuntimeError(
                f"Max instances ({self.max_instances}) reached — cannot start tenant={tenant_id}"
            )
        existing = self._find_by_tenant(tenant_id)
        if existing is not None and existing.state not in {
            BridgeInstanceState.STOPPED,
            BridgeInstanceState.FAILED,
        }:
            raise RuntimeError(
                f"Tenant {tenant_id} already has an active instance (id={existing.instance_id}, state={existing.state})"
            )
        port = self._next_available_port()
        health_port = port + 1
        instance_id = f"bridge-{tenant_id}-{port}"
        instance = BridgeInstance(
            instance_id=instance_id,
            tenant_id=tenant_id,
            state=BridgeInstanceState.STARTING,
            port=port,
            health_port=health_port,
            started_at=datetime.now(UTC).isoformat(),
        )
        try:
            proc = subprocess.Popen(
                [
                    "uv",
                    "run",
                    self._rig_relay_path,
                    "--server-only",
                    "--tenant-id",
                    tenant_id,
                    "--ws-port",
                    str(port),
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            instance.process = proc
            instance.pid = proc.pid
            time.sleep(0.5)
            if proc.poll() is not None:
                instance.state = BridgeInstanceState.FAILED
                instance.process = None
                self.instances[instance_id] = instance
                return instance
            instance.state = BridgeInstanceState.HEALTHY
            instance.last_heartbeat = datetime.now(UTC).isoformat()
        except Exception:
            instance.state = BridgeInstanceState.FAILED
        self.instances[instance_id] = instance
        return instance

    def stop_instance(self, instance_id: str) -> None:
        instance = self.instances.get(instance_id)
        if instance is None:
            return
        if instance.process is not None and instance.pid is not None:
            try:
                os.kill(instance.pid, signal.SIGTERM)
                try:
                    instance.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.kill(instance.pid, signal.SIGKILL)
                    instance.process.wait(timeout=2)
            except (ProcessLookupError, OSError):
                pass
        instance.state = BridgeInstanceState.STOPPED
        instance.process = None
        instance.pid = None
        instance.health_metrics = {}

    def stop_all(self) -> None:
        for instance_id in list(self.instances):
            self.stop_instance(instance_id)

    def health_check(self) -> dict[str, BridgeInstanceState]:
        result: dict[str, BridgeInstanceState] = {}
        for instance_id, instance in self.instances.items():
            if instance.state == BridgeInstanceState.STOPPED:
                result[instance_id] = instance.state
                continue
            if instance.process is not None:
                rc = instance.process.poll()
                if rc is not None:
                    instance.state = BridgeInstanceState.FAILED
                    instance.process = None
                    result[instance_id] = BridgeInstanceState.FAILED
                    continue
            instance.last_heartbeat = datetime.now(UTC).isoformat()
            result[instance_id] = instance.state
        return result

    def restart_degraded(self) -> list[str]:
        restarted: list[str] = []
        for instance_id, instance in list(self.instances.items()):
            if instance.state in {
                BridgeInstanceState.DEGRADED,
                BridgeInstanceState.DISCONNECTED,
            }:
                tenant_id = instance.tenant_id
                self.stop_instance(instance_id)
                del self.instances[instance_id]
                new_instance = self.start_instance(tenant_id)
                restarted.append(new_instance.instance_id)
        return restarted

    def fleet_status(self) -> dict[str, Any]:
        now = datetime.now(UTC)
        tenants: dict[str, Any] = {}
        total = len(self.instances)
        healthy_count = 0
        degraded_count = 0
        disconnected_count = 0
        failed_count = 0
        for instance in self.instances.values():
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

    def all_healthy(self) -> bool:
        if not self.instances:
            return False
        return all(
            i.state == BridgeInstanceState.HEALTHY for i in self.instances.values()
        )

    def build_spiderweb_fleet_section(self) -> dict[str, Any]:
        """Build the fleet section for spiderweb topology projection."""
        status = self.fleet_status()
        nodes: list[dict[str, Any]] = []
        edges: list[dict[str, Any]] = []
        for instance in self.instances.values():
            nodes.append({
                "node_id": instance.instance_id,
                "node_type": "bridge_instance",
                "label": f"tenant={instance.tenant_id} port={instance.port}",
                "strand_state": instance.state.value,
                "event_count": instance.event_count,
                "details": (
                    f"pid={instance.pid} active_strands={instance.active_strands}"
                ),
            })
        instance_ids = list(self.instances)
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
                "bridge_health": ("healthy" if self.all_healthy() else "degraded"),
            },
            "causal_summary": {
                "observed_links": 0,
                "correlated_only_links": len(edges),
                "total_links": len(edges),
            },
            "degraded_reasons": [
                i.instance_id
                for i in self.instances.values()
                if i.state == BridgeInstanceState.DEGRADED
            ],
            "source_artifact_hashes": {},
            "renderer_mode": "deterministic_svg",
            "raw_payloads_exposed": False,
            "redaction_status": "content_light",
            "cross_tenant_summary": {
                "total_tenants": len({i.tenant_id for i in self.instances.values()}),
                "healthy_tenants": status["healthy"],
                "degraded_tenants": status["degraded"],
                "tenant_health_map": {
                    i.tenant_id: i.state.value for i in self.instances.values()
                },
            },
        }

    def _find_by_tenant(self, tenant_id: str) -> BridgeInstance | None:
        for instance in self.instances.values():
            if instance.tenant_id == tenant_id:
                return instance
        return None

    def _next_available_port(self) -> int:
        used = {i.port for i in self.instances.values()}
        port = self.base_port
        while port in used:
            port += 2
        return port


__all__ = [
    "BridgeInstance",
    "BridgeInstanceState",
    "FleetController",
    "FleetHealthSummary",
]
