from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
import os
from typing import TYPE_CHECKING, Any, Literal
from urllib.parse import urljoin

import httpx

from rig_relay import __version__
from rig_relay.core.config import ProviderConfig, VibeConfig
from rig_relay.core.llm.format import ResolvedToolCall
from rig_relay.core.telemetry.build_metadata import build_base_metadata
from rig_relay.core.telemetry.constants import EventName
from rig_relay.core.telemetry.tool_contract import (
    ToolDeterminismClass,
    ToolMutationClass,
    ToolOutputKind,
)
from rig_relay.core.telemetry.types import (
    AgentEntrypoint,
    EntrypointMetadata,
    TelemetryCallType,
    TeleportCompletedPayload,
    TeleportFailedPayload,
    TeleportFailureStage,
)
from rig_relay.core.utils import get_server_url_from_api_base, get_user_agent
from rig_relay.core.utils.http import build_ssl_context
from rig_relay.evidence.redaction import redact_for_remote

if TYPE_CHECKING:
    from rig_relay.core.agent_loop import ToolDecision
    from rig_relay.core.types import LLMMessage

_DEFAULT_TELEMETRY_BASE_URL = "https://api.deepseek.com"
_DATALAKE_EVENTS_PATH = "/v1/datalake/events"


@dataclass
class TelemetryUploadDecision:
    allowed: bool
    reason: str
    consent_status: str | None = None
    matched_scopes: list[str] = field(default_factory=list)
    missing_scopes: list[str] = field(default_factory=list)
    policy_version: str | None = None
    remote_enabled: bool = False
    decided_at: str = ""


_EVENT_SCOPE_PREFIX_MAP: dict[str, str] = {
    "rig.relay.tool.": "tool_refinement_metrics",
    "rig.relay.session.": "usage_metrics",
    "rig.relay.context.": "usage_metrics",
    "rig.relay.checkpoint.": "coordination_metrics",
    "coord.": "coordination_metrics",
    "rig.relay.model_observation.": "provider_model_benchmarking",
}


def _required_scopes_for_event(event_name: str) -> set:
    from rig_relay.identity.telemetry_consent import TelemetryConsentScope

    for prefix, scope_name in _EVENT_SCOPE_PREFIX_MAP.items():
        if event_name.startswith(prefix):
            if scope_name == "tool_refinement_metrics":
                return {TelemetryConsentScope.TOOL_REFINEMENT_METRICS}
            if scope_name == "usage_metrics":
                return {TelemetryConsentScope.USAGE_METRICS}
            if scope_name == "coordination_metrics":
                return {TelemetryConsentScope.COORDINATION_METRICS}
            if scope_name == "provider_model_benchmarking":
                return {TelemetryConsentScope.PROVIDER_MODEL_BENCHMARKING}
    return {TelemetryConsentScope.USAGE_METRICS}


