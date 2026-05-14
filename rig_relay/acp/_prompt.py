"""ACP mixin — prompt."""
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


class PromptMixin:
    """Mixin for VibeAcpAgentLoop."""

    @override
    async def prompt(
        self,
        prompt: list[ContentBlock],
        session_id: str,
        message_id: str | None = None,
        **kwargs: Any,
    ) -> PromptResponse:
        session = self._get_session(session_id)

        if session.prompt_task is not None:
            raise InvalidRequestError(
                "Concurrent prompts are not supported yet, wait for agent loop to finish"
            )

        text_prompt = self._build_text_prompt(prompt)
        resolved_message_id = _resolved_user_message_id(message_id)

        if command_response := await self._maybe_handle_builtin_command(
            session, text_prompt, resolved_message_id
        ):
            return command_response

        try:
            skill = session.agent_loop.skill_manager.parse_skill_command(text_prompt)
        except OSError as e:
            raise InternalError(f"Failed to read skill file: {e}") from e

        if skill:
            session.agent_loop.telemetry_client.send_slash_command_used(
                skill.name, "skill"
            )
            text_prompt = SkillManager.build_skill_prompt(text_prompt, skill)

        async def agent_loop_task() -> None:
            async for update in self._run_agent_loop(
                session, text_prompt, resolved_message_id
            ):
                await self.client.session_update(session_id=session.id, update=update)

        try:
            task = session.set_prompt_task(agent_loop_task())
            await task

        except asyncio.CancelledError:
            self._send_usage_update(session)
            return PromptResponse(
                stop_reason="cancelled",
                usage=self._build_usage(session),
                user_message_id=resolved_message_id,
            )

        except CoreRateLimitError as e:
            raise RateLimitError.from_core(e) from e

        except CoreContextTooLongError as e:
            raise ContextTooLongError.from_core(e) from e

        except ConversationLimitException as e:
            raise ConversationLimitError(str(e)) from e

        except Exception as e:
            raise InternalError(str(e)) from e

        self._send_usage_update(session)
        return PromptResponse(
            stop_reason="end_turn",
            usage=self._build_usage(session),
            user_message_id=resolved_message_id,
        )


    def _build_text_prompt(self, acp_prompt: list[ContentBlock]) -> str:
        text_prompt = ""
        for block in acp_prompt:
            separator = "\n\n" if text_prompt else ""
            match block.type:
                # NOTE: ACP supports annotations, but we don't use them here yet.
                case "text":
                    text_prompt = f"{text_prompt}{separator}{block.text}"
                case "resource":
                    block_content = (
                        block.resource.text
                        if isinstance(block.resource, TextResourceContents)
                        else block.resource.blob
                    )
                    fields = {"path": block.resource.uri, "content": block_content}
                    parts = [
                        f"{k}: {v}"
                        for k, v in fields.items()
                        if v is not None and (v or isinstance(v, (int, float)))
                    ]
                    block_prompt = "\n".join(parts)
                    text_prompt = f"{text_prompt}{separator}{block_prompt}"
                case "resource_link":
                    # NOTE: we currently keep more information than just the URI
                    # making it more detailed than the output of the read_file tool.
                    # This is OK, but might be worth testing how it affect performance.
                    fields = {
                        "uri": block.uri,
                        "name": block.name,
                        "title": block.title,
                        "description": block.description,
                        "mime_type": block.mime_type,
                        "size": block.size,
                    }
                    parts = [
                        f"{k}: {v}"
                        for k, v in fields.items()
                        if v is not None and (v or isinstance(v, (int, float)))
                    ]
                    block_prompt = "\n".join(parts)
                    text_prompt = f"{text_prompt}{separator}{block_prompt}"
                case _:
                    raise InvalidRequestError(
                        f"We currently don't support {block.type} content blocks"
                    )
        return text_prompt


    async def _run_agent_loop(
        self, session: AcpSessionLoop, prompt: str, client_message_id: str | None = None
    ) -> AsyncGenerator[SessionUpdate | UsageUpdate]:
        rendered_prompt = render_path_prompt(prompt, base_dir=Path.cwd())

        async with aclosing(
            session.agent_loop.act(rendered_prompt, client_message_id=client_message_id)
        ) as events:
            async for event in events:
                if isinstance(event, AssistantEvent):
                    yield AgentMessageChunk(
                        session_update="agent_message_chunk",
                        content=TextContentBlock(type="text", text=event.content),
                        message_id=event.message_id,
                    )

                elif isinstance(event, ReasoningEvent):
                    yield AgentThoughtChunk(
                        session_update="agent_thought_chunk",
                        content=TextContentBlock(type="text", text=event.content),
                        message_id=event.message_id,
                    )

                elif isinstance(event, ToolCallEvent):
                    if issubclass(event.tool_class, BaseAcpTool):
                        event.tool_class.update_tool_state(
                            tool_manager=session.agent_loop.tool_manager,
                            client=self.client,
                            session_id=session.id,
                            tool_call_id=event.tool_call_id,
                        )

                    session_update = tool_call_session_update(event)
                    if session_update:
                        yield session_update

                elif isinstance(event, ToolResultEvent):
                    session_update = tool_result_session_update(event)
                    if session_update:
                        yield session_update
                    self._send_usage_update(session)

                elif isinstance(event, ToolStreamEvent):
                    yield ToolCallProgress(
                        session_update="tool_call_update",
                        tool_call_id=event.tool_call_id,
                        kind=resolve_kind(event.tool_name),
                        content=[
                            ContentToolCallContent(
                                type="content",
                                content=TextContentBlock(
                                    type="text", text=event.message
                                ),
                            )
                        ],
                        field_meta={"tool_name": event.tool_name},
                    )

                elif isinstance(event, CompactStartEvent):
                    yield create_compact_start_session_update(event)

                elif isinstance(event, CompactEndEvent):
                    yield create_compact_end_session_update(event)

                elif isinstance(event, AgentProfileChangedEvent):
                    pass

