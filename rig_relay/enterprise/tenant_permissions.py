from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum, auto

from rig_relay.enterprise.tenancy import TenantRegistry


class TenantPermission(StrEnum):
    READ_EVENT_FABRIC = auto()
    PUBLISH_EVENT = auto()
    VIEW_TOPOLOGY = auto()
    EXECUTE_LIVE_MUTATION = auto()
    MODIFY_GATES = auto()
    CROSS_TENANT_VIEW = auto()


_SYSTEM_LEVEL_PERMISSIONS: frozenset[TenantPermission] = frozenset({
    TenantPermission.CROSS_TENANT_VIEW
})


@dataclass(slots=True)
class TenantPermissionEvaluator:
    registry: TenantRegistry

    def check(self, tenant_id: str, permission: TenantPermission) -> bool:
        if permission in _SYSTEM_LEVEL_PERMISSIONS:
            return False
        tenant = self.registry.get(tenant_id)
        if tenant is None:
            return False
        if not tenant.active:
            return False
        return permission in tenant.permissions

    def grant(self, tenant_id: str, permission: TenantPermission) -> None:
        if permission in _SYSTEM_LEVEL_PERMISSIONS:
            raise PermissionError(
                f"Cannot grant system-level permission {permission} to tenant {tenant_id}. "
                f"CROSS_TENANT_VIEW is reserved for system-level operators."
            )
        tenant = self.registry.get(tenant_id)
        if tenant is None:
            raise KeyError(f"Unknown tenant: {tenant_id}")
        if permission not in tenant.permissions:
            permissions = list(tenant.permissions)
            permissions.append(permission)
            object.__setattr__(tenant, "permissions", permissions)

    def revoke(self, tenant_id: str, permission: TenantPermission) -> None:
        if permission in _SYSTEM_LEVEL_PERMISSIONS:
            raise PermissionError(
                f"Cannot revoke system-level permission {permission} from tenant {tenant_id}."
            )
        tenant = self.registry.get(tenant_id)
        if tenant is None:
            raise KeyError(f"Unknown tenant: {tenant_id}")
        if permission in tenant.permissions:
            object.__setattr__(
                tenant,
                "permissions",
                [p for p in tenant.permissions if p != permission],
            )


__all__ = ["TenantPermission", "TenantPermissionEvaluator"]
