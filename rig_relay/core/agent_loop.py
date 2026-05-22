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
from typing import TYPE_CHECKING, Any, cast

from pydantic import BaseModel

from rig_relay.core.agents.models import AgentProfile, BuiltinAgentName
from rig_relay.core.config import VibeConfig
from rig_relay.core.hooks.models import HookConfigResult
from rig_relay.core.llm.backend.factory import BACKEND_FACTORY
from rig_relay.core.llm.format import FailedToolCall
from rig_relay.core.llm.types import BackendLike
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
from rig_relay.core.context_runtime import ContextRuntime
from rig_relay.core.conversation_loop_adapter import _ConversationLoopAdapter
from rig_relay.core.conversation_runtime import ConversationRuntime
from rig_relay.core.conversation_runtime.models import ConversationRuntimeCallbacks
from rig_relay.core.conversation_turn import ConversationTurnRuntime, TurnPhase
from rig_relay.core.governance_runtime import GovernanceRuntime
from rig_relay.core.model_runtime import ModelRuntime
from rig_relay.core.runtime_state import AgentRuntimeState
from rig_relay.core.session_runtime import SessionRuntime
from rig_relay.core.telemetry_runtime import TelemetryRuntime
from rig_relay.core.tool_executor import (
    CouncilGate,
    ToolConcurrencyManager,
    ToolExecutionContext,
    ToolExecutor,
    ToolRuntimeAdapterBuilder,
)
from rig_relay.core.tool_result_runtime import ToolResultRuntime
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
        self._model_runtime: ModelRuntime | None = None

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

        self._governance_runtime = GovernanceRuntime(config=config)
        self._governance_runtime.session_rules = self._session_rules

        self._init_telemetry_and_guard(
            config, entrypoint_metadata, is_subagent, hook_config_result
        )

        self._model_runtime = ModelRuntime(
            config=self.config,
            backend=self.backend,
            tool_manager=self.tool_manager,
            format_handler=self.format_handler,
            messages=self.messages,
            stats=self.stats,
            telemetry_client=self.telemetry_client,
            entrypoint_metadata=self.entrypoint_metadata,
            session_id=self.session_id,
            parent_session_id=self.parent_session_id,
            is_user_prompt_call=self._is_user_prompt_call,
            current_user_message_id=self._current_user_message_id,
            middleware_pipeline=self.middleware_pipeline,
            agent_profile_getter=lambda: self.agent_profile,
            plan_session=self._plan_session,
            workspace_root=self._workspace_root,
            headless=self._headless,
            report_context_assembly=self._report_context_assembly,
            compact_fn=self.compact,
        )

        self._context_runtime = ContextRuntime(
            config=self.config,
            workspace_root=self._workspace_root,
            session_id=self.session_id,
            messages=self.messages,
            telemetry_client=self.telemetry_client,
            context_compiler=self._context_compiler,
            governed_context_enabled=self.config.governed_context_enabled,
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
        self._tool_result_runtime = ToolResultRuntime(loop=self)
        self._telemetry_runtime = TelemetryRuntime(loop=self)

        self._exec_ctx = ToolExecutionContext(
            session_id=self.session_id,
            workspace_root=self._workspace_root,
            config=self.config,
            tool_manager=self.tool_manager,
            trace_runtime=self._trace_runtime,
            rewind_manager=self.rewind_manager,
            approval_callback=self.approval_callback,
            result_sink=self._tool_result_sink,
            stats=self.stats,
            handle_tool_response=self._tool_result_runtime.handle_tool_response,
            telemetry_client=self.telemetry_client,
        )

        self._tool_executor: ToolExecutor = ToolExecutor(
            ctx=self._exec_ctx,
            adapter_builder=ToolRuntimeAdapterBuilder(loop=self, ctx=self._exec_ctx),
            council_gate=CouncilGate(ctx=self._exec_ctx),
            concurrency=ToolConcurrencyManager(),
        )

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
        cr_callbacks = cast(ConversationRuntimeCallbacks, adapter)
        async for event in cr.execute_turn_loop(cr_callbacks):
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

        self._exec_ctx.update_turn(
            turn_id=str(getattr(self._current_turn, "turn_id", "")),
            user_message_id=self._current_user_message_id or "",
            bypass_permissions=self.bypass_tool_permissions,
            current_turn=self._current_turn,
        )

        async for event in self._tool_executor.execute_batch(resolved):
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

    async def _should_execute_tool(
        self, tool: BaseTool, args: BaseModel, tool_call_id: str
    ) -> ToolDecision:
        return self._governance_runtime.should_execute_tool(
            tool_call_id=tool_call_id,
            tool_name=tool.get_name(),
            tool_args=args.model_dump(),
            execution_mode="tool",
        )

    # ── ModelRuntime delegation (Phase 1) ───────────────────────────

    async def _prepare_llm_call(self, *args: Any, **kwargs: Any) -> Any:
        return await self._model_runtime.prepare_llm_call(*args, **kwargs)  # type: ignore[union-attr]

    async def _chat(self, *args: Any, **kwargs: Any) -> Any:
        return await self._model_runtime.chat(*args, **kwargs)  # type: ignore[union-attr]

    async def _chat_streaming(
        self, *args: Any, **kwargs: Any
    ) -> AsyncGenerator[Any, None]:
        mr = self._model_runtime
        if mr is None:
            async for chunk in LLMCallMixin._chat_streaming(self, *args, **kwargs):
                yield chunk
            return
        async for chunk in mr.chat_streaming(*args, **kwargs):
            yield chunk

    def _update_stats(self, *args: Any, **kwargs: Any) -> None:
        self._model_runtime._update_stats(*args, **kwargs)  # type: ignore[union-attr]

    def _reraise_llm_error(self, *args: Any, **kwargs: Any) -> None:
        self._model_runtime._reraise_llm_error(*args, **kwargs)  # type: ignore[union-attr]

    def _build_backend_metadata(self, *args: Any, **kwargs: Any) -> Any:
        return self._model_runtime.build_backend_metadata(*args, **kwargs)  # type: ignore[union-attr]

    def _get_extra_headers(self, *args: Any, **kwargs: Any) -> Any:
        return self._model_runtime.get_extra_headers(*args, **kwargs)  # type: ignore[union-attr]

    def _setup_middleware(self) -> None:
        if self._model_runtime is not None:
            self._model_runtime.setup_middleware(self._max_turns, self._max_price)
        else:
            MiddlewareMetadataMixin._setup_middleware(self)

    async def _handle_middleware_result(self, result: Any) -> AsyncGenerator[Any, None]:
        async for event in self._model_runtime.handle_middleware_result(result):  # type: ignore[union-attr]
            yield event

    def _get_context(self) -> Any:
        return self._model_runtime.get_middleware_context()  # type: ignore[union-attr]

    # ── ContextRuntime delegation (Phase 2) ─────────────────────────

    async def _build_context_envelope(self, user_msg: str) -> None:
        envelope = await self._context_runtime.build_context(user_msg)
        self._current_context_envelope = envelope

    # ── SessionRuntime delegation (Phase 3) ─────────────────────────

    def _clean_message_history(self) -> None:
        self._session_runtime.clean_message_history()

    def _fill_missing_tool_responses(self) -> None:
        self._session_runtime.fill_missing_tool_responses()

    def _reset_session(self, keep_parent: bool = True) -> None:
        self._session_runtime.reset_session(keep_parent=keep_parent)

    def _messages_for_fork(self, message_id: str | None) -> list[LLMMessage]:
        return self._session_runtime.messages_for_fork(message_id)

    # ── ToolResultRuntime delegation (Phase 4) ──────────────────────

    def _handle_tool_response(self, *args: Any, **kwargs: Any) -> None:
        self._tool_result_runtime.handle_tool_response(*args, **kwargs)

    def _tool_failure_event(self, *args: Any, **kwargs: Any) -> ToolResultEvent:
        return self._tool_result_runtime.tool_failure_event(*args, **kwargs)

    def _capture_model_observation_for_tool_response(
        self, *args: Any, **kwargs: Any
    ) -> None:
        self._tool_result_runtime.capture_model_observation(*args, **kwargs)

    def _check_patch_proposal_gating(
        self, tool_call: Any, tool_instance: Any
    ) -> Any | None:
        return PatchGatingMixin._check_patch_proposal_gating(
            self, tool_call, tool_instance
        )

    def set_approval_callback(self, callback: object) -> None:
        self.approval_callback = callback
        if self._governance_runtime is not None:
            self._governance_runtime.approval_callback = callback

    def set_user_input_callback(self, callback: object) -> None:
        self.user_input_callback = callback

    def set_tool_permission(
        self, tool_name: str, permission: Any, save_permanently: bool = False
    ) -> None:
        GovernanceMixin.set_tool_permission(
            self, tool_name, permission, save_permanently
        )

    def _add_session_rule(self, rule: Any) -> None:
        if self._governance_runtime is not None:
            self._governance_runtime.add_session_rule(rule)

    def _is_permission_covered(self, tool_name: str, rp: Any) -> bool:
        return GovernanceMixin._is_permission_covered(self, tool_name, rp)

    def approve_always(
        self,
        tool_name: str,
        required_permissions: list[Any] | None,
        save_permanently: bool = False,
    ) -> None:
        GovernanceMixin.approve_always(
            self, tool_name, required_permissions, save_permanently
        )

    # ── TelemetryRuntime delegation (Phase 6) ───────────────────────

    def emit_new_session_telemetry(self) -> None:
        self._telemetry_runtime.emit_new_session()

    def emit_ready_telemetry(self, init_duration_ms: int) -> None:
        self._telemetry_runtime.emit_ready(init_duration_ms)

    def emit_session_closed_telemetry(self) -> None:
        self._telemetry_runtime.emit_session_closed()

    def _emit_context_observation(
        self,
        tool_call: Any,
        status: str,
        args_dict: dict[str, Any],
        blocked_by_policy: bool = False,
    ) -> None:
        self._telemetry_runtime.emit_context_observation(
            tool_call, status, args_dict, blocked_by_policy
        )

    # ── Governance delegation ────────────────────────────────────────

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
