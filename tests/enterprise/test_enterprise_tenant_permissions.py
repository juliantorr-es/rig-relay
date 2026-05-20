from __future__ import annotations

import pytest

from rig_relay.enterprise.tenancy import Tenant, TenantRegistry
from rig_relay.enterprise.tenant_permissions import (
    TenantPermission,
    TenantPermissionEvaluator,
)

pytestmark = [pytest.mark.contract, pytest.mark.integration]


@pytest.fixture
def registry() -> TenantRegistry:
    return TenantRegistry()


@pytest.fixture
def evaluator(registry: TenantRegistry) -> TenantPermissionEvaluator:
    return TenantPermissionEvaluator(registry=registry)


def _register_with_perms(
    registry: TenantRegistry, tenant_id: str, *permissions: str
) -> Tenant:
    t = Tenant(tenant_id=tenant_id, permissions=list(permissions))
    registry.register(t)
    return t


def test_default_tenant_has_no_permissions(
    evaluator: TenantPermissionEvaluator, registry: TenantRegistry
) -> None:
    _register_with_perms(registry, "default")

    for perm in TenantPermission:
        if perm != TenantPermission.CROSS_TENANT_VIEW:
            assert evaluator.check("default", perm) is False


def test_grant_adds_permission(
    evaluator: TenantPermissionEvaluator, registry: TenantRegistry
) -> None:
    _register_with_perms(registry, "T1")

    evaluator.grant("T1", TenantPermission.READ_EVENT_FABRIC)
    assert TenantPermission.READ_EVENT_FABRIC in registry.get("T1").permissions  # type: ignore[union-attr]


def test_revoke_removes_permission(
    evaluator: TenantPermissionEvaluator, registry: TenantRegistry
) -> None:
    _register_with_perms(registry, "T1", TenantPermission.READ_EVENT_FABRIC.value)

    evaluator.revoke("T1", TenantPermission.READ_EVENT_FABRIC)
    assert TenantPermission.READ_EVENT_FABRIC not in registry.get("T1").permissions  # type: ignore[union-attr]


def test_check_returns_true_for_granted(
    evaluator: TenantPermissionEvaluator, registry: TenantRegistry
) -> None:
    _register_with_perms(registry, "T1", TenantPermission.PUBLISH_EVENT.value)

    assert evaluator.check("T1", TenantPermission.PUBLISH_EVENT) is True


def test_check_returns_false_for_ungranted(
    evaluator: TenantPermissionEvaluator, registry: TenantRegistry
) -> None:
    _register_with_perms(registry, "T1")

    assert evaluator.check("T1", TenantPermission.VIEW_TOPOLOGY) is False


def test_cross_tenant_view_cannot_be_granted(
    evaluator: TenantPermissionEvaluator, registry: TenantRegistry
) -> None:
    _register_with_perms(registry, "T1")

    with pytest.raises(PermissionError, match="Cannot grant system-level"):
        evaluator.grant("T1", TenantPermission.CROSS_TENANT_VIEW)


def test_cross_tenant_view_check_always_false(
    evaluator: TenantPermissionEvaluator, registry: TenantRegistry
) -> None:
    _register_with_perms(
        registry, "admin-tenant", TenantPermission.CROSS_TENANT_VIEW.value
    )

    assert evaluator.check("admin-tenant", TenantPermission.CROSS_TENANT_VIEW) is False


def test_execute_live_mutation_requires_explicit_grant(
    evaluator: TenantPermissionEvaluator, registry: TenantRegistry
) -> None:
    _register_with_perms(registry, "T1")

    assert evaluator.check("T1", TenantPermission.EXECUTE_LIVE_MUTATION) is False

    evaluator.grant("T1", TenantPermission.EXECUTE_LIVE_MUTATION)
    assert evaluator.check("T1", TenantPermission.EXECUTE_LIVE_MUTATION) is True


def test_permission_evaluation_deterministic(
    evaluator: TenantPermissionEvaluator, registry: TenantRegistry
) -> None:
    _register_with_perms(
        registry,
        "T1",
        TenantPermission.READ_EVENT_FABRIC.value,
        TenantPermission.VIEW_TOPOLOGY.value,
    )

    results1 = [evaluator.check("T1", p) for p in TenantPermission]
    results2 = [evaluator.check("T1", p) for p in TenantPermission]
    assert results1 == results2


def test_check_unknown_tenant_returns_false(
    evaluator: TenantPermissionEvaluator,
) -> None:
    assert (
        evaluator.check("no-such-tenant", TenantPermission.READ_EVENT_FABRIC) is False
    )


def test_check_inactive_tenant_returns_false(
    evaluator: TenantPermissionEvaluator, registry: TenantRegistry
) -> None:
    t = Tenant(
        tenant_id="inactive",
        permissions=[TenantPermission.READ_EVENT_FABRIC.value],
        active=False,
    )
    registry.register(t)

    assert evaluator.check("inactive", TenantPermission.READ_EVENT_FABRIC) is False
