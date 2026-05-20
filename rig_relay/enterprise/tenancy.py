from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum, auto
from pathlib import Path


class TenantScope(StrEnum):
    ISOLATED = auto()
    SHARED_READ = auto()
    PUBLIC = auto()


_REPO_ROOT = Path(__file__).resolve().parents[2]
_TENANTS_DIR = _REPO_ROOT / ".build" / "rig-relay" / "tenants"


def _default_event_log_path(tenant_id: str) -> Path:
    return _TENANTS_DIR / tenant_id / "events"


def _default_topology_path(tenant_id: str) -> Path:
    return _TENANTS_DIR / tenant_id / "derived"


@dataclass(slots=True)
class Tenant:
    tenant_id: str
    scope: TenantScope = TenantScope.ISOLATED
    event_log_path: Path = field(default=None)  # type: ignore[assignment]
    topology_path: Path = field(default=None)  # type: ignore[assignment]
    permissions: list[str] = field(default_factory=list)
    active: bool = True

    def __post_init__(self) -> None:
        if self.event_log_path is None:
            object.__setattr__(
                self, "event_log_path", _default_event_log_path(self.tenant_id)
            )
        if self.topology_path is None:
            object.__setattr__(
                self, "topology_path", _default_topology_path(self.tenant_id)
            )


@dataclass(slots=True)
class TenantRegistry:
    tenants: dict[str, Tenant] = field(default_factory=dict)

    def register(self, tenant: Tenant) -> None:
        self.tenants[tenant.tenant_id] = tenant
        tenant.event_log_path.mkdir(parents=True, exist_ok=True)
        tenant.topology_path.mkdir(parents=True, exist_ok=True)

    def get(self, tenant_id: str) -> Tenant | None:
        return self.tenants.get(tenant_id)

    def unregister(self, tenant_id: str) -> None:
        self.tenants.pop(tenant_id, None)

    def list_active(self) -> list[Tenant]:
        return [t for t in self.tenants.values() if t.active]

    def event_log_path_for(self, tenant_id: str) -> Path:
        tenant = self.get(tenant_id)
        if tenant is None:
            raise KeyError(f"Unknown tenant: {tenant_id}")
        return tenant.event_log_path


__all__ = ["Tenant", "TenantRegistry", "TenantScope"]
