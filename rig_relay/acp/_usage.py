"""ACP mixin — usage."""
from __future__ import annotations
import asyncio
from collections.abc import AsyncGenerator, Callable
from contextlib import aclosing
import logging
import os
from pathlib import Path
import signal
import sys
from typing import Any, cast, override
from uuid import uuid4
from acp import (
    PROTOCOL_VERSION,
    Agent as AcpAgent,
    Client,
    InitializeResponse,
    LoadSessionResponse,
    NewSessionResponse,
    PromptResponse,
    SetSessionModelResponse,
    SetSessionModeResponse,
    run_agent,
)
from acp.helpers import ContentBlock, SessionUpdate, update_available_commands
from acp.schema import (
    AgentCapabilities,
    AgentMessageChunk,
    AgentThoughtChunk,
    AllowedOutcome,
    AuthenticateResponse,
    AuthMethodAgent,
    AvailableCommand,
    AvailableCommandInput,
    ClientCapabilities,
    CloseSessionResponse,
    ConfigOptionUpdate,
    ContentToolCallContent,
    Cost,
    EnvVarAuthMethod,
    ForkSessionResponse,
    HttpMcpServer,
    Implementation,
    ListSessionsResponse,
    McpServerStdio,
    PromptCapabilities,
    ResumeSessionResponse,
    SessionCapabilities,
    SessionCloseCapabilities,
    SessionConfigOptionBoolean,
    SessionConfigOptionSelect,
    SessionForkCapabilities,
    SessionInfo,
    SessionInfoUpdate,
    SessionListCapabilities,
    SetSessionConfigOptionResponse,
    SseMcpServer,
    TerminalAuthMethod,
    TextContentBlock,
    TextResourceContents,
    ToolCallProgress,
    ToolCallUpdate,
    UnstructuredCommandInput,
    Usage,
    UsageUpdate,
)
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, ValidationError
from rig_relay import RIG_ROOT, __version__
from rig_relay.acp.acp_logger import acp_message_observer
from rig_relay.acp.commands import AcpCommandRegistry
from rig_relay.acp.exceptions import (
    ConfigurationError,
    ContextTooLongError,
    ConversationLimitError,
    InternalError,
    InvalidRequestError,
    NotImplementedMethodError,
    RateLimitError,
    SessionLoadError,
    SessionNotFoundError,
    UnauthenticatedError,
)
from rig_relay.acp.session import AcpSessionLoop
from rig_relay.acp.tools.base import BaseAcpTool
from rig_relay.acp.tools.session_update import (
    resolve_kind,
    tool_call_session_update,
    tool_result_session_update,
)
from rig_relay.acp.utils import (
    THINKING_LEVELS,
    ThinkingLevel,
    ToolOption,
    build_mode_state,
    build_model_state,
    build_permission_options,
    create_assistant_message_replay,
    create_compact_end_session_update,
    create_compact_start_session_update,
    create_reasoning_replay,
    create_tool_call_replay,
    create_tool_result_replay,
    create_user_message_replay,
    get_proxy_help_text,
    is_valid_acp_mode,
    make_thinking_response,
)
from rig_relay.core.agent_loop import AgentLoop
from rig_relay.core.agents.models import CHAT as CHAT_AGENT, BuiltinAgentName
from rig_relay.core.autocompletion.path_prompt_adapter import render_path_prompt
from rig_relay.core.config import (
    MissingAPIKeyError,
    SessionLoggingConfig,
    VibeConfig,
    load_dotenv_values,
)
from rig_relay.core.data_retention import DATA_RETENTION_MESSAGE
from rig_relay.core.hooks.config import load_hooks_from_fs
from rig_relay.core.proxy_setup import (
    ProxySetupError,
    parse_proxy_command,
    set_proxy_var,
    unset_proxy_var,
)
from rig_relay.core.session.saved_sessions import (
    update_saved_session_title,
    update_saved_session_title_at_path,
)
from rig_relay.core.session.session_loader import SessionLoader
from rig_relay.core.skills.manager import SkillManager
from rig_relay.core.telemetry.build_metadata import build_entrypoint_metadata
from rig_relay.core.telemetry.send import TelemetryClient
from rig_relay.core.telemetry.types import EntrypointMetadata
from rig_relay.core.tools.permissions import RequiredPermission
from rig_relay.core.types import (
    AgentProfileChangedEvent,
    ApprovalCallback,
    ApprovalResponse,
    AssistantEvent,
    CompactEndEvent,
    CompactStartEvent,
    ContextTooLongError as CoreContextTooLongError,
    LLMMessage,
    RateLimitError as CoreRateLimitError,
    ReasoningEvent,
    Role,
    ToolCallEvent,
    ToolResultEvent,
    ToolStreamEvent,
)
from rig_relay.core.utils import (
    CancellationReason,
    ConversationLimitException,
    get_user_cancellation_message,
)


class UsageMixin:
    """Mixin for VibeAcpAgentLoop."""

    def _build_usage(self, session: AcpSessionLoop) -> Usage:
        stats = session.agent_loop.stats
        return Usage(
            input_tokens=stats.session_prompt_tokens,
            output_tokens=stats.session_completion_tokens,
            total_tokens=stats.session_total_llm_tokens,
        )


    def _build_usage_update(self, session: AcpSessionLoop) -> UsageUpdate:
        stats = session.agent_loop.stats
        active_model = session.agent_loop.config.get_active_model()
        cost = (
            Cost(amount=stats.session_cost, currency="USD")
            if stats.input_price_per_million > 0 or stats.output_price_per_million > 0
            else None
        )
        return UsageUpdate(
            session_update="usage_update",
            used=stats.context_tokens,
            size=active_model.auto_compact_threshold,
            cost=cost,
        )


    def _send_usage_update(self, session: AcpSessionLoop) -> None:
        async def _send() -> None:
            try:
                update = self._build_usage_update(session)
                await self.client.session_update(session_id=session.id, update=update)
            except Exception:
                pass

        session.spawn(_send())


    async def _replay_tool_calls(self, session_id: str, msg: LLMMessage) -> None:
        if not msg.tool_calls:
            return
        for tool_call in msg.tool_calls:
            if tool_call.id and tool_call.function.name:
                update = create_tool_call_replay(
                    tool_call.id, tool_call.function.name, tool_call.function.arguments
                )
                await self.client.session_update(session_id=session_id, update=update)


    async def _replay_conversation_history(
        self, session_id: str, messages: list[LLMMessage]
    ) -> None:
        for msg in messages:
            if msg.role == Role.user:
                update = create_user_message_replay(msg)
                await self.client.session_update(session_id=session_id, update=update)

            elif msg.role == Role.assistant:
                if reasoning_update := create_reasoning_replay(msg):
                    await self.client.session_update(
                        session_id=session_id, update=reasoning_update
                    )
                if text_update := create_assistant_message_replay(msg):
                    await self.client.session_update(
                        session_id=session_id, update=text_update
                    )
                await self._replay_tool_calls(session_id, msg)

            elif msg.role == Role.tool:
                if result_update := create_tool_result_replay(msg):
                    await self.client.session_update(
                        session_id=session_id, update=result_update
                    )

