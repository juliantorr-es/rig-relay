"""Remote workflow event translator mixin — tool events."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ValidationError

from rig_relay.core.nuage.events import (
    CustomTaskCanceled,
    CustomTaskCompleted,
    CustomTaskFailed,
    CustomTaskInProgress,
    CustomTaskStarted,
    CustomTaskTimedOut,
)
from rig_relay.core.nuage.remote_workflow_event_models import (
    AgentToolCallState,
    AnyToolUIState,
    CommandUIState,
    FileUIState,
    GenericToolUIState,
)
from rig_relay.core.tools.base import BaseTool
from rig_relay.core.types import (
    BaseEvent,
    FunctionCall,
    LLMMessage,
    Role,
    ToolCall,
    ToolCallEvent,
    ToolResultEvent,
    ToolStreamEvent,
)

_ASK_USER_QUESTION_TOOL = "ask_user_question"
_SEND_USER_MESSAGE_TOOL = "send_user_message"


class ToolEventsMixin:
    """Mixin providing tool events methods for RemoteWorkflowEventTranslator."""

    def _tool_events(
        self,
        task_id: str,
        state: dict[str, Any],
        event: CustomTaskStarted | CustomTaskInProgress | CustomTaskCompleted,
    ) -> list[BaseEvent]:
        parsed = AgentToolCallState.model_validate(state)
        tool_name = parsed.name
        if tool_name == _SEND_USER_MESSAGE_TOOL:
            return []

        events = self._tool_call_and_stream_events(task_id, state)

        if not isinstance(event, CustomTaskCompleted) or not tool_name:
            return events

        tool_call_id = parsed.tool_call_id or task_id
        events.extend(
            self._emit_tool_result_events(
                tool_name=tool_name,
                tool_call_id=tool_call_id,
                output=parsed.output,
                error=None,
            )
        )
        return events

    def _tool_args_from_ui_state(
        self, ui_state: AnyToolUIState | None
    ) -> dict[str, Any]:
        if isinstance(ui_state, FileUIState):
            if not ui_state.operations:
                return {}
            op = ui_state.operations[0]
            return {
                "path": op.uri,
                "content": op.content,
                "overwrite": op.type == "replace",
            }
        if isinstance(ui_state, CommandUIState):
            return {"command": ui_state.command}
        if isinstance(ui_state, GenericToolUIState):
            return ui_state.arguments
        return {}

    def _tool_result_from_ui_state(
        self, ui_state: AnyToolUIState | None
    ) -> tuple[dict[str, Any] | None, str | None]:
        if isinstance(ui_state, FileUIState):
            return self._file_ui_result(ui_state)
        if isinstance(ui_state, CommandUIState):
            return self._command_ui_result(ui_state)
        if isinstance(ui_state, GenericToolUIState):
            return self._generic_ui_result(ui_state)
        return None, None

    def _file_ui_result(
        self, ui_state: FileUIState
    ) -> tuple[dict[str, Any] | None, str | None]:
        if not ui_state.operations:
            return None, "No file operations in result"
        op = ui_state.operations[0]
        return {
            "path": op.uri,
            "bytes_written": len(op.content.encode()),
            "file_existed": op.type == "replace",
            "content": op.content,
        }, None

    def _command_ui_result(
        self, ui_state: CommandUIState
    ) -> tuple[dict[str, Any] | None, str | None]:
        result = ui_state.result
        if result is None or result.status == "running":
            return None, None
        if result.status == "failed":
            return None, result.output or "Command failed"
        return {
            "command": ui_state.command,
            "stdout": result.output,
            "stderr": "",
            "returncode": 0,
        }, None

    def _generic_ui_result(
        self, ui_state: GenericToolUIState
    ) -> tuple[dict[str, Any] | None, str | None]:
        result = ui_state.result
        if result is None or result.status == "running":
            return None, None
        if result.status == "failed":
            return None, result.error or "Tool failed"
        return ui_state.arguments, None

    def _emit_tool_call_events(
        self,
        *,
        tool_name: str,
        tool_call_id: str,
        tool_args: dict[str, Any],
        task_key: str,
    ) -> list[BaseEvent]:
        if not tool_name or tool_name == _SEND_USER_MESSAGE_TOOL:
            return []

        question_events = self._ask_user_question_events(tool_name, tool_args)
        tool_class = self._resolve_tool_class(tool_name)
        args_model, _ = tool_class._get_tool_args_results()
        validated_args: BaseModel | None = None
        try:
            validated_args = args_model.model_validate(tool_args)
        except ValidationError:
            validated_args = None

        if tool_call_id in self._seen_tool_call_ids:
            return []

        self._seen_tool_call_ids.add(tool_call_id)
        self._stats.tool_calls_agreed += 1
        self._open_tool_calls[tool_call_id] = tool_name
        if tool_name == _ASK_USER_QUESTION_TOOL:
            self._pending_ask_user_question_call_id = tool_call_id
        self._merge_message(
            LLMMessage(
                role=Role.assistant,
                tool_calls=[
                    ToolCall(
                        id=tool_call_id,
                        function=FunctionCall(
                            name=tool_name, arguments=self._json_string(tool_args)
                        ),
                    )
                ],
            )
        )
        return [
            ToolCallEvent(
                tool_call_id=tool_call_id,
                tool_name=tool_name,
                tool_class=tool_class,
                args=validated_args,
            ),
            *question_events,
        ]

    def _tool_stream_events(
        self, tool_name: str, tool_call_id: str, result_key: str, output: Any
    ) -> list[ToolStreamEvent]:
        preview = self._output_preview_text(output)
        if not preview:
            return []

        previous_preview = self._tool_stream_snapshots.get(result_key, "")
        if preview == previous_preview:
            return []

        self._tool_stream_snapshots[result_key] = preview
        if not preview.strip():
            return []

        return [
            ToolStreamEvent(
                tool_name=tool_name, tool_call_id=tool_call_id, message=preview
            )
        ]

    def _resolve_tool_class(self, tool_name: str) -> type[BaseTool]:
        if tool_class := self._available_tools.get(tool_name):
            return tool_class

        short_name = tool_name.rsplit(".", 1)[-1]
        if short_name != tool_name and (
            tool_class := self._available_tools.get(short_name)
        ):
            return tool_class

        suffix_matches = [
            available_tool_class
            for available_name, available_tool_class in self._available_tools.items()
            if available_name.endswith(f".{short_name}") or available_name == short_name
        ]
        if len(suffix_matches) == 1:
            return suffix_matches[0]

        from rig_relay.core.nuage.remote_workflow_event_translator import (
            _remote_tool_class,
        )

        return _remote_tool_class(tool_name)

    def _finalize_tool_call(self, tool_call_id: str) -> None:
        self._seen_tool_results.add(tool_call_id)
        self._open_tool_calls.pop(tool_call_id, None)
        self._pending_tool_progress.pop(tool_call_id, None)
        self._tool_stream_snapshots.pop(tool_call_id, None)

    def _emit_tool_result_events(
        self, *, tool_name: str, tool_call_id: str, output: Any, error: str | None
    ) -> list[BaseEvent]:
        if tool_name == _SEND_USER_MESSAGE_TOOL:
            return []

        if tool_call_id in self._seen_tool_results:
            return []

        tool_class = self._resolve_tool_class(tool_name)

        if error:
            self._finalize_tool_call(tool_call_id)
            return self._emit_tool_error_result(
                tool_name=tool_name,
                tool_class=tool_class,
                tool_call_id=tool_call_id,
                error=error,
            )

        if output is None:
            self._finalize_tool_call(tool_call_id)
            return self._emit_missing_tool_output(
                tool_name=tool_name, tool_class=tool_class, tool_call_id=tool_call_id
            )

        output_dict = self._normalize_output(output)
        output_error = output_dict.get("error")
        if isinstance(output_error, str) and output_error:
            self._finalize_tool_call(tool_call_id)
            return self._emit_tool_error_result(
                tool_name=tool_name,
                tool_class=tool_class,
                tool_call_id=tool_call_id,
                error=output_error,
            )

        self._finalize_tool_call(tool_call_id)

        _, result_model = tool_class._get_tool_args_results()
        result_value: BaseModel | None = None
        try:
            result_value = result_model.model_validate(output_dict)
        except ValidationError:
            result_value = None

        self._stats.tool_calls_succeeded += 1
        result_text = "\n".join(f"{k}: {v}" for k, v in output_dict.items())
        self._merge_message(
            LLMMessage(
                role=Role.tool,
                name=tool_name,
                tool_call_id=tool_call_id,
                content=result_text,
            )
        )
        return [
            ToolResultEvent(
                tool_name=tool_name,
                tool_class=tool_class,
                result=result_value,
                tool_call_id=tool_call_id,
            )
        ]

    def _emit_missing_tool_output(
        self, tool_name: str, tool_class: type[BaseTool], tool_call_id: str
    ) -> list[BaseEvent]:
        error = "Tool did not produce output"
        self._stats.tool_calls_failed += 1
        self._merge_message(
            LLMMessage(
                role=Role.tool, name=tool_name, tool_call_id=tool_call_id, content=error
            )
        )
        return [
            ToolResultEvent(
                tool_name=tool_name,
                tool_class=tool_class,
                error=error,
                tool_call_id=tool_call_id,
            )
        ]

    def _emit_tool_error_result(
        self, tool_name: str, tool_class: type[BaseTool], tool_call_id: str, error: str
    ) -> list[BaseEvent]:
        self._stats.tool_calls_failed += 1
        self._merge_message(
            LLMMessage(
                role=Role.tool, name=tool_name, tool_call_id=tool_call_id, content=error
            )
        )
        return [
            ToolResultEvent(
                tool_name=tool_name,
                tool_class=tool_class,
                error=error,
                tool_call_id=tool_call_id,
            )
        ]

    def _tool_call_and_stream_events(
        self, task_id: str, state: dict[str, Any]
    ) -> list[BaseEvent]:
        parsed = AgentToolCallState.model_validate(state)
        tool_name = parsed.name
        tool_call_id = parsed.tool_call_id or task_id
        tool_args = self._normalize_mapping(parsed.kwargs)
        events = self._emit_tool_call_events(
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            tool_args=tool_args,
            task_key=task_id,
        )

        if pending_progress := self._pending_tool_progress.pop(tool_call_id, None):
            pending_tool_name, pending_content = pending_progress
            if pending_tool_name == tool_name:
                events.extend(
                    self._tool_stream_events(
                        tool_name=tool_name,
                        tool_call_id=tool_call_id,
                        result_key=tool_call_id,
                        output=pending_content,
                    )
                )

        if tool_call_id in self._seen_tool_results:
            return events

        events.extend(
            self._tool_stream_events(
                tool_name=tool_name,
                tool_call_id=tool_call_id,
                result_key=tool_call_id,
                output=parsed.output,
            )
        )
        return events

    def _tool_terminal_events(
        self,
        task_id: str,
        state: dict[str, Any],
        event: CustomTaskFailed | CustomTaskTimedOut | CustomTaskCanceled,
    ) -> list[BaseEvent]:
        parsed = AgentToolCallState.model_validate(state)
        tool_name = parsed.name
        if not tool_name:
            return []
        if tool_name == _SEND_USER_MESSAGE_TOOL:
            return []
        if tool_name == _ASK_USER_QUESTION_TOOL:
            self._pending_question_prompt = None

        tool_call_id = parsed.tool_call_id or task_id
        if tool_call_id in self._seen_tool_results:
            return []

        tool_class = self._resolve_tool_class(tool_name)
        error = self._tool_terminal_error(event)
        self._finalize_tool_call(tool_call_id)
        self._stats.tool_calls_failed += 1
        self._merge_message(
            LLMMessage(
                role=Role.tool, name=tool_name, tool_call_id=tool_call_id, content=error
            )
        )
        return [
            ToolResultEvent(
                tool_name=tool_name,
                tool_class=tool_class,
                error=error,
                cancelled=isinstance(event, CustomTaskCanceled),
                tool_call_id=tool_call_id,
            )
        ]

    def _tool_terminal_error(
        self, event: CustomTaskFailed | CustomTaskTimedOut | CustomTaskCanceled
    ) -> str:
        if isinstance(event, CustomTaskFailed):
            return event.attributes.failure.message

        if isinstance(event, CustomTaskTimedOut):
            timeout_type = event.attributes.timeout_type
            return f"Timed out ({timeout_type})" if timeout_type else "Timed out"

        if event.attributes.reason:
            return f"Canceled: {event.attributes.reason}"
        return "Canceled"
