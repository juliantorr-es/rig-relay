from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Callable, Generator
import contextlib
import copy
import os
from pathlib import Path
import threading
from threading import Thread
import time
from typing import TYPE_CHECKING, Any

from opentelemetry import trace
from pydantic import BaseModel

from rig_relay.core.agents.models import AgentProfile, BuiltinAgentName
from rig_relay.core.config import VibeConfig
from rig_relay.core.guard import DirtyGuardFailurePolicy, GuardCaptureReason, get_guard
from rig_relay.core.hooks.models import HookConfigResult, HookType, HookUserMessage
from rig_relay.core.llm.backend.factory import BACKEND_FACTORY
from rig_relay.core.llm.format import FailedToolCall, ResolvedMessage, ResolvedToolCall
from rig_relay.core.llm.types import BackendLike
from rig_relay.core.logger import logger
from rig_relay.core.middleware import ResetReason
from rig_relay.core.prompts import UtilityPrompt
from rig_relay.core.session.session_id import extract_suffix, generate_session_id
from rig_relay.core.session.session_migration import migrate_sessions_entrypoint
from rig_relay.core.skills.manager import SkillManager
from rig_relay.core.system_prompt import get_universal_system_prompt
from rig_relay.core.telemetry.types import EntrypointMetadata

_TRUNCATION_PROMPT_BYTES = 64_000
from rig_relay.context.compiler import ContextCompiler
from rig_relay.context.models import ContextEnvelopeReceipt
from rig_relay.context.repo_index import RepoContextIndex
from rig_relay.context.symbol_codec import expand_aliases
from rig_relay.core.teleport.errors import ServiceTeleportError
from rig_relay.core.teleport.telemetry import TeleportTelemetryTracker
from rig_relay.core.teleport.types import TeleportCompleteEvent
from rig_relay.core.tools.base import BaseTool, InvokeContext, ToolPermission
from rig_relay.core.tools.connectors import ConnectorRegistry, connectors_enabled
from rig_relay.core.tools.manager import ToolManager
from rig_relay.core.tools.permissions import ApprovedRule, RequiredPermission
from rig_relay.core.tracing import agent_span, tool_span
from rig_relay.core.types import (
    AgentProfileChangedEvent,
    AgentStats,
    ApprovalCallback,
    ApprovalResponse,
    AssistantEvent,
    BaseEvent,
    LLMMessage,
    ReasoningEvent,
    Role,
    ToolCall,
    ToolCallEvent,
    ToolResultEvent,
    ToolStreamEvent,
    UserInputCallback,
    UserMessageEvent,
)
from rig_relay.core.utils import (
    TOOL_ERROR_TAG,
    CancellationReason,
    get_server_url_from_api_base,
    get_user_cancellation_message,
)

try:
    from rig_relay.core.teleport.teleport import TeleportService as _TeleportService

    _TELEPORT_AVAILABLE = True
except ImportError:
    _TELEPORT_AVAILABLE = False
    _TeleportService = None

if TYPE_CHECKING:
    from rig_relay.core.teleport.teleport import TeleportService
    from rig_relay.core.teleport.types import (
        TeleportPushResponseEvent,
        TeleportYieldEvent,
    )


from rig_relay.core._agent_helpers import requires_init
from rig_relay.core._agent_init import InitHelpersMixin
from rig_relay.core._agent_models import ToolDecision, ToolExecutionResponse
from rig_relay.core._context_envelope import ContextEnvelopeMixin
from rig_relay.core._errors import (
    AgentLoopError,
    AgentLoopLLMResponseError,
    TeleportError,
)
from rig_relay.core._governance import GovernanceMixin
from rig_relay.core._llm_call import LLMCallMixin
from rig_relay.core._middleware_metadata import MiddlewareMetadataMixin
from rig_relay.core._patch_gating import PatchGatingMixin
from rig_relay.core._session_lifecycle import SessionLifecycleMixin
from rig_relay.core._telemetry import TelemetryMixin
from rig_relay.core._tool_response import ToolResponseMixin
from rig_relay.core.conversation_runtime import ConversationRuntime
from rig_relay.core.conversation_turn import (
    ConversationTurnRuntime,
    TurnOutcome,
    TurnPhase,
)
from rig_relay.core.runtime_state import AgentRuntimeState, ReadinessState
from rig_relay.core.tool_runtime import ToolRuntime
from rig_relay.core.tool_runtime_models import (
    ToolRuntimeExecutionMode,
    ToolRuntimeRequest,
    ToolRuntimeStatus,
)


