"""ACP mixin — config."""

from __future__ import annotations

from typing import Any, cast, override

from acp import SetSessionModelResponse, SetSessionModeResponse
from acp.schema import (
    ConfigOptionUpdate,
    SessionConfigOptionBoolean,
    SessionConfigOptionSelect,
    SetSessionConfigOptionResponse,
)

from rig_relay.acp.session import AcpSessionLoop
from rig_relay.acp.utils import (
    THINKING_LEVELS,
    ThinkingLevel,
    build_mode_state,
    build_model_state,
    is_valid_acp_mode,
    make_thinking_response,
)
from rig_relay.core.config import VibeConfig


class ConfigMixin:
    """Mixin for VibeAcpAgentLoop."""

    async def _apply_mode_change(self, session: AcpSessionLoop, mode_id: str) -> bool:
        profiles = list(session.agent_loop.agent_manager.available_agents.values())
        if not is_valid_acp_mode(profiles, mode_id):
            return False

        await session.agent_loop.switch_agent(mode_id)

        if session.agent_loop.bypass_tool_permissions:
            session.agent_loop.approval_callback = None
        else:
            session.agent_loop.set_approval_callback(
                self._create_approval_callback(session.id)
            )

        return True

    async def _reload_config(self, session: AcpSessionLoop) -> None:
        new_config = VibeConfig.load(
            tool_paths=session.agent_loop.config.tool_paths,
            disabled_tools=NON_INTERACTIVE_DISABLED_TOOLS,
        )
        await session.agent_loop.reload_with_initial_messages(base_config=new_config)

    async def _apply_model_change(self, session: AcpSessionLoop, model_id: str) -> bool:
        model_aliases = [model.alias for model in session.agent_loop.config.models]
        if model_id not in model_aliases:
            return False

        VibeConfig.save_updates({"active_model": model_id})
        await self._reload_config(session)
        return True

    async def _apply_thinking_change(
        self, session: AcpSessionLoop, level: ThinkingLevel
    ) -> bool:
        session.agent_loop.config.set_thinking(level)
        await self._reload_config(session)
        return True

    @override
    async def set_session_mode(
        self, mode_id: str, session_id: str, **kwargs: Any
    ) -> SetSessionModeResponse | None:
        session = self._get_session(session_id)

        if not await self._apply_mode_change(session, mode_id):
            return None

        return SetSessionModeResponse()

    @override
    async def set_session_model(
        self, model_id: str, session_id: str, **kwargs: Any
    ) -> SetSessionModelResponse | None:
        session = self._get_session(session_id)

        if not await self._apply_model_change(session, model_id):
            return None

        return SetSessionModelResponse()

    @override
    async def set_config_option(
        self, config_id: str, session_id: str, value: str | bool, **kwargs: Any
    ) -> SetSessionConfigOptionResponse | None:
        session = self._get_session(session_id)

        match config_id:
            case "mode" if isinstance(value, str):
                success = await self._apply_mode_change(session, value)
            case "model" if isinstance(value, str):
                success = await self._apply_model_change(session, value)
            case "thinking" if isinstance(value, str) and value in THINKING_LEVELS:
                success = await self._apply_thinking_change(
                    session, cast(ThinkingLevel, value)
                )
            case _:
                success = False

        if not success:
            return None

        return SetSessionConfigOptionResponse(
            config_options=self._build_config_options(session)
        )

    def _build_config_options(
        self, session: AcpSessionLoop
    ) -> list[SessionConfigOptionSelect | SessionConfigOptionBoolean]:
        """Build the current modes + models config options for a session."""
        profiles = list(session.agent_loop.agent_manager.available_agents.values())
        _, modes_config = build_mode_state(
            profiles, session.agent_loop.agent_profile.name
        )
        _, models_config = build_model_state(
            session.agent_loop.config.models, session.agent_loop.config.active_model
        )
        thinking_config = make_thinking_response(
            session.agent_loop.config.get_active_model().thinking
        )
        return [modes_config, models_config, thinking_config]

    async def _send_config_option_update(self, session: AcpSessionLoop) -> None:
        """Push updated config options (modes, models) to the client."""
        await self.client.session_update(
            session_id=session.id,
            update=ConfigOptionUpdate(
                session_update="config_option_update",
                config_options=self._build_config_options(session),
            ),
        )
