"""SessionRuntime — extracted session lifecycle and state snapshot from AgentLoop.

Wave 3 of AgentLoop Refactor. Extracts fork, clear_history, compact,
switch_agent, reload_with_initial_messages, and build_runtime_state.
Receives a reference to the parent AgentLoop for attribute access
during the transition — SessionRuntime owns no policy.
"""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from rig_relay.core._errors import AgentLoopLLMResponseError
from rig_relay.core.guard import DirtyGuardFailurePolicy, GuardCaptureReason, get_guard
from rig_relay.core.middleware import ResetReason
from rig_relay.core.prompts import UtilityPrompt
from rig_relay.core.runtime_state import AgentRuntimeState, ReadinessState
from rig_relay.core.session.session_id import extract_suffix, generate_session_id
from rig_relay.core.skills.manager import SkillManager
from rig_relay.core.system_prompt import get_universal_system_prompt
from rig_relay.core.tools.manager import ToolManager
from rig_relay.core.types import AgentStats, LLMMessage, Role

if TYPE_CHECKING:
    from rig_relay.core.config._settings import VibeConfig


@dataclass(slots=True)
class SessionRuntime:
    """Extracted session lifecycle operations and runtime state snapshot."""

    agent_loop: Any
    dirty_guard: Any = field(default_factory=get_guard)

    async def fork(self, message_id: str | None = None) -> Any:
        from rig_relay.core.agent_loop import AgentLoop

        loop = self.agent_loop
        messages = loop._messages_for_fork(message_id)
        forked = AgentLoop(
            config=loop.base_config.model_copy(deep=True),
            agent_name=loop.agent_profile.name,
            enable_streaming=loop.enable_streaming,
            entrypoint_metadata=loop.entrypoint_metadata,
            defer_heavy_init=True,
            hook_config_result=loop._hook_config_result,
            workspace_root=loop._workspace_root,
        )
        forked.session_id = generate_session_id(suffix=extract_suffix(loop.session_id))
        forked.parent_session_id = loop.session_id
        forked.session_logger.reset_session(
            forked.session_id, parent_session_id=loop.session_id
        )

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

    async def clear_history(self) -> None:
        loop = self.agent_loop
        await loop.session_logger.save_interaction(
            loop.messages,
            loop.stats,
            loop._base_config,
            loop.tool_manager,
            loop.agent_profile,
        )
        loop.messages.reset(loop.messages[:1])

        loop.stats = AgentStats.create_fresh(loop.stats)
        loop.stats.trigger_listeners()

        try:
            active_model = loop.config.get_active_model()
            loop.stats.update_pricing(
                active_model.input_price, active_model.output_price
            )
        except ValueError:
            pass

        loop.middleware_pipeline.reset()
        loop.tool_manager.reset_all()
        loop._reset_session(keep_parent=False)

    async def compact(self, extra_instructions: str = "") -> str:
        loop = self.agent_loop
        try:
            loop._clean_message_history()
            await loop.session_logger.save_interaction(
                loop.messages,
                loop.stats,
                loop._base_config,
                loop.tool_manager,
                loop.agent_profile,
            )

            summary_request = UtilityPrompt.COMPACT.read()
            if extra_instructions:
                summary_request += (
                    f"\n\n## Additional Instructions\n{extra_instructions}"
                )
            loop.stats.steps += 1

            with loop.messages.silent():
                loop.messages.append(
                    LLMMessage(role=Role.user, content=summary_request)
                )
                summary_result = await loop._chat(
                    model_override=loop.config.get_compaction_model()
                )

            if summary_result.usage is None:
                raise AgentLoopLLMResponseError(
                    "Usage data missing in compaction summary response"
                )
            summary_content = summary_result.message.content or ""

            system_message = loop.messages[0]
            summary_message = LLMMessage(role=Role.user, content=summary_content)
            loop.messages.reset([system_message, summary_message])

            active_model = loop.config.get_active_model()
            loop._reset_session()

            actual_context_tokens = await loop.backend.count_tokens(
                model=active_model,
                messages=loop.messages,
                tools=loop.format_handler.get_available_tools(loop.tool_manager),
                extra_headers=loop._get_extra_headers(),
                metadata=loop._build_backend_metadata().model_dump(exclude_none=True),
            )

            loop.stats.context_tokens = actual_context_tokens
            await loop.session_logger.save_interaction(
                loop.messages,
                loop.stats,
                loop._base_config,
                loop.tool_manager,
                loop.agent_profile,
            )

            loop.middleware_pipeline.reset(reset_reason=ResetReason.COMPACT)

            return summary_content or ""

        except Exception:
            await loop.session_logger.save_interaction(
                loop.messages,
                loop.stats,
                loop._base_config,
                loop.tool_manager,
                loop.agent_profile,
            )
            raise

    async def switch_agent(self, agent_name: str) -> None:
        loop = self.agent_loop
        if agent_name == loop.agent_profile.name:
            return
        loop.agent_manager.switch_profile(agent_name)
        await self.reload_with_initial_messages(reset_middleware=False)

    async def reload_with_initial_messages(
        self,
        base_config: VibeConfig | None = None,
        max_turns: int | None = None,
        max_price: float | None = None,
        reset_middleware: bool = True,
    ) -> None:
        loop = self.agent_loop
        await asyncio.sleep(0)

        await loop.session_logger.save_interaction(
            loop.messages,
            loop.stats,
            loop._base_config,
            loop.tool_manager,
            loop.agent_profile,
        )

        if base_config is not None:
            loop._base_config = base_config
            loop.agent_manager.invalidate_config()

        old_backend = loop.backend
        new_backend = loop.backend_factory()
        loop.backend = new_backend
        if new_backend is not old_backend:
            with contextlib.suppress(Exception):
                await old_backend.__aexit__(None, None, None)

        if max_turns is not None:
            loop._max_turns = max_turns
        if max_price is not None:
            loop._max_price = max_price

        loop.tool_manager = ToolManager(
            lambda: loop.config,
            mcp_registry=loop.mcp_registry,
            connector_registry=loop.connector_registry,
        )
        loop.skill_manager = SkillManager(lambda: loop.config)

        new_system_prompt = get_universal_system_prompt(
            loop.tool_manager,
            loop.config,
            loop.skill_manager,
            loop.agent_manager,
            scratchpad_dir=loop.scratchpad_dir,
            headless=loop._headless,
        )

        loop.messages.update_system_prompt(new_system_prompt)

        if len(loop.messages) == 1:
            loop.stats.reset_context_state()

        try:
            active_model = loop.config.get_active_model()
            loop.stats.update_pricing(
                active_model.input_price, active_model.output_price
            )
        except ValueError:
            pass

        if reset_middleware:
            loop._setup_middleware()

    def build_runtime_state(self) -> AgentRuntimeState:
        loop = self.agent_loop
        readiness = ReadinessState.UNKNOWN
        if loop._init_error is not None:
            readiness = ReadinessState.FAILED
        elif loop.is_initialized:
            readiness = ReadinessState.READY
        elif loop._defer_heavy_init:
            readiness = ReadinessState.INITIALIZING

        return AgentRuntimeState(
            session_id=loop.session_id,
            parent_session_id=loop.parent_session_id,
            agent_profile_name=loop.agent_profile.name,
            workspace_root=str(loop._workspace_root),
            current_turn_id=loop._current_user_message_id,
            current_context_receipt_id=(
                loop._current_context_envelope.envelope_id
                if loop._current_context_envelope
                else None
            ),
            is_user_prompt_call=loop._is_user_prompt_call,
            readiness=readiness,
            init_duration_ms=loop._init_duration_ms,
            init_error=str(loop._init_error) if loop._init_error else None,
            deferred_init=loop._defer_heavy_init,
            max_turns=loop._max_turns,
            max_price=loop._max_price,
            session_rules_count=len(loop._session_rules),
            bypass_tool_permissions=loop.bypass_tool_permissions,
            enable_local_observability=loop.config.enable_local_observability,
            enable_streaming=loop.enable_streaming,
            steps=loop.stats.steps,
            context_tokens=loop.stats.context_tokens,
            tool_calls_succeeded=loop.stats.tool_calls_succeeded,
            tool_calls_failed=loop.stats.tool_calls_failed,
            tool_calls_agreed=loop.stats.tool_calls_agreed,
            tool_calls_rejected=loop.stats.tool_calls_rejected,
            last_turn_duration=loop.stats.last_turn_duration,
            input_price_per_million=loop.stats.input_price_per_million,
            output_price_per_million=loop.stats.output_price_per_million,
            active_model=(
                loop.config.active_model if hasattr(loop.config, "active_model") else ""
            ),
            active_provider=loop.config.get_active_provider().name,
            context_packet_available=loop._context_packet is not None,
        )
