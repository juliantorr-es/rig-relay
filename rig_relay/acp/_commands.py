"""ACP mixin — commands."""
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


class CommandsMixin:
    """Mixin for VibeAcpAgentLoop."""

    async def _send_available_commands(self, session: AcpSessionLoop) -> None:
        commands: list[AvailableCommand] = []

        for cmd in session.command_registry.commands.values():
            input_spec = (
                AvailableCommandInput(
                    root=UnstructuredCommandInput(hint=cmd.input_hint)
                )
                if cmd.input_hint
                else None
            )
            commands.append(
                AvailableCommand(
                    name=cmd.name, description=cmd.description, input=input_spec
                )
            )

        builtin_names = set(session.command_registry.commands)
        for skill in session.agent_loop.skill_manager.available_skills.values():
            if not skill.user_invocable or skill.name in builtin_names:
                continue
            commands.append(
                AvailableCommand(
                    name=skill.name,
                    description=skill.description,
                    input=AvailableCommandInput(
                        root=UnstructuredCommandInput(hint="instructions for the skill")
                    ),
                )
            )

        await self.client.session_update(
            session_id=session.id, update=update_available_commands(commands)
        )


    async def _maybe_handle_builtin_command(
        self, session: AcpSessionLoop, text_prompt: str, message_id: str
    ) -> PromptResponse | None:
        normalized = text_prompt.strip().lower()
        parts = normalized.split(None, 1)
        if not parts or not parts[0].startswith("/"):
            return None

        cmd_name = parts[0][1:]  # strip leading "/"
        command = session.command_registry.get(cmd_name)
        if command is None:
            return None

        session.agent_loop.telemetry_client.send_slash_command_used(cmd_name, "builtin")
        handler = getattr(self, command.handler)
        return await handler(session, text_prompt, message_id)


    async def _command_reply(
        self, session: AcpSessionLoop, text: str, message_id: str
    ) -> PromptResponse:
        """Send a text message to the client and return an end-turn response."""
        await self.client.session_update(
            session_id=session.id,
            update=AgentMessageChunk(
                session_update="agent_message_chunk",
                content=TextContentBlock(type="text", text=text),
                message_id=str(uuid4()),
            ),
        )
        return PromptResponse(stop_reason="end_turn", user_message_id=message_id)


    async def _handle_help(
        self, session: AcpSessionLoop, text_prompt: str, message_id: str
    ) -> PromptResponse:
        lines = ["### Available Commands", ""]
        for cmd in session.command_registry.commands.values():
            hint = f" `<{cmd.input_hint}>`" if cmd.input_hint else ""
            lines.append(f"- `/{cmd.name}`{hint}: {cmd.description}")

        builtin_names = set(session.command_registry.commands)
        invocable = {
            n: s
            for n, s in session.agent_loop.skill_manager.available_skills.items()
            if s.user_invocable and n not in builtin_names
        }
        if invocable:
            lines.extend(["", "### Available Skills", ""])
            for name, info in invocable.items():
                lines.append(f"- `/{name}`: {info.description}")

        return await self._command_reply(session, "\n".join(lines), message_id)


    async def _handle_compact(
        self, session: AcpSessionLoop, text_prompt: str, message_id: str
    ) -> PromptResponse:
        if len(session.agent_loop.messages) <= 1:
            return await self._command_reply(
                session, "No conversation history to compact yet.", message_id
            )

        tool_call_id = str(uuid4())
        old_tokens = session.agent_loop.stats.context_tokens
        old_session_id = session.agent_loop.session_id
        parts = text_prompt.strip().split(None, 1)
        cmd_args = parts[1] if len(parts) > 1 else ""

        start_event = CompactStartEvent(
            current_context_tokens=old_tokens or 0,
            threshold=0,
            tool_call_id=tool_call_id,
        )
        await self.client.session_update(
            session_id=session.id,
            update=create_compact_start_session_update(start_event),
        )

        await session.agent_loop.compact(extra_instructions=cmd_args.strip())
        new_tokens = session.agent_loop.stats.context_tokens

        end_event = CompactEndEvent(
            old_context_tokens=old_tokens or 0,
            new_context_tokens=new_tokens or 0,
            summary_length=0,
            old_session_id=old_session_id,
            new_session_id=session.agent_loop.session_id,
            tool_call_id=tool_call_id,
        )
        await self.client.session_update(
            session_id=session.id, update=create_compact_end_session_update(end_event)
        )

        return PromptResponse(stop_reason="end_turn", user_message_id=message_id)


    async def _reload_session_config(self, session: AcpSessionLoop) -> None:
        """Reload config from disk and reinitialize the agent loop."""
        new_config = VibeConfig.load(
            tool_paths=session.agent_loop.config.tool_paths,
            disabled_tools=NON_INTERACTIVE_DISABLED_TOOLS,
        )
        await session.agent_loop.reload_with_initial_messages(base_config=new_config)


    async def _handle_reload(
        self, session: AcpSessionLoop, text_prompt: str, message_id: str
    ) -> PromptResponse:
        try:
            await self._reload_session_config(session)
        except Exception as e:
            return await self._command_reply(
                session, f"Failed to reload config: {e}", message_id
            )

        try:
            await session.command_registry.notify_changed()
        except Exception as e:
            return await self._command_reply(
                session,
                f"Configuration reloaded, but failed to advertise updated commands: {e}",
                message_id,
            )

        return await self._command_reply(
            session,
            "Configuration reloaded (includes agent instructions and skills).",
            message_id,
        )


    async def _handle_log(
        self, session: AcpSessionLoop, text_prompt: str, message_id: str
    ) -> PromptResponse:
        logger = session.agent_loop.session_logger
        if not logger.enabled:
            return await self._command_reply(
                session, "Session logging is disabled in configuration.", message_id
            )

        return await self._command_reply(
            session,
            f"## Current Log Directory\n\n`{logger.session_dir}`\n\n"
            "You can send this directory to share your interaction.",
            message_id,
        )


    async def _handle_proxy_setup(
        self, session: AcpSessionLoop, text_prompt: str, message_id: str
    ) -> PromptResponse:
        parts = text_prompt.strip().split(None, 1)
        args = parts[1] if len(parts) > 1 else ""

        try:
            if not args:
                message = get_proxy_help_text()
            else:
                key, value = parse_proxy_command(args)
                if value is not None:
                    set_proxy_var(key, value)
                    message = (
                        f"Set `{key}={value}` in ~/.vibe/.env\n\n"
                        "Please start a new chat for changes to take effect."
                    )
                else:
                    unset_proxy_var(key)
                    message = (
                        f"Removed `{key}` from ~/.vibe/.env\n\n"
                        "Please start a new chat for changes to take effect."
                    )
        except ProxySetupError as e:
            message = f"Error: {e}"

        return await self._command_reply(session, message, message_id)


    async def _handle_leanstall(
        self, session: AcpSessionLoop, text_prompt: str, message_id: str
    ) -> PromptResponse:
        current = list(session.agent_loop.base_config.installed_agents)
        if "lean" in current:
            return await self._command_reply(
                session, "Lean agent is already installed.", message_id
            )

        VibeConfig.save_updates({"installed_agents": [*current, "lean"]})
        await self._reload_session_config(session)
        await self._send_config_option_update(session)
        return await self._command_reply(
            session,
            "Lean agent installed. Start a new session to switch to Lean mode.",
            message_id,
        )


    async def _handle_unleanstall(
        self, session: AcpSessionLoop, text_prompt: str, message_id: str
    ) -> PromptResponse:
        current = list(session.agent_loop.base_config.installed_agents)
        if "lean" not in current:
            return await self._command_reply(
                session, "Lean agent is not installed.", message_id
            )

        VibeConfig.save_updates({
            "installed_agents": [a for a in current if a != "lean"]
        })
        await self._reload_session_config(session)
        await self._send_config_option_update(session)
        return await self._command_reply(session, "Lean agent uninstalled.", message_id)


    async def _handle_data_retention(
        self, session: AcpSessionLoop, text_prompt: str, message_id: str
    ) -> PromptResponse:
        return await self._command_reply(session, DATA_RETENTION_MESSAGE, message_id)


