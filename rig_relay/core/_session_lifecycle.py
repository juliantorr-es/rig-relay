"""Session lifecycle mixin for AgentLoop.

Extracted from agent_loop.py. Provides methods for message history
cleaning, missing tool response filling, session reset, and fork
message extraction. These methods are purely about message and session
state — they don't depend on LLM, tools, or backend.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from rig_relay.core.guard import GuardCaptureReason, get_guard
from rig_relay.core.session.session_id import extract_suffix, generate_session_id
from rig_relay.core.types import LLMMessage, Role
from rig_relay.core.utils import CancellationReason, get_user_cancellation_message

if TYPE_CHECKING:
    pass


class SessionLifecycleMixin:
    """Mixin providing message history and session lifecycle management."""

    def _clean_message_history(self) -> None:
        ACCEPTABLE_HISTORY_SIZE = 2
        if len(self.messages) < ACCEPTABLE_HISTORY_SIZE:
            return
        self._fill_missing_tool_responses()

    def _fill_missing_tool_responses(self) -> None:
        i = 1
        while i < len(self.messages):  # noqa: PLR1702
            msg = self.messages[i]

            if msg.role == "assistant" and msg.tool_calls:
                expected_responses = len(msg.tool_calls)

                if expected_responses > 0:
                    responded_ids: set[str] = set()
                    j = i + 1
                    while j < len(self.messages) and self.messages[j].role == "tool":
                        tool_call_id = self.messages[j].tool_call_id
                        if tool_call_id is not None:
                            responded_ids.add(tool_call_id)
                        j += 1

                    if len(responded_ids) < expected_responses:
                        insertion_point = j

                        for tool_call_data in msg.tool_calls:
                            if (tool_call_data.id or "") in responded_ids:
                                continue

                            empty_response = LLMMessage(
                                role=Role.tool,
                                tool_call_id=tool_call_data.id or "",
                                name=(
                                    (tool_call_data.function.name or "")
                                    if tool_call_data.function
                                    else ""
                                ),
                                content=str(
                                    get_user_cancellation_message(
                                        CancellationReason.TOOL_NO_RESPONSE
                                    )
                                ),
                            )

                            self.messages.insert(insertion_point, empty_response)
                            insertion_point += 1

                    i = i + 1 + expected_responses
                    continue

            i += 1

    def _reset_session(self, keep_parent: bool = True) -> None:
        old_session_id = self.session_id
        self.emit_session_closed_telemetry()
        suffix = extract_suffix(self.session_id)
        self.session_id = generate_session_id(suffix=suffix)
        parent_session_id = old_session_id if keep_parent else None
        self.parent_session_id = parent_session_id
        self.session_logger.reset_session(
            self.session_id, parent_session_id=parent_session_id
        )
        self.emit_new_session_telemetry()

        try:
            get_guard().recapture(reason=GuardCaptureReason.RESET_SESSION)
        except Exception:
            pass

    def _messages_for_fork(self, message_id: str | None) -> list[LLMMessage]:
        source_messages = [m for m in self.messages if m.role != Role.system]
        if message_id is None:
            return [m.model_copy(deep=True) for m in source_messages]

        anchor_index = next(
            (i for i, m in enumerate(source_messages) if message_id == m.message_id),
            None,
        )
        if anchor_index is None:
            raise ValueError(f"Cannot fork from unknown message_id: {message_id}")

        if source_messages[anchor_index].role != Role.user:
            raise ValueError("Fork from message_id is only supported for user messages")

        next_turn_index = next(
            (
                i
                for i, m in enumerate(
                    source_messages[anchor_index + 1 :], start=anchor_index + 1
                )
                if m.role == Role.user
            ),
            len(source_messages),
        )
        return [m.model_copy(deep=True) for m in source_messages[:next_turn_index]]
