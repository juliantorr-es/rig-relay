from __future__ import annotations

import json
from pathlib import Path

import pytest

from rig_relay.enterprise.tenancy import Tenant, TenantRegistry
from rig_relay.enterprise.tenant_event_fabric import TenantEventDispatcher

pytestmark = [pytest.mark.contract, pytest.mark.integration]


@pytest.fixture
def registry(tmp_tenants_dir: Path) -> TenantRegistry:
    return TenantRegistry()


@pytest.fixture
def tmp_tenants_dir(tmp_path: Path) -> Path:
    d = tmp_path / ".build" / "rig-relay" / "tenants"
    d.mkdir(parents=True, exist_ok=True)
    return d


@pytest.fixture
def dispatcher(
    monkeypatch: pytest.MonkeyPatch, registry: TenantRegistry, tmp_tenants_dir: Path
) -> TenantEventDispatcher:
    monkeypatch.setattr(
        "rig_relay.enterprise.tenant_event_fabric._TENANTS_DIR", tmp_tenants_dir
    )
    monkeypatch.setattr(
        "rig_relay.enterprise.tenant_event_fabric._tenant_event_log_path",
        lambda tid: tmp_tenants_dir / tid / "events" / "event_fabric_v1.jsonl",
    )
    return TenantEventDispatcher(registry=registry)


def _register_active(registry: TenantRegistry, tenant_id: str) -> Tenant:
    t = Tenant(tenant_id=tenant_id)
    registry.register(t)
    return t


@pytest.mark.asyncio
async def test_publish_writes_to_tenant_log(
    dispatcher: TenantEventDispatcher, registry: TenantRegistry, tmp_tenants_dir: Path
) -> None:
    _register_active(registry, "T-A")

    event = {"event_type": "tool.execute", "payload": {"cmd": "ls"}}
    dispatcher.publish("T-A", event)
    await dispatcher.drain("T-A")

    log_path = tmp_tenants_dir / "T-A" / "events" / "event_fabric_v1.jsonl"
    assert log_path.exists()

    lines = log_path.read_text().strip().split("\n")
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["event_type"] == "tenant:T-A:tool.execute"


@pytest.mark.asyncio
async def test_publish_event_has_tenant_prefix(
    dispatcher: TenantEventDispatcher, registry: TenantRegistry, tmp_tenants_dir: Path
) -> None:
    _register_active(registry, "T-B")

    event = {"event_type": "read_file", "payload": {}}
    dispatcher.publish("T-B", event)
    await dispatcher.drain("T-B")

    log_path = tmp_tenants_dir / "T-B" / "events" / "event_fabric_v1.jsonl"
    record = json.loads(log_path.read_text().strip())
    assert record["event_type"].startswith("tenant:T-B:")
    assert record["event_type"] == "tenant:T-B:read_file"


@pytest.mark.asyncio
async def test_publish_does_not_double_prefix(
    dispatcher: TenantEventDispatcher, registry: TenantRegistry, tmp_tenants_dir: Path
) -> None:
    _register_active(registry, "T-C")

    event = {"event_type": "tenant:T-C:already_prefixed"}
    dispatcher.publish("T-C", event)
    await dispatcher.drain("T-C")

    log_path = tmp_tenants_dir / "T-C" / "events" / "event_fabric_v1.jsonl"
    record = json.loads(log_path.read_text().strip())
    assert record["event_type"] == "tenant:T-C:already_prefixed"


def test_publish_to_nonexistent_tenant_raises(
    dispatcher: TenantEventDispatcher,
) -> None:
    with pytest.raises(KeyError, match="Unknown tenant"):
        dispatcher.publish("no-such-tenant", {"event_type": "x"})


def test_publish_to_inactive_tenant_is_noop(
    dispatcher: TenantEventDispatcher, registry: TenantRegistry, tmp_tenants_dir: Path
) -> None:
    t = Tenant(tenant_id="inactive", active=False)
    registry.register(t)

    dispatcher.publish("inactive", {"event_type": "quiet"})

    log_path = tmp_tenants_dir / "inactive" / "events" / "event_fabric_v1.jsonl"
    assert not log_path.exists()


def test_subscribe_matches_tenant_scoped_events(
    dispatcher: TenantEventDispatcher, registry: TenantRegistry
) -> None:
    _register_active(registry, "T-S")
    received: list[dict[str, object]] = []

    async def handler(event: dict) -> None:
        received.append(event)

    dispatcher.subscribe("T-S", "tenant:T-S:", handler)

    assert "T-S" in dispatcher.dispatchers


@pytest.mark.asyncio
async def test_cross_tenant_publish_allows_resource_events(
    dispatcher: TenantEventDispatcher, registry: TenantRegistry, tmp_tenants_dir: Path
) -> None:
    _register_active(registry, "T-X")
    _register_active(registry, "T-Y")

    dispatcher.cross_tenant_publish({"event_type": "resource.quota_update", "v": 1})
    await dispatcher.drain()

    log_x = tmp_tenants_dir / "T-X" / "events" / "event_fabric_v1.jsonl"
    log_y = tmp_tenants_dir / "T-Y" / "events" / "event_fabric_v1.jsonl"
    assert log_x.exists()
    assert log_y.exists()

    record_x = json.loads(log_x.read_text().strip())
    record_y = json.loads(log_y.read_text().strip())
    assert record_x["event_type"] == "tenant:T-X:resource.quota_update"
    assert record_y["event_type"] == "tenant:T-Y:resource.quota_update"


def test_cross_tenant_publish_rejects_non_system_events(
    dispatcher: TenantEventDispatcher, registry: TenantRegistry
) -> None:
    _register_active(registry, "T-A")

    with pytest.raises(PermissionError, match="Cross-tenant publish rejected"):
        dispatcher.cross_tenant_publish({"event_type": "bridge.start"})


def test_cross_tenant_publish_rejects_tool_events(
    dispatcher: TenantEventDispatcher, registry: TenantRegistry
) -> None:
    _register_active(registry, "T-A")

    with pytest.raises(PermissionError, match="Cross-tenant publish rejected"):
        dispatcher.cross_tenant_publish({"event_type": "tool.execute"})


def test_each_tenant_gets_separate_dispatcher(
    dispatcher: TenantEventDispatcher,
) -> None:
    d1 = dispatcher.tenant_dispatcher("T-1")
    d2 = dispatcher.tenant_dispatcher("T-2")
    d1_again = dispatcher.tenant_dispatcher("T-1")

    assert d1 is not d2
    assert d1 is d1_again
    assert len(dispatcher.dispatchers) == 2


@pytest.mark.asyncio
async def test_tenant_isolation_separate_event_logs(
    dispatcher: TenantEventDispatcher, registry: TenantRegistry, tmp_tenants_dir: Path
) -> None:
    _register_active(registry, "isolated-A")
    _register_active(registry, "isolated-B")

    dispatcher.publish("isolated-A", {"event_type": "secret_for_A", "data": "A-only"})
    dispatcher.publish("isolated-B", {"event_type": "secret_for_B", "data": "B-only"})

    log_a = tmp_tenants_dir / "isolated-A" / "events" / "event_fabric_v1.jsonl"
    log_b = tmp_tenants_dir / "isolated-B" / "events" / "event_fabric_v1.jsonl"

    content_a = log_a.read_text()
    content_b = log_b.read_text()
    assert "secret_for_A" in content_a
    assert "secret_for_B" not in content_a
    assert "secret_for_B" in content_b
    assert "secret_for_A" not in content_b
