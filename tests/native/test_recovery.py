"""Tests for recovery service."""

from __future__ import annotations

from rig_relay.native._recovery import RecoveryService
from rig_relay.native.models import RecoveryEvidence, RecoveryState


def test_assess_health_all_healthy() -> None:
    svc = RecoveryService()
    evidence = svc.assess_health()
    assert evidence.state == RecoveryState.HEALTHY
    assert len(evidence.affected_components) == 0


def test_assess_health_degraded_when_frontend_missing() -> None:
    svc = RecoveryService()
    from pathlib import Path

    evidence = svc.assess_health(frontend_bundle_path=Path("/nonexistent/index.html"))
    assert evidence.state == RecoveryState.DEGRADED
    assert "frontend_resources" in evidence.affected_components


def test_assess_health_extension_binding_deferred() -> None:
    svc = RecoveryService()
    evidence = svc.assess_health(
        extension_bundle_id="com.rigrelay.RigRelayShell.SafariExtension"
    )
    assert "extension_binding" in evidence.affected_components


def test_assess_health_db_migration_failure_reported() -> None:
    svc = RecoveryService()
    evidence = svc.assess_health(db_migration_status="failed")
    assert evidence.db_migration_status == "failed"
    assert "database" in evidence.affected_components


def test_recovery_actions_for_frontend() -> None:
    svc = RecoveryService()
    evidence = RecoveryEvidence(
        state=RecoveryState.DEGRADED, affected_components=["frontend_resources"]
    )
    actions = svc.recovery_actions_for(evidence)
    assert any("rebuild_app_bundle" in a for a in actions)


def test_recovery_actions_for_extension() -> None:
    svc = RecoveryService()
    evidence = RecoveryEvidence(
        state=RecoveryState.DEGRADED, affected_components=["extension_binding"]
    )
    actions = svc.recovery_actions_for(evidence)
    assert any("xcode_project" in a for a in actions)


def test_recovery_actions_for_database_is_handoff_only() -> None:
    svc = RecoveryService()
    evidence = RecoveryEvidence(
        state=RecoveryState.DEGRADED, affected_components=["database"]
    )
    actions = svc.recovery_actions_for(evidence)
    assert any("handoff_to_x1" in a for a in actions)
    assert any("no_direct_database" in a for a in actions)


def test_record_recovery_event() -> None:
    svc = RecoveryService()
    evidence = svc.record_recovery_event(
        current_state=RecoveryState.REPAIRED,
        action_taken="rebuild_app_bundle",
        successful=True,
    )
    assert evidence.state == RecoveryState.REPAIRED
    assert len(evidence.recovery_actions_taken) > 0
    assert evidence.recovery_successful is True
