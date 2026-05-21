"""ACP mixin — prompt."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from contextlib import aclosing
from pathlib import Path
from typing import Any

from acp import PromptResponse
from acp.helpers import ContentBlock, SessionUpdate
from acp.schema import (
    AgentMessageChunk,
    AgentThoughtChunk,
    ContentToolCallContent,
    TextContentBlock,
    TextResourceContents,
    ToolCallProgress,
    UsageUpdate,
)

from rig_relay.acp.exceptions import (
    ContextTooLongError,
    ConversationLimitError,
    InternalError,
    InvalidRequestError,
    RateLimitError,
)
from rig_relay.acp.session import AcpSessionLoop
from rig_relay.acp.tools.base import BaseAcpTool
from rig_relay.acp.tools.session_update import (
    resolve_kind,
    tool_call_session_update,
    tool_result_session_update,
)
from rig_relay.acp.utils import (
    create_compact_end_session_update,
    create_compact_start_session_update,
)
from rig_relay.core.autocompletion.path_prompt_adapter import render_path_prompt
from rig_relay.core.skills.manager import SkillManager
from rig_relay.core.types import (
    AgentProfileChangedEvent,
    AssistantEvent,
    CompactEndEvent,
    CompactStartEvent,
    ContextTooLongError as CoreContextTooLongError,
    RateLimitError as CoreRateLimitError,
    ReasoningEvent,
    ToolCallEvent,
    ToolResultEvent,
    ToolStreamEvent,
)
from rig_relay.core.utils import ConversationLimitException


def _resolved_user_message_id(message_id: str | None) -> str | None:
    return message_id


class PromptMixin:
    """Mixin for VibeAcpAgentLoop."""

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
