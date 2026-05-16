"""ACP mixin — session lifecycle."""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
import sys
from typing import Any, override

from acp import (
    PROTOCOL_VERSION,
    InitializeResponse,
    LoadSessionResponse,
    NewSessionResponse,
)
from acp.schema import (
    AgentCapabilities,
    AuthMethodAgent,
    ClientCapabilities,
    CloseSessionResponse,
    EnvVarAuthMethod,
    ForkSessionResponse,
    HttpMcpServer,
    Implementation,
    McpServerStdio,
    PromptCapabilities,
    ResumeSessionResponse,
    SessionCapabilities,
    SessionCloseCapabilities,
    SessionForkCapabilities,
    SessionListCapabilities,
    SseMcpServer,
    TerminalAuthMethod,
)
from pydantic import ValidationError

from rig_relay import __version__
from rig_relay.acp.commands import AcpCommandRegistry
from rig_relay.acp.exceptions import (
    ConfigurationError,
    InvalidRequestError,
    NotImplementedMethodError,
    SessionLoadError,
    SessionNotFoundError,
)
from rig_relay.acp.session import AcpSessionLoop
from rig_relay.acp.utils import build_mode_state, build_model_state
from rig_relay.core.agent_loop import AgentLoop
from rig_relay.core.agents.models import CHAT as CHAT_AGENT, BuiltinAgentName
from rig_relay.core.config import (
    MissingAPIKeyError,
    SessionLoggingConfig,
    VibeConfig,
    load_dotenv_values,
)
from rig_relay.core.hooks.config import load_hooks_from_fs
from rig_relay.core.session.session_loader import SessionLoader
from rig_relay.core.types import Role


