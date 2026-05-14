from __future__ import annotations

import asyncio
from collections.abc import Callable
import hashlib
from typing import TYPE_CHECKING, Any

from rig_relay.desktop.chat_state import ChatMessage, ChatRole
from rig_relay.core.logger import logger
from rig_relay.core.types import (
    AssistantEvent,
    BaseEvent,
    ReasoningEvent,
    ToolCallEvent,
    ToolResultEvent,
    ToolStreamEvent,
    UserMessageEvent,
)

if TYPE_CHECKING:
    from rig_relay.core.agent_loop import AgentLoop
    from rig_relay.desktop.chat_store import ChatStore


class ChatAgentAdapter:
    """Adapter to route desktop chat messages to the AgentLoop and update ChatStore.

    This class bridges the async stream of events from AgentLoop.act() to the
    persistent ChatStore and triggers UI updates via a broadcast callback.
    """

    def __init__(
        self, agent_loop: AgentLoop, store: ChatStore, on_update: Callable[[], None]
    ) -> None:
        self._agent_loop = agent_loop
        self._store = store
        self._on_update = on_update
        self._active_task: asyncio.Task[None] | None = None
        self._status = "idle"  # idle, running, cancelling

    @property
    def status(self) -> str:
        """Current lifecycle status."""
        if self._active_task is None or self._active_task.done():
            return "idle"
        return self._status

    @property
    def is_running(self) -> bool:
        return self.status != "idle"

    async def process_message(self, text: str, client_message_id: str) -> None:
        """Process a user message through the agent loop."""
        if self.is_running:
            logger.warning(
                "Message ignored: agent loop is already running (status=%s)",
                self.status,
            )
            return

        self._status = "running"
        self._active_task = asyncio.create_task(self._run_loop(text, client_message_id))

    def cancel(self) -> bool:
        """Cancel the active agent loop task.

        Returns:
            True if a task was signalled for cancellation, False if idle.
        """
        if self._active_task and not self._active_task.done():
            self._status = "cancelling"
            self._active_task.cancel()
            logger.info("Agent loop task signalled for cancellation")
            return True
        return False

    async def _run_loop(self, text: str, client_message_id: str) -> None:
        try:
            async for event in self._agent_loop.act(
                text, client_message_id=client_message_id
            ):
                await self._handle_event(event)
        except asyncio.CancelledError:
            logger.info("Agent loop turn cancelled")
            self._finalize_pending_messages(status="cancelled")
        except Exception as e:
            logger.error("Error in agent loop: %s", e, exc_info=True)
            self._finalize_pending_messages(status="error")
        finally:
            self._finalize_pending_messages(status=None)
            self._active_task = None
            self._status = "idle"
            self._on_update()

    async def _handle_event(self, event: BaseEvent) -> None:
        """Map AgentLoop events to ChatStore updates."""
        # Load current state
        state = self._store.load_state()
        state.pending_response = True

        if isinstance(event, UserMessageEvent):
            self._handle_user_message(state, event)
        elif isinstance(event, AssistantEvent):
            self._update_assistant_message(
                state, event.content, event.message_id, role=ChatRole.ASSISTANT
            )
        elif isinstance(event, ReasoningEvent):
            self._update_assistant_message(
                state,
                event.content,
                event.message_id,
                role=ChatRole.STATUS,
                status="thinking",
            )
        elif isinstance(event, ToolCallEvent):
            self._handle_tool_call(state, event)
        elif isinstance(event, ToolResultEvent):
            self._handle_tool_result(state, event)
        elif isinstance(event, ToolStreamEvent):
            self._handle_tool_stream(state, event)

        # Save and broadcast
        self._store.save_state(state)
        self._on_update()

    def _handle_user_message(self, state: Any, event: UserMessageEvent) -> None:
        found = False
        for msg in state.messages:
            if msg.metadata.get("client_message_id") == event.message_id:
                found = True
                break
        if not found:
            user_msg = ChatMessage(
                role=ChatRole.USER,
                content=event.content,
                metadata={"client_message_id": event.message_id},
            )
            state.messages.append(user_msg)
            self._store.append_event("chat.message.created", message=user_msg)

    def _handle_tool_call(self, state: Any, event: ToolCallEvent) -> None:
        # Show tool calling status
        status_msg = ChatMessage(
            role=ChatRole.STATUS,
            content=f"Calling tool: {event.tool_name}...",
            status="running",
            metadata={"tool_call_id": event.tool_call_id},
        )
        state.messages.append(status_msg)
        self._store.append_event("chat.status.created", message=status_msg)

    def _handle_tool_result(self, state: Any, event: ToolResultEvent) -> None:
        # Finalize tool status with summary
        for msg in reversed(state.messages):
            if msg.metadata.get("tool_call_id") == event.tool_call_id:
                if event.error:
                    error_preview = self._sanitize_tool_output(event.error, limit=200)
                    msg.content = f"Tool {event.tool_name} failed: {error_preview}"
                    msg.status = "error"
                elif event.skipped:
                    msg.content = f"Tool {event.tool_name} skipped: {event.skip_reason}"
                    msg.status = "skipped"
                else:
                    result_str = str(event.result) if event.result else "Done"
                    preview = self._sanitize_tool_output(result_str, limit=120)
                    msg.content = f"Tool {event.tool_name} finished: {preview}..."
                    msg.status = "success"
                break

    def _handle_tool_stream(self, state: Any, event: ToolStreamEvent) -> None:
        # Progress update for a tool
        for msg in reversed(state.messages):
            if msg.metadata.get("tool_call_id") == event.tool_call_id:
                progress_preview = self._sanitize_tool_output(event.message, limit=120)
                msg.content = f"Tool {event.tool_name} progress: {progress_preview}..."
                break

    def _sanitize_tool_output(self, text: str, limit: int) -> str:
        """Strip raw stdout/stderr/diff/source/secrets from tool output."""
        # Replace newlines with spaces for single-line preview
        clean = text.replace("\n", " ").replace("\r", " ")

        # Heuristic: strip anything that looks like a raw shell output or diff
        # (This is a lightweight preview-only sanitizer)
        if "--- " in clean and "+++ " in clean:
            clean = "[diff content omitted]"
        elif "Traceback (most recent call last):" in clean:
            clean = "[stack trace omitted]"

        # Truncate
        if len(clean) > limit:
            return clean[:limit].rstrip()
        return clean

    def _update_assistant_message(
        self,
        state: Any,
        content: str,
        message_id: str | None,
        role: ChatRole,
        status: str | None = None,
    ) -> None:
        """Helper to append content to an existing message or create a new one."""
        if message_id:
            for msg in reversed(state.messages):
                if msg.message_id == message_id:
                    msg.content += content
                    return

        # Not found, create new
        new_msg = ChatMessage(
            role=role,
            content=content,
            message_id=message_id
            or str(hashlib.sha256(content.encode()).hexdigest()[:16]),
            status=status,
        )
        state.messages.append(new_msg)

    def _finalize_pending_messages(self, status: str | None) -> None:
        state = self._store.load_state()
        state.pending_response = False

        # Log event for failures
        if status == "error":
            self._store.append_event("chat.response.error")
        elif status == "cancelled":
            self._store.append_event("chat.response.cancelled")

        # Update any 'running' or 'thinking' status messages to the final status if provided
        updated = False
        if status:
            for msg in state.messages:
                if msg.status in {"running", "thinking"}:
                    msg.status = status
                    updated = True

            # If nothing was updated and we have an error, add a generic error message
            if not updated and status == "error":
                error_msg = ChatMessage(
                    role=ChatRole.STATUS,
                    content="Agent response failed due to an internal error.",
                    status="error",
                )
                state.messages.append(error_msg)

        self._store.save_state(state)
