from __future__ import annotations

import subprocess

import pytest

from rig_relay.enterprise.fleet_controller import (
    BridgeInstance,
    BridgeInstanceState,
    FleetController,
    FleetHealthSummary,
)

pytestmark = [pytest.mark.contract, pytest.mark.integration]


@pytest.fixture
def fleet() -> FleetController:
    return FleetController()


@pytest.fixture(autouse=True)
def _no_real_processes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        subprocess,
        "Popen",
        lambda *a, **kw: (_ for _ in ()).throw(
            RuntimeError("Real subprocess blocked in tests")
        ),
    )


def _make_mock_instance(
    tenant_id: str,
    instance_id: str,
    state: BridgeInstanceState = BridgeInstanceState.HEALTHY,
    port: int = 9100,
    pid: int | None = 12345,
) -> BridgeInstance:
    return BridgeInstance(
        instance_id=instance_id,
        tenant_id=tenant_id,
        state=state,
        port=port,
        health_port=port + 1,
        pid=pid,
        started_at="2026-01-01T00:00:00+00:00",
        last_heartbeat="2026-01-01T01:00:00+00:00",
        active_strands=2,
        event_count=10,
    )


def test_fleet_controller_starts_with_zero_instances(fleet: FleetController) -> None:
    assert len(fleet.instances) == 0


def test_fleet_status_no_instances(fleet: FleetController) -> None:
    status = fleet.fleet_status()
    assert status["total_instances"] == 0
    assert status["health_summary"] == "NO_INSTANCES"
    assert status["healthy"] == 0
    assert status["degraded"] == 0
    assert status["disconnected"] == 0
    assert status["failed"] == 0
    assert status["tenants"] == {}


def test_fleet_status_dict_has_correct_structure(fleet: FleetController) -> None:
    fleet.instances["bridge-t1-9100"] = _make_mock_instance(
        "t1", "bridge-t1-9100", BridgeInstanceState.HEALTHY, port=9100
    )

    status = fleet.fleet_status()

    assert "total_instances" in status
    assert status["total_instances"] == 1
    assert status["healthy"] == 1
    assert status["health_summary"] == "ALL_HEALTHY"
    assert "t1" in status["tenants"]
    assert status["tenants"]["t1"]["state"] == "healthy"
    assert status["tenants"]["t1"]["port"] == 9100
    assert "generated_at" in status


def test_all_healthy_returns_false_when_no_instances(fleet: FleetController) -> None:
    assert fleet.all_healthy() is False


def test_all_healthy_returns_true_when_all_healthy(fleet: FleetController) -> None:
    fleet.instances["bridge-a-9100"] = _make_mock_instance(
        "a", "bridge-a-9100", BridgeInstanceState.HEALTHY
    )
    fleet.instances["bridge-b-9102"] = _make_mock_instance(
        "b", "bridge-b-9102", BridgeInstanceState.HEALTHY
    )
    assert fleet.all_healthy() is True


def test_all_healthy_returns_false_when_degraded_present(
    fleet: FleetController,
) -> None:
    fleet.instances["bridge-a-9100"] = _make_mock_instance(
        "a", "bridge-a-9100", BridgeInstanceState.HEALTHY
    )
    fleet.instances["bridge-b-9102"] = _make_mock_instance(
        "b", "bridge-b-9102", BridgeInstanceState.DEGRADED
    )
    assert fleet.all_healthy() is False


def test_health_check_returns_empty_when_no_instances(fleet: FleetController) -> None:
    result = fleet.health_check()
    assert result == {}


def test_bridge_instance_state_has_all_expected_values() -> None:
    expected = {"starting", "healthy", "degraded", "disconnected", "failed", "stopped"}
    actual = {s.value for s in BridgeInstanceState}
    assert actual == expected


def test_fleet_health_summary_has_all_expected_members() -> None:
    expected = {
        "ALL_HEALTHY",
        "DEGRADED_PRESENT",
        "DISCONNECTED_PRESENT",
        "FAILED_PRESENT",
        "NO_INSTANCES",
    }
    actual = {m.name for m in FleetHealthSummary}
    assert actual == expected

    assert FleetHealthSummary.ALL_HEALTHY == 0
    assert FleetHealthSummary.NO_INSTANCES == 4


def test_max_instances_enforces_capacity_limit() -> None:
    fleet_capped = FleetController(max_instances=2)

    fleet_capped.instances["a"] = _make_mock_instance("t1", "a")
    fleet_capped.instances["b"] = _make_mock_instance("t2", "b")

    with pytest.raises(RuntimeError, match="Max instances"):
        fleet_capped.start_instance("t3")


def test_fleet_status_handles_degraded_and_failed(fleet: FleetController) -> None:
    fleet.instances["bridge-h-9100"] = _make_mock_instance(
        "h", "bridge-h-9100", BridgeInstanceState.HEALTHY
    )
    fleet.instances["bridge-d-9102"] = _make_mock_instance(
        "d", "bridge-d-9102", BridgeInstanceState.DEGRADED
    )
    fleet.instances["bridge-f-9104"] = _make_mock_instance(
        "f", "bridge-f-9104", BridgeInstanceState.FAILED
    )

    status = fleet.fleet_status()
    assert status["total_instances"] == 3
    assert status["healthy"] == 1
    assert status["degraded"] == 1
    assert status["failed"] == 1
    assert status["health_summary"] == "FAILED_PRESENT"


def test_build_spiderweb_fleet_section_empty(fleet: FleetController) -> None:
    result = fleet.build_spiderweb_fleet_section()
    assert result["available"] is True
    assert result["status"] == "empty"
    assert result["nodes"] == []
    assert result["edges"] == []


def test_build_spiderweb_fleet_section_with_instances(fleet: FleetController) -> None:
    fleet.instances["bridge-a-9100"] = _make_mock_instance(
        "t1", "bridge-a-9100", BridgeInstanceState.HEALTHY, port=9100
    )
    fleet.instances["bridge-b-9102"] = _make_mock_instance(
        "t2", "bridge-b-9102", BridgeInstanceState.HEALTHY, port=9102
    )

    result = fleet.build_spiderweb_fleet_section()
    assert result["status"] == "live"
    assert len(result["nodes"]) == 2
    assert len(result["edges"]) == 1  # one mesh edge between two instances
    assert result["nodes"][0]["node_type"] == "bridge_instance"
    assert result["edges"][0]["edge_type"] == "fleet_peer"