class SessionLifecycleMixin:
    """Mixin for VibeAcpAgentLoop."""

    @override
    async def initialize(
        self,
        protocol_version: int,
        client_capabilities: ClientCapabilities | None = None,
        client_info: Implementation | None = None,
        **kwargs: Any,
    ) -> InitializeResponse:
        self.client_capabilities = client_capabilities
        self.client_info = client_info

        # The ACP Agent process can be launched in 3 different ways, depending on installation
        #  - dev mode: `uv run vibe-acp`, ran from the project root
        #  - uv tool install: `vibe-acp`, similar to dev mode, but uv takes care of path resolution
        #  - bundled binary: `./vibe-acp` from binary location
        # The 2 first modes are working similarly, under the hood uv runs `/some/python /my/entrypoint.py``
        # The last mode is quite different as our bundler also includes the python install.
        # So sys.executable is already /path/to/binary/vibe-acp.
        # For this reason, we make a distinction in the way we call the setup command
        command = sys.executable
        if "python" not in Path(command).name:
            # It's the case for bundled binaries, we don't need any other arguments
            args = ["--setup"]
        else:
            script_name = sys.argv[0]
            args = [script_name, "--setup"]

        supports_terminal_auth = (
            self.client_capabilities
            and self.client_capabilities.field_meta
            and self.client_capabilities.field_meta.get("terminal-auth") is True
        )

        auth_methods: list[EnvVarAuthMethod | TerminalAuthMethod | AuthMethodAgent] = (
            [
                TerminalAuthMethod(
                    type="terminal",
                    id="rig-relay-setup",
                    name="Register your API Key",
                    description="Register your API Key inside Rig Relay",
                    field_meta={
                        "terminal-auth": {
                            "command": command,
                            "args": args,
                            "label": "Rig Relay Setup",
                        }
                    },
                )
            ]
            if supports_terminal_auth
            else []
        )

        response = InitializeResponse(
            agent_capabilities=AgentCapabilities(
                load_session=True,
                prompt_capabilities=PromptCapabilities(
                    audio=False, embedded_context=True, image=False
                ),
                session_capabilities=SessionCapabilities(
                    close=SessionCloseCapabilities(),
                    list=SessionListCapabilities(),
                    fork=SessionForkCapabilities(),
                ),
            ),
            protocol_version=PROTOCOL_VERSION,
            agent_info=Implementation(
                name="@rig/rig-relay", title="Rig Relay", version=__version__
            ),
            auth_methods=auth_methods,
        )
        return response


    async def _create_acp_session(
        self, session_id: str, agent_loop: AgentLoop
    ) -> AcpSessionLoop:
        command_registry = AcpCommandRegistry()
        session = AcpSessionLoop(
            id=session_id, agent_loop=agent_loop, command_registry=command_registry
        )
        self.sessions[session.id] = session

        async def _on_commands_changed() -> None:
            session.spawn(self._send_available_commands(session))

        command_registry.set_on_changed(_on_commands_changed)

        if not agent_loop.bypass_tool_permissions:
            agent_loop.set_approval_callback(self._create_approval_callback(session.id))

        session.spawn(self._send_available_commands(session))
        session.spawn(self._warm_up_agent_loop(agent_loop))

        return session


    async def _warm_up_agent_loop(self, agent_loop: AgentLoop) -> None:
        """Proactively await deferred init so `vibe.ready` telemetry is emitted
        without waiting for the user's first prompt. Errors are swallowed here
        and will resurface on the first `act()` call via `requires_init`.
        """
        try:
            await agent_loop.wait_until_ready()
        except Exception:
            pass


    def _create_agent_loop(
        self, config: VibeConfig, agent_name: str, hook_config_result: Any = None
    ) -> AgentLoop:
        agent_loop = AgentLoop(
            config=config,
            agent_name=agent_name,
            enable_streaming=True,
            entrypoint_metadata=self._build_entrypoint_metadata(),
            defer_heavy_init=True,
            hook_config_result=hook_config_result,
        )
        agent_loop.agent_manager.register_agent(CHAT_AGENT)
        return agent_loop


    def _build_session_state(
        self, session: AcpSessionLoop
    ) -> tuple[Any, Any, Any, Any]:
        modes_state, modes_config = build_mode_state(
            list(session.agent_loop.agent_manager.available_agents.values()),
            session.agent_loop.agent_profile.name,
        )
        models_state, models_config = build_model_state(
            session.agent_loop.config.models, session.agent_loop.config.active_model
        )
        return modes_state, modes_config, models_state, models_config


    @override
    async def new_session(
        self,
        cwd: str,
        mcp_servers: list[HttpMcpServer | SseMcpServer | McpServerStdio] | None = None,
        **kwargs: Any,
    ) -> NewSessionResponse:
        load_dotenv_values()
        os.chdir(cwd)

        config = self._load_config()
        hook_config_result = load_hooks_from_fs(config)

        try:
            agent_loop = self._create_agent_loop(
                config, BuiltinAgentName.DEFAULT, hook_config_result=hook_config_result
            )
            # NOTE: For now, we pin session.id to agent_loop.session_id right after init time.
            # We should just use agent_loop.session_id everywhere, but it can still change during
            # session lifetime (e.g. agent_loop.compact is called).
            # We should refactor agent_loop.session_id to make it immutable in ACP context.
            session = await self._create_acp_session(agent_loop.session_id, agent_loop)
        except Exception as e:
            raise ConfigurationError(str(e)) from e

        agent_loop.emit_new_session_telemetry()

        modes_state, _, models_state, _ = self._build_session_state(session)

        return NewSessionResponse(
            session_id=session.id,
            models=models_state,
            modes=modes_state,
            config_options=self._build_config_options(session),
        )


    def _get_session(self, session_id: str) -> AcpSessionLoop:
        if session_id not in self.sessions:
            raise SessionNotFoundError(session_id)
        return self.sessions[session_id]


    def _find_acp_session_by_vibe_session_id(
        self, session_id: str
    ) -> AcpSessionLoop | None:
        for candidate in self.sessions.values():
            if candidate.agent_loop.session_id == session_id:
                return candidate

        return None


    def _load_session_logging_config(self) -> SessionLoggingConfig:
        try:
            return VibeConfig.load().session_logging
        except MissingAPIKeyError:
            try:
                persisted_config = VibeConfig.get_persisted_config()
                return SessionLoggingConfig.model_validate(
                    persisted_config.get("session_logging", {})
                )
            except Exception as e:
                raise ConfigurationError(str(e)) from e
        except Exception as e:
            raise ConfigurationError(str(e)) from e


    @override
    async def load_session(
        self,
        cwd: str,
        session_id: str,
        mcp_servers: list[HttpMcpServer | SseMcpServer | McpServerStdio] | None = None,
        **kwargs: Any,
    ) -> LoadSessionResponse | None:
        load_dotenv_values()
        os.chdir(cwd)

        config = self._load_config()
        hook_config_result = load_hooks_from_fs(config)

        session_dir = SessionLoader.find_session_by_id(
            session_id, config.session_logging
        )
        if session_dir is None:
            raise SessionNotFoundError(session_id)

        try:
            loaded_messages, metadata = SessionLoader.load_session(session_dir)
        except Exception as e:
            raise SessionLoadError(session_id, str(e)) from e

        agent_loop = self._create_agent_loop(
            config, BuiltinAgentName.DEFAULT, hook_config_result=hook_config_result
        )
        loaded_session_id = metadata.get("session_id", agent_loop.session_id)
        agent_loop.session_id = loaded_session_id
        agent_loop.parent_session_id = metadata.get("parent_session_id")
        agent_loop.session_logger.resume_existing_session(
            loaded_session_id, session_dir
        )

        non_system_messages = [
            msg for msg in loaded_messages if msg.role != Role.system
        ]
        if non_system_messages:
            agent_loop.messages.extend(non_system_messages)
        session = await self._create_acp_session(session_id, agent_loop)
        await self._replay_conversation_history(session.id, non_system_messages)
        self._send_usage_update(session)

        modes_state, _, models_state, _ = self._build_session_state(session)

        return LoadSessionResponse(
            models=models_state,
            modes=modes_state,
            config_options=self._build_config_options(session),
        )


    @override
    async def close_session(
        self, session_id: str, **kwargs: Any
    ) -> CloseSessionResponse | None:
        session = self._get_session(session_id)
        self.sessions.pop(session_id, None)

        session.agent_loop.emit_session_closed_telemetry()
        await session.close()
        await self._close_agent_loop(session.agent_loop)

        return CloseSessionResponse()


    async def emit_session_closed_for_active_sessions(self) -> None:
        agent_loops = [session.agent_loop for session in self.sessions.values()]
        for agent_loop in agent_loops:
            agent_loop.telemetry_client._client = None
            agent_loop.emit_session_closed_telemetry()
        await asyncio.gather(
            *(agent_loop.telemetry_client.aclose() for agent_loop in agent_loops),
            return_exceptions=True,
        )


    async def _close_agent_loop(self, agent_loop: AgentLoop) -> None:
        deferred_init_thread = agent_loop._deferred_init_thread
        if deferred_init_thread is not None and deferred_init_thread.is_alive():
            await asyncio.to_thread(deferred_init_thread.join)

        await agent_loop.aclose()
        await agent_loop.telemetry_client.aclose()


    @override
    async def fork_session(
        self,
        cwd: str,
        session_id: str,
        mcp_servers: list[HttpMcpServer | SseMcpServer | McpServerStdio] | None = None,
        **kwargs: Any,
    ) -> ForkSessionResponse:
        load_dotenv_values()
        os.chdir(cwd)

        source_session = self._get_session(session_id)
        try:
            message_id = ForkSessionParams.model_validate(kwargs).message_id
        except ValidationError as e:
            raise InvalidRequestError(f"Invalid fork parameters: {e}") from e
        if (
            source_session.prompt_task is not None
            and not source_session.prompt_task.done()
        ):
            raise InvalidRequestError(
                "Cannot fork a session while the agent loop is running"
            )

        try:
            agent_loop = await source_session.agent_loop.fork(message_id)
            agent_loop.agent_manager.register_agent(CHAT_AGENT)
            session = await self._create_acp_session(agent_loop.session_id, agent_loop)
        except InvalidRequestError:
            raise
        except ValueError as e:
            raise InvalidRequestError(str(e)) from e
        except Exception as e:
            raise ConfigurationError(str(e)) from e

        modes_state, _, models_state, _ = self._build_session_state(session)

        return ForkSessionResponse(
            session_id=session.id,
            models=models_state,
            modes=modes_state,
            config_options=self._build_config_options(session),
        )


    @override
    async def resume_session(
        self,
        cwd: str,
        session_id: str,
        mcp_servers: list[HttpMcpServer | SseMcpServer | McpServerStdio] | None = None,
        **kwargs: Any,
    ) -> ResumeSessionResponse:
        raise NotImplementedMethodError("resume_session")

