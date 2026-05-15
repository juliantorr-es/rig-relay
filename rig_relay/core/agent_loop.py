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
from rig_relay.core.middleware import MiddlewareAction, ResetReason
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
from rig_relay.core.tools.base import (
    BaseTool,
    InvokeContext,
    ToolError,
    ToolPermission,
    ToolPermissionError,
)
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
    CANCELLATION_TAG,
    TOOL_ERROR_TAG,
    CancellationReason,
    get_server_url_from_api_base,
    get_user_cancellation_message,
    is_user_cancellation_event,
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
from rig_relay.core.conversation_turn import (
    ConversationTurnRuntime,
    TurnOutcome,
    TurnPhase,
)
from rig_relay.core.runtime_state import AgentRuntimeState, ReadinessState


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
        self.backend_factory = lambda: backend or self._select_backend()
        self.backend = self.backend_factory()
        self.enable_streaming = enable_streaming

        self._init_core_managers(
            config, agent_name, is_subagent, defer_heavy_init
        )

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
        self._current_context_envelope: ContextEnvelopeReceipt | None = None
        self._is_user_prompt_call: bool = False

        self._init_ambient_context_packet()
        self._init_context_compiler(defer_heavy_init)

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
                self.config.active_model
                if hasattr(self.config, 'active_model')
                else ""
            ),
            active_provider=self.config.get_active_provider().name,
            context_packet_available=self._context_packet is not None,
        )

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

    async def _conversation_loop(
        self, user_msg: str, client_message_id: str | None = None
    ) -> AsyncGenerator[BaseEvent]:
        turn = ConversationTurnRuntime(
            session_id=self.session_id,
            user_message_id=client_message_id,
            user_message_text=user_msg,
        )
        self._current_turn = turn
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

        try:
            should_break_loop = False
            first_llm_turn = True
            while not should_break_loop:
                self._is_user_prompt_call = False
                result = await self.middleware_pipeline.run_before_turn(
                    self._get_context()
                )
                async for event in self._handle_middleware_result(result):
                    yield event

                if result.action == MiddlewareAction.STOP:
                    return

                self.stats.steps += 1
                user_cancelled = False
                if first_llm_turn:
                    self._is_user_prompt_call = True
                    first_llm_turn = False

                    turn.advance(TurnPhase.CONTEXT_BUILDING)
                    await self._build_context_envelope(user_msg)
                    if self._current_context_envelope:
                        turn.context_envelope_id = self._current_context_envelope.envelope_id
                        turn.context_section_count = self._current_context_envelope.section_count
                    turn.advance(TurnPhase.CONTEXT_READY)

                turn.advance(TurnPhase.MODEL_CALLING)

                async for event in self._perform_llm_turn():
                    if is_user_cancellation_event(event):
                        user_cancelled = True
                    yield event
                    await self._save_messages()
                self._is_user_prompt_call = False

                last_message = self.messages[-1]
                should_break_loop = last_message.role != Role.tool

                if user_cancelled:
                    turn.advance(TurnPhase.FINALIZING)
                    turn.mark_outcome(TurnOutcome.USER_CANCELLED, "user cancelled")
                    return

                if should_break_loop and self._hooks_manager:
                    hook_retry: HookUserMessage | None = None
                    async for hook_event in self._hooks_manager.run(
                        HookType.POST_AGENT_TURN, self.session_id, self.session_logger
                    ):
                        if isinstance(hook_event, HookUserMessage):
                            hook_retry = hook_event
                        else:
                            yield hook_event
                    if hook_retry is not None:
                        self.messages.append(
                            LLMMessage(
                                role=Role.user,
                                content=hook_retry.content,
                                injected=True,
                            )
                        )
                        should_break_loop = False

            turn.advance(TurnPhase.FINALIZING)
            turn.mark_outcome(TurnOutcome.SUCCESS)

        finally:
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

        if (turn := getattr(self, '_current_turn', None)) is not None:
            turn.advance(TurnPhase.ASSISTANT_PARSED)
            if last_message.content:
                turn.assistant_content_length = len(last_message.content)

        if not resolved.tool_calls and not resolved.failed_calls:
            return

        if (turn := getattr(self, '_current_turn', None)) is not None:
            turn.tool_call_count = len(resolved.tool_calls) + len(resolved.failed_calls)
            turn.advance(TurnPhase.TOOL_CALLS_RUNNING)

        profile_before = self.agent_profile.name
        async for event in self._handle_tool_calls(resolved):
            yield event
        if (turn := getattr(self, '_current_turn', None)) is not None:
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
        determinism_cls = getattr(
            tool_call.tool_class, "determinism_class", None
        )
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
        try:
            tool_instance = self.tool_manager.get(tool_call.tool_name)
        except Exception as exc:
            error_msg = f"Error getting tool '{tool_call.tool_name}': {exc}"
            yield self._tool_failure_event(tool_call, error_msg, span=span)
            return

        cached_result = self._check_tool_result_cache(tool_call)
        if cached_result is not None:
            yield cached_result
            self.stats.tool_calls_succeeded += 1
            return

        decision: ToolDecision | None = None
        try:
            decision = await self._should_execute_tool(
                tool_instance, tool_call.validated_args, tool_call.call_id
            )

            # ── Patch proposal gating ─────────────────────────────
            if decision.verdict == ToolExecutionResponse.EXECUTE:
                gating = self._check_patch_proposal_gating(
                    tool_call, tool_instance
                )
                if gating:
                    yield gating
                    self.stats.tool_calls_rejected += 1
                    return

            if decision.verdict == ToolExecutionResponse.SKIP:
                self.stats.tool_calls_rejected += 1
                skip_reason = decision.feedback or str(
                    get_user_cancellation_message(
                        CancellationReason.TOOL_SKIPPED, tool_call.tool_name
                    )
                )
                yield ToolResultEvent(
                    tool_name=tool_call.tool_name,
                    tool_class=tool_call.tool_class,
                    skipped=True,
                    skip_reason=skip_reason,
                    cancelled=f"<{CANCELLATION_TAG}>" in skip_reason,
                    tool_call_id=tool_call.call_id,
                )
                self._emit_context_observation(
                    tool_call, "skipped", tool_call.args_dict, blocked_by_policy=False
                )
                self._handle_tool_response(
                    tool_call, skip_reason, "skipped", decision, span=span
                )
                return

            self.stats.tool_calls_agreed += 1

            snapshot = tool_instance.get_file_snapshot(tool_call.validated_args)
            if snapshot is not None:
                self.rewind_manager.add_snapshot(snapshot)

            start_time = time.perf_counter()
            result_model = None
            expanded_args = self._expand_tool_call_args(tool_call.args_dict)
            async for item in tool_instance.invoke(
                ctx=InvokeContext(
                    tool_call_id=tool_call.call_id,
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
                ),
                **expanded_args,
            ):
                if isinstance(item, ToolStreamEvent):
                    yield item
                else:
                    result_model = item

            duration = time.perf_counter() - start_time
            if result_model is None:
                raise ToolError("Tool did not yield a result")

            result_dict = result_model.model_dump()
            text = "\n".join(f"{k}: {v}" for k, v in result_dict.items())
            extra = tool_instance.get_result_extra(result_model)
            if extra:
                text += "\n\n" + extra
            self._handle_tool_response(
                tool_call,
                text,
                "success",
                decision,
                result_dict,
                span=span,
                duration_ms=duration * 1000,
            )

            # Emit content-light tool receipt if the tool produces one
            build_receipt = getattr(tool_instance, "build_receipt", None)
            if build_receipt is not None:
                try:
                    receipt = build_receipt(result_model)
                    from rig_relay.evidence.model_observations import (
                        capture_tool_receipt,
                    )

                    capture_tool_receipt(
                        session_id=self.session_id,
                        tool_name=tool_call.tool_name,
                        receipt=receipt.model_dump(mode="json"),
                    )
                except Exception:
                    logger.warning(
                        "Failed to capture tool receipt for %s",
                        tool_call.tool_name,
                        exc_info=True,
                    )

            # Store in cache if deterministic and read-only
            determinism_cls = getattr(
                tool_call.tool_class, "determinism_class", None
            )
            if determinism_cls is not None:
                from rig_relay.core.tools.cache import set_cached_result

                determinism_str = str(determinism_cls.value)
                if determinism_str in {"DETERMINISTIC_PURE", "DETERMINISTIC_REPO_STATE"}:
                    try:
                        set_cached_result(
                            tool_name=tool_call.tool_name,
                            args_dict=tool_call.args_dict,
                            result_dict=result_model.model_dump(mode="json"),
                            determinism_class=determinism_str,
                        )
                    except Exception:
                        pass

            yield ToolResultEvent(
                tool_name=tool_call.tool_name,
                tool_class=tool_call.tool_class,
                result=result_model,
                cancelled=getattr(result_model, "cancelled", False),
                duration=duration,
                tool_call_id=tool_call.call_id,
            )
            self.stats.tool_calls_succeeded += 1

            # ── Context observation telemetry ───────────────────
            self._emit_context_observation(
                tool_call, "succeeded", tool_call.args_dict, blocked_by_policy=False
            )

        except asyncio.CancelledError:
            cancel = str(
                get_user_cancellation_message(CancellationReason.TOOL_INTERRUPTED)
            )
            self.stats.tool_calls_failed += 1
            self._emit_context_observation(
                tool_call, "failed", tool_call.args_dict, blocked_by_policy=False
            )
            yield self._tool_failure_event(
                tool_call, cancel, decision, cancelled=True, span=span
            )
            raise

        except Exception as exc:
            error_msg = f"<{TOOL_ERROR_TAG}>{tool_instance.get_name()} failed: {exc}</{TOOL_ERROR_TAG}>"
            if isinstance(exc, ToolPermissionError):
                self.stats.tool_calls_agreed -= 1
                self.stats.tool_calls_rejected += 1
            else:
                self.stats.tool_calls_failed += 1
            yield self._tool_failure_event(tool_call, error_msg, decision, span=span)

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

            summary = compute_storage_summary(
                self._workspace_root / ".rig" / "relay",
            )
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
