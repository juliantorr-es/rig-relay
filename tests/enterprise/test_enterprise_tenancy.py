from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path

import pytest

from rig_relay.enterprise.tenancy import Tenant, TenantRegistry, TenantScope

pytestmark = [pytest.mark.contract, pytest.mark.integration, pytest.mark.substrate]


@pytest.fixture
def tenant_registry() -> TenantRegistry:
    return TenantRegistry()


@pytest.fixture
def tmp_tenants_dir(tmp_path: Path) -> Path:
    tenants_dir = tmp_path / ".build" / "rig-relay" / "tenants"
    tenants_dir.mkdir(parents=True, exist_ok=True)
    return tenants_dir


def _make_tenant(
    tenant_id: str, scope: TenantScope = TenantScope.ISOLATED, active: bool = True
) -> Tenant:
    return Tenant(tenant_id=tenant_id, scope=scope, active=active)


def test_registry_starts_empty(tenant_registry: TenantRegistry) -> None:
    assert len(tenant_registry.tenants) == 0
    assert tenant_registry.list_active() == []


def test_register_adds_tenant_with_correct_fields(
    tenant_registry: TenantRegistry,
    tmp_tenants_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("rig_relay.enterprise.tenancy._TENANTS_DIR", tmp_tenants_dir)
    monkeypatch.setattr(
        "rig_relay.enterprise.tenancy._default_event_log_path",
        lambda tid: tmp_tenants_dir / tid / "events",
    )
    monkeypatch.setattr(
        "rig_relay.enterprise.tenancy._default_topology_path",
        lambda tid: tmp_tenants_dir / tid / "derived",
    )

    tenant = Tenant(tenant_id="acme-corp", scope=TenantScope.ISOLATED)
    tenant_registry.register(tenant)

    registered = tenant_registry.get("acme-corp")
    assert isinstance(registered, Tenant)
    assert registered.tenant_id == "acme-corp"
    assert registered.scope == TenantScope.ISOLATED
    assert registered.active is True
    assert registered.event_log_path == tmp_tenants_dir / "acme-corp" / "events"
    assert registered.topology_path == tmp_tenants_dir / "acme-corp" / "derived"


def test_get_returns_registered_tenant(tenant_registry: TenantRegistry) -> None:
    tenant = _make_tenant("T1")
    tenant_registry.register(tenant)

    result = tenant_registry.get("T1")
    assert isinstance(result, Tenant)
    assert result is tenant
    assert result.tenant_id == "T1"


def test_get_returns_none_for_unknown(tenant_registry: TenantRegistry) -> None:
    assert tenant_registry.get("no-such-tenant") is None


def test_unregister_removes_tenant(tenant_registry: TenantRegistry) -> None:
    tenant = _make_tenant("T1")
    tenant_registry.register(tenant)
    assert "T1" in tenant_registry.tenants

    tenant_registry.unregister("T1")
    assert "T1" not in tenant_registry.tenants
    assert tenant_registry.get("T1") is None


def test_unregister_nonexistent_is_noop(tenant_registry: TenantRegistry) -> None:
    tenant_registry.unregister("ghost")  # does not raise


def test_list_active_returns_only_active_tenants(
    tenant_registry: TenantRegistry,
) -> None:
    a = _make_tenant("active-a", active=True)
    b = _make_tenant("inactive-b", active=False)
    c = _make_tenant("active-c", active=True)

    tenant_registry.register(a)
    tenant_registry.register(b)
    tenant_registry.register(c)

    active = tenant_registry.list_active()
    assert len(active) == 2
    active_ids = {t.tenant_id for t in active}
    assert active_ids == {"active-a", "active-c"}


def test_tenant_isolated_scope_has_isolated_path(
    tmp_tenants_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("rig_relay.enterprise.tenancy._TENANTS_DIR", tmp_tenants_dir)
    monkeypatch.setattr(
        "rig_relay.enterprise.tenancy._default_event_log_path",
        lambda tid: tmp_tenants_dir / tid / "events",
    )
    monkeypatch.setattr(
        "rig_relay.enterprise.tenancy._default_topology_path",
        lambda tid: tmp_tenants_dir / tid / "derived",
    )

    tenant = Tenant(tenant_id="isolated-1", scope=TenantScope.ISOLATED)
    assert str(tenant.event_log_path).endswith("/isolated-1/events")
    assert str(tenant.topology_path).endswith("/isolated-1/derived")


def test_tenant_shared_read_scope_has_shared_path(
    tmp_tenants_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("rig_relay.enterprise.tenancy._TENANTS_DIR", tmp_tenants_dir)
    monkeypatch.setattr(
        "rig_relay.enterprise.tenancy._default_event_log_path",
        lambda tid: tmp_tenants_dir / tid / "events",
    )
    monkeypatch.setattr(
        "rig_relay.enterprise.tenancy._default_topology_path",
        lambda tid: tmp_tenants_dir / tid / "derived",
    )

    tenant = Tenant(tenant_id="shared-1", scope=TenantScope.SHARED_READ)
    assert TenantScope.SHARED_READ == tenant.scope
    assert str(tenant.event_log_path).endswith("/shared-1/events")


def test_duplicate_register_overwrites_previous(
    tenant_registry: TenantRegistry,
    tmp_tenants_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("rig_relay.enterprise.tenancy._TENANTS_DIR", tmp_tenants_dir)

    t1 = _make_tenant("dup", scope=TenantScope.ISOLATED)
    tenant_registry.register(t1)

    t2 = Tenant(tenant_id="dup", scope=TenantScope.SHARED_READ, active=False)
    tenant_registry.register(t2)

    result = tenant_registry.get("dup")
    assert isinstance(result, Tenant)
    assert result is t2
    assert result.scope == TenantScope.SHARED_READ
    assert result.active is False
    assert len(tenant_registry.tenants) == 1


def test_register_creates_tenant_directories(
    tenant_registry: TenantRegistry,
    tmp_tenants_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("rig_relay.enterprise.tenancy._TENANTS_DIR", tmp_tenants_dir)
    monkeypatch.setattr(
        "rig_relay.enterprise.tenancy._default_event_log_path",
        lambda tid: tmp_tenants_dir / tid / "events",
    )
    monkeypatch.setattr(
        "rig_relay.enterprise.tenancy._default_topology_path",
        lambda tid: tmp_tenants_dir / tid / "derived",
    )

    events_path = tmp_tenants_dir / "new-tenant" / "events"
    topology_path = tmp_tenants_dir / "new-tenant" / "derived"
    assert not events_path.exists()
    assert not topology_path.exists()

    tenant = Tenant(tenant_id="new-tenant")
    tenant_registry.register(tenant)

    assert events_path.is_dir()
    assert topology_path.is_dir()


def test_event_log_path_for_returns_correct_path(
    tenant_registry: TenantRegistry,
    tmp_tenants_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("rig_relay.enterprise.tenancy._TENANTS_DIR", tmp_tenants_dir)
    monkeypatch.setattr(
        "rig_relay.enterprise.tenancy._default_event_log_path",
        lambda tid: tmp_tenants_dir / tid / "events",
    )
    monkeypatch.setattr(
        "rig_relay.enterprise.tenancy._default_topology_path",
        lambda tid: tmp_tenants_dir / tid / "derived",
    )

    tenant = Tenant(tenant_id="path-test")
    tenant_registry.register(tenant)

    result = tenant_registry.event_log_path_for("path-test")
    assert result == tmp_tenants_dir / "path-test" / "events"


def test_event_log_path_for_raises_for_unknown_tenant(
    tenant_registry: TenantRegistry,
) -> None:
    with pytest.raises(KeyError, match="Unknown tenant"):
        tenant_registry.event_log_path_for("no-such-tenant")


def test_registry_serializes_to_schema_compatible_dict(
    tenant_registry: TenantRegistry,
    tmp_tenants_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("rig_relay.enterprise.tenancy._TENANTS_DIR", tmp_tenants_dir)
    monkeypatch.setattr(
        "rig_relay.enterprise.tenancy._default_event_log_path",
        lambda tid: tmp_tenants_dir / tid / "events",
    )
    monkeypatch.setattr(
        "rig_relay.enterprise.tenancy._default_topology_path",
        lambda tid: tmp_tenants_dir / tid / "derived",
    )

    tenant = Tenant(tenant_id="schema-test", scope=TenantScope.SHARED_READ)
    tenant_registry.register(tenant)

    tenants_dict: dict[str, dict[str, object]] = {}
    for tid, t in tenant_registry.tenants.items():
        tenants_dict[tid] = {
            "tenant_id": t.tenant_id,
            "scope": t.scope.value,
            "event_log_path": str(t.event_log_path),
            "topology_path": str(t.topology_path),
            "permissions": list(t.permissions),
            "active": t.active,
        }

    doc = {
        "schema_version": "rig.enterprise.tenant_registry.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "tenants": tenants_dict,
        "content_light": True,
        "mutation_authority": False,
    }

    assert doc["schema_version"] == "rig.enterprise.tenant_registry.v1"
    assert len(doc["tenants"]) == 1
    assert doc["tenants"]["schema-test"]["tenant_id"] == "schema-test"
    assert doc["tenants"]["schema-test"]["scope"] == "shared_read"
    assert doc["tenants"]["schema-test"]["active"] is True

    schema_path = (
        Path(__file__).resolve().parents[2]
        / "docs"
        / "schemas"
        / "rig.enterprise.tenant_registry.v1.schema.json"
    )
    schema = json.loads(schema_path.read_text())
    from jsonschema import validate

    validate(instance=doc, schema=schema)