class AgentLoop(
    LLMCallMixin,
    ToolResponseMixin,
    PatchGatingMixin,
    InitHelpersMixin,
    SessionLifecycleMixin,
    GovernanceMixin,
    TelemetryMixin,
    ContextEnvelopeMixin,
    MiddlewareMetadataMixin,
):
    def __init__(
        self,
        config: VibeConfig,
        *,
        agent_name: str = BuiltinAgentName.DEFAULT,
        message_observer: Callable[[LLMMessage], None] | None = None,
        max_turns: int | None = None,
        max_price: float | None = None,
        backend: BackendLike | None = None,
        enable_streaming: bool = False,
        entrypoint_metadata: EntrypointMetadata | None = None,
        is_subagent: bool = False,
        defer_heavy_init: bool = False,
        headless: bool = False,
        hook_config_result: HookConfigResult | None = None,
        workspace_root: Path | None = None,
    ) -> None:
        self._base_config = config
        self._headless = headless
        self._workspace_root = (workspace_root or Path.cwd()).resolve()
        self._worktree_id: str | None = None

        self._defer_heavy_init = defer_heavy_init
        self._deferred_init_thread: threading.Thread | None = None
        self._deferred_init_lock = threading.Lock()
        self._init_error: Exception | None = None
        self._init_start_time = time.monotonic()
        self._init_duration_ms: int | None = None

        self.message_observer = message_observer
        self._max_turns = max_turns
        self._max_price = max_price

        self._init_core_managers(config, agent_name, is_subagent, defer_heavy_init)

        self.backend_factory = lambda: backend or self._select_backend()
        self.backend = self.backend_factory()
        self.enable_streaming = enable_streaming

        self.stats = AgentStats()
        self.approval_callback: ApprovalCallback | None = None
        self.user_input_callback: UserInputCallback | None = None
        self.entrypoint_metadata = entrypoint_metadata

        try:
            active_model = config.get_active_model()
            self.stats.input_price_per_million = active_model.input_price
            self.stats.output_price_per_million = active_model.output_price
        except ValueError:
            pass

        self._current_user_message_id: str | None = None
        self._current_turn: ConversationTurnRuntime | None = None
        self._conversation_runtime: ConversationRuntime | None = None
        self._current_context_envelope: ContextEnvelopeReceipt | None = None
        self._is_user_prompt_call: bool = False

        self._init_ambient_context_packet()
        self._init_context_compiler(defer_heavy_init)
        self._tool_runtime: ToolRuntime | None = None
        self._tool_result_sink = self._make_result_sink()

        self._session_rules: list[ApprovedRule] = []
        self._approval_lock = asyncio.Lock()

        self._init_telemetry_and_guard(
            config, entrypoint_metadata, is_subagent, hook_config_result
        )

        self._teleport_service: TeleportService | None = None

        Thread(
            target=migrate_sessions_entrypoint,
            args=(config.session_logging,),
            daemon=True,
            name="migrate_sessions",
        ).start()

        if defer_heavy_init:
            self._start_deferred_init()

    def _start_deferred_init(self) -> threading.Thread:
        """Spawn a daemon thread that finishes deferred heavy I/O once."""
        with self._deferred_init_lock:
            if self._deferred_init_thread is not None:
                return self._deferred_init_thread

            thread = threading.Thread(
                target=self._complete_init, daemon=True, name="agent_loop_init"
            )
            self._deferred_init_thread = thread
            thread.start()
            return thread

    @property
    def is_initialized(self) -> bool:
        """Whether deferred initialization has completed (successfully or not)."""
        if not self._defer_heavy_init:
            return True
        thread = self._deferred_init_thread
        return thread is not None and not thread.is_alive()

    def _complete_init(self) -> None:
        """Run deferred heavy I/O: MCP, connector discovery, and context compiler.

        Intended to be called from a background thread when
        ``defer_heavy_init=True`` was passed to ``__init__``.
        """
        try:
            self.tool_manager.integrate_all(raise_on_mcp_failure=True)
            system_prompt = get_universal_system_prompt(
                self.tool_manager,
                self.config,
                self.skill_manager,
                self.agent_manager,
                scratchpad_dir=self.scratchpad_dir,
                headless=self._headless,
            )
            self.messages.update_system_prompt(system_prompt)

            # Initialize context compiler (including DuckDB repo index)
            if self._context_compiler is None:
                try:
                    repo_index = RepoContextIndex(workspace_root=self._workspace_root)
                    if repo_index.is_available:
                        repo_index.populate()
                        self._repo_index = repo_index
                except Exception:
                    self._repo_index = None
                from rig_relay.evidence.receipt_store import FilesystemReceiptStore

                self._context_compiler = ContextCompiler(
                    session_id=self.session_id,
                    workspace_root=self._workspace_root,
                    receipt_store=FilesystemReceiptStore(
                        self._workspace_root / ".rig" / "relay" / "receipts"
                    ),
                    repo_index=self._repo_index,
                )

            self._init_duration_ms = int(
                (time.monotonic() - self._init_start_time) * 1000
            )
        except Exception as exc:
            self._init_error = exc

    async def wait_until_ready(self) -> None:
        """Await deferred initialization from an async context."""
        if not self._defer_heavy_init:
            return
        thread = self._start_deferred_init()
        await asyncio.to_thread(thread.join)
        if err := self._init_error:
            raise copy.copy(err).with_traceback(err.__traceback__)
        if self._init_duration_ms is not None:
            duration, self._init_duration_ms = self._init_duration_ms, None
            self.emit_ready_telemetry(duration)

    @property
    def agent_profile(self) -> AgentProfile:
        return self.agent_manager.active_profile

    @property
    def base_config(self) -> VibeConfig:
        return self._base_config

    @property
    def config(self) -> VibeConfig:
        return self.agent_manager.config

    @property
    def bypass_tool_permissions(self) -> bool:
        return self.config.bypass_tool_permissions

    def build_runtime_state(self) -> AgentRuntimeState:
        """Build a structured snapshot of current AgentLoop runtime state."""
        readiness = ReadinessState.UNKNOWN
        if self._init_error is not None:
            readiness = ReadinessState.FAILED
        elif self.is_initialized:
            readiness = ReadinessState.READY
        elif self._defer_heavy_init:
            readiness = ReadinessState.INITIALIZING

        return AgentRuntimeState(
            session_id=self.session_id,
            parent_session_id=self.parent_session_id,
            agent_profile_name=self.agent_profile.name,
            workspace_root=str(self._workspace_root),
            current_turn_id=self._current_user_message_id,
            current_context_receipt_id=(
                self._current_context_envelope.envelope_id
                if self._current_context_envelope
                else None
            ),
            is_user_prompt_call=self._is_user_prompt_call,
            readiness=readiness,
            init_duration_ms=self._init_duration_ms,
            init_error=str(self._init_error) if self._init_error else None,
            deferred_init=self._defer_heavy_init,
            max_turns=self._max_turns,
            max_price=self._max_price,
            session_rules_count=len(self._session_rules),
            bypass_tool_permissions=self.bypass_tool_permissions,
            enable_local_observability=self.config.enable_local_observability,
            enable_streaming=self.enable_streaming,
            steps=self.stats.steps,
            context_tokens=self.stats.context_tokens,
            tool_calls_succeeded=self.stats.tool_calls_succeeded,
            tool_calls_failed=self.stats.tool_calls_failed,
            tool_calls_agreed=self.stats.tool_calls_agreed,
            tool_calls_rejected=self.stats.tool_calls_rejected,
            last_turn_duration=self.stats.last_turn_duration,
            input_price_per_million=self.stats.input_price_per_million,
            output_price_per_million=self.stats.output_price_per_million,
            active_model=(
                self.config.active_model if hasattr(self.config, "active_model") else ""
            ),
            active_provider=self.config.get_active_provider().name,
            context_packet_available=self._context_packet is not None,
        )

    @staticmethod
    def _make_result_sink() -> Any:
        """Create the tool result sink and register it as active."""
        from rig_relay.core.tool_runtime_ledger import (
            InMemoryToolRuntimeResultLedger,
            set_active_ledger,
        )

        ledger = InMemoryToolRuntimeResultLedger()
        set_active_ledger(ledger)
        return ledger

    def _get_tool_runtime(self) -> ToolRuntime:
        """Lazily construct ToolRuntime with injected adapters."""
        if self._tool_runtime is not None:
            return self._tool_runtime

        # ── Invoke tool adapter ─────────────────────────────────
        async def invoke_adapter(args_dict: dict) -> AsyncGenerator[Any, None]:
            """Adapter: ToolRuntime calls this, AgentLoop handles InvokeContext.

            ToolRuntime passes expanded args; we find the tool instance from
            the current tool call context stored on the request.
            """
            tool_name = args_dict.pop("_tool_runtime_name", "")
            tool_meta = args_dict.pop("_tool_runtime_meta", {})
            subprocess_runner = tool_meta.get("subprocess_runner")
            tool_instance = self.tool_manager.get(tool_name)
            async for item in tool_instance.invoke(
                ctx=InvokeContext(
                    tool_call_id="",
                    parent_turn_id=self._current_user_message_id,
                    agent_manager=self.agent_manager,
                    session_dir=self.session_logger.session_dir,
                    entrypoint_metadata=self.entrypoint_metadata,
                    approval_callback=self.approval_callback,
                    user_input_callback=self.user_input_callback,
                    sampling_callback=self._sampling_handler,
                    plan_file_path=self._plan_session.plan_file_path,
                    switch_agent_callback=self.switch_agent,
                    skill_manager=self.skill_manager,
                    scratchpad_dir=self.scratchpad_dir,
                    tool_manager=self.tool_manager,
                    subprocess_runner=subprocess_runner,
                    trace_recorder=getattr(self._tool_runtime, "_trace_recorder", None) if self._tool_runtime else None,
                    tool_runtime=self._tool_runtime,
                ),
                **args_dict,
            ):
                yield item

        # ── Cache adapters ──────────────────────────────────────
        def cache_check(tool_name: str, args_dict: dict) -> tuple[bool, Any]:
            tool_class = self.tool_manager.available_tools.get(tool_name)
            if tool_class is None:
                return False, None
            determinism_cls = getattr(tool_class, "determinism_class", None)
            if determinism_cls is None:
                return False, None
            from rig_relay.core.tools.cache import get_cached_result

            determinism_str = str(determinism_cls.value)
            if determinism_str not in {
                "DETERMINISTIC_PURE",
                "DETERMINISTIC_REPO_STATE",
            }:
                return False, None
            cached = get_cached_result(
                tool_name=tool_name,
                args_dict=args_dict,
                determinism_class=determinism_str,
            )
            if cached is not None:
                __args_model, _result_model = tool_class._get_type_hints()
                return True, _result_model(**cached)
            return False, None

        def cache_store(tool_name: str, args_dict: dict, result_dict: dict) -> None:
            tool_class = self.tool_manager.available_tools.get(tool_name)
            if tool_class is None:
                return
            determinism_cls = getattr(tool_class, "determinism_class", None)
            if determinism_cls is None:
                return
            from rig_relay.core.tools.cache import set_cached_result

            determinism_str = str(determinism_cls.value)
            if determinism_str in {"DETERMINISTIC_PURE", "DETERMINISTIC_REPO_STATE"}:
                set_cached_result(
                    tool_name=tool_name,
                    args_dict=args_dict,
                    result_dict=result_dict,
                    determinism_class=determinism_str,
                )

        # ── Permission decision ─────────────────────────────────
        async def permission_decision(
            tool_name: str, args_dict: dict, call_id: str
        ) -> tuple[bool, str]:
            if self.bypass_tool_permissions:
                return True, ""
            try:
                tool_instance = self.tool_manager.get(tool_name)
                from rig_relay.core._agent_models import ToolExecutionResponse

                decision = await self._should_execute_tool(
                    tool_instance, tool_instance.ArgsModel(**args_dict), call_id
                )
                if decision.verdict == ToolExecutionResponse.SKIP:
                    return False, decision.feedback or "Tool execution skipped"
                return True, ""
            except Exception:
                return True, ""

        # ── Approval adapter ────────────────────────────────────
        async def approval_request(
            tool_name: str, args_dict: dict, call_id: str
        ) -> tuple[bool, str]:
            if self.approval_callback is None:
                return True, ""
            try:
                tool_instance = self.tool_manager.get(tool_name)
                from rig_relay.core.types import ApprovalResponse

                response, feedback = await self.approval_callback(
                    tool_name, tool_instance.ArgsModel(**args_dict), call_id, []
                )
                return response == ApprovalResponse.YES, feedback or ""
            except Exception:
                return True, ""

        # ── Patch gate adapter ──────────────────────────────────
        def patch_gate_check(tool_call_ref: Any, tool_instance_ref: Any) -> Any | None:
            """Patch gate check. tool_call_ref expected to be a ResolvedToolCall."""
            if tool_call_ref is None:
                return None
            tool_name = getattr(tool_call_ref, "tool_name", "")
            try:
                tool_instance = self.tool_manager.get(tool_name)
            except Exception:
                return None
            return self._check_patch_proposal_gating(tool_call_ref, tool_instance)

        # ── Expand args adapter ─────────────────────────────────
        def expand_args(args_dict: dict) -> dict:
            return self._expand_tool_call_args(args_dict)

        # ── Receipt adapters ────────────────────────────────────
        def receipt_build(tool_name: str, result_model: Any) -> Any | None:
            tool_class = self.tool_manager.available_tools.get(tool_name)
            if tool_class is None:
                return None
            build_receipt = getattr(tool_class, "build_receipt", None)
            if build_receipt is None:
                return None
            return build_receipt(result_model)

        def receipt_capture(
            session_id: str, tool_name: str, receipt_dict: dict
        ) -> None:
            try:
                from rig_relay.evidence.model_observations import capture_tool_receipt

                capture_tool_receipt(
                    session_id=self.session_id,
                    tool_name=tool_name,
                    receipt=receipt_dict,
                )
            except Exception:
                logger.warning(
                    "Receipt capture failed for %s", tool_name, exc_info=True
                )

        # ── Context observation adapter ─────────────────────────
        def context_observe(
            status: str,
            tool_name: str,
            args_dict: dict,
            blocked_by_policy: bool = False,
        ) -> None:
            if not self.config.enable_local_observability:
                return
            try:
                import hashlib

                from rig_relay.evidence.model_observations import observe_tool_call

                observe_tool_call(
                    session_id=self.session_id,
                    task_kind="tool_execution",
                    task_fingerprint=hashlib.sha256(
                        str(args_dict).encode("utf-8")
                    ).hexdigest(),
                    provider_kind=self.config.get_active_provider().name,
                    provider_name=self.config.get_active_provider().name,
                    model_id=(
                        self.config.active_model
                        if hasattr(self.config, "active_model")
                        else ""
                    ),
                    tool_call_count=1,
                    tool_success_count=1 if status == "succeeded" else 0,
                    failure_count=1 if status == "failed" else 0,
                )
            except Exception:
                pass

        # ── Stats adapter ───────────────────────────────────────
        def stats_delta(key: str, delta: int) -> None:
            current = getattr(self.stats, key, 0)
            setattr(self.stats, key, current + delta)

        self._tool_runtime = ToolRuntime(
            invoke_tool=invoke_adapter,
            cache_check=cache_check,
            cache_store=cache_store,
            permission_decision=permission_decision,
            approval_request=approval_request,
            patch_gate_check=patch_gate_check,
            expand_args=expand_args,
            receipt_build=receipt_build,
            receipt_capture=receipt_capture,
            context_observe=context_observe,
            stats_delta=stats_delta,
            subprocess_runner=self._build_subprocess_runner(),
        )
        return self._tool_runtime

    def _build_subprocess_runner(self) -> Any:
        """Build a RuntimeSupervisor-backed subprocess runner if available."""
        try:
            from rig_relay.runtime.supervisor_invoker import (
                RuntimeSupervisorToolSubprocessRunner,
            )

            return RuntimeSupervisorToolSubprocessRunner()
        except Exception:
            return None

    def refresh_config(self) -> None:
        self._base_config = VibeConfig.load()
        self.agent_manager.invalidate_config()

    async def aclose(self) -> None:
        with contextlib.suppress(Exception):
            await self.backend.__aexit__(None, None, None)

    def _create_connector_registry(self) -> ConnectorRegistry | None:
        if not connectors_enabled():
            return None

        provider = self._base_config.get_mistral_provider()
        if provider is None:
            return None

        api_key_env = provider.api_key_env_var or "MISTRAL_API_KEY"
        api_key = os.getenv(api_key_env, "")
        if not api_key:
            return None

        server_url = get_server_url_from_api_base(provider.api_base)
        return ConnectorRegistry(api_key=api_key, server_url=server_url)

    @requires_init
    async def refresh_system_prompt(self) -> None:
        """Rebuild and replace the system prompt with current tool/skill state."""
        system_prompt = get_universal_system_prompt(
            self.tool_manager,
            self.config,
            self.skill_manager,
            self.agent_manager,
            headless=self._headless,
        )
        self.messages.update_system_prompt(system_prompt)

    def _select_backend(self) -> BackendLike:
        provider = self.config.get_active_provider()
        timeout = self.config.api_timeout
        return BACKEND_FACTORY[provider.backend](provider=provider, timeout=timeout)

    async def _save_messages(self) -> None:
        await self.session_logger.save_interaction(
            self.messages,
            self.stats,
            self._base_config,
            self.tool_manager,
            self.agent_profile,
        )

    @requires_init
    async def inject_user_context(self, content: str) -> None:
        self.messages.append(LLMMessage(role=Role.user, content=content, injected=True))
        await self._save_messages()

    def _get_conversation_runtime(self) -> ConversationRuntime:
        """Lazily construct ConversationRuntime with AgentLoop as callback adapter."""
        return ConversationRuntime()

    @requires_init
    async def act(
        self,
        msg: str,
        client_message_id: str | None = None,
        *,
        context_envelope: ContextEnvelopeReceipt | None = None,
    ) -> AsyncGenerator[BaseEvent, None]:
        self._clean_message_history()
        self.rewind_manager.create_checkpoint()
        try:
            model_name = self.config.get_active_model().name
        except ValueError:
            model_name = None
        async with agent_span(model=model_name, session_id=self.session_id):
            previous_context_envelope = self._current_context_envelope
            self._current_context_envelope = context_envelope
            try:
                async for event in self._conversation_loop(
                    msg, client_message_id=client_message_id
                ):
                    yield event
            finally:
                self._current_context_envelope = previous_context_envelope
                self._current_turn = None
                self._conversation_runtime = None

    @property
    def teleport_service(self) -> TeleportService:
        if not _TELEPORT_AVAILABLE:
            raise TeleportError(
                "Teleport requires git to be installed. "
                "Please install git and try again."
            )

        if self._teleport_service is None:
            if _TeleportService is None:
                raise TeleportError("_TeleportService is unexpectedly None")
            self._teleport_service = _TeleportService(
                session_logger=self.session_logger,
                vibe_code_base_url=self.config.vibe_code_base_url,
                vibe_code_workflow_id=self.config.vibe_code_workflow_id,
                vibe_code_api_key=self.config.vibe_code_api_key,
                vibe_code_task_queue=self.config.vibe_code_task_queue,
                vibe_config=self._base_config,
            )
        return self._teleport_service

    @requires_init
    async def teleport_to_vibe_code(
        self, prompt: str | None
    ) -> AsyncGenerator[TeleportYieldEvent, TeleportPushResponseEvent | None]:
        from rig_relay.core.teleport.nuage import TeleportSession

        session_messages = [
            msg.model_dump(exclude_none=True) for msg in self.messages[1:]
        ]
        telemetry_tracker = TeleportTelemetryTracker(
            telemetry_client=self.telemetry_client,
            nb_session_messages=len(session_messages),
            stage="no_history"
            if prompt is None and not session_messages
            else "git_check",
        )
        session = TeleportSession(
            metadata={
                "agent": self.agent_profile.name,
                "model": self.config.active_model,
                "stats": self.stats.model_dump(),
            },
            messages=session_messages,
        )
        try:
            async with self.teleport_service:
                gen = self.teleport_service.execute(prompt=prompt, session=session)
                response: TeleportPushResponseEvent | None = None
                while True:
                    try:
                        event = await gen.asend(response)
                        telemetry_tracker.record_event(event)
                        if isinstance(event, TeleportCompleteEvent):
                            telemetry_tracker.send_success()
                        response = yield event
                    except StopAsyncIteration:
                        break
        except ServiceTeleportError as e:
            telemetry_tracker.record_service_error(e)
            raise TeleportError(str(e)) from e
        except (asyncio.CancelledError, GeneratorExit):
            telemetry_tracker.record_cancelled()
            raise
        except Exception as e:
            telemetry_tracker.record_unexpected_error(e)
            raise
        finally:
            telemetry_tracker.send_failure_if_needed()
            self._teleport_service = None

    def _build_loop_adapter(self, user_msg: str) -> _ConversationLoopAdapter:
        return _ConversationLoopAdapter(self, user_msg)

    async def _conversation_loop(
        self, user_msg: str, client_message_id: str | None = None
    ) -> AsyncGenerator[BaseEvent]:
        turn = ConversationTurnRuntime(
            session_id=self.session_id,
            user_message_id=client_message_id,
            user_message_text=user_msg,
        )
        self._current_turn = turn

        cr = self._get_conversation_runtime()
        self._conversation_runtime = cr
        cr._session_id = self.session_id
        cr._start_time = time.monotonic()
        cr.set_turn_id(turn.turn_id)
        cr._phase(TurnPhase.CREATED)

        user_message = LLMMessage(
            role=Role.user, content=user_msg, message_id=client_message_id
        )
        self.messages.append(user_message)
        self.stats.steps += 1
        self._current_user_message_id = user_message.message_id

        if user_message.message_id is None:
            raise AgentLoopError("User message must have a message_id")

        yield UserMessageEvent(content=user_msg, message_id=user_message.message_id)

        if self._hooks_manager:
            self._hooks_manager.reset_retry_count()

        adapter = self._build_loop_adapter(user_msg)
        async for event in cr.execute_turn_loop(adapter):
            yield event
            await self._save_messages()

    async def _perform_llm_turn(self) -> AsyncGenerator[BaseEvent, None]:
        if self.enable_streaming:
            async for event in self._stream_assistant_events():
                yield event
        else:
            assistant_event = await self._get_assistant_event()
            if assistant_event.content:
                yield assistant_event

        last_message = self.messages[-1]

        parsed = self.format_handler.parse_message(last_message)
        resolved = self.format_handler.resolve_tool_calls(parsed, self.tool_manager)

        if (turn := getattr(self, "_current_turn", None)) is not None:
            turn.advance(TurnPhase.ASSISTANT_PARSED)
            if last_message.content:
                turn.assistant_content_length = len(last_message.content)

        if not resolved.tool_calls and not resolved.failed_calls:
            return

        if (turn := getattr(self, "_current_turn", None)) is not None:
            turn.tool_call_count = len(resolved.tool_calls) + len(resolved.failed_calls)
            turn.advance(TurnPhase.TOOL_CALLS_RUNNING)
            if (cr := self._conversation_runtime) is not None:
                cr.set_tool_call_count(turn.tool_call_count)

        profile_before = self.agent_profile.name
        async for event in self._handle_tool_calls(resolved):
            yield event
        if (turn := getattr(self, "_current_turn", None)) is not None:
            turn.advance(TurnPhase.TOOL_CALLS_COMPLETED)
        if self.agent_profile.name != profile_before:
            yield AgentProfileChangedEvent(agent_name=self.agent_profile.name)

    def _build_tool_call_events(
        self, tool_calls: list[ToolCall] | None, emitted_ids: set[str]
    ) -> Generator[ToolCallEvent, None, None]:
        for tc in tool_calls or []:
            if tc.id is None or not tc.function.name:
                continue
            if tc.id in emitted_ids:
                continue

            tool_class = self.tool_manager.available_tools.get(tc.function.name)
            if tool_class is None:
                continue

            yield ToolCallEvent(
                tool_call_id=tc.id,
                tool_call_index=tc.index,
                tool_name=tc.function.name,
                tool_class=tool_class,
            )

    async def _stream_assistant_events(
        self,
    ) -> AsyncGenerator[AssistantEvent | ReasoningEvent | ToolCallEvent]:
        message_id: str | None = None
        reasoning_message_id: str | None = None
        emitted_tool_call_ids = set[str]()

        async for chunk in self._chat_streaming():
            if message_id is None:
                message_id = chunk.message.message_id
            if reasoning_message_id is None:
                reasoning_message_id = chunk.message.reasoning_message_id

            for event in self._build_tool_call_events(
                chunk.message.tool_calls, emitted_tool_call_ids
            ):
                emitted_tool_call_ids.add(event.tool_call_id)
                yield event

            if chunk.message.reasoning_content:
                yield ReasoningEvent(
                    content=chunk.message.reasoning_content,
                    message_id=reasoning_message_id,
                )

            if chunk.message.content:
                yield AssistantEvent(
                    content=chunk.message.content, message_id=message_id
                )

    async def _get_assistant_event(self) -> AssistantEvent:
        llm_result = await self._chat()
        return AssistantEvent(
            content=llm_result.message.content or "",
            message_id=llm_result.message.message_id,
        )

    async def _emit_failed_tool_events(
        self, failed_calls: list[FailedToolCall]
    ) -> AsyncGenerator[ToolResultEvent]:
        for failed in failed_calls:
            error_msg = f"<{TOOL_ERROR_TAG}>{failed.tool_name}: {failed.error}</{TOOL_ERROR_TAG}>"
            yield ToolResultEvent(
                tool_name=failed.tool_name,
                tool_class=None,
                error=error_msg,
                tool_call_id=failed.call_id,
            )
            self.stats.tool_calls_failed += 1
            self.messages.append(
                self.format_handler.create_failed_tool_response_message(
                    failed, error_msg
                )
            )

    async def _process_one_tool_call(
        self, tool_call: ResolvedToolCall
    ) -> AsyncGenerator[ToolResultEvent | ToolStreamEvent]:
        async with tool_span(
            tool_name=tool_call.tool_name,
            call_id=tool_call.call_id,
            arguments=tool_call.validated_args.model_dump_json(),
        ) as span:
            async for event in self._execute_tool_call(span, tool_call):
                yield event

    def _expand_tool_call_args(self, args: Any) -> Any:
        envelope = self._current_context_envelope
        if envelope is None or envelope.symbol_manifest is None:
            return args
        if isinstance(args, str):
            return expand_aliases(args, envelope.symbol_manifest)
        if isinstance(args, list):
            return [self._expand_tool_call_args(item) for item in args]
        if isinstance(args, tuple):
            return tuple(self._expand_tool_call_args(item) for item in args)
        if isinstance(args, dict):
            return {
                key: self._expand_tool_call_args(value) for key, value in args.items()
            }
        return args

    def _check_tool_result_cache(
        self, tool_call: ResolvedToolCall
    ) -> ToolResultEvent | None:
        """Check the deterministic tool result cache. Returns cached result event or None."""
        determinism_cls = getattr(tool_call.tool_class, "determinism_class", None)
        if determinism_cls is None:
            return None

        from rig_relay.core.tools.cache import get_cached_result

        determinism_str = str(determinism_cls.value)
        if determinism_str not in {"DETERMINISTIC_PURE", "DETERMINISTIC_REPO_STATE"}:
            return None

        cached = get_cached_result(
            tool_name=tool_call.tool_name,
            args_dict=tool_call.args_dict,
            determinism_class=determinism_str,
        )
        if cached is None:
            return None

        _args_model, _result_model_cls = tool_call.tool_class._get_type_hints()
        result_model = _result_model_cls(**cached)
        return ToolResultEvent(
            tool_name=tool_call.tool_name,
            tool_class=tool_call.tool_class,
            result=result_model,
            cached=True,
            tool_call_id=tool_call.call_id,
        )

    async def _execute_tool_call(
        self, span: trace.Span, tool_call: ResolvedToolCall
    ) -> AsyncGenerator[ToolResultEvent | ToolStreamEvent]:
        """Delegate one-tool execution to ToolRuntime.

        AgentLoop builds the request, delegates to ToolRuntime for
        governed execution, then adapts the structured result into
        provider-compatible events and telemetry.
        """
        runtime = self._get_tool_runtime()
        tn = tool_call.tool_name
        cid = tool_call.call_id

        # ── Build request ───────────────────────────────────────
        exec_mode = ToolRuntimeExecutionMode.UNKNOWN
        if tool_call.tool_class is not None:
            mut_cls = getattr(tool_call.tool_class, "mutation_class", None)
            if mut_cls is not None:
                mut_str = (
                    str(mut_cls.value) if hasattr(mut_cls, "value") else str(mut_cls)
                )
                if "execution" in mut_str.lower():
                    exec_mode = ToolRuntimeExecutionMode.MUTATION_EXECUTION
                elif "proposal" in mut_str.lower():
                    exec_mode = ToolRuntimeExecutionMode.MUTATION_PROPOSAL
            else:
                exec_mode = ToolRuntimeExecutionMode.READ_ONLY

        # Verify tool exists (same error as before)
        try:
            self.tool_manager.get(tn)
        except Exception as exc:
            yield self._tool_failure_event(
                tool_call, f"Error getting tool '{tn}': {exc}", span=span
            )
            return

        request = ToolRuntimeRequest(
            tool_name=tn,
            tool_args=tool_call.args_dict,
            tool_call_id=cid,
            turn_id=self._current_user_message_id,
            session_id=self.session_id,
            execution_mode=exec_mode,
            bypass_permissions=self.bypass_tool_permissions,
        )

        # ── Rewind snapshot (pre-invocation) ─────────────────────
        try:
            of_interest = self.tool_manager.get(tn)
            snapshot = of_interest.get_file_snapshot(tool_call.validated_args)
            if snapshot is not None:
                self.rewind_manager.add_snapshot(snapshot)
        except Exception:
            pass

        # ── Governed execution ───────────────────────────────────
        try:
            result = await runtime.execute_one(request)
        except asyncio.CancelledError:
            cancel = str(
                get_user_cancellation_message(CancellationReason.TOOL_INTERRUPTED)
            )
            if (turn := getattr(self, "_current_turn", None)) is not None:
                turn.tool_failure_count += 1
            yield self._tool_failure_event(
                tool_call, cancel, None, cancelled=True, span=span
            )
            raise

        # ── Adapt result ─────────────────────────────────────────
        if (turn := getattr(self, "_current_turn", None)) is not None:
            if result.duration_ms is not None:
                turn.tool_total_duration_ms += result.duration_ms

        match result.status:
            case ToolRuntimeStatus.CACHED:
                cached_event = ToolResultEvent(
                    tool_name=tn,
                    tool_class=tool_call.tool_class,
                    result=result.provider_tool_response,
                    cached=True,
                    tool_call_id=cid,
                )
                if (turn := getattr(self, "_current_turn", None)) is not None:
                    turn.tool_success_count += 1
                self._tool_result_sink.record(result)
                yield cached_event
                return

            case ToolRuntimeStatus.COMPLETED | ToolRuntimeStatus.DEGRADED:
                # Yield stream events collected during invocation
                for ev in result.tool_events:
                    yield ev

                response_model = result.provider_tool_response
                duration_sec = result.duration_ms / 1000 if result.duration_ms else 0

                if response_model is not None and hasattr(response_model, "model_dump"):
                    result_dict = response_model.model_dump()
                    text = "\n".join(f"{k}: {v}" for k, v in result_dict.items())
                    try:
                        of_interest = self.tool_manager.get(tn)
                        extra = of_interest.get_result_extra(response_model)
                        if extra:
                            text += "\n\n" + extra
                    except Exception:
                        pass

                    self._handle_tool_response(
                        tool_call,
                        text,
                        "success",
                        None,
                        result_dict,
                        span=span,
                        duration_ms=duration_sec * 1000,
                    )

                yield ToolResultEvent(
                    tool_name=tn,
                    tool_class=tool_call.tool_class,
                    result=response_model,
                    cancelled=(
                        getattr(response_model, "cancelled", False)
                        if response_model is not None
                        else False
                    ),
                    duration=duration_sec,
                    tool_call_id=cid,
                )
                if (turn := getattr(self, "_current_turn", None)) is not None:
                    turn.tool_success_count += 1
                self._tool_result_sink.record(result)
                return

            case ToolRuntimeStatus.REFUSED:
                refusal = result.refusal
                reason = refusal.message if refusal else "Tool execution refused"
                skip_event = ToolResultEvent(
                    tool_name=tn,
                    tool_class=tool_call.tool_class,
                    skipped=True,
                    skip_reason=reason,
                    cancelled=False,
                    tool_call_id=cid,
                )
                if (turn := getattr(self, "_current_turn", None)) is not None:
                    turn.tool_skip_count += 1
                yield skip_event
                self._handle_tool_response(
                    tool_call, reason, "skipped", None, span=span
                )
                self._tool_result_sink.record(result)
                return

            case ToolRuntimeStatus.FAILED:
                error_msg = (
                    f"<{TOOL_ERROR_TAG}>{tn} failed: "
                    f"{result.error_message or ''}</{TOOL_ERROR_TAG}>"
                )
                if (turn := getattr(self, "_current_turn", None)) is not None:
                    turn.tool_failure_count += 1
                yield self._tool_failure_event(tool_call, error_msg, None, span=span)
                self._tool_result_sink.record(result)
                return

            case _:
                error_msg = (
                    f"<{TOOL_ERROR_TAG}>{tn}: unknown status "
                    f"{result.status}</{TOOL_ERROR_TAG}>"
                )
                if (turn := getattr(self, "_current_turn", None)) is not None:
                    turn.tool_failure_count += 1
                yield self._tool_failure_event(tool_call, error_msg, None, span=span)

    async def _handle_tool_calls(
        self, resolved: ResolvedMessage
    ) -> AsyncGenerator[ToolCallEvent | ToolResultEvent | ToolStreamEvent]:
        async for event in self._emit_failed_tool_events(resolved.failed_calls):
            yield event
        if not resolved.tool_calls:
            return

        for tool_call in resolved.tool_calls:
            yield ToolCallEvent(
                tool_name=tool_call.tool_name,
                tool_class=tool_call.tool_class,
                args=tool_call.validated_args,
                tool_call_id=tool_call.call_id,
            )

        async for event in self._run_tools_concurrently(resolved.tool_calls):
            yield event

        # Passive GC: after tool execution, check storage budget
        # and prune stale artifacts if over threshold.
        await self._maybe_auto_gc()

    async def _execute_tool_to_queue(
        self,
        tc: ResolvedToolCall,
        queue: asyncio.Queue[ToolCallEvent | ToolResultEvent | ToolStreamEvent | None],
    ) -> None:
        """Run a single tool call, sending events to the queue."""
        async for event in self._process_one_tool_call(tc):
            await queue.put(event)

    async def _run_tools_concurrently(
        self, tool_calls: list[ResolvedToolCall]
    ) -> AsyncGenerator[ToolCallEvent | ToolResultEvent | ToolStreamEvent]:
        """Execute multiple tool calls concurrently, yielding events as they arrive."""
        queue: asyncio.Queue[
            ToolCallEvent | ToolResultEvent | ToolStreamEvent | None
        ] = asyncio.Queue()

        tasks = [
            asyncio.create_task(self._execute_tool_to_queue(tc, queue))
            for tc in tool_calls
        ]

        async def _signal_when_all_done() -> None:
            try:
                await asyncio.gather(*tasks, return_exceptions=True)
            finally:
                await queue.put(None)

        monitor = asyncio.create_task(_signal_when_all_done())

        try:
            while True:
                event = await queue.get()
                if event is None:
                    break
                yield event
        except GeneratorExit:
            for t in tasks:
                if not t.done():
                    t.cancel()
            raise
        except asyncio.CancelledError:
            for t in tasks:
                if not t.done():
                    t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise
        finally:
            if not monitor.done():
                monitor.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await monitor

    async def _maybe_auto_gc(self) -> None:
        if not self.config.enable_local_observability:
            return

        try:
            from rig_relay.evidence.storage_lifecycle import compute_storage_summary

            summary = compute_storage_summary(self._workspace_root / ".rig" / "relay")
            budget_status = summary.get("budget_status", "ok")

            if budget_status not in {"warn", "over_budget", "fleet_blocked"}:
                return

            try:
                from rig_relay.evidence.storage_lifecycle import run_artifact_gc

                result = run_artifact_gc(
                    root=self._workspace_root / ".rig" / "relay",
                    budget=summary,
                    confirm=True,
                )
                deleted = result.get("summary", {}).get("deleted", 0)
                freed_mb = result.get("summary", {}).get("freed_mb", 0.0)
                if deleted > 0:
                    self.stats.gc_deleted_count = (
                        getattr(self.stats, "gc_deleted_count", 0) + deleted
                    )
                    logger.info(
                        "Auto-GC: removed %d artifacts (%.1f MB) after tool execution",
                        deleted,
                        freed_mb,
                    )
            except ImportError:
                pass
        except Exception:
            logger.warning("Auto-GC failed", exc_info=True)

    async def _should_execute_tool(
        self, tool: BaseTool, args: BaseModel, tool_call_id: str
    ) -> ToolDecision:
        if self.bypass_tool_permissions:
            return ToolDecision(
                verdict=ToolExecutionResponse.EXECUTE,
                approval_type=ToolPermission.ALWAYS,
            )

    async def _ask_approval(
        self,
        tool_name: str,
        args: BaseModel,
        tool_call_id: str,
        required_permissions: list[RequiredPermission],
    ) -> ToolDecision:
        if not self.approval_callback:
            return ToolDecision(
                verdict=ToolExecutionResponse.SKIP,
                approval_type=ToolPermission.ASK,
                feedback="Tool execution not permitted.",
            )
        response, feedback = await self.approval_callback(
            tool_name, args, tool_call_id, required_permissions
        )

        match response:
            case ApprovalResponse.YES:
                verdict = ToolExecutionResponse.EXECUTE
            case _:
                verdict = ToolExecutionResponse.SKIP

        return ToolDecision(
            verdict=verdict, approval_type=ToolPermission.ASK, feedback=feedback
        )

    async def fork(self, message_id: str | None = None) -> AgentLoop:
        messages = self._messages_for_fork(message_id)
        forked = AgentLoop(
            config=self.base_config.model_copy(deep=True),
            agent_name=self.agent_profile.name,
            enable_streaming=self.enable_streaming,
            entrypoint_metadata=self.entrypoint_metadata,
            defer_heavy_init=True,
            hook_config_result=self._hook_config_result,
            workspace_root=self._workspace_root,
        )
        forked.session_id = generate_session_id(suffix=extract_suffix(self.session_id))
        forked.parent_session_id = self.session_id
        forked.session_logger.reset_session(
            forked.session_id, parent_session_id=self.session_id
        )

        # ── dirty-file guard: child baseline from current repo state ──
        try:
            get_guard().recapture(
                reason=GuardCaptureReason.FORK_CHILD,
                failure_policy=DirtyGuardFailurePolicy.FAIL_CLOSED_FOR_MUTATION,
            )
        except Exception:
            pass

        forked.messages.extend(messages)
        await forked.session_logger.save_interaction(
            forked.messages,
            forked.stats,
            forked.base_config,
            forked.tool_manager,
            forked.agent_profile,
        )
        return forked

    @requires_init
    async def clear_history(self) -> None:
        await self.session_logger.save_interaction(
            self.messages,
            self.stats,
            self._base_config,
            self.tool_manager,
            self.agent_profile,
        )
        self.messages.reset(self.messages[:1])

        self.stats = AgentStats.create_fresh(self.stats)
        self.stats.trigger_listeners()

        try:
            active_model = self.config.get_active_model()
            self.stats.update_pricing(
                active_model.input_price, active_model.output_price
            )
        except ValueError:
            pass

        self.middleware_pipeline.reset()
        self.tool_manager.reset_all()
        self._reset_session(keep_parent=False)

    @requires_init
    async def compact(self, extra_instructions: str = "") -> str:
        try:
            self._clean_message_history()
            await self.session_logger.save_interaction(
                self.messages,
                self.stats,
                self._base_config,
                self.tool_manager,
                self.agent_profile,
            )

            summary_request = UtilityPrompt.COMPACT.read()
            if extra_instructions:
                summary_request += (
                    f"\n\n## Additional Instructions\n{extra_instructions}"
                )
            self.stats.steps += 1

            with self.messages.silent():
                self.messages.append(
                    LLMMessage(role=Role.user, content=summary_request)
                )
                summary_result = await self._chat(
                    model_override=self.config.get_compaction_model()
                )

            if summary_result.usage is None:
                raise AgentLoopLLMResponseError(
                    "Usage data missing in compaction summary response"
                )
            summary_content = summary_result.message.content or ""

            system_message = self.messages[0]
            summary_message = LLMMessage(role=Role.user, content=summary_content)
            self.messages.reset([system_message, summary_message])

            active_model = self.config.get_active_model()
            self._reset_session()

            actual_context_tokens = await self.backend.count_tokens(
                model=active_model,
                messages=self.messages,
                tools=self.format_handler.get_available_tools(self.tool_manager),
                extra_headers=self._get_extra_headers(),
                metadata=self._build_backend_metadata().model_dump(exclude_none=True),
            )

            self.stats.context_tokens = actual_context_tokens
            await self.session_logger.save_interaction(
                self.messages,
                self.stats,
                self._base_config,
                self.tool_manager,
                self.agent_profile,
            )

            self.middleware_pipeline.reset(reset_reason=ResetReason.COMPACT)

            return summary_content or ""

        except Exception:
            await self.session_logger.save_interaction(
                self.messages,
                self.stats,
                self._base_config,
                self.tool_manager,
                self.agent_profile,
            )
            raise

    @requires_init
    async def switch_agent(self, agent_name: str) -> None:
        if agent_name == self.agent_profile.name:
            return
        self.agent_manager.switch_profile(agent_name)
        await self.reload_with_initial_messages(reset_middleware=False)

    @requires_init
    async def reload_with_initial_messages(
        self,
        base_config: VibeConfig | None = None,
        max_turns: int | None = None,
        max_price: float | None = None,
        reset_middleware: bool = True,
    ) -> None:
        # Force an immediate yield to allow the UI to update before heavy sync work.
        # When there are no messages, save_interaction returns early without any await,
        # so the coroutine would run synchronously through ToolManager, SkillManager,
        # and system prompt generation without yielding control to the event loop.
        await asyncio.sleep(0)

        await self.session_logger.save_interaction(
            self.messages,
            self.stats,
            self._base_config,
            self.tool_manager,
            self.agent_profile,
        )

        if base_config is not None:
            self._base_config = base_config
            self.agent_manager.invalidate_config()

        old_backend = self.backend
        new_backend = self.backend_factory()
        self.backend = new_backend
        if new_backend is not old_backend:
            with contextlib.suppress(Exception):
                await old_backend.__aexit__(None, None, None)

        if max_turns is not None:
            self._max_turns = max_turns
        if max_price is not None:
            self._max_price = max_price

        self.tool_manager = ToolManager(
            lambda: self.config,
            mcp_registry=self.mcp_registry,
            connector_registry=self.connector_registry,
        )
        self.skill_manager = SkillManager(lambda: self.config)

        new_system_prompt = get_universal_system_prompt(
            self.tool_manager,
            self.config,
            self.skill_manager,
            self.agent_manager,
            scratchpad_dir=self.scratchpad_dir,
            headless=self._headless,
        )

        self.messages.update_system_prompt(new_system_prompt)

        if len(self.messages) == 1:
            self.stats.reset_context_state()

        try:
            active_model = self.config.get_active_model()
            self.stats.update_pricing(
                active_model.input_price, active_model.output_price
            )
        except ValueError:
            pass

        if reset_middleware:
            self._setup_middleware()


