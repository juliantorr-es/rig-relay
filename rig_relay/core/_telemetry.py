"""Telemetry mixin for AgentLoop.

Extracted from agent_loop.py. Provides session lifecycle telemetry
emission (new session, ready, closed) and context observation emission
for tool call outcomes. Best-effort: failures are logged but never
break the calling flow.
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, Any

from rig_relay.core.logger import logger
from rig_relay.core.paths._vibe_home import (
    SESSIONS_ROOT,
    resolve_evidence_root_resolution,
)
from rig_relay.core.telemetry.local import dump_canonical_json
from rig_relay.core.telemetry.manifest import write_session_manifest
from rig_relay.core.telemetry.receipts import write_session_receipts
from rig_relay.core.telemetry.runtime import collect_startup_provenance
from rig_relay.core.terminal_detect import detect_terminal
from rig_relay.core.trusted_folders import has_agents_md_file

if TYPE_CHECKING:
    pass


class TelemetryMixin:
    """Mixin providing session and tool call telemetry emission."""

    def emit_new_session_telemetry(self) -> None:
        entrypoint = (
            self.entrypoint_metadata.agent_entrypoint
            if self.entrypoint_metadata
            else "unknown"
        )
        client_name = (
            self.entrypoint_metadata.client_name if self.entrypoint_metadata else None
        )
        client_version = (
            self.entrypoint_metadata.client_version
            if self.entrypoint_metadata
            else None
        )
        has_agents_md = has_agents_md_file(self._workspace_root)
        nb_skills = len(self.skill_manager.available_skills)
        nb_mcp_servers = len(self.config.mcp_servers)
        nb_models = len(self.config.models)

        terminal_emulator = None
        if entrypoint == "cli":
            terminal_emulator = detect_terminal().value

        self.telemetry_client.send_new_session(
            has_agents_md=has_agents_md,
            nb_skills=nb_skills,
            nb_mcp_servers=nb_mcp_servers,
            nb_models=nb_models,
            entrypoint=entrypoint,
            client_name=client_name,
            client_version=client_version,
            terminal_emulator=terminal_emulator,
            evidence_root_mode=resolve_evidence_root_resolution().mode.value,
            evidence_root_source=resolve_evidence_root_resolution().source,
        )

        provenance = collect_startup_provenance()
        logger.info(
            "session_id=%s package_path=%s python=%s git_head=%s version=%s",
            self.session_id,
            provenance.get("package_path"),
            provenance.get("python_executable"),
            provenance.get("git_head"),
            provenance.get("installed_version"),
        )

    def emit_ready_telemetry(self, init_duration_ms: int) -> None:
        self.telemetry_client.send_ready(init_duration_ms=init_duration_ms)

    def emit_session_closed_telemetry(self) -> None:
        self.telemetry_client.send_session_closed()
        try:
            session_path = SESSIONS_ROOT.path / self.session_id
            write_session_manifest(session_path, self.session_id)
            write_session_receipts(session_path, self.session_id)
        except Exception as e:
            logger.warning(
                "Failed to write evidence manifest/receipts for session %s: %s",
                self.session_id,
                e,
            )

    def _emit_context_observation(
        self,
        tool_call: Any,
        status: str,
        args_dict: dict[str, Any],
        blocked_by_policy: bool = False,
    ) -> None:
        try:
            if not self.config.enable_local_observability:
                return
            from rig_relay.evidence.model_observations import observe_tool_call

            observe_tool_call(
                session_id=self.session_id,
                task_kind="tool_execution",
                task_fingerprint=hashlib.sha256(
                    dump_canonical_json(args_dict).encode("utf-8")
                ).hexdigest(),
                provider_kind=self.config.get_active_provider().name,
                provider_name=self.config.get_active_provider().name,
                model_id=self.config.active_model,
                tool_call_count=1,
                tool_success_count=1 if status == "succeeded" else 0,
                failure_count=1 if status == "failed" else 0,
            )
        except Exception:
            logger.warning(
                "Failed to emit context observation for %s",
                tool_call.tool_name,
                exc_info=True,
            )
