"""Recovery orchestration service — native app recovery boundary (X4).

Defines the native/release recovery orchestration surface that can
consume X1 PostgreSQL migration outcomes and X2 runtime/provider status.
Does not implement PostgreSQL internals owned by X1.
"""

from __future__ import annotations

from pathlib import Path

from rig_relay.native.models import RecoveryEvidence, RecoveryState


class RecoveryService:
    """Service boundary for native app recovery orchestration.

    Recovery domains:
      - Failed app update rollback
      - Failed native package installation
      - Incompatible/missing frontend resources
      - Unavailable extension binding
      - Future: PostgreSQL migration failure handoff (X1 consumption interface)
      - Future: Runtime/provider status (X2 consumption interface)
    """

    def __init__(self, project_root: Path | None = None) -> None:
        self._repo_root = (
            project_root or Path(__file__).resolve().parent.parent.parent.parent
        )

    def assess_health(
        self,
        *,
        frontend_bundle_path: Path | None = None,
        extension_bundle_id: str | None = None,
        db_migration_status: str | None = None,
        bridge_connection_status: str | None = None,
    ) -> RecoveryEvidence:
        """Assess current recovery state of the native app.

        All component statuses are strings from the owning service interfaces.
        X4 only orchestrates — X1 provides db_migration_status, X2 provides
        runtime/provider status.
        """
        evidence = RecoveryEvidence(state=RecoveryState.HEALTHY)

        degraded = False

        if frontend_bundle_path and not frontend_bundle_path.exists():
            degraded = True
            evidence.affected_components.append("frontend_resources")
            evidence.frontend_bundle_status = "missing"

        if extension_bundle_id:
            evidence.extension_binding_status = "deferred_xcode_project"
            evidence.affected_components.append("extension_binding")

        if db_migration_status and db_migration_status != "healthy":
            evidence.db_migration_status = db_migration_status
            evidence.affected_components.append("database")

        if bridge_connection_status and bridge_connection_status != "connected":
            evidence.bridge_connection_status = bridge_connection_status
            evidence.affected_components.append("native_bridge")

        if degraded:
            evidence.state = RecoveryState.DEGRADED

        return evidence

    def recovery_actions_for(self, evidence: RecoveryEvidence) -> list[str]:
        """Return recommended recovery actions for the given evidence."""
        actions: list[str] = []

        if "frontend_resources" in evidence.affected_components:
            actions.append("rebuild_app_bundle_to_restore_frontend_resources")
            actions.append("run_build-app.sh_to_regenerate_bundle")

        if "extension_binding" in evidence.affected_components:
            actions.append("safari_extension_requires_xcode_project_generation")
            actions.append(
                "xcrun_safari-web-extension-packager_to_convert_web_extension_to_xcode"
            )

        if "native_bridge" in evidence.affected_components:
            actions.append("restart_rig_relay_desktop_app")
            actions.append("verify_websocket_server_on_port_9876")

        if "database" in evidence.affected_components:
            actions.append("handoff_to_x1_migration_recovery")
            actions.append("no_direct_database_intervention_by_x4")

        if "update" in evidence.affected_components:
            actions.append("rollback_to_previous_app_version")
            actions.append("restore_from_update_backup")

        return actions

    def record_recovery_event(
        self, current_state: RecoveryState, action_taken: str, successful: bool
    ) -> RecoveryEvidence:
        return RecoveryEvidence(
            state=current_state,
            recovery_actions_taken=[action_taken],
            recovery_successful=successful,
            requires_manual_intervention=not successful,
        )