# ── ConversationRuntime adapter ──────────────────────────────────


class _ConversationLoopAdapter:
    """Adapter implementing ConversationRuntimeCallbacks for AgentLoop."""

    __slots__ = ("_loop", "_user_msg")

    def __init__(self, loop: AgentLoop, user_msg: str) -> None:  # type: ignore[name-defined]
        self._loop = loop
        self._user_msg = user_msg

    def get_turn(self):
        return self._loop._current_turn

    def get_turn_id(self) -> str:
        return str(self._loop._current_turn.turn_id)

    def mark_turn_outcome(self, outcome: TurnOutcome, reason: str) -> None:  # type: ignore[name-defined]
        self._loop._current_turn.mark_outcome(outcome, reason)

    def persist_turn_state(self) -> None:
        pass

    def middleware_before_turn(self, ctx: dict[str, str]):
        raise NotImplementedError("use async version")

    def reset_hooks(self) -> None:
        if self._loop._hooks_manager:
            self._loop._hooks_manager.reset_retry_count()

    def build_context_envelope(self, request):
        import asyncio
        loop = asyncio.get_event_loop()

        async def _build():
            await self._loop._build_context_envelope(self._user_msg)
            return self._loop._current_context_envelope

        return loop.run_until_complete(_build())

    def set_context_envelope(self, receipt) -> None:
        if receipt is not None:
            turn = self._loop._current_turn
            turn.context_envelope_id = receipt.envelope_id
            turn.context_section_count = receipt.section_count

    async def stream_llm_turn(self):
        async for event in self._loop._perform_llm_turn():
            yield event

    def is_user_cancellation_event(self, event) -> bool:
        from rig_relay.core._llm_call import is_user_cancellation_event
        return is_user_cancellation_event(event)

    async def stream_hooks_post_turn(self):
        if not self._loop._hooks_manager:
            return
        async for hook_event in self._loop._hooks_manager.run(
            HookType.POST_AGENT_TURN,  # type: ignore[name-defined]
            self._loop.session_id,
            self._loop.session_logger,
        ):
            yield hook_event

    def is_hook_user_message(self, event) -> bool:
        return isinstance(event, HookUserMessage)  # type: ignore[name-defined]

    def inject_hook_message(self, hook_message) -> None:
        self._loop.messages.append(
            LLMMessage(  # type: ignore[name-defined]
                role=Role.user,  # type: ignore[name-defined]
                content=hook_message.content,
                injected=True,
            )
        )

    def last_message_has_no_tool_calls(self) -> bool:
        last = self._loop.messages[-1]
        return last.role != Role.tool  # type: ignore[name-defined]

    async def execute_tool_batch(self):
        """Tool execution already happened inside stream_llm_turn().

        _perform_llm_turn() handles tool execution internally via
        _handle_tool_calls(). The run_tools decision exists solely
        to continue the while-loop after tools were executed.
        """
        if False:
            yield

    def check_max_turns(self) -> int | None:
        return self._loop._max_turns
