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
from rig_relay.core.hooks.models import HookConfigResult, HookType, HookUserMessage
from rig_relay.core.llm.backend.factory import BACKEND_FACTORY
from rig_relay.core.llm.format import FailedToolCall, ResolvedMessage, ResolvedToolCall
from rig_relay.core.llm.types import BackendLike
from rig_relay.core.logger import logger
from rig_relay.core.session.session_migration import migrate_sessions_entrypoint
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
from rig_relay.core.tools.base import BaseTool
from rig_relay.core.tools.connectors import ConnectorRegistry, connectors_enabled
from rig_relay.core.tools.permissions import ApprovedRule, RequiredPermission
from rig_relay.core.trace_runtime import TraceRuntime
from rig_relay.core.types import (
    AgentProfileChangedEvent,
    AgentStats,
    ApprovalCallback,
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
from rig_relay.core.utils import TOOL_ERROR_TAG, get_server_url_from_api_base

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
from rig_relay.core._agent_models import ToolDecision
from rig_relay.core._context_envelope import ContextEnvelopeMixin
from rig_relay.core._errors import AgentLoopError, TeleportError
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
from rig_relay.core.governance_runtime import GovernanceRuntime
from rig_relay.core.runtime_state import AgentRuntimeState
from rig_relay.core.session_runtime import SessionRuntime
from rig_relay.core.tool_executor import (
    CouncilGate,
    ToolConcurrencyManager,
    ToolExecutor,
    ToolRuntimeAdapterBuilder,
)
from rig_relay.core.tool_runtime import ToolRuntime

_COUNCIL_MUTATION_TOOLS = frozenset({
    "BashTool",
    "WriteFileTool",
    "SearchReplaceTool",
    "CheckpointTool",
})


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
        self._tool_executor: ToolExecutor = ToolExecutor(
            loop=self,
            adapter_builder=ToolRuntimeAdapterBuilder(loop=self),
            council_gate=CouncilGate(loop=self),
            concurrency=ToolConcurrencyManager(),
        )

        self._session_rules: list[ApprovedRule] = []
        self._approval_lock = asyncio.Lock()

        self._governance_runtime = GovernanceRuntime(config=config)
        self._governance_runtime.session_rules = self._session_rules

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

        self._session_runtime = SessionRuntime(agent_loop=self)
        self._trace_runtime = TraceRuntime(session_id=self.session_id)

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

    # ── SessionRuntime delegation (Wave 3) ──────────────────────────

    def build_runtime_state(self) -> AgentRuntimeState:
        """Build a structured snapshot of current AgentLoop runtime state.

        Deprecated: delegates to SessionRuntime.build_runtime_state().
        """
        return self._session_runtime.build_runtime_state()

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
        """(deprecated) Lazily construct ToolRuntime via ToolRuntimeAdapterBuilder."""
        if self._tool_runtime is not None:
            return self._tool_runtime
        self._tool_runtime = self._tool_executor.adapter_builder.build_tool_runtime()
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
        if (
            provider.name == "local_inference"
            and not self.config.local_inference_enabled
        ):
            from rig_relay.core.logger import logger

            logger.warning(
                "local_inference provider selected but local_inference_enabled=False"
            )
            msg = "Local inference is not enabled. Set local_inference_enabled=True in config."
            raise RuntimeError(msg)
        if provider.name == "local_inference":
            from rig_relay.providers.local_inference.airlock import (
                get_airlock,
                is_local_inference_available,
                is_local_inference_configured,
            )

            if not is_local_inference_configured():
                msg = "Local inference endpoint not configured. Configure via airlock."
                raise RuntimeError(msg)
            if not is_local_inference_available():
                msg = "Local inference blocked by capability gate."
                raise RuntimeError(msg)
            airlock = get_airlock()
            config = airlock.get_config()
            if config and config.endpoint_url:
                provider.api_base = config.endpoint_url.rstrip("/") + "/v1"
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
        async with self._trace_runtime.agent_span(model=model_name or ""):
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
        self._pending_tool_resolved: object | None = None
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
            self._pending_tool_resolved = None
            return

        self._pending_tool_resolved = resolved

        if (turn := getattr(self, "_current_turn", None)) is not None:
            turn.tool_call_count = len(resolved.tool_calls) + len(resolved.failed_calls)
            turn.advance(TurnPhase.TOOL_CALLS_RUNNING)
            if (cr := self._conversation_runtime) is not None:
                cr.set_tool_call_count(turn.tool_call_count)

    async def _execute_pending_tool_batch(self) -> AsyncGenerator[BaseEvent, None]:
        """Execute stored tool calls. Called from adapter.execute_tool_batch()."""
        resolved = self._pending_tool_resolved
        if resolved is None:
            return
        self._pending_tool_resolved = None
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
        async for event in self._tool_executor.execute_one_tool(tool_call):
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

    async def _consult_council_before_mutation(
        self, tn: str, tool_args: dict[str, Any], tool_class: type[BaseTool] | None
    ) -> str:
        return await self._tool_executor.council_gate.consult(tn, tool_args, tool_class)

    async def _execute_tool_call(
        self, span: trace.Span, tool_call: ResolvedToolCall
    ) -> AsyncGenerator[ToolResultEvent | ToolStreamEvent]:
        async for event in self._tool_executor.execute_one_tool(tool_call):
            yield event

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
        async for event in self._tool_executor.execute_concurrently(tool_calls):
            yield event

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
        return self._governance_runtime.should_execute_tool(
            tool_call_id=tool_call_id,
            tool_name=tool.get_name(),
            tool_args=args.model_dump(),
            execution_mode="tool",
        )

    async def _ask_approval(
        self,
        tool_name: str,
        args: BaseModel,
        tool_call_id: str,
        required_permissions: list[RequiredPermission],
    ) -> ToolDecision:
        return await self._governance_runtime.ask_approval(
            tool_name=tool_name,
            tool_args=args,
            tool_call_id=tool_call_id,
            required_permissions=required_permissions,
        )

    # ── SessionRuntime delegation (Wave 3) ──────────────────────────

    async def fork(self, message_id: str | None = None) -> AgentLoop:
        return await self._session_runtime.fork(message_id=message_id)

    @requires_init
    async def clear_history(self) -> None:
        """Deprecated: delegates to SessionRuntime.clear_history()."""
        return await self._session_runtime.clear_history()

    @requires_init
    async def compact(self, extra_instructions: str = "") -> str:
        """Deprecated: delegates to SessionRuntime.compact()."""
        return await self._session_runtime.compact(
            extra_instructions=extra_instructions
        )

    @requires_init
    async def switch_agent(self, agent_name: str) -> None:
        """Deprecated: delegates to SessionRuntime.switch_agent()."""
        return await self._session_runtime.switch_agent(agent_name=agent_name)

    @requires_init
    async def reload_with_initial_messages(
        self,
        base_config: VibeConfig | None = None,
        max_turns: int | None = None,
        max_price: float | None = None,
        reset_middleware: bool = True,
    ) -> None:
        """Deprecated: delegates to SessionRuntime.reload_with_initial_messages()."""
        return await self._session_runtime.reload_with_initial_messages(
            base_config=base_config,
            max_turns=max_turns,
            max_price=max_price,
            reset_middleware=reset_middleware,
        )


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

    async def middleware_before_turn(self, ctx: dict[str, str]):
        """Run AgentLoop middleware pipeline and return (result, events)."""
        result = await self._loop.middleware_pipeline.run_before_turn(
            self._loop._get_context()
        )
        events = []
        async for event in self._loop._handle_middleware_result(result):
            events.append(event)
        return result, events

    def reset_hooks(self) -> None:
        if self._loop._hooks_manager:
            self._loop._hooks_manager.reset_retry_count()

    async def build_context_envelope(self, request):
        """Build context envelope asynchronously. No run_until_complete."""
        await self._loop._build_context_envelope(self._user_msg)
        return self._loop._current_context_envelope

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
        """Execute tool calls stored from stream_llm_turn().

        _perform_llm_turn() stores resolved tool calls in
        _pending_tool_resolved instead of executing them.
        This method executes those pending calls via _handle_tool_calls().
        """
        async for event in self._loop._execute_pending_tool_batch():
            yield event

    def check_max_turns(self) -> int | None:
        return self._loop._max_turns
