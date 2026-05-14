"""ACP mixin — protocol."""
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


class ProtocolMixin:
    """Mixin for VibeAcpAgentLoop."""

    @override
    async def authenticate(
        self, method_id: str, **kwargs: Any
    ) -> AuthenticateResponse | None:
        raise NotImplementedMethodError("authenticate")


    async def _emit_session_info_update(
        self, session_id: str, *, title: str, updated_at: str | None
    ) -> None:
        update_kwargs: dict[str, Any] = {
            "session_update": "session_info_update",
            "title": title,
        }
        if updated_at is not None:
            update_kwargs["updated_at"] = updated_at

        await self.client.session_update(
            session_id=session_id, update=SessionInfoUpdate(**update_kwargs)
        )


    async def _persist_live_session_title(
        self, session: AcpSessionLoop, title: str
    ) -> dict[str, Any] | None:
        logger = session.agent_loop.session_logger
        if not logger.enabled or logger.session_dir is None:
            return None
        if not logger.metadata_filepath.exists():
            return None

        try:
            return await update_saved_session_title_at_path(logger.session_dir, title)
        except ValueError as exc:
            raise InternalError(
                f"Failed to persist title update for session {logger.session_id}: {exc}"
            ) from exc


    def _set_live_session_title(self, session: AcpSessionLoop, title: str) -> None:
        try:
            session.agent_loop.session_logger.set_title(title)
        except ValueError as exc:
            raise InvalidRequestError(
                f"Invalid ACP session title request: {exc}"
            ) from exc


    async def _handle_session_set_title(self, params: dict[str, Any]) -> dict[str, Any]:
        try:
            request = SessionSetTitleRequest.model_validate(params)
        except ValidationError as exc:
            raise InvalidRequestError(
                f"Invalid ACP session title request: {exc}"
            ) from exc

        live_session = self.sessions.get(
            request.session_id
        ) or self._find_acp_session_by_vibe_session_id(request.session_id)
        if live_session is None:
            try:
                metadata = await update_saved_session_title(
                    request.session_id,
                    request.title,
                    self._load_session_logging_config(),
                )
            except ValueError as exc:
                raise SessionNotFoundError(request.session_id) from exc

            await self._emit_session_info_update(
                request.session_id,
                title=request.title,
                updated_at=metadata.get("end_time"),
            )
            return {}

        persisted_metadata = await self._persist_live_session_title(
            live_session, request.title
        )
        self._set_live_session_title(live_session, request.title)
        updated_at = (
            persisted_metadata.get("end_time")
            if persisted_metadata is not None
            else (
                live_session.agent_loop.session_logger.session_metadata.end_time
                if live_session.agent_loop.session_logger.session_metadata is not None
                else None
            )
        )

        await self._emit_session_info_update(
            live_session.id, title=request.title, updated_at=updated_at
        )
        return {}


    @override
    async def ext_method(self, method: str, params: dict) -> dict:
        if method == "session/set_title":
            return await self._handle_session_set_title(params)

        raise NotImplementedMethodError(method)


    @override
    async def ext_notification(self, method: str, params: dict) -> None:
        # ACP strips the leading "_" before delegating extension notifications here.
        if method == "telemetry/send":
            self._handle_telemetry_notification(params)


    @override
    def on_connect(self, conn: Client) -> None:
        self.client = conn

    # -- Command handlers ------------------------------------------------------

