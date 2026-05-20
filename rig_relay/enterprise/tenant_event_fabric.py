from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any

from rig_relay.enterprise.tenancy import TenantRegistry
from rig_relay.events.dispatcher import EventDispatcher, Handler

_SYSTEM_EVENT_PREFIXES: frozenset[str] = frozenset({
    "resource.",
    "telemetry.",
    "redaction.",
    "policy.",
})

_TENANTS_DIR = Path(__file__).resolve().parents[2] / ".build" / "rig-relay" / "tenants"


def _tenant_event_log_path(tenant_id: str) -> Path:
    return _TENANTS_DIR / tenant_id / "events" / "event_fabric_v1.jsonl"


def _is_system_event(event_type: str) -> bool:
    return any(event_type.startswith(prefix) for prefix in _SYSTEM_EVENT_PREFIXES)


def _prefix_event(event: dict[str, Any], tenant_id: str) -> dict[str, Any]:
    event_type = event.get("event_type", "")
    if not event_type.startswith(f"tenant:{tenant_id}:"):
        event_type = f"tenant:{tenant_id}:{event_type}"
    return {**event, "event_type": event_type}


def _validate_cross_tenant_event(event: dict[str, Any]) -> None:
    event_type = event.get("event_type", "")
    if not _is_system_event(event_type):
        raise PermissionError(
            f"Cross-tenant publish rejected: event_type '{event_type}' "
            f"is not a system-level event. Only resource.*, telemetry.*, "
            f"redaction.*, policy.* events may cross tenant boundaries."
        )


@dataclass(slots=True)
class TenantEventDispatcher:
    registry: TenantRegistry
    dispatchers: dict[str, EventDispatcher] = field(default_factory=dict)

    def publish(self, tenant_id: str, event: dict[str, Any]) -> None:
        tenant = self.registry.get(tenant_id)
        if tenant is None:
            raise KeyError(f"Unknown tenant: {tenant_id}")
        if not tenant.active:
            return
        prefixed = _prefix_event(event, tenant_id)
        _write_event(tenant_id, prefixed)
        dispatcher = self.tenant_dispatcher(tenant_id)
        asyncio.create_task(dispatcher.publish(prefixed))

    def subscribe(self, tenant_id: str, pattern: str, handler: Handler) -> None:
        dispatcher = self.tenant_dispatcher(tenant_id)
        dispatcher.subscribe(pattern, handler)

    def tenant_dispatcher(self, tenant_id: str) -> EventDispatcher:
        if tenant_id not in self.dispatchers:
            self.dispatchers[tenant_id] = EventDispatcher()
        return self.dispatchers[tenant_id]

    def cross_tenant_publish(self, event: dict[str, Any]) -> None:
        _validate_cross_tenant_event(event)
        for tenant_id, tenant in self.registry.tenants.items():
            if not tenant.active:
                continue
            prefixed = _prefix_event(event, tenant_id)
            _write_event(tenant_id, prefixed)
            dispatcher = self.tenant_dispatcher(tenant_id)
            asyncio.create_task(dispatcher.publish(prefixed))

    async def drain(self, tenant_id: str | None = None) -> None:
        if tenant_id is not None:
            disp = self.dispatchers.get(tenant_id)
            if disp is not None:
                await disp.drain()
            return
        for disp in self.dispatchers.values():
            await disp.drain()


def _write_event(tenant_id: str, event: dict[str, Any]) -> None:
    log_path = _tenant_event_log_path(tenant_id)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(event, sort_keys=True) + "\n"
    with open(log_path, "a") as f:
        f.write(line)
        f.flush()


__all__ = ["TenantEventDispatcher"]
