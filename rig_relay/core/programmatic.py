from __future__ import annotations

import asyncio
from contextlib import aclosing

from rig_relay import __version__
from rig_relay.core.agent_loop import AgentLoop, TeleportError
from rig_relay.core.agents.models import BuiltinAgentName
from rig_relay.core.config import VibeConfig
from rig_relay.core.hooks.models import HookConfigResult
from rig_relay.core.logger import logger
from rig_relay.core.output_formatters import create_formatter
from rig_relay.core.telemetry.build_metadata import build_entrypoint_metadata
from rig_relay.core.telemetry.types import ClientMetadata
from rig_relay.core.teleport.types import (
    TeleportPushRequiredEvent,
    TeleportPushResponseEvent,
)
from rig_relay.core.types import AssistantEvent, LLMMessage, OutputFormat, Role
from rig_relay.core.utils import ConversationLimitException

__all__ = ["TeleportError", "run_programmatic"]

_DEFAULT_CLIENT_METADATA = ClientMetadata(name="vibe_programmatic", version=__version__)


def run_programmatic(  # noqa: PLR0913, PLR0917
    config: VibeConfig,
    prompt: str,
    max_turns: int | None = None,
    max_price: float | None = None,
    output_format: OutputFormat = OutputFormat.TEXT,
    previous_messages: list[LLMMessage] | None = None,
    agent_name: str = BuiltinAgentName.AUTO_APPROVE,
    client_metadata: ClientMetadata = _DEFAULT_CLIENT_METADATA,
    teleport: bool = False,
    headless: bool = False,
    hook_config_result: HookConfigResult | None = None,
) -> str | None:
    formatter = create_formatter(output_format)

    agent_loop = AgentLoop(
        config,
        agent_name=agent_name,
        message_observer=formatter.on_message_added,
        max_turns=max_turns,
        max_price=max_price,
        enable_streaming=False,
        headless=headless,
        entrypoint_metadata=build_entrypoint_metadata(
            agent_entrypoint="programmatic",
            agent_version=__version__,
            client_name=client_metadata.name,
            client_version=client_metadata.version,
        ),
        hook_config_result=hook_config_result,
    )
    logger.info("USER: %s", prompt)

    async def _async_run() -> str | None:
        try:
            if previous_messages:
                non_system_messages = [
                    msg for msg in previous_messages if not (msg.role == Role.system)
                ]
                agent_loop.messages.extend(non_system_messages)
                logger.info(
                    "Loaded %d messages from previous session", len(non_system_messages)
                )
            else:
                agent_loop.emit_new_session_telemetry()

            if teleport and config.vibe_code_enabled:
                gen = agent_loop.teleport_to_vibe_code(prompt or None)
                async for event in gen:
                    formatter.on_event(event)
                    if isinstance(event, TeleportPushRequiredEvent):
                        next_event = await gen.asend(
                            TeleportPushResponseEvent(approved=True)
                        )
                        formatter.on_event(next_event)
            else:
                async with aclosing(agent_loop.act(prompt)) as events:
                    async for event in events:
                        formatter.on_event(event)
                        if (
                            isinstance(event, AssistantEvent)
                            and event.stopped_by_middleware
                        ):
                            raise ConversationLimitException(event.content)

            return formatter.finalize()
        finally:
            agent_loop.emit_session_closed_telemetry()
            await agent_loop.aclose()
            await agent_loop.telemetry_client.aclose()

    return asyncio.run(_async_run())