class TelemetryClient:
    def __init__(
        self,
        config_getter: Callable[[], VibeConfig],
        session_id_getter: Callable[[], str | None] | None = None,
        parent_session_id_getter: Callable[[], str | None] | None = None,
        entrypoint_metadata_getter: Callable[[], EntrypointMetadata | None]
        | None = None,
        consent_record_getter: Callable[[], object | None] | None = None,
    ) -> None:
        self._config_getter = config_getter
        self._session_id_getter = session_id_getter
        self._parent_session_id_getter = parent_session_id_getter
        self._entrypoint_metadata_getter = entrypoint_metadata_getter
        self._consent_record_getter = consent_record_getter
        self._client: httpx.AsyncClient | None = None
        self._pending_tasks: set[asyncio.Task[Any]] = set()
        self.last_correlation_id: str | None = None

    def _get_telemetry_url(self, api_base: str) -> str:
        base = get_server_url_from_api_base(api_base) or _DEFAULT_TELEMETRY_BASE_URL
        return urljoin(base.rstrip("/"), _DATALAKE_EVENTS_PATH)

    def _get_mistral_api_key(self) -> str | None:
        """Get the API key from the active provider if it's Mistral,
        otherwise the first Mistral provider.

        Only returns an API key if the provider is a Mistral provider
        to avoid leaking third-party credentials to the telemetry endpoint.
        """
        provider_and_api_key = self._get_mistral_provider_and_api_key()
        if provider_and_api_key is None:
            return None
        _, api_key = provider_and_api_key
        return api_key

    def _get_mistral_provider_and_api_key(self) -> tuple[ProviderConfig, str] | None:
        try:
            provider = self._config_getter().get_mistral_provider()
        except Exception:
            return None
        if provider is None:
            return None
        env_var = provider.api_key_env_var
        api_key = os.getenv(env_var) if env_var else None
        if api_key is None:
            return None
        return provider, api_key

    def _is_local_observability_enabled(self) -> bool:
        try:
            config = self._config_getter()
            return config.enable_local_observability
        except Exception:
            return True

    def _is_remote_telemetry_enabled(self) -> bool:
        """Check if remote telemetry is enabled."""
        try:
            config = self._config_getter()
            return config.enable_remote_telemetry or config.enable_telemetry
        except Exception:
            return False

    def is_active(self) -> bool:
        return (
            self._is_remote_telemetry_enabled()
            and self._get_mistral_api_key() is not None
        )

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(5.0),
                limits=httpx.Limits(max_keepalive_connections=5, max_connections=10),
                verify=build_ssl_context(),
            )
        return self._client

    @property
    def session_id(self) -> str | None:
        if self._session_id_getter is None:
            return None
        return self._session_id_getter()

    @property
    def parent_session_id(self) -> str | None:
        if self._parent_session_id_getter is None:
            return None
        return self._parent_session_id_getter()

    def build_client_event_metadata(self) -> dict[str, str]:
        return build_base_metadata(
            entrypoint_metadata=(
                self._entrypoint_metadata_getter()
                if self._entrypoint_metadata_getter is not None
                else None
            ),
            session_id=self.session_id,
            parent_session_id=self.parent_session_id,
        )

    def send_telemetry_event(
        self,
        event_name: str,
        properties: dict[str, Any],
        *,
        correlation_id: str | None = None,
        receipt_candidate: bool = False,
    ) -> None:
        # Local Observability Sink
        if self._is_local_observability_enabled():
            from rig_relay.core.telemetry.local import log_local_event

            if self.session_id:
                log_local_event(
                    self.session_id,
                    event_name,
                    properties,
                    parent_session_id=self.parent_session_id,
                    receipt_candidate=receipt_candidate,
                )

        # Remote Telemetry Sink — gated by settings AND consent
        decision = self._evaluate_consent_gate(event_name)

        if not decision.allowed:
            self._log_consent_decision(event_name, decision)
            return

        provider_and_api_key = self._get_mistral_provider_and_api_key()
        if provider_and_api_key is None:
            return
        provider, mistral_api_key = provider_and_api_key
        telemetry_url = self._get_telemetry_url(provider.api_base)
        user_agent = get_user_agent(provider.backend)
        properties = self.build_client_event_metadata() | properties
        properties = redact_for_remote(properties).payload

        payload: dict[str, Any] = {"event": event_name, "properties": properties}
        if correlation_id:
            payload["correlation_id"] = correlation_id

        self._log_consent_decision(event_name, decision)

        async def _send() -> None:
            try:
                await self.client.post(
                    telemetry_url,
                    json=payload,
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {mistral_api_key}",
                        "User-Agent": user_agent,
                    },
                )
            except Exception:
                pass  # Silently swallow all exceptions for fire-and-forget telemetry

        task = asyncio.create_task(_send())
        self._pending_tasks.add(task)
        task.add_done_callback(self._pending_tasks.discard)

    async def aclose(self) -> None:
        if self._pending_tasks:
            await asyncio.gather(*self._pending_tasks, return_exceptions=True)
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    # ── Consent enforcement ───────────────────────────────────────────

    def _evaluate_consent_gate(  # noqa: PLR0911
        self, event_name: str
    ) -> TelemetryUploadDecision:
        if not self._is_remote_telemetry_enabled():
            return TelemetryUploadDecision(
                allowed=False,
                reason="remote_disabled",
                remote_enabled=False,
                decided_at=datetime.now(UTC).isoformat(),
            )

        try:
            consent = (
                self._consent_record_getter() if self._consent_record_getter else None
            )
        except Exception:
            return TelemetryUploadDecision(
                allowed=False,
                reason="consent_not_found",
                remote_enabled=True,
                decided_at=datetime.now(UTC).isoformat(),
            )

        if consent is None:
            return TelemetryUploadDecision(
                allowed=False,
                reason="consent_not_found",
                remote_enabled=True,
                decided_at=datetime.now(UTC).isoformat(),
            )

        from rig_relay.identity.telemetry_consent import (
            TelemetryConsentRecord,
            TelemetryConsentStatus,
            active_consent_scopes,
        )

        if not isinstance(consent, TelemetryConsentRecord):
            return TelemetryUploadDecision(
                allowed=False,
                reason="consent_policy_invalid",
                remote_enabled=True,
                decided_at=datetime.now(UTC).isoformat(),
            )

        if consent.status == TelemetryConsentStatus.NOT_REQUESTED:
            return TelemetryUploadDecision(
                allowed=False,
                reason="consent_not_requested",
                consent_status=consent.status.value,
                remote_enabled=True,
                decided_at=datetime.now(UTC).isoformat(),
            )

        if consent.status == TelemetryConsentStatus.DENIED:
            return TelemetryUploadDecision(
                allowed=False,
                reason="consent_denied",
                consent_status=consent.status.value,
                remote_enabled=True,
                decided_at=datetime.now(UTC).isoformat(),
            )

        if consent.status == TelemetryConsentStatus.REVOKED:
            return TelemetryUploadDecision(
                allowed=False,
                reason="consent_revoked",
                consent_status=consent.status.value,
                remote_enabled=True,
                decided_at=datetime.now(UTC).isoformat(),
            )

        if consent.status != TelemetryConsentStatus.GRANTED:
            return TelemetryUploadDecision(
                allowed=False,
                reason="consent_policy_invalid",
                consent_status=consent.status.value,
                remote_enabled=True,
                decided_at=datetime.now(UTC).isoformat(),
            )

        if consent.expires_at:
            try:
                expires = datetime.fromisoformat(consent.expires_at)
                if expires <= datetime.now(UTC):
                    return TelemetryUploadDecision(
                        allowed=False,
                        reason="consent_expired",
                        consent_status=consent.status.value,
                        remote_enabled=True,
                        decided_at=datetime.now(UTC).isoformat(),
                    )
            except ValueError:
                pass

        required_scopes = _required_scopes_for_event(event_name)
        active = set(active_consent_scopes(consent))
        matched = required_scopes & active
        missing = required_scopes - active

        if missing:
            return TelemetryUploadDecision(
                allowed=False,
                reason="scope_missing",
                consent_status=consent.status.value,
                matched_scopes=sorted(s.value for s in matched),
                missing_scopes=sorted(s.value for s in missing),
                remote_enabled=True,
                decided_at=datetime.now(UTC).isoformat(),
            )

        return TelemetryUploadDecision(
            allowed=True,
            reason="consent_granted",
            consent_status=consent.status.value,
            matched_scopes=sorted(s.value for s in required_scopes),
            policy_version=getattr(consent, "policy_version", None),
            remote_enabled=True,
            decided_at=datetime.now(UTC).isoformat(),
        )

    def _log_consent_decision(
        self, event_name: str, decision: TelemetryUploadDecision
    ) -> None:
        if not self._is_local_observability_enabled():
            return
        if not self.session_id:
            return
        from rig_relay.core.telemetry.local import log_local_event

        decision_event = (
            EventName.TELEMETRY_REMOTE_UPLOAD_ALLOWED
            if decision.allowed
            else EventName.TELEMETRY_REMOTE_UPLOAD_DENIED
        )
        denial_properties: dict[str, Any] = {
            "original_event": event_name,
            "reason": decision.reason,
            "remote_enabled": decision.remote_enabled,
            "decided_at": decision.decided_at,
        }
        if decision.consent_status:
            denial_properties["consent_status"] = decision.consent_status
        if decision.matched_scopes:
            denial_properties["matched_scopes"] = decision.matched_scopes
        if decision.missing_scopes:
            denial_properties["missing_scopes"] = decision.missing_scopes
        if decision.policy_version:
            denial_properties["policy_version"] = decision.policy_version

        log_local_event(
            self.session_id,
            decision_event,
            denial_properties,
            parent_session_id=self.parent_session_id,
        )

    # ── File metrics ──────────────────────────────────────────────────

    def _calculate_file_metrics(
        self,
        tool_call: ResolvedToolCall,
        status: Literal["success", "failure", "skipped"],
        result: dict[str, Any] | None = None,
    ) -> tuple[int, int]:
        nb_files_created = 0
        nb_files_modified = 0
        if status == "success" and result is not None:
            if tool_call.tool_name == "write_file":
                file_existed = result.get("file_existed", False)
                if file_existed:
                    nb_files_modified = 1
                else:
                    nb_files_created = 1
            elif tool_call.tool_name == "search_replace":
                nb_files_modified = 1 if result.get("blocks_applied", 0) > 0 else 0
        return nb_files_created, nb_files_modified

    def send_tool_call_finished(
        self,
        *,
        tool_call: ResolvedToolCall,
        status: Literal["success", "failure", "skipped"],
        decision: ToolDecision | None,
        agent_profile_name: str,
        model: str,
        result: dict[str, Any] | None = None,
        message_id: str | None = None,
        input_sha256: str | None = None,
        output_sha256: str | None = None,
        output_kind: ToolOutputKind = ToolOutputKind.UNKNOWN,
        mutation_class: ToolMutationClass = ToolMutationClass.UNKNOWN,
        determinism_class: ToolDeterminismClass = ToolDeterminismClass.UNKNOWN,
    ) -> None:
        verdict_value = decision.verdict.value if decision else None
        approval_type_value = decision.approval_type.value if decision else None

        nb_files_created, nb_files_modified = self._calculate_file_metrics(
            tool_call, status, result
        )

        result_keys = []
        if result:
            try:
                if isinstance(result, dict):
                    result_keys = list(result.keys())
            except Exception:
                pass

        payload = {
            "tool_name": tool_call.tool_name,
            "status": status,
            "decision": verdict_value,
            "approval_type": approval_type_value,
            "agent_profile_name": agent_profile_name,
            "model": model,
            "nb_files_created": nb_files_created,
            "nb_files_modified": nb_files_modified,
            "result_keys": result_keys,
            "message_id": message_id,
            "tool_input_sha256": input_sha256,
            "tool_output_sha256": output_sha256,
            "tool_output_kind": output_kind,
            "tool_mutation_class": mutation_class,
            "tool_determinism_class": determinism_class,
            "receipt_candidate": True,
        }
        self.send_telemetry_event(
            EventName.TOOL_CALL_COMPLETED, payload, receipt_candidate=True
        )

    def send_tool_reasoning_trace(
        self,
        *,
        session_id: str,
        tool_name: str,
        tool_call_id: str,
        message_id: str | None = None,
        normalized_input_sha256: str = "",
        tool_output_sha256: str = "",
        tool_output_kind: str = "unknown",
        output_kind_enum: ToolOutputKind = ToolOutputKind.UNKNOWN,
        tool_output_artifact_path: str | None = None,
        latency_ms: float = 0.0,
        input_bytes: int = 0,
        output_bytes: int = 0,
        inline_output_bytes: int = 0,
        artifacted_output_bytes: int = 0,
        truncated: bool = False,
        determinism_class: str = "unknown",
        mutation_class: str = "unknown",
        warnings: list[str] | None = None,
    ) -> None:
        """Emit a structured reasoning-trace event for a tool call.

        This records observable metadata around tool use — latency, byte sizes,
        determinism classification — without capturing hidden chain-of-thought.
        """
        payload = {
            "session_id": session_id,
            "tool_name": tool_name,
            "tool_call_id": tool_call_id,
            "message_id": message_id,
            "normalized_input_sha256": normalized_input_sha256,
            "tool_output_sha256": tool_output_sha256,
            "tool_output_kind": tool_output_kind,
            "tool_output_kind_enum": str(output_kind_enum),
            "tool_output_artifact_path": tool_output_artifact_path,
            "latency_ms": latency_ms,
            "input_bytes": input_bytes,
            "output_bytes": output_bytes,
            "inline_output_bytes": inline_output_bytes,
            "artifacted_output_bytes": artifacted_output_bytes,
            "truncated": truncated,
            "determinism_class": determinism_class,
            "mutation_class": mutation_class,
            "warnings": warnings or [],
        }
        self.send_telemetry_event(
            EventName.TOOL_REASONING_TRACE, payload, receipt_candidate=False
        )

    def send_user_copied_text(self, text: str) -> None:
        payload = {"text_length": len(text)}
        self.send_telemetry_event(EventName.USER_COPIED_TEXT, payload)

    def send_user_cancelled_action(self, action: str) -> None:
        payload = {"action": action}
        self.send_telemetry_event(EventName.USER_CANCELLED_ACTION, payload)

    def send_auto_compact_triggered(
        self,
        *,
        nb_context_tokens_before: int,
        nb_context_tokens_after: int,
        auto_compact_threshold: int,
        status: Literal["success", "failure", "cancelled"],
        session_id: str | None = None,
        parent_session_id: str | None = None,
    ) -> None:
        payload = {
            "nb_context_tokens_before": nb_context_tokens_before,
            "nb_context_tokens_after": nb_context_tokens_after,
            "auto_compact_threshold": auto_compact_threshold,
            "status": status,
        }
        if session_id is not None:
            payload["session_id"] = session_id
            payload["parent_session_id"] = parent_session_id
        payload = {**payload, "compact_type": "auto"}
        self.send_telemetry_event(EventName.AUTO_COMPACT_TRIGGERED, payload)

    def send_slash_command_used(
        self, command: str, command_type: Literal["builtin", "skill"]
    ) -> None:
        payload = {"command": command.lstrip("/"), "command_type": command_type}
        self.send_telemetry_event(EventName.SLASH_COMMAND_USED, payload)

    def send_new_session(
        self,
        has_agents_md: bool,
        nb_skills: int,
        nb_mcp_servers: int,
        nb_models: int,
        entrypoint: AgentEntrypoint,
        client_name: str | None,
        client_version: str | None,
        terminal_emulator: str | None = None,
        evidence_root_mode: str | None = None,
        evidence_root_source: str | None = None,
    ) -> None:
        payload = {
            "has_agents_md": has_agents_md,
            "nb_skills": nb_skills,
            "nb_mcp_servers": nb_mcp_servers,
            "nb_models": nb_models,
            "entrypoint": entrypoint,
            "version": __version__,
            "client_name": client_name,
            "client_version": client_version,
            "terminal_emulator": terminal_emulator,
            "evidence_root_mode": evidence_root_mode,
            "evidence_root_source": evidence_root_source,
        }
        self.send_telemetry_event(EventName.SESSION_STARTED, payload)

    def send_session_closed(self) -> None:
        self.send_telemetry_event(EventName.SESSION_CLOSED, {})

    def send_onboarding_api_key_added(self) -> None:
        self.send_telemetry_event(
            EventName.ONBOARDING_API_KEY_ADDED, {"version": __version__}
        )

    def send_request_sent(
        self,
        *,
        model: str,
        nb_context_chars: int,
        nb_context_messages: int,
        nb_prompt_chars: int,
        call_type: TelemetryCallType,
        message_id: str | None = None,
        messages: Sequence[LLMMessage] | None = None,
    ) -> None:
        payload: dict[str, Any] = {
            "model": model,
            "nb_context_chars": nb_context_chars,
            "nb_context_messages": nb_context_messages,
            "nb_prompt_chars": nb_prompt_chars,
            "call_source": "vibe_code",
            "call_type": call_type,
            "message_id": message_id,
        }

        if messages and self._is_local_observability_enabled():
            from rig_relay.core.telemetry.local import compute_fingerprint
            from rig_relay.core.types import Role

            by_role: dict[str, int] = {}
            largest_messages = []
            system_chars = 0
            tool_chars = 0
            user_chars = 0
            assistant_chars = 0

            for i, m in enumerate(messages):
                role_name = m.role.value
                by_role[role_name] = by_role.get(role_name, 0) + 1
                content = m.content or ""
                length = len(content)

                if m.role == Role.system:
                    system_chars += length
                elif m.role == Role.tool:
                    tool_chars += length
                elif m.role == Role.user:
                    user_chars += length
                elif m.role == Role.assistant:
                    assistant_chars += length

                largest_messages.append({
                    "role": role_name,
                    "index": i,
                    "chars": length,
                    "tool_name": m.name,
                })

            largest_messages.sort(key=lambda x: x["chars"], reverse=True)
            largest_messages = largest_messages[:10]

            # Context fingerprints
            stable_prefix = messages[0].content or "" if messages else ""
            dynamic_suffix = "".join(m.content or "" for m in messages[-3:])

            payload["context_accounting"] = {
                "total_messages": len(messages),
                "total_chars": sum(len(m.content or "") for m in messages),
                "estimated_tokens": sum(len(m.content or "") for m in messages) // 4,
                "by_role": by_role,
                "largest_messages": largest_messages,
                "system_prompt_chars": system_chars,
                "tool_result_chars": tool_chars,
                "user_message_chars": user_chars,
                "assistant_message_chars": assistant_chars,
                "stable_prefix_fingerprint": compute_fingerprint(stable_prefix),
                "dynamic_suffix_fingerprint": compute_fingerprint(dynamic_suffix),
            }

        self.send_telemetry_event(EventName.REQUEST_ACCOUNTED, payload)

    def send_ready(self, *, init_duration_ms: int) -> None:
        payload = {"init_duration_ms": init_duration_ms}
        self.send_telemetry_event(EventName.READY, payload)

    def send_at_mention_inserted(
        self,
        *,
        nb_mentions: int,
        context_types: dict[str, int],
        file_extensions: dict[str, int] | None,
        message_id: str | None,
    ) -> None:
        payload: dict[str, Any] = {
            "nb_mentions": nb_mentions,
            "context_types": context_types,
            "file_extensions": file_extensions,
            "message_id": message_id,
        }
        self.send_telemetry_event(EventName.AT_MENTION_INSERTED, payload)

    def send_user_rating_feedback(self, rating: int, model: str) -> None:
        self.send_telemetry_event(
            EventName.USER_RATING_FEEDBACK,
            {"rating": rating, "version": __version__, "model": model},
            correlation_id=self.last_correlation_id,
        )

    def send_teleport_completed(
        self,
        *,
        push_required: bool,
        github_auth_required: bool,
        nb_session_messages: int,
    ) -> None:
        payload: TeleportCompletedPayload = {
            "push_required": push_required,
            "github_auth_required": github_auth_required,
            "nb_session_messages": nb_session_messages,
        }
        self.send_telemetry_event(EventName.TELEPORT_COMPLETED, dict(payload))

    def send_teleport_failed(
        self,
        *,
        stage: TeleportFailureStage,
        error_class: str,
        push_required: bool,
        github_auth_required: bool,
        nb_session_messages: int,
    ) -> None:
        payload: TeleportFailedPayload = {
            "stage": stage,
            "error_class": error_class,
            "push_required": push_required,
            "github_auth_required": github_auth_required,
            "nb_session_messages": nb_session_messages,
        }
        self.send_telemetry_event(EventName.TELEPORT_FAILED, dict(payload))

    def send_artifact_written(
        self,
        *,
        session_id: str,
        artifact_id: str,
        artifact_path: str,
        tool_name: str,
        raw_byte_size: int,
        prompt_visible_byte_size: int,
        payload_sha256: str,
        artifact_record_sha256: str | None = None,
        truncated: bool = True,
        source_event_id: str | None = None,
        schema_version: str = "rig.relay.artifact.envelope.v1",
        evidence_kind: str = "tool_result",
        evidence_relative_path: str | None = None,
        evidence_sha256: str | None = None,
    ) -> None:
        payload = {
            "session_id": session_id,
            "evidence_kind": evidence_kind,
            "evidence_relative_path": evidence_relative_path or artifact_path,
            "evidence_sha256": evidence_sha256,
            "artifact_id": artifact_id,
            "artifact_path": artifact_path,
            "tool_name": tool_name,
            "raw_byte_size": raw_byte_size,
            "prompt_visible_byte_size": prompt_visible_byte_size,
            "payload_sha256": payload_sha256,
            "truncated": truncated,
            "source_event_id": source_event_id,
            "schema_version": schema_version,
        }
        if artifact_record_sha256 is not None:
            payload["artifact_record_sha256"] = artifact_record_sha256
        self.send_telemetry_event(
            EventName.ARTIFACT_WRITTEN, payload, receipt_candidate=True
        )

    def send_context_assembly_reported(
        self,
        session_id: str,
        report_id: str,
        total_bytes: int,
        total_estimated_tokens: int,
        stable_prefix_bytes: int,
        dynamic_suffix_bytes: int,
        cache_candidate_bytes: int,
        stable_prefix_fingerprint: str,
        dynamic_suffix_fingerprint: str,
        largest_blocks: list[dict[str, Any]],
        optimization_hints: list[str],
        evidence_kind: str = "context_assembly_report",
        evidence_relative_path: str | None = None,
        evidence_sha256: str | None = None,
    ) -> None:
        payload = {
            "session_id": session_id,
            "evidence_kind": evidence_kind,
            "evidence_relative_path": evidence_relative_path,
            "evidence_sha256": evidence_sha256,
            "report_id": report_id,
            "total_bytes": total_bytes,
            "total_estimated_tokens": total_estimated_tokens,
            "stable_prefix_bytes": stable_prefix_bytes,
            "dynamic_suffix_bytes": dynamic_suffix_bytes,
            "cache_candidate_bytes": cache_candidate_bytes,
            "stable_prefix_fingerprint": stable_prefix_fingerprint,
            "dynamic_suffix_fingerprint": dynamic_suffix_fingerprint,
            "largest_blocks": largest_blocks,
            "optimization_hints": optimization_hints,
        }
        self.send_telemetry_event(
            EventName.CONTEXT_ASSEMBLY_REPORTED, payload, receipt_candidate=False
        )

    def send_context_layout_planned(
        self,
        session_id: str,
        layout_id: str,
        stable_prefix_fingerprint: str,
        dynamic_suffix_fingerprint: str,
        stable_prefix_fingerprint_short: str,
        dynamic_suffix_fingerprint_short: str,
        stable_prefix_bytes: int,
        dynamic_suffix_bytes: int,
        ephemeral_bytes: int,
        cache_candidate_bytes: int,
        cacheability_ratio: float,
        prefix_stability_status: str,
        prefix_change_reasons: list[str],
        optimization_hints: list[str],
        layout_path: str,
        layout_hash: str,
        evidence_kind: str = "context_layout_plan",
        evidence_relative_path: str | None = None,
        evidence_sha256: str | None = None,
    ) -> None:
        payload = {
            "session_id": session_id,
            "evidence_kind": evidence_kind,
            "evidence_relative_path": evidence_relative_path or layout_path,
            "evidence_sha256": evidence_sha256 or layout_hash,
            "layout_id": layout_id,
            "stable_prefix_fingerprint": stable_prefix_fingerprint,
            "dynamic_suffix_fingerprint": dynamic_suffix_fingerprint,
            "stable_prefix_fingerprint_short": stable_prefix_fingerprint_short,
            "dynamic_suffix_fingerprint_short": dynamic_suffix_fingerprint_short,
            "stable_prefix_bytes": stable_prefix_bytes,
            "dynamic_suffix_bytes": dynamic_suffix_bytes,
            "ephemeral_bytes": ephemeral_bytes,
            "cache_candidate_bytes": cache_candidate_bytes,
            "cacheability_ratio": cacheability_ratio,
            "prefix_stability_status": prefix_stability_status,
            "prefix_change_reasons": prefix_change_reasons,
            "optimization_hints": optimization_hints,
            "layout_path": layout_path,
            "layout_hash": layout_hash,
        }
        self.send_telemetry_event(
            EventName.CONTEXT_LAYOUT_PLANNED, payload, receipt_candidate=False
        )

    def send_shadow_request_assembled(
        self,
        *,
        session_id: str,
        actual_message_count: int,
        shadow_message_count: int,
        actual_estimated_tokens: int,
        shadow_estimated_tokens: int,
        stable_prefix_bytes: int,
        dynamic_suffix_bytes: int,
        cache_candidate_bytes: int,
        estimated_token_delta: int,
        byte_delta: int,
        unchanged_stable_prefix: bool,
        shadow_diff_summary: str,
        reason_not_applied: str = "shadow_mode_only",
        stable_prefix_fingerprint: str | None = None,
        dynamic_suffix_fingerprint: str | None = None,
        evidence_kind: str = "shadow_request_report",
        evidence_relative_path: str | None = None,
        evidence_sha256: str | None = None,
    ) -> None:
        payload: dict[str, Any] = {
            "session_id": session_id,
            "evidence_kind": evidence_kind,
            "evidence_relative_path": evidence_relative_path,
            "evidence_sha256": evidence_sha256,
            "actual_message_count": actual_message_count,
            "shadow_message_count": shadow_message_count,
            "actual_estimated_tokens": actual_estimated_tokens,
            "shadow_estimated_tokens": shadow_estimated_tokens,
            "stable_prefix_bytes": stable_prefix_bytes,
            "dynamic_suffix_bytes": dynamic_suffix_bytes,
            "cache_candidate_bytes": cache_candidate_bytes,
            "estimated_token_delta": estimated_token_delta,
            "byte_delta": byte_delta,
            "unchanged_stable_prefix": unchanged_stable_prefix,
            "shadow_diff_summary": shadow_diff_summary,
            "reason_not_applied": reason_not_applied,
        }
        if stable_prefix_fingerprint is not None:
            payload["stable_prefix_fingerprint"] = stable_prefix_fingerprint
        if dynamic_suffix_fingerprint is not None:
            payload["dynamic_suffix_fingerprint"] = dynamic_suffix_fingerprint
        self.send_telemetry_event(
            EventName.SHADOW_REQUEST_ASSEMBLED, payload, receipt_candidate=False
        )
