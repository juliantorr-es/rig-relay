"""TelemetryEvidenceService — unified telemetry evidence emission.

Step 2 of AgentLoop mixin refactor. Merges ToolResponseMixin and
TelemetryMixin into a single service with explicit constructor
dependencies. No MRO-based self.* access.

Tool response telemetry is wired via the ToolExecutionContext callback.
Session lifecycle telemetry calls this service directly.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from rig_relay.core.logger import logger
from rig_relay.core.paths._vibe_home import (
    SESSIONS_ROOT,
    resolve_evidence_root_resolution,
)
from rig_relay.core.telemetry.local import dump_canonical_json
from rig_relay.core.telemetry.manifest import write_session_manifest
from rig_relay.core.telemetry.receipts import write_session_receipts
from rig_relay.core.telemetry.runtime import collect_startup_provenance
from rig_relay.core.telemetry.tool_contract import (
    ToolDeterminismClass,
    ToolMutationClass,
    ToolOutputKind,
)
from rig_relay.core.terminal_detect import detect_terminal
from rig_relay.core.trusted_folders import has_agents_md_file

_TRUNCATION_PROMPT_BYTES = 64_000

if TYPE_CHECKING:
    from rig_relay.core.llm.format import ResolvedToolCall
    from rig_relay.core.telemetry.send import TelemetryClient


class TelemetryEvidenceService:
    """Unified telemetry evidence emission.

    All dependencies passed via __init__. No attribute resolution
    through AgentLoop MRO.
    """

    __slots__ = (
        "_telemetry_client",
        "_session_id",
        "_config",
        "_entrypoint_metadata",
        "_workspace_root",
        "_skill_manager",
        "_agent_profile_name_getter",
        "_current_user_message_id_getter",
        "_active_model_getter",
    )

    def __init__(
        self,
        *,
        telemetry_client: TelemetryClient,
        session_id: str,
        config: Any,
        entrypoint_metadata: Any,
        workspace_root: Path,
        skill_manager: Any,
        agent_profile_name_getter: Any,
        current_user_message_id_getter: Any,
        active_model_getter: Any,
    ) -> None:
        self._telemetry_client = telemetry_client
        self._session_id = session_id
        self._config = config
        self._entrypoint_metadata = entrypoint_metadata
        self._workspace_root = workspace_root
        self._skill_manager = skill_manager
        self._agent_profile_name_getter = agent_profile_name_getter
        self._current_user_message_id_getter = current_user_message_id_getter
        self._active_model_getter = active_model_getter

    # ── Tool response telemetry ──────────────────────────────────

    def emit_tool_call_finished(
        self,
        *,
        tool_call: ResolvedToolCall,
        status: Literal["success", "failure", "skipped"],
        decision: Any = None,
        result: dict[str, Any] | None = None,
        input_sha256: str = "",
        output_sha256: str = "",
        output_kind: ToolOutputKind = ToolOutputKind.INLINE,
    ) -> None:
        self._telemetry_client.send_tool_call_finished(
            tool_call=tool_call,
            agent_profile_name=self._agent_profile_name_getter(),
            model=self._active_model_getter(),
            status=status,
            decision=decision,
            result=result,
            message_id=self._current_user_message_id_getter(),
            input_sha256=input_sha256,
            output_sha256=output_sha256,
            output_kind=output_kind,
            mutation_class=getattr(
                tool_call.tool_class, "mutation_class", ToolMutationClass.UNKNOWN
            ),
            determinism_class=getattr(
                tool_call.tool_class, "determinism_class", ToolDeterminismClass.UNKNOWN
            ),
        )

    def emit_tool_reasoning_trace(
        self,
        *,
        tool_call: ResolvedToolCall,
        input_sha256: str = "",
        output_sha256: str = "",
        output_kind: ToolOutputKind = ToolOutputKind.INLINE,
        input_json: str = "",
        text: str = "",
        duration_ms: float | None = None,
    ) -> None:
        text_bytes = len(text.encode("utf-8"))
        determinism_class_str = getattr(
            tool_call.tool_class, "determinism_class", ToolDeterminismClass.UNKNOWN
        )
        mutation_class_str = getattr(
            tool_call.tool_class, "mutation_class", ToolMutationClass.UNKNOWN
        )

        self._telemetry_client.send_tool_reasoning_trace(
            session_id=self._session_id,
            tool_name=tool_call.tool_name,
            tool_call_id=tool_call.call_id,
            message_id=self._current_user_message_id_getter(),
            normalized_input_sha256=input_sha256,
            tool_output_sha256=f"sha256:{output_sha256}",
            tool_output_kind=output_kind.value,
            output_kind_enum=output_kind,
            latency_ms=duration_ms or 0.0,
            input_bytes=len(input_json.encode("utf-8")),
            output_bytes=text_bytes,
            inline_output_bytes=text_bytes
            if output_kind == ToolOutputKind.INLINE
            else 0,
            artifacted_output_bytes=text_bytes
            if output_kind == ToolOutputKind.ARTIFACTED
            else 0,
            truncated=text_bytes > _TRUNCATION_PROMPT_BYTES,
            determinism_class=str(determinism_class_str),
            mutation_class=str(mutation_class_str),
        )

    def emit_artifact_written(
        self, *, artifact: Any, display_text: str, tool_name: str, sequence: int
    ) -> str:
        loop_session_id = self._session_id
        writer = None
        from rig_relay.core.telemetry.artifacts import (
            ToolOutputArtifactWriter,
            should_artifact_tool_result,
        )

        if not should_artifact_tool_result(display_text):
            return display_text

        writer = ToolOutputArtifactWriter(loop_session_id)
        artifact_rec = writer.write_artifact(
            tool_name=tool_name, raw_output=display_text, sequence=sequence
        )
        excerpt = artifact_rec.prompt_excerpt or ""
        session_root = SESSIONS_ROOT.path / loop_session_id
        artifact_relative_path = (
            Path(artifact_rec.path).relative_to(session_root).as_posix()
        )

        self._telemetry_client.send_artifact_written(
            session_id=loop_session_id,
            artifact_id=artifact_rec.artifact_id,
            artifact_path=artifact_relative_path,
            tool_name=artifact_rec.tool_name,
            raw_byte_size=artifact_rec.byte_size,
            prompt_visible_byte_size=len(excerpt.encode("utf-8")),
            payload_sha256=artifact_rec.payload_sha256,
            artifact_record_sha256=artifact_rec.artifact_record_sha256,
            truncated=artifact_rec.truncated_for_prompt,
            evidence_relative_path=artifact_relative_path,
            evidence_sha256=artifact_rec.artifact_record_sha256
            or artifact_rec.payload_sha256,
        )
        return excerpt

    def capture_model_observation(
        self,
        tool_call: ResolvedToolCall,
        status: Literal["success", "failure", "skipped"],
        duration_ms: float | None = None,
    ) -> None:
        if status == "skipped":
            return
        if not getattr(self._config, "enable_local_observability", False):
            return

        try:
            from rig_relay.evidence.model_observations import observe_tool_call
            from rig_relay.identity.consent_store import ConsentStore
            from rig_relay.identity.telemetry_consent import (
                observation_allowed_by_consent,
            )

            record = ConsentStore().get()
            provider = self._config.get_active_provider()
            is_local = getattr(provider, "backend", "") in {
                "mlx",
                "llama_cpp",
                "ollama",
            } or provider.name in {"mlx", "llama_cpp", "ollama"}
            observation_kind = "local_model" if is_local else "provider"

            if not observation_allowed_by_consent(record, observation_kind):
                return

            observe_tool_call(
                session_id=self._session_id,
                task_kind="tool_execution",
                task_fingerprint=hashlib.sha256(
                    dump_canonical_json(tool_call.args_dict).encode("utf-8")
                ).hexdigest(),
                provider_kind=provider.name,
                provider_name=provider.name,
                model_id=self._active_model_getter(),
                tool_call_count=1,
                tool_success_count=1 if status == "success" else 0,
                failure_count=1 if status == "failure" else 0,
                latency_ms=duration_ms,
            )
        except Exception:
            logger.warning(
                "Failed to capture model observation for %s",
                tool_call.tool_name,
                exc_info=True,
            )

    # ── Session lifecycle telemetry ───────────────────────────────

    def emit_new_session(self) -> None:
        entrypoint = (
            self._entrypoint_metadata.agent_entrypoint
            if self._entrypoint_metadata
            else "unknown"
        )
        client_name = (
            self._entrypoint_metadata.client_name if self._entrypoint_metadata else None
        )
        client_version = (
            self._entrypoint_metadata.client_version
            if self._entrypoint_metadata
            else None
        )
        has_agents_md = has_agents_md_file(self._workspace_root)
        nb_skills = len(self._skill_manager.available_skills)
        nb_mcp_servers = len(self._config.mcp_servers)
        nb_models = len(self._config.models)

        terminal_emulator = None
        if entrypoint == "cli":
            terminal_emulator = detect_terminal().value

        self._telemetry_client.send_new_session(
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
            self._session_id,
            provenance.get("package_path"),
            provenance.get("python_executable"),
            provenance.get("git_head"),
            provenance.get("installed_version"),
        )

    def emit_ready(self, init_duration_ms: int) -> None:
        self._telemetry_client.send_ready(init_duration_ms=init_duration_ms)

    def emit_session_closed(self) -> None:
        self._telemetry_client.send_session_closed()
        try:
            session_path = SESSIONS_ROOT.path / self._session_id
            write_session_manifest(session_path, self._session_id)
            write_session_receipts(session_path, self._session_id)
        except Exception as e:
            logger.warning(
                "Failed to write evidence manifest/receipts for session %s: %s",
                self._session_id,
                e,
            )

    def emit_context_observation(
        self,
        tool_call: Any,
        status: str,
        args_dict: dict[str, Any],
        blocked_by_policy: bool = False,
    ) -> None:
        try:
            if not getattr(self._config, "enable_local_observability", False):
                return
            from rig_relay.evidence.model_observations import observe_tool_call

            observe_tool_call(
                session_id=self._session_id,
                task_kind="tool_execution",
                task_fingerprint=hashlib.sha256(
                    dump_canonical_json(args_dict).encode("utf-8")
                ).hexdigest(),
                provider_kind=self._config.get_active_provider().name,
                provider_name=self._config.get_active_provider().name,
                model_id=self._active_model_getter(),
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
