"""Remote workflow event translator mixin — working events."""
from __future__ import annotations

from typing import Any

from rig_relay.core.types import BaseEvent, LLMMessage, Role


class WorkingEventsMixin:
    """Mixin providing working events methods for RemoteWorkflowEventTranslator."""

    def _working_events_without_tool_call(
        self,
        task_id: str,
        working: WorkingState,
        previous_working: WorkingState,
        parsed_ui_state: AnyToolUIState | None,
        event: CustomTaskStarted | CustomTaskInProgress | CustomTaskCompleted,
    ) -> list[BaseEvent]:
        if isinstance(event, CustomTaskStarted):
            return []

        if working.type == "thinking":
            return self._working_thinking_events(task_id, working, previous_working)

        tool_name = working.title.removeprefix("Executing ")
        if not tool_name or tool_name == _SEND_USER_MESSAGE_TOOL:
            return []

        events = self._emit_tool_call_events(
            tool_name=tool_name,
            tool_call_id=task_id,
            tool_args={"summary": working.title},
            task_key=task_id,
        )
        stream_output = self._working_stream_output(
            parsed_ui_state=parsed_ui_state, content=working.content
        )
        if stream_output:
            events.extend(
                self._tool_stream_events(
                    tool_name=tool_name,
                    tool_call_id=task_id,
                    result_key=task_id,
                    output=stream_output,
                )
            )
        if isinstance(event, CustomTaskCompleted):
            output, error = self._tool_result_from_ui_state(parsed_ui_state)
            events.extend(
                self._emit_tool_result_events(
                    tool_name=tool_name,
                    tool_call_id=task_id,
                    output=output or {"message": working.title},
                    error=error,
                )
            )
        return events


    def _working_thinking_events(
        self, task_id: str, working: WorkingState, previous_working: WorkingState
    ) -> list[BaseEvent]:
        delta = working.content[len(previous_working.content) :]
        if not delta:
            return []
        message_id = self._completion_message_ids.setdefault(
            task_id, LLMMessage(role=Role.assistant).message_id or task_id
        )
        self._merge_message(
            LLMMessage(
                role=Role.assistant, reasoning_content=delta, message_id=message_id
            )
        )
        return [ReasoningEvent(content=delta, message_id=message_id)]


    def _working_events_with_tool_call(
        self,
        task_id: str,
        working: WorkingState,
        parsed_ui_state: AnyToolUIState | None,
        tool_call_id: str,
        event: CustomTaskStarted | CustomTaskInProgress | CustomTaskCompleted,
    ) -> list[BaseEvent]:
        tool_name = working.title.removeprefix("Executing ")
        if not tool_name or tool_name == _SEND_USER_MESSAGE_TOOL:
            return []

        tool_args = self._tool_args_from_ui_state(parsed_ui_state)
        events = self._emit_tool_call_events(
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            tool_args=tool_args,
            task_key=task_id,
        )

        if not isinstance(parsed_ui_state, FileUIState) and working.content:
            events.extend(
                self._tool_stream_events(
                    tool_name=tool_name,
                    tool_call_id=tool_call_id,
                    result_key=tool_call_id,
                    output=working.content,
                )
            )

        if isinstance(event, CustomTaskCompleted):
            output, error = self._tool_result_from_ui_state(parsed_ui_state)
            events.extend(
                self._emit_tool_result_events(
                    tool_name=tool_name,
                    tool_call_id=tool_call_id,
                    output=output or {"message": working.title},
                    error=error,
                )
            )

        return events


    def _working_stream_output(
        self, *, parsed_ui_state: AnyToolUIState | None, content: str
    ) -> Any:
        if content:
            return content

        output, error = self._tool_result_from_ui_state(parsed_ui_state)
        if error:
            return {"error": error}
        if output is not None:
            return output
        return None

