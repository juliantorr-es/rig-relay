from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
import os
import signal
import subprocess
import time
from typing import Any

from rig_relay.enterprise._fleet_models import (
    BridgeInstance,
    BridgeInstanceState,
    FleetHealthSummary,
)
from rig_relay.enterprise._fleet_projection import (
    build_spiderweb_fleet_section as _build_spiderweb,
    compute_fleet_status as _compute_fleet_status,
    instances_all_healthy as _instances_all_healthy,
)


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

    # ── projection delegates ────────────────────────────────────────

    def fleet_status(self) -> dict[str, Any]:
        return _compute_fleet_status(self.instances)

    def all_healthy(self) -> bool:
        return _instances_all_healthy(self.instances)

    def build_spiderweb_fleet_section(self) -> dict[str, Any]:
        return _build_spiderweb(self.instances)

    # ── internal helpers ────────────────────────────────────────────

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
