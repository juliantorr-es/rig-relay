"""Tool response handling mixin for AgentLoop.

Extracted from agent_loop.py. Provides _handle_tool_response,
_tool_failure_event, and _capture_model_observation_for_tool_response.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from rig_relay.core.paths._vibe_home import SESSIONS_ROOT
from rig_relay.core.telemetry.artifacts import (
    ToolOutputArtifactWriter,
    should_artifact_tool_result,
)
from rig_relay.core.telemetry.local import dump_canonical_json
from rig_relay.core.telemetry.tool_contract import (
    ToolDeterminismClass,
    ToolMutationClass,
    ToolOutputKind,
)
from rig_relay.core.types import LLMMessage, ToolResultEvent

_TRUNCATION_PROMPT_BYTES = 64_000

if TYPE_CHECKING:
    from opentelemetry import trace

    from rig_relay.core._agent_models import ToolDecision
    from rig_relay.core.llm.format import ResolvedToolCall


class ToolResponseMixin:
    """Mixin providing tool response recording and telemetry."""

    def _handle_tool_response(
        self,
        tool_call: ResolvedToolCall,
        text: str,
        status: Literal["success", "failure", "skipped"],
        decision: ToolDecision | None = None,
        result: dict[str, Any] | None = None,
        span: trace.Span | None = None,
        duration_ms: float | None = None,
    ) -> None:
        input_json = dump_canonical_json(tool_call.args_dict)
        input_sha256 = hashlib.sha256(input_json.encode("utf-8")).hexdigest()
        output_sha256 = hashlib.sha256(text.encode("utf-8")).hexdigest()

        output_kind = ToolOutputKind.INLINE
        if status == "failure":
            output_kind = ToolOutputKind.ERROR
        elif not text:
            output_kind = ToolOutputKind.EMPTY
        elif should_artifact_tool_result(text):
            output_kind = ToolOutputKind.ARTIFACTED

        display_text = text
        if should_artifact_tool_result(text):
            writer = ToolOutputArtifactWriter(self.session_id)
            artifact = writer.write_artifact(
                tool_name=tool_call.tool_name,
                raw_output=text,
                sequence=len(self.messages),
            )
            display_text = artifact.prompt_excerpt or ""
            session_root = SESSIONS_ROOT.path / self.session_id
            artifact_relative_path = (
                Path(artifact.path).relative_to(session_root).as_posix()
            )

            self.telemetry_client.send_artifact_written(
                session_id=self.session_id,
                artifact_id=artifact.artifact_id,
                artifact_path=artifact_relative_path,
                tool_name=artifact.tool_name,
                raw_byte_size=artifact.byte_size,
                prompt_visible_byte_size=len(display_text.encode("utf-8")),
                payload_sha256=artifact.payload_sha256,
                artifact_record_sha256=artifact.artifact_record_sha256,
                truncated=artifact.truncated_for_prompt,
                evidence_relative_path=artifact_relative_path,
                evidence_sha256=artifact.artifact_record_sha256
                or artifact.payload_sha256,
            )

        self.messages.append(
            LLMMessage.model_validate(
                self.format_handler.create_tool_response_message(
                    tool_call, display_text
                )
            )
        )

        if span is not None:
            from rig_relay.core.tracing import set_tool_result

            set_tool_result(span, text)
        self.telemetry_client.send_tool_call_finished(
            tool_call=tool_call,
            agent_profile_name=self.agent_profile.name,
            model=self.config.active_model,
            status=status,
            decision=decision,
            result=result,
            message_id=self._current_user_message_id,
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

        determinism_class_str = getattr(
            tool_call.tool_class, "determinism_class", ToolDeterminismClass.UNKNOWN
        )
        mutation_class_str = getattr(
            tool_call.tool_class, "mutation_class", ToolMutationClass.UNKNOWN
        )
        text_bytes = len(text.encode("utf-8"))
        self.telemetry_client.send_tool_reasoning_trace(
            session_id=self.session_id,
            tool_name=tool_call.tool_name,
            tool_call_id=tool_call.call_id,
            message_id=self._current_user_message_id,
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

        self._capture_model_observation_for_tool_response(
            tool_call, status, duration_ms
        )

    def _tool_failure_event(
        self,
        tool_call: ResolvedToolCall,
        error_msg: str,
        decision: ToolDecision | None = None,
        cancelled: bool = False,
        span: trace.Span | None = None,
    ) -> ToolResultEvent:
        self._handle_tool_response(tool_call, error_msg, "failure", decision, span=span)
        return ToolResultEvent(
            tool_name=tool_call.tool_name,
            tool_class=tool_call.tool_class,
            error=error_msg,
            cancelled=cancelled,
            tool_call_id=tool_call.call_id,
        )

    def _capture_model_observation_for_tool_response(
        self,
        tool_call: ResolvedToolCall,
        status: Literal["success", "failure", "skipped"],
        duration_ms: float | None = None,
    ) -> None:
        """Build and persist a content-light ModelObservation for a completed tool call.

        Gated on:
        - status != "skipped" (skipped tools are not observed)
        - enable_local_observability (config-level gate)
        - observation_allowed_by_consent() (user-level consent gate)

        Observation failures are caught and logged without breaking tool execution.
        """
        if status == "skipped":
            return
        if not self.config.enable_local_observability:
            return

        try:
            from rig_relay.evidence.model_observations import observe_tool_call
            from rig_relay.identity.consent_store import ConsentStore
            from rig_relay.identity.telemetry_consent import (
                observation_allowed_by_consent,
            )

            record = ConsentStore().get()
            provider = self.config.get_active_provider()
            is_local = getattr(provider, "backend", "") in {
                "mlx",
                "llama_cpp",
                "ollama",
            } or provider.name in {"mlx", "llama_cpp", "ollama"}
            observation_kind = "local_model" if is_local else "provider"

            if not observation_allowed_by_consent(record, observation_kind):
                return

            observe_tool_call(
                session_id=self.session_id,
                task_kind="tool_execution",
                task_fingerprint=hashlib.sha256(
                    dump_canonical_json(tool_call.args_dict).encode("utf-8")
                ).hexdigest(),
                provider_kind=provider.name,
                provider_name=provider.name,
                model_id=self.config.active_model,
                tool_call_count=1,
                tool_success_count=1 if status == "success" else 0,
                failure_count=1 if status == "failure" else 0,
                latency_ms=duration_ms,
            )
        except Exception:
            from rig_relay.core.logger import logger

            logger.warning(
                "Failed to capture model observation for %s",
                tool_call.tool_name,
                exc_info=True,
            )
